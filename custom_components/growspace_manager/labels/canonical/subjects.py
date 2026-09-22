"""[[Source Adapter]]s: one saved strain or live plant, read exactly once.

A caller names a subject. It does not send a strain name, a breeder, a lineage,
a logo, a URL or a date — the backend authorizes the request, reads integration
state, normalizes it through `resolve_subject` and freezes the result. That is
the whole of why a preview and its print cannot disagree about what a label
says, and why a batch's twelfth record is validated rather than assumed.

Three contexts, two adapters: a `strain` subject is a saved strain-library row
plus an optional saved phenotype, and `plant` and `batch_item` are one live
plant enriched through *its own* captured library relationship. A plant's
strain and phenotype names come from the plant and never from the library,
because those are its identity; breeder, lineage and the dynamic logo come
from the library and never from a dialog, an entity attribute or a stale
override.

Everything a later change could move is captured by value here: the logo's
normalized bytes rather than its path, both QR URIs rather than the URL
configuration that built them, and one `as_of` for the whole batch.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime
import hashlib
from io import BytesIO
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PIL import Image, UnidentifiedImageError

from custom_components.growspace_manager.domain.stage import (
    STAGE_REGISTRY,
    get_stage_definition,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.util import dt as dt_util

from .catalogue import PrintContext
from .content import (
    PARENT_STAGES,
    ContentAbsence,
    LabelAsset,
    LabelContentSnapshot,
    SubjectFacts,
    normalize_value,
    resolve_locale,
    resolve_subject,
)
from .diagnostics import Severity

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
    from custom_components.growspace_manager.models import Plant
    from custom_components.growspace_manager.strain_library import StrainLibrary

_LOGGER = logging.getLogger(__name__)

#: What a snapshot taken from live integration state says it came from, so a
#: raster of a real record cannot be cached as though it were a fixture's.
RECORD_SOURCE = "record"

#: The one plant route both QR forms address. Spelled once, because the whole
#: point of offering two targets is that they reach the same page.
PLANT_ROUTE = "growspace/plant/{plant_id}"

#: Above this a stored logo is refused before it is opened as an image. It is
#: a breeder's mark, not a photograph, and a file this size is a sign
#: something else was saved into the column.
MAX_LOGO_SOURCE_BYTES = 4 * 1024 * 1024

#: What a captured logo is normalized to. The B1's printhead is 384 pixels
#: wide, so nothing larger can add ink on the hardware this profile describes.
LOGO_NORMALIZED_BOX = (384, 384)

#: Where a `/local/...` logo path resolves under the Home Assistant config
#: directory.
_LOCAL_PREFIX = "/local/"
_DATA_URI_PREFIX = "data:image/"

#: What a stored logo that PIL cannot open raises.
_LOGO_ERRORS = (binascii.Error, OSError, UnidentifiedImageError, ValueError)


def stage_started_at(plant: Plant) -> str | None:
    """Return the [[Lifecycle Timestamp]] of the plant's *current* stage.

    Only that one. A plant in flower reads `flower_start` and nothing else,
    so an empty `flower_start` yields no date rather than the `veg_start`
    still sitting beside it — which would date the label to a stage the plant
    has left. Sub-stages read their parent's field, because a plant does not
    separately enter late flower.
    """
    stage = str(plant.stage or "")
    definition = get_stage_definition(stage)
    if definition is None:
        parent = PARENT_STAGES.get(stage)
        definition = STAGE_REGISTRY.get(parent) if parent else None
    if definition is None:
        return None
    value = getattr(plant, definition.start_field, None)
    return str(value) if value else None


async def async_capture_strain(
    hass: HomeAssistant,
    strain_library: StrainLibrary,
    *,
    strain: str,
    phenotype: str | None = None,
    locale: str | None = None,
    as_of: datetime | None = None,
) -> LabelContentSnapshot:
    """Capture one saved strain, and optionally one of its saved phenotypes.

    Both are *references*, resolved here against what the library holds: a
    name the library does not know is a subject that does not exist, not a
    strain name the caller may supply. That is what keeps a strain editor's
    unsaved draft off paper — the user saves it, and then it can be printed.
    """
    await strain_library.load()
    row = strain_library.get_all().get(strain)
    if row is None:
        raise HomeAssistantError(f"Strain {strain!r} is not in the strain library")
    meta: Mapping[str, Any] = row.get("meta", {})

    sources = {"strain": strain}
    selected = _saved_phenotype(row, phenotype)
    if selected:
        sources["phenotype"] = selected

    facts = SubjectFacts(
        context=PrintContext.STRAIN,
        subject=strain,
        strain_name=strain,
        phenotype_name=selected,
        breeder=meta.get("breeder"),
        lineage=meta.get("lineage"),
        sources=sources,
    )
    facts = await _async_with_logo(hass, facts, meta.get("breeder_logo"))
    return _freeze(facts, locale=locale, as_of=as_of)


def _saved_phenotype(row: Mapping[str, Any], requested: str | None) -> str | None:
    """Return the saved phenotype a request selected, or refuse the reference.

    `default` is the library's own name for a strain with no named phenotype,
    and the card's placeholders mean the same thing, so all of them select
    nothing. Anything else has to be a phenotype that strain really has,
    because a name accepted on trust here would be a caller supplying the
    value the label prints.
    """
    name = normalize_value(requested)
    if name is None or name.casefold() == "default":
        return None
    phenotypes: Mapping[str, Any] = row.get("phenotypes", {})
    if name not in phenotypes:
        raise HomeAssistantError(f"Phenotype {name!r} is not saved for this strain")
    return name


async def async_capture_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    *,
    plant_id: str,
    context: PrintContext = PrintContext.PLANT,
    locale: str | None = None,
    as_of: datetime | None = None,
) -> LabelContentSnapshot:
    """Capture one live plant, enriched through its own library relationship.

    `context` exists so a single item of a batch can be re-captured under the
    context it was printed in; it changes no value, and the batch adapter is
    still the only way to capture an ordered set against one instant.
    """
    facts = await _async_plant_facts(
        hass, coordinator, strain_library, plant_id=plant_id, context=context
    )
    return _freeze(facts, locale=locale, as_of=as_of)


async def async_capture_batch(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    *,
    plant_ids: Sequence[str],
    locale: str | None = None,
    as_of: datetime | None = None,
) -> tuple[LabelContentSnapshot, ...]:
    """Capture one ordered batch, in submitted order, against one instant.

    The instant is captured once for the whole batch, so a run crossing local
    midnight prints one date and one age on every item and on every later
    retry of any of them.

    A repeated plant identity is refused rather than read as an implicit extra
    copy: copies are a count, and a list that says a plant twice is a list its
    author did not mean.
    """
    if not plant_ids:
        raise HomeAssistantError("A label batch needs at least one plant")
    seen: set[str] = set()
    duplicates: set[str] = set()
    for plant_id in plant_ids:
        if plant_id in seen:
            duplicates.add(plant_id)
        seen.add(plant_id)
    if duplicates:
        raise HomeAssistantError(
            f"A label batch lists {', '.join(sorted(duplicates))} more than once; "
            "use the copy count instead"
        )

    resolved_locale = resolve_locale(locale)
    instant = as_of or dt_util.now()
    captured: list[LabelContentSnapshot] = []
    for plant_id in plant_ids:
        facts = await _async_plant_facts(
            hass,
            coordinator,
            strain_library,
            plant_id=plant_id,
            context=PrintContext.BATCH_ITEM,
        )
        captured.append(_freeze(facts, locale=resolved_locale, as_of=instant))
    return tuple(captured)


async def _async_plant_facts(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    *,
    plant_id: str,
    context: PrintContext,
) -> SubjectFacts:
    """Read one plant and the strain-library row it points at."""
    plant = coordinator.plants.get(plant_id)
    if plant is None:
        raise HomeAssistantError(f"Plant {plant_id} not found")

    await strain_library.load()
    strain_name = plant.genetics.strain_name
    row = strain_library.get_all().get(strain_name) if strain_name else None
    meta: Mapping[str, Any] = (row or {}).get("meta", {})

    links, link_absence = _plant_links(hass, plant_id)
    sources = {"plant": plant_id}
    if row is not None:
        sources["strain"] = strain_name

    facts = SubjectFacts(
        context=context,
        subject=plant_id,
        strain_name=strain_name,
        phenotype_name=plant.genetics.phenotype_name,
        breeder=meta.get("breeder"),
        lineage=meta.get("lineage"),
        library_linked=row is not None,
        plant_id=plant_id,
        stage=str(plant.stage or ""),
        stage_started_at=stage_started_at(plant),
        links=links,
        link_absence=link_absence,
        sources=sources,
    )
    return await _async_with_logo(hass, facts, meta.get("breeder_logo"))


def _freeze(
    facts: SubjectFacts, *, locale: str | None, as_of: datetime | None
) -> LabelContentSnapshot:
    """Normalize captured facts against one instant, locale and time zone.

    `dt_util.now()` is already in Home Assistant's configured zone, which is
    the calendar the printed date, the stage date and the age are all read
    off. Recording the zone beside the instant is what lets a later reader
    tell which midnight a label's date belongs to.
    """
    return resolve_subject(
        facts,
        as_of=as_of or dt_util.now(),
        locale=resolve_locale(locale),
        time_zone=str(dt_util.DEFAULT_TIME_ZONE),
        source=RECORD_SOURCE,
    )


# ---------------------------------------------------------------------------
# QR routing
# ---------------------------------------------------------------------------


def _plant_links(
    hass: HomeAssistant, plant_id: str
) -> tuple[Mapping[str, str], ContentAbsence | None]:
    """Build both QR forms of one plant's configured route.

    Both are captured, not just the one a layout happens to select today: a
    template edited tomorrow to prefer the app deep link must reprint against
    the snapshot rather than against whatever the URL configuration has become
    by then. Only the web form can fail — it needs a configured external or
    internal URL, and an installation that has neither cannot produce a
    scannable dashboard link at all.
    """
    route = PLANT_ROUTE.format(plant_id=plant_id)
    links: dict[str, str] = {"home_assistant_app": f"homeassistant://navigate/{route}"}
    try:
        base = get_url(hass)
    except NoURLAvailableError:
        return links, ContentAbsence(
            code="content.qr_target_unavailable",
            severity=Severity.ERROR,
            parameters={"binding": "plant.link", "target": "dashboard_url"},
        )
    links["dashboard_url"] = f"{base.rstrip('/')}/{route}"
    return links, None


# ---------------------------------------------------------------------------
# Logo capture
# ---------------------------------------------------------------------------


async def _async_with_logo(
    hass: HomeAssistant, facts: SubjectFacts, stored: object
) -> SubjectFacts:
    """Capture the breeder's logo by value, or say why there is none.

    By value because a snapshot that held a path would reprint whatever the
    breeder's logo has become, and a retry that differs from the label it
    replaces is the one thing an immutable snapshot exists to prevent.

    Only the integration-managed image counts. A remote URL is refused rather
    than fetched: it is not ours, it can change or disappear between preview
    and paper, and fetching one at print time would make a label depend on the
    internet.
    """
    if not isinstance(stored, str) or not stored.strip():
        return facts
    asset, absence = await hass.async_add_executor_job(
        _capture_logo, hass.config.path(), stored.strip()
    )
    return replace(facts, logo=asset, logo_absence=absence)


def _capture_logo(
    config_dir: str, stored: str
) -> tuple[LabelAsset | None, ContentAbsence | None]:
    """Read, bound, normalize and hash one stored logo.

    In the executor: this opens a file and initialises Pillow's native
    libraries, neither of which belongs on the event loop.
    """
    try:
        raw = _read_logo(config_dir, stored)
    except _LogoRefused as refusal:
        return None, refusal.absence
    except _LOGO_ERRORS as err:
        return None, _logo_absence("unreadable", str(err))

    if len(raw) > MAX_LOGO_SOURCE_BYTES:
        return None, _logo_absence(
            "oversized", f"{len(raw)} bytes exceeds {MAX_LOGO_SOURCE_BYTES}"
        )

    try:
        with Image.open(BytesIO(raw)) as image:
            image.load()
            normalized = _flatten(image)
            normalized.thumbnail(LOGO_NORMALIZED_BOX)
            buffer = BytesIO()
            normalized.save(buffer, format="PNG", optimize=True)
            width, height = normalized.size
    except _LOGO_ERRORS as err:
        return None, _logo_absence("unconvertible", str(err))

    payload = buffer.getvalue()
    return (
        LabelAsset(
            asset_id=f"breeder-logo:{hashlib.sha256(stored.encode()).hexdigest()[:16]}",
            content_hash=f"sha256:{hashlib.sha256(payload).hexdigest()}",
            media_type="image/png",
            data_uri=f"data:image/png;base64,{base64.b64encode(payload).decode()}",
            width=width,
            height=height,
        ),
        None,
    )


class _LogoRefused(Exception):
    """A stored logo this integration does not own, or cannot reach."""

    def __init__(self, absence: ContentAbsence) -> None:
        """Carry the absence the caller should record."""
        super().__init__(absence.code)
        self.absence = absence


def _read_logo(config_dir: str, stored: str) -> bytes:
    """Return the bytes behind one stored logo value, whatever shape it takes."""
    if stored.startswith(_DATA_URI_PREFIX):
        _, _, encoded = stored.partition(",")
        return base64.b64decode(encoded, validate=True)
    if stored.startswith(_LOCAL_PREFIX):
        return _read_file(Path(config_dir) / "www" / stored[len(_LOCAL_PREFIX) :])
    if "://" in stored:
        raise _LogoRefused(
            _logo_absence("not_integration_managed", "a remote URL is not an asset")
        )
    return _read_file(Path(stored))


def _read_file(path: Path) -> bytes:
    """Read one logo file, refusing a path that escapes into unread bytes."""
    if not path.is_file():
        raise _LogoRefused(_logo_absence("unreadable", f"{path} is not a file"))
    return path.read_bytes()


def _flatten(image: Image.Image) -> Image.Image:
    """Return one image on white, with any alpha composited rather than dropped.

    A transparent logo saved straight to a monochrome raster prints its
    transparency as black, which turns a wordmark into a filled rectangle.
    """
    if image.mode in ("RGBA", "LA") or (
        image.mode == "P" and "transparency" in image.info
    ):
        converted = image.convert("RGBA")
        background = Image.new("RGB", converted.size, (255, 255, 255))
        background.paste(converted, mask=converted.split()[3])
        return background
    return image.convert("RGB")


def _logo_absence(reason: str, detail: str) -> ContentAbsence:
    """Return the one absence a logo failure produces, naming what happened."""
    _LOGGER.debug("Breeder logo unusable (%s): %s", reason, detail)
    return ContentAbsence(
        code="content.logo_unusable",
        severity=Severity.WARNING,
        parameters={"binding": "strain.breeder.logo", "reason": reason},
    )


__all__ = [
    "LOGO_NORMALIZED_BOX",
    "MAX_LOGO_SOURCE_BYTES",
    "PLANT_ROUTE",
    "RECORD_SOURCE",
    "async_capture_batch",
    "async_capture_plant",
    "async_capture_strain",
    "stage_started_at",
]
