"""The Compatibility Adapter for the Classic `print_label` request.

The only module that understands the pre-template request shape: a subject
given as either `plant_id` or a bare strain, caller-supplied breeder/lineage
overrides, the strain-library meta fallback behind them, the `fields`
visibility flags, `base_url`, and `qr_target`. It resolves all of that exactly
once and then paints through the same compiler and rasterizer every Label
Template uses:

    request -> compatibility content snapshot   (what this label says)
            -> compatibility layout             (legacy size x visible fields)
            -> compatibility profile            (the legacy raster, provisional)
            -> canonical.compile_layout         -> LabelRenderPlan
            -> niimbot adapter                  -> paper or preview

None of the three inputs is state. A Classic request writes no template, no
draft, no default and no capability, and its layout binds a namespace no
Template can bind (see `canonical.compatibility`).

Compatibility preserves what a supported request meant, not what a driver
happened to do with it. A printer this adapter knows cannot carry the raster,
or cannot accept the density, is refused here by name before anything is sent,
rather than left to the firmware to crop, reject or corrupt.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING, Any

from custom_components.growspace_manager.const import (
    ATTR_BREEDER,
    ATTR_BREEDER_LOGO,
    ATTR_LINEAGE,
    ATTR_PHENOTYPE,
    ATTR_STRAIN,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.network import get_url
from homeassistant.util import dt as dt_util

from .canonical import compatibility as compat, preview
from .canonical.canonicalization import digest
from .canonical.catalogue import PrintContext
from .canonical.compiler import CompiledLabel, compile_layout
from .canonical.diagnostics import Severity
from .canonical.document import LabelLayout
from .canonical.profiles import CapabilityProfile
from .niimbot import async_print_inputs, async_raster_inputs, printer_limits

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
    from custom_components.growspace_manager.strain_library import StrainLibrary

_LOGGER = logging.getLogger(__name__)

#: Values the card and the strain library both use to mean "nothing recorded".
#: They must never reach the label as literal text.
_EMPTY_VALUES = ("-", "–")

#: The phenotype name the card sends for a strain with no named phenotype.
_DEFAULT_PHENOTYPE = "default"

_DATE_FORMAT = "%d.%m.%Y"

#: How far past a known printhead a Classic raster may run and still be sent.
#:
#: Every 50 mm Classic label is a 400-pixel raster, and the B1 and B21 heads
#: are 384 dots: their firmware has always dropped the last 16 columns, and
#: released cards print that way on the one printer this product is verified
#: on. That overhang is a known, accepted legacy deviation -- the canonical
#: path compiles onto 48 mm precisely to avoid it -- and it is kept so those
#: cards keep printing. It is the whole tolerance, and it must be settled
#: before the fixed renderer is removed (hub #232). A raster any wider, such as
#: a 50 mm label on a 96-dot D110 head, cannot print and is refused.
CLASSIC_PRINTHEAD_OVERHANG = 16


@dataclass(frozen=True, slots=True)
class ClassicPrintRequest:
    """Immutable transient canonical inputs for one Classic request.

    None of these is a Template Revision, a draft or a default, and the
    layout cannot become one: document validation refuses it.
    """

    content: compat.CompatibilityContentSnapshot
    layout: LabelLayout
    profile: CapabilityProfile
    #: The symbolic Classic density, after the legacy fallback to `normal`.
    density: str
    device_id: str | None
    preview: bool
    #: Plant id where there was one, else the strain -- for logging only.
    subject: str
    #: The legacy size, after the legacy fallback to 50x30.
    classic_size: str
    #: The versioned compatibility layout: version, legacy size, visible fields.
    layout_id: str

    @property
    def label_size_id(self) -> str:
        """The canonical stock identity this request prints on."""
        return self.layout.label_size_id


async def async_compatibility_print(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    data: dict[str, Any],
) -> dict[str, Any] | None:
    """Resolve, compile, check and send one legacy request.

    The response is whatever the printer integration answered, exactly as a
    released card has always received it. The canonical identities behind it
    are logged rather than added, because the legacy response has no field an
    old card is guaranteed to ignore.
    """
    request = await resolve_classic_request(hass, coordinator, strain_library, data)
    compiled = compile_classic(request)
    refuse_unsafe_printer(hass, request, compiled)
    inputs = await async_raster_inputs(hass, compiled.plan)
    _LOGGER.info(
        "Classic label for %s: layout %s, content %s, raster %s",
        request.subject,
        request.layout_id,
        request.content.identity,
        digest(inputs),
    )
    return await async_print_inputs(
        hass,
        inputs,
        device_id=request.device_id,
        preview=request.preview,
        subject=request.subject,
    )


def compile_classic(request: ClassicPrintRequest) -> CompiledLabel:
    """Compile one Classic request through the canonical compiler.

    A compatibility layout that does not compile cleanly is a defect in this
    adapter rather than in the request, so it is an error rather than a label
    with pieces missing.
    """
    compiled = compile_layout(
        request.layout, request.content, request.profile, density=request.density
    )
    errors = sorted(
        {item.code for item in compiled.diagnostics if item.severity is Severity.ERROR}
    )
    if errors:
        raise HomeAssistantError(
            f"Classic label for {request.subject} could not be compiled: "
            + ", ".join(errors)
        )
    return compiled


def refuse_unsafe_printer(
    hass: HomeAssistant, request: ClassicPrintRequest, compiled: CompiledLabel
) -> None:
    """Refuse a raster or density the selected printer's driver cannot take.

    Only models the Niimbot adapter has driver limits for are judged. An
    unknown model, or no printer named at all, is sent as it always was:
    refusing it would be a guess, and a guess is not a safety correction.
    Preview is judged too, so a preview never shows a label its print refuses.
    """
    if not request.device_id:
        return
    model = preview.device_model(hass, request.device_id)
    limits = printer_limits(model)
    if limits is None:
        return

    plan = compiled.plan
    if plan.canvas.width > limits.printhead_pixels + CLASSIC_PRINTHEAD_OVERHANG:
        raise ServiceValidationError(
            f"A {request.classic_size} label is a {plan.canvas.width}-pixel raster "
            f"and the {model} printhead is {limits.printhead_pixels} pixels wide, "
            "so it cannot print. Choose a printer that takes this label size."
        )
    level = plan.density_level
    if level is not None and not limits.accepts_density(level):
        raise ServiceValidationError(
            f"Density {request.density!r} is level {level}, and the {model} "
            f"accepts {limits.density_min}-{limits.density_max}. Choose another "
            "density."
        )


async def resolve_classic_request(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    data: dict[str, Any],
) -> ClassicPrintRequest:
    """Turn one Classic `print_label` request into transient canonical inputs."""
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

    # The library is the fallback behind every caller-supplied override, so it
    # has to be loaded even when the caller supplied all three.
    await strain_library.load()
    meta = strain_library.get_all().get(strain_name, {}).get("meta", {})
    breeder = breeder or meta.get(ATTR_BREEDER)
    lineage = lineage or meta.get(ATTR_LINEAGE)
    breeder_logo = breeder_logo or meta.get(ATTR_BREEDER_LOGO)

    size = compat.classic_size(data.get("label_size"))
    visible = compat.visible_fields(data.get("fields"))
    now = dt_util.now()
    content = compat.compatibility_snapshot(
        context=PrintContext.PLANT if plant_id else PrintContext.STRAIN,
        subject=plant_id or strain_name,
        as_of=now,
        values={
            compat.TITLE: strain_name,
            compat.DETAIL_BINDINGS["phenotype"]: _printable(
                None if phenotype_name == _DEFAULT_PHENOTYPE else phenotype_name
            ),
            compat.DETAIL_BINDINGS["breeder"]: _printable(breeder),
            compat.DETAIL_BINDINGS["lineage"]: _printable(lineage),
            compat.LOGO: breeder_logo,
            # Resolved only when it will print: the web route needs Home
            # Assistant to know its own URL, and a label with its QR code
            # switched off must not fail for want of one.
            compat.QR: _qr_data(hass, plant_id, data) if "qr" in visible else None,
            compat.PRINTED_ON: now.strftime(_DATE_FORMAT),
        },
    )

    density = data.get("density")
    return ClassicPrintRequest(
        content=content,
        layout=compat.compatibility_layout(size, visible),
        profile=compat.compatibility_profile(size),
        # Classic has always printed an unrecognised density at its default.
        density=(
            density
            if isinstance(density, str) and density in compat.CLASSIC_DENSITY_LEVELS
            else "normal"
        ),
        device_id=data.get("device_id"),
        preview=data.get("preview", False),
        subject=plant_id or strain_name,
        classic_size=size,
        layout_id=compat.layout_id(size, visible),
    )


def _printable(value: str | None) -> str | None:
    """Drop a blank or placeholder value, which must never print as text."""
    if not value or value in _EMPTY_VALUES:
        return None
    return value


def _qr_data(
    hass: HomeAssistant, plant_id: str | None, data: dict[str, Any]
) -> str | None:
    """Resolve the Classic QR route for a plant, or nothing for a strain.

    A strain has no instance to point at, so a strain label carries no QR code
    however the request is flagged. `base_url` is caller-supplied and stays
    confined to this adapter -- no canonical binding accepts an arbitrary URL.
    """
    if not plant_id:
        return None
    if data.get("qr_target", "web") == "deeplink":
        return f"homeassistant://navigate/growspace/plant/{plant_id}"
    base_url = data.get("base_url")
    if base_url:
        return f"{base_url}?plantId={plant_id}"
    return f"{get_url(hass)}/plant/{plant_id}"
