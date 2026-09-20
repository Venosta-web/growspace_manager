"""The Compatibility Adapter for the Classic `print_label` request.

The only module that understands the pre-template request shape: a subject
given as either `plant_id` or a bare strain, caller-supplied breeder/lineage
overrides, the strain-library meta fallback behind them, the `fields`
visibility flags, `base_url`, and `qr_target`. It resolves all of that exactly
once into an immutable [[Label Content]] snapshot and hands it to the renderer.

It is not a second renderer, and it creates no state. A Classic request writes
no template, no draft, no default, and no capability — it is a transient
operational artifact that exists for the length of one print.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from custom_components.growspace_manager.const import (
    ATTR_BREEDER,
    ATTR_BREEDER_LOGO,
    ATTR_LINEAGE,
    ATTR_PHENOTYPE,
    ATTR_STRAIN,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.network import get_url
from homeassistant.util import dt as dt_util

from .canonical.catalogue import LABEL_SIZES
from .model import LabelContent
from .niimbot import async_print
from .renderer import DEFAULT_LABEL_SIZE, render

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
    from custom_components.growspace_manager.strain_library import StrainLibrary

#: Values the card and the strain library both use to mean "nothing recorded".
#: They must never reach the label as literal text.
_EMPTY_VALUES = ("-", "–")

#: The phenotype name the card sends for a strain with no named phenotype.
_DEFAULT_PHENOTYPE = "default"

_DATE_FORMAT = "%d.%m.%Y"


@dataclass(frozen=True, slots=True)
class ClassicPrintRequest:
    """Immutable transient canonical inputs for one Classic request.

    These inputs have an explicit compatibility-layout identity and canonical
    stock identity, but are never a Template Revision, draft, or default.  The
    fixed compatibility layout remains behind the common renderer seam for the
    deprecation window, so released clients keep byte-for-byte output while
    every legacy request is isolated in this adapter.
    """

    content: LabelContent
    label_size: str | None
    density: str
    device_id: str | None
    preview: bool
    #: Plant id where there was one, else the strain — for logging only.
    subject: str
    label_size_id: str
    layout_id: str = "growspace.classic-layout.v1"


async def async_compatibility_print(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    data: dict[str, Any],
) -> dict[str, Any] | None:
    """Resolve, render, and adapt one legacy request without library state."""
    request = await resolve_classic_request(hass, coordinator, strain_library, data)
    plan = render(
        request.content, label_size=request.label_size, density=request.density
    )
    return await async_print(
        hass,
        plan,
        device_id=request.device_id,
        preview=request.preview,
        subject=request.subject,
    )


async def resolve_classic_request(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    data: dict[str, Any],
) -> ClassicPrintRequest:
    """Turn one Classic `print_label` request into a renderable snapshot."""
    plant_id: str | None = data.get("plant_id")
    strain_name: str | None
    breeder: str | None = None
    lineage: str | None = None
    breeder_logo: str | None = None

    if plant_id:
        plant = coordinator.plants.get(plant_id)
        if not plant:
            raise HomeAssistantError(f"Plant {plant_id} not found")
        strain_name = plant.genetics.strain_name
        phenotype_name = plant.genetics.phenotype_name or _DEFAULT_PHENOTYPE
    else:
        strain_name = data.get(ATTR_STRAIN)
        phenotype_name = data.get(ATTR_PHENOTYPE) or _DEFAULT_PHENOTYPE
        breeder = data.get(ATTR_BREEDER)
        lineage = data.get(ATTR_LINEAGE)
        breeder_logo = data.get(ATTR_BREEDER_LOGO)

    if not strain_name:
        raise HomeAssistantError(
            "Neither plant_id nor strain name provided for label printing"
        )

    if phenotype_name == _DEFAULT_PHENOTYPE:
        phenotype_name = "-"

    # The library is the fallback behind every caller-supplied override, so it
    # has to be loaded even when the caller supplied all three.
    await strain_library.load()
    meta = strain_library.get_all().get(strain_name, {}).get("meta", {})
    breeder = breeder or meta.get(ATTR_BREEDER, "-")
    lineage = lineage or meta.get(ATTR_LINEAGE, "-")
    breeder_logo = breeder_logo or meta.get(ATTR_BREEDER_LOGO)

    fields: dict[str, bool] = data.get("fields") or {}
    content = LabelContent(
        title=strain_name,
        info_lines=_info_lines(phenotype_name, breeder, lineage, fields),
        logo=breeder_logo if breeder_logo and fields.get("logo", True) else None,
        qr_data=_qr_data(hass, plant_id, data) if fields.get("qr", True) else None,
        printed_on=dt_util.now().strftime(_DATE_FORMAT),
    )

    return ClassicPrintRequest(
        content=content,
        label_size=data.get("label_size"),
        density=data.get("density", "normal"),
        device_id=data.get("device_id"),
        preview=data.get("preview", False),
        subject=plant_id or strain_name,
        label_size_id=_canonical_size(data.get("label_size")),
    )


def _canonical_size(classic_key: object) -> str:
    """Map a legacy stock spelling to its canonical identity.

    Unknown and absent sizes retain the Classic contract's documented 50x30
    fallback.  The canonical Template path does not accept this coercion; it
    exists only inside the deprecated adapter.
    """
    requested = classic_key if isinstance(classic_key, str) else None
    for size in LABEL_SIZES.values():
        if size.classic_key == requested:
            return size.id
    for size in LABEL_SIZES.values():
        if size.classic_key == DEFAULT_LABEL_SIZE:
            return size.id
    raise RuntimeError("The Classic default Label Size is absent from the catalogue")


def _info_lines(
    phenotype: str | None,
    breeder: str | None,
    lineage: str | None,
    fields: dict[str, bool],
) -> tuple[str, ...]:
    """Select the body lines, dropping suppressed and placeholder values."""
    candidates = (
        ("phenotype", phenotype),
        ("breeder", breeder),
        ("lineage", lineage),
    )
    return tuple(
        value
        for field, value in candidates
        if fields.get(field, True) and value and value not in _EMPTY_VALUES
    )


def _qr_data(
    hass: HomeAssistant, plant_id: str | None, data: dict[str, Any]
) -> str | None:
    """Resolve the Classic QR route for a plant, or nothing for a strain.

    A strain has no instance to point at, so a strain label carries no QR code
    however the request is flagged. `base_url` is caller-supplied and stays
    confined to this adapter — no canonical binding accepts an arbitrary URL.
    """
    if not plant_id:
        return None
    if data.get("qr_target", "web") == "deeplink":
        return f"homeassistant://navigate/growspace/plant/{plant_id}"
    base_url = data.get("base_url")
    if base_url:
        return f"{base_url}?plantId={plant_id}"
    return f"{get_url(hass)}/plant/{plant_id}"
