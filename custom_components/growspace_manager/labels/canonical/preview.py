"""The canonical render operation: one implementation, two callers.

`async_render` is the whole of it. A preview and a print differ by one
argument, because the only way a preview can stand in for a print is for both
to be the same code reaching the same adapter with the same compiled payload.
Anything that made a preview cheaper would make it a second renderer, and a
second renderer is the fidelity bug this route exists to end.

What comes back is the raster the printer driver would receive, decoded and
measured rather than taken on trust, alongside the complete Render Context, an
outcome per stable element ID, the ink each one laid down, where that ink
overlaps, every diagnostic of every layer, one eligibility answer per
operation, and the cache identity the pair may be reused under.

Safety is judged before the raster is asked for, not after it comes back: the
policy layer reads the compiled plan and the pinned toolchain, so a layout
that cannot print says why even when the printer integration is missing
entirely.

`imagespec` appears nowhere in this module's interface. A caller supplies a
validated layout, an immutable content snapshot and a profile; the payload
that realises them is the adapter's private business, and no public operation
accepts one.
"""

from __future__ import annotations

import base64
import binascii
from io import BytesIO
from typing import Any

from PIL import Image, UnidentifiedImageError

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from ..niimbot import async_print
from .compiler import compile_layout
from .content import LabelContentSnapshot
from .diagnostics import Diagnostic, Layer, Severity
from .document import LabelLayout
from .factory import FactoryTemplate, factory_template_for_size
from .fonts import FontLibrary, niimbot_font_library
from .profiles import CapabilityProfile, profiles_for_size
from .result import (
    CURRENT,
    FAILED,
    Raster,
    RenderContext,
    RenderResult,
    eligibility_for,
    merged_diagnostics,
)
from .safety import evaluate_safety

#: What the renderer returns its PNG in.
_DATA_URI_PREFIX = "data:image/png;base64,"

PREVIEW = "preview"
PRINT = "print"

#: The stock a preview is of when the caller names none. The one size with a
#: shipped layout and a profile today; it stops being a default the moment a
#: second one has both.
DEFAULT_LABEL_SIZE_ID = "growspace.stock.50x30.v1"


async def async_render(
    hass: HomeAssistant,
    *,
    layout: LabelLayout,
    content: LabelContentSnapshot,
    profile: CapabilityProfile,
    density: str = "normal",
    device_id: str | None = None,
    operation: str = PREVIEW,
    local_calibration: str | None = None,
    fonts: FontLibrary | None = None,
) -> RenderResult:
    """Render one label, as a preview or on paper, through one implementation."""
    compiled = compile_layout(layout, content, profile, density=density)
    library = fonts or _font_library(hass)
    # Measuring ink decodes images and rasterizes glyphs, which is exactly the
    # kind of work the event loop must not do.
    report = await hass.async_add_executor_job(
        evaluate_safety, layout, compiled, profile, library
    )

    context = RenderContext(
        layout_digest=layout.digest,
        label_size_id=layout.label_size_id,
        profile_id=profile.id,
        profile_evidence=str(profile.evidence),
        local_calibration=local_calibration,
        content_identity=content.identity,
        content_context=str(content.context),
        content_source=content.source,
        locale=content.locale,
        time_zone=content.time_zone,
        as_of=content.as_of.isoformat(),
        density=density,
        density_level=profile.density_level(density),
        operation=operation,
        font_identity=report.font_identity,
    )

    raster, raster_diagnostics = await _async_raster(
        hass,
        compiled.plan,
        preview=operation == PREVIEW,
        device_id=device_id,
        subject=content.subject,
    )
    diagnostics = merged_diagnostics(
        compiled.diagnostics, report.diagnostics, raster_diagnostics
    )
    return RenderResult(
        context=context,
        status=CURRENT if raster is not None else FAILED,
        raster=raster,
        outcomes=compiled.outcomes,
        diagnostics=diagnostics,
        profile=profile,
        ink=report.ink,
        overlaps=report.overlaps,
        eligibility=eligibility_for(
            diagnostics,
            raster,
            profile=profile,
            local_calibration=local_calibration,
        ),
    )


def _font_library(hass: HomeAssistant) -> FontLibrary:
    """Resolve the printer integration's fonts for this installation.

    The two faces belong to `niimbot`, not to this integration, so they are
    looked up where that integration keeps them and nowhere else. An
    installation without them measures no text and says so, rather than
    measuring a similarly named face and calling the answer fidelity.
    """
    config_directory = getattr(getattr(hass, "config", None), "config_dir", None)
    return niimbot_font_library(
        config_directory if isinstance(config_directory, str) else None
    )


