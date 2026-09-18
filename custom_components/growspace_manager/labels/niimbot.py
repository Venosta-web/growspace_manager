"""The Niimbot printer adapter.

The only module that knows what `imagespec` is, what a density number means on
this hardware, or that the `niimbot` integration exists at all. It consumes a
[[Label Render Plan]] and nothing else, which is what makes a second printer a
matter of writing a second adapter rather than a second renderer.

No card command, stored template, or export ever carries `imagespec`: it is
this module's private wire format.
"""

from __future__ import annotations

import base64
from dataclasses import replace
from io import BytesIO
import logging
from typing import Any

from PIL import Image

from custom_components.growspace_manager.exceptions import GrowspaceError
from homeassistant.core import HomeAssistant, ServiceResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .model import (
    Divider,
    FittedText,
    LabelElement,
    LabelRenderPlan,
    Logo,
    QrCode,
    TextBlock,
    TextLine,
)

_LOGGER = logging.getLogger(__name__)

NIIMBOT_DOMAIN = "niimbot"
NIIMBOT_PRINT_SERVICE = "print"

#: Symbolic density to this hardware's 1-8 scale. A word means different heat
#: on different printers, which is why the plan keeps it symbolic and the
#: mapping lives here.
_DENSITY_LEVELS = {"low": 3, "normal": 5, "high": 8}
_DEFAULT_DENSITY = 5

#: Above this, a data-URI logo risks Home Assistant's 32 KB event bus limit and
#: the printer's own buffer, so it is re-encoded before it is sent.
_MAX_LOGO_DATA_URI = 25000

#: What an oversized logo is thumbnailed to. Matches the logo box the Classic
#: design reserves.
_LOGO_THUMBNAIL = (100, 100)

#: The errors a misconfigured printer, a bad payload or an absent `niimbot`
#: integration surface as. Anything else is a bug here and must not be masked.
_PRINT_ERRORS = (
    AttributeError,
    KeyError,
    ValueError,
    ServiceValidationError,
    GrowspaceError,
)

#: What a logo that cannot be re-encoded raises. Carried over verbatim from the
#: fixed-coordinate implementation: it is wider than PIL alone needs, and
#: narrowing it is a behaviour change rather than part of moving the code.
_LOGO_DECODE_ERRORS = (
    AttributeError,
    KeyError,
    ValueError,
    ServiceValidationError,
    GrowspaceError,
)


async def async_print(
    hass: HomeAssistant,
    plan: LabelRenderPlan,
    *,
    device_id: str | None = None,
    preview: bool = False,
    subject: str,
) -> ServiceResponse:
    """Send one render plan to a Niimbot printer, or render it as a preview.

    `preview` is the same call with the same payload — the printer integration
    returns the raster instead of committing it to paper. Preview and print
    therefore cannot drift, which is the property the seam exists to keep.
    """
    plan = await _with_printable_logos(hass, plan)

    service_data: dict[str, Any] = {
        "width": plan.canvas.width,
        "height": plan.canvas.height,
        "rotate": 0,
        "density": _density(plan),
        "payload": [_imagespec(element) for element in plan.elements],
        "preview": preview,
    }
    if device_id:
        service_data["device_id"] = device_id

    try:
        response = await hass.services.async_call(
            NIIMBOT_DOMAIN,
            NIIMBOT_PRINT_SERVICE,
            service_data,
            blocking=True,
            return_response=True,
        )
    except _PRINT_ERRORS as err:
        _LOGGER.error("Failed to print Niimbot label: %s", err)
        raise HomeAssistantError(f"Failed to print Niimbot label: {err}") from err
    else:
        _LOGGER.info("Sent label to Niimbot for %s", subject)
        return response


def _density(plan: LabelRenderPlan) -> int:
    """Resolve the plan's density to this hardware's 1-8 scale.

    A plan compiled against a [[Capability Profile]] arrives with the device
    value already chosen from that printer class's own valid range, and it
    wins: the global table below is the Classic path's, and its top value is
    out of range on several printers this adapter can reach.
    """
    if plan.density_level is not None:
        return plan.density_level
    return _DENSITY_LEVELS.get(plan.density, _DEFAULT_DENSITY)