async def async_render_factory_preview(
    hass: HomeAssistant,
    *,
    content: LabelContentSnapshot,
    label_size_id: str = DEFAULT_LABEL_SIZE_ID,
    template: FactoryTemplate | None = None,
    profile: CapabilityProfile | None = None,
    density: str = "normal",
    fonts: FontLibrary | None = None,
) -> RenderResult:
    """Preview one shipped Factory Template against one subject.

    The convenience the editor and the acceptance tests both want: name a
    template, or let a stock choose its designated one, and let that stock
    choose a compatible profile. Everything after that is `async_render`.

    A stock with no shipped layout, or no profile that can render it, is an
    error naming which of the two is missing. Both are ordinary states while
    the shipped set is still growing, and neither may quietly become a
    preview of some other size.
    """
    shipped = template or factory_template_for_size(label_size_id)
    if shipped is None:
        raise HomeAssistantError(f"No Factory Template is shipped for {label_size_id}")
    layout = shipped.layout
    selected = profile or _first_profile(layout.label_size_id)
    return await async_render(
        hass,
        layout=layout,
        content=content,
        profile=selected,
        density=density,
        operation=PREVIEW,
        fonts=fonts,
    )


def _first_profile(label_size_id: str) -> CapabilityProfile:
    """Return a profile that can render one stock, or say there is none."""
    profiles = profiles_for_size(label_size_id)
    if not profiles:
        raise HomeAssistantError(f"No Capability Profile can render {label_size_id}")
    return profiles[0]


async def _async_raster(
    hass: HomeAssistant,
    plan: Any,
    *,
    preview: bool,
    device_id: str | None,
    subject: str,
) -> tuple[Raster | None, tuple[Diagnostic, ...]]:
    """Ask the printer adapter for the raster, and turn failure into diagnostics.

    A renderer failure and a transport failure are different diagnostics on
    purpose. "Printer offline" standing in for a missing font is exactly the
    conflation the layered model exists to prevent, so an adapter error is
    recorded at the layer it came from and never re-labelled.
    """
    try:
        response = await async_print(
            hass, plan, device_id=device_id, preview=preview, subject=subject
        )
    except HomeAssistantError as err:
        return None, (
            Diagnostic(
                code="raster.render_failed",
                severity=Severity.ERROR,
                layer=Layer.RASTER,
                message=f"The renderer did not produce a raster: {err}",
                parameters={"error": str(err)},
            ),
        )

    image = (response or {}).get("image")
    if not isinstance(image, str) or not image.startswith(_DATA_URI_PREFIX):
        return None, (
            Diagnostic(
                code="raster.missing",
                severity=Severity.ERROR,
                layer=Layer.RASTER,
                message="The renderer returned no PNG for this render.",
            ),
        )

    return await hass.async_add_executor_job(_decode_raster, image)


def _decode_raster(image: str) -> tuple[Raster | None, tuple[Diagnostic, ...]]:
    """Decode and measure the returned PNG.

    In the executor: Pillow initialises its native libraries lazily, so the
    first decode on a fresh install would otherwise block the event loop.
    """
    try:
        payload = base64.b64decode(image.removeprefix(_DATA_URI_PREFIX), validate=True)
        with Image.open(BytesIO(payload)) as decoded:
            decoded.load()
            width, height = decoded.size
            fmt = decoded.format
            colours = decoded.getcolors(2)
            # `getcolors` returns nothing at all once the image exceeds the
            # limit, which is the case that must read as *not* monochrome.
            monochrome = decoded.mode == "1" or (
                colours is not None and len(colours) <= 2
            )
    except (binascii.Error, ValueError, OSError, UnidentifiedImageError) as err:
        return None, (
            Diagnostic(
                code="raster.unreadable",
                severity=Severity.ERROR,
                layer=Layer.RASTER,
                message=f"The returned raster could not be decoded: {err}",
                parameters={"error": str(err)},
            ),
        )

    diagnostics: tuple[Diagnostic, ...] = ()
    if fmt != "PNG":
        diagnostics = (
            Diagnostic(
                code="raster.unexpected_format",
                severity=Severity.WARNING,
                layer=Layer.RASTER,
                message=f"The renderer returned {fmt}, not the expected PNG.",
                parameters={"format": fmt},
            ),
        )

    return (
        Raster(
            content_type="image/png",
            width=width,
            height=height,
            data_uri=image,
            byte_length=len(payload),
            monochrome=monochrome,
        ),
        diagnostics,
    )