def _imagespec(element: LabelElement) -> dict[str, Any]:
    """Compile one placed element into its `imagespec` entry."""
    if isinstance(element, TextBlock):
        return {
            "type": "new_multiline",
            "value": element.value,
            "x": element.x,
            "y": element.y,
            "x_end": element.x_end,
            "size": element.size,
            "width": element.width,
            "height": element.height,
            "fit": element.fit,
            "font": element.font,
        }
    if isinstance(element, TextLine):
        return {
            "type": "text",
            "value": element.value,
            "x": element.x,
            "y": element.y,
            "size": element.size,
            "font": element.font,
        }
    if isinstance(element, FittedText):
        return {
            "type": "text_fit",
            "value": element.value,
            "x": element.x,
            "y": element.y,
            "width": element.width,
            "height": element.height,
            "size": element.size,
            "min_size": element.min_size,
            "max_lines": element.max_lines,
            "line_spacing": element.line_spacing,
            "align": element.align,
            "valign": element.valign,
            "fit": element.fit,
            "ellipsis": element.ellipsis,
            "font": element.font,
        }
    if isinstance(element, Divider):
        return {
            "type": "rectangle",
            "x_start": element.x_start,
            "x_end": element.x_end,
            "y_start": element.y_start,
            "y_end": element.y_end,
            "fill": element.fill,
        }
    if isinstance(element, Logo):
        return _optional(
            {
                "type": "dlimg",
                "url": element.url,
                "x": element.x,
                "y": element.y,
                "xsize": element.xsize,
                "ysize": element.ysize,
            },
            mode=element.mode,
            dither=element.dither,
        )
    if isinstance(element, QrCode):
        return _optional(
            {
                "type": "qrcode",
                "data": element.data,
                "x": element.x,
                "y": element.y,
                "boxsize": element.boxsize,
            },
            width=element.width,
            height=element.height,
            border=element.border,
            eclevel=element.error_correction,
        )
    raise TypeError(f"No Niimbot compilation for label element {element!r}")


def _optional(payload: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """Add the keys the canonical path sets, leaving the Classic payload alone.

    An unset key is absent rather than null: the Classic golden payloads are
    exact, and `imagespec` reads a present key before it reads its default.
    """
    payload.update({key: value for key, value in extra.items() if value is not None})
    return payload


async def _with_printable_logos(
    hass: HomeAssistant, plan: LabelRenderPlan
) -> LabelRenderPlan:
    """Re-encode any logo too large to survive the bus and the print buffer.

    Runs in the executor: PIL initialises its native libraries lazily, so the
    first decode on a fresh install would otherwise block the event loop.
    """
    elements = list(plan.elements)
    for index, element in enumerate(elements):
        if not isinstance(element, Logo):
            continue
        url = await hass.async_add_executor_job(_downscale_logo_if_needed, element.url)
        elements[index] = replace(element, url=url)
    return replace(plan, elements=tuple(elements))


def _downscale_logo_if_needed(logo_data: str) -> str:
    """Downscale a breeder logo if it is a large base64 string, else pass it on."""
    if not logo_data or not logo_data.startswith("data:image/"):
        return logo_data

    # If the string is already small enough, skip processing
    if len(logo_data) < _MAX_LOGO_DATA_URI:
        return logo_data

    try:
        # Extract base64 part
        _, encoded = logo_data.split(",", 1)
        image_data = base64.b64decode(encoded)

        # Load image
        img: Image.Image = Image.open(BytesIO(image_data))

        img.thumbnail(_LOGO_THUMBNAIL)

        # Save back to base64 as PNG (Niimbot handles data URIs)
        output = BytesIO()
        img.save(output, format="PNG", optimize=True)
        new_encoded = base64.b64encode(output.getvalue()).decode("utf-8")
        result = f"data:image/png;base64,{new_encoded}"

        # If it's still large due to complexity, convert to 1-bit monochrome
        if len(result) >= _MAX_LOGO_DATA_URI:
            if img.mode in ("RGBA", "LA") or (
                img.mode == "P" and "transparency" in img.info
            ):
                img = img.convert("RGBA")
                background = Image.new("RGB", img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[3])
                img = background

            img = img.convert("1")
            output = BytesIO()
            img.save(output, format="PNG", optimize=True)
            new_encoded = base64.b64encode(output.getvalue()).decode("utf-8")
            result = f"data:image/png;base64,{new_encoded}"

    except _LOGO_DECODE_ERRORS as err:
        _LOGGER.warning("Failed to downscale breeder logo: %s", err)
        return logo_data
    else:
        return result
