"""Tests for the Niimbot printer adapter.

The adapter is the only module that knows `imagespec`, the device's density
scale, or that a logo may be too large to put on the bus. Everything above it
speaks `LabelRenderPlan`.
"""

from __future__ import annotations

import base64
from dataclasses import replace
from io import BytesIO
import os
import random
from unittest.mock import AsyncMock, MagicMock, patch

from PIL import Image
import pytest

from custom_components.growspace_manager.labels.model import (
    Canvas,
    Divider,
    FittedText,
    LabelRenderPlan,
    Logo,
    QrCode,
    TextBlock,
    TextLine,
)
from custom_components.growspace_manager.labels.niimbot import (
    _downscale_logo_if_needed,
    _imagespec,
    async_print,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError


def _hass() -> MagicMock:
    hass = MagicMock(spec=HomeAssistant)
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock(return_value={"status": "ok"})
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *a: func(*a))
    return hass


def _plan(*elements: object, density: str = "normal") -> LabelRenderPlan:
    return LabelRenderPlan(
        canvas=Canvas(width=400, height=240),
        elements=tuple(elements),  # type: ignore[arg-type]
        density=density,
    )


# ---------------------------------------------------------------------------
# imagespec compilation
# ---------------------------------------------------------------------------


def test_every_element_variant_compiles_to_its_imagespec_type() -> None:
    """Each variant keeps the wire `type` the niimbot integration expects."""
    compiled = [
        _imagespec(
            TextBlock(
                value="X",
                x=0,
                y=1,
                x_end=2,
                width=3,
                height=4,
                size=5,
                font="ppb.ttf",
            )
        ),
        _imagespec(TextLine(value="X", x=0, y=1, size=2, font="rbm.ttf")),
        _imagespec(Divider(x_start=0, x_end=1, y_start=2, y_end=3)),
        _imagespec(Logo(url="u", x=0, y=1, xsize=2, ysize=3)),
        _imagespec(QrCode(data="d", x=0, y=1, boxsize=3)),
    ]
    assert [item["type"] for item in compiled] == [
        "new_multiline",
        "text",
        "rectangle",
        "dlimg",
        "qrcode",
    ]


def test_an_unknown_element_refuses_rather_than_printing_nothing() -> None:
    """A new element variant must fail loudly until the adapter learns it."""
    with pytest.raises(TypeError, match="No Niimbot compilation"):
        _imagespec(object())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# density, canvas, and transport fields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("symbolic", "expected"),
    [("low", 3), ("normal", 5), ("high", 8), ("scorching", 5)],
)
@pytest.mark.asyncio
async def test_symbolic_density_maps_onto_the_device_scale(
    symbolic: str, expected: int
) -> None:
    """The plan stays symbolic; only the adapter knows what the word costs."""
    hass = _hass()
    await async_print(hass, _plan(density=symbolic), subject="s")
    assert hass.services.async_call.call_args.args[2]["density"] == expected


@pytest.mark.asyncio
async def test_the_plan_canvas_becomes_the_printed_extent() -> None:
    hass = _hass()
    plan = LabelRenderPlan(
        canvas=Canvas(width=320, height=640), elements=(), density="normal"
    )
    await async_print(hass, plan, subject="s")
    service_data = hass.services.async_call.call_args.args[2]
    assert (service_data["width"], service_data["height"]) == (320, 640)


@pytest.mark.asyncio
async def test_device_id_is_omitted_rather_than_sent_empty() -> None:
    """An absent printer means "the configured one", not a blank device."""
    hass = _hass()
    await async_print(hass, _plan(), subject="s")
    assert "device_id" not in hass.services.async_call.call_args.args[2]

    hass = _hass()
    await async_print(hass, _plan(), device_id="b21", subject="s")
    assert hass.services.async_call.call_args.args[2]["device_id"] == "b21"


@pytest.mark.asyncio
async def test_preview_sends_the_same_payload_as_a_print() -> None:
    """The fidelity guarantee: preview differs by one flag and nothing else."""
    printed = _hass()
    await async_print(
        printed, _plan(TextLine(value="X", x=1, y=2, size=6, font="f")), subject="s"
    )
    previewed = _hass()
    await async_print(
        previewed,
        _plan(TextLine(value="X", x=1, y=2, size=6, font="f")),
        preview=True,
        subject="s",
    )

    as_printed = printed.services.async_call.call_args.args[2]
    as_previewed = previewed.services.async_call.call_args.args[2]
    assert as_printed["preview"] is False
    assert as_previewed["preview"] is True
    assert {k: v for k, v in as_printed.items() if k != "preview"} == {
        k: v for k, v in as_previewed.items() if k != "preview"
    }


@pytest.mark.asyncio
async def test_a_printer_failure_surfaces_as_a_home_assistant_error() -> None:
    hass = _hass()
    hass.services.async_call = AsyncMock(side_effect=ValueError("Service error"))
    with pytest.raises(HomeAssistantError, match="Failed to print Niimbot label"):
        await async_print(hass, _plan(), subject="s")


# ---------------------------------------------------------------------------
# logo preparation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_plan_without_a_logo_never_touches_the_executor() -> None:
    """Decoding is only paid for when there is an image to decode."""
    hass = _hass()
    await async_print(
        hass, _plan(TextLine(value="X", x=1, y=2, size=6, font="f")), subject="s"
    )
    hass.async_add_executor_job.assert_not_called()


@pytest.mark.asyncio
async def test_a_logo_is_prepared_off_the_event_loop() -> None:
    """PIL initialises native libraries lazily, so the first decode must not block."""
    hass = _hass()
    await async_print(
        hass, _plan(Logo(url="http://x/y.png", x=0, y=0, xsize=1, ysize=1)), subject="s"
    )
    hass.async_add_executor_job.assert_called_once()
    assert hass.services.async_call.call_args.args[2]["payload"][0]["url"] == (
        "http://x/y.png"
    )


def test_downscale_logo_if_needed_small() -> None:
    """Test _downscale_logo_if_needed returns early if the string is small."""
    logo_data = "data:image/png;base64,abc"
    result = _downscale_logo_if_needed(logo_data)
    assert result == logo_data


def test_downscale_logo_if_needed_not_image() -> None:
    """A URL a printer will fetch itself is passed straight through."""
    logo_data = "https://example.com/logo.png"
    assert _downscale_logo_if_needed(logo_data) == logo_data
    assert _downscale_logo_if_needed("") == ""


def test_downscale_logo_if_needed_large_rgba_to_monochrome() -> None:
    """Test _downscale_logo_if_needed downscales large RGBA image and converts to monochrome."""
    # Create a 100x100 RGBA image with random bytes to exceed 25000 bytes when encoded
    img = Image.frombytes("RGBA", (100, 100), os.urandom(100 * 100 * 4))
    buff = BytesIO()
    img.save(buff, format="PNG")
    large_rgba_base64 = (
        f"data:image/png;base64,{base64.b64encode(buff.getvalue()).decode()}"
    )

    # Ensure our constructed image is indeed large enough (> 25000 chars)
    assert len(large_rgba_base64) >= 25000

    result = _downscale_logo_if_needed(large_rgba_base64)

    assert result.startswith("data:image/png;base64,")
    _, encoded = result.split(",", 1)
    decoded_img = Image.open(BytesIO(base64.b64decode(encoded)))
    # The output should be downscaled and converted to mode "1" (monochrome)
    assert decoded_img.width <= 100
    assert decoded_img.height <= 100
    assert decoded_img.mode == "1"


def test_downscale_logo_if_needed_exception_handling() -> None:
    """Test _downscale_logo_if_needed exception handling."""
    # Create a base64 string that is large enough (> 25000 characters)
    large_logo = "data:image/png;base64," + "A" * 25000

    with patch("PIL.Image.open", side_effect=ValueError("Mock ValueError")):
        result = _downscale_logo_if_needed(large_logo)
        assert result == large_logo


# ---------------------------------------------------------------------------
# The elements the canonical path adds (hub issue #214)
# ---------------------------------------------------------------------------


def test_fitted_text_compiles_to_the_renderer_s_bounded_primitive() -> None:
    compiled = _imagespec(
        FittedText(
            value="Blue Dream",
            x=16,
            y=16,
            width=344,
            height=67,
            size=45,
            font="ppb.ttf",
            min_size=24,
            max_lines=2,
            line_spacing=2,
            align="left",
            valign="center",
            fit="shrink_ellipsis",
        )
    )
    assert compiled == {
        "type": "text_fit",
        "value": "Blue Dream",
        "x": 16,
        "y": 16,
        "width": 344,
        "height": 67,
        "size": 45,
        "min_size": 24,
        "max_lines": 2,
        "line_spacing": 2,
        "align": "left",
        "valign": "center",
        "fit": "shrink_ellipsis",
        "ellipsis": "…",
        "font": "ppb.ttf",
    }


def test_an_unset_optional_key_is_absent_rather_than_null() -> None:
    """The Classic golden payloads are exact, and a present key wins over a default."""
    logo = _imagespec(Logo(url="u", x=0, y=1, xsize=2, ysize=3))
    qr = _imagespec(QrCode(data="d", x=0, y=1, boxsize=3))
    assert set(logo) == {"type", "url", "x", "y", "xsize", "ysize"}
    assert set(qr) == {"type", "data", "x", "y", "boxsize"}


def test_a_canonical_logo_carries_its_fit_and_its_monochrome_policy() -> None:
    compiled = _imagespec(
        Logo(url="u", x=0, y=1, xsize=2, ysize=3, mode="contain", dither=False)
    )
    assert compiled["mode"] == "contain"
    # `False` is a choice the monochrome token made, not an unset key.
    assert compiled["dither"] is False


def test_a_canonical_qr_is_sized_by_its_box() -> None:
    compiled = _imagespec(
        QrCode(
            data="http://ha.test/plant/1",
            x=10,
            y=20,
            boxsize=1,
            width=80,
            height=80,
            border=4,
            error_correction="h",
        )
    )
    assert compiled["width"] == compiled["height"] == 80
    assert compiled["border"] == 4
    assert compiled["eclevel"] == "h"


# ---------------------------------------------------------------------------
# Density
# ---------------------------------------------------------------------------


async def test_a_profile_resolved_density_wins_over_the_global_table() -> None:
    """The global map's top value is out of range on every B-series printer."""
    hass = _hass()
    plan = replace(_plan(density="high"), density_level=5)
    await async_print(hass, plan, subject="s")
    assert hass.services.async_call.await_args.args[2]["density"] == 5


async def test_a_plan_without_a_resolved_density_falls_back_unchanged() -> None:
    hass = _hass()
    await async_print(hass, _plan(density="high"), subject="s")
    assert hass.services.async_call.await_args.args[2]["density"] == 8


async def test_an_unknown_symbolic_density_still_has_a_default() -> None:
    hass = _hass()
    await async_print(hass, _plan(density="scorching"), subject="s")
    assert hass.services.async_call.await_args.args[2]["density"] == 5


# ---------------------------------------------------------------------------
# The two outcomes of the logo downscaler's second pass
# ---------------------------------------------------------------------------


def test_a_logo_the_thumbnail_alone_shrinks_enough_keeps_its_greys() -> None:
    """Flattening to one bit is the fallback, not the first move.

    A large detailed logo whose 100x100 thumbnail compresses comfortably: the
    ordinary case, and the one where throwing away every grey would be a
    gratuitous loss of the breeder's mark.
    """
    detailed = Image.linear_gradient("L").resize((1200, 1200)).convert("RGB")
    detailed.paste(
        Image.frombytes("RGB", (150, 150), random.Random(0).randbytes(150 * 150 * 3)),
        (0, 0),
    )
    buffer = BytesIO()
    detailed.save(buffer, format="PNG")
    original = f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode()}"
    assert len(original) >= 25000

    result = _downscale_logo_if_needed(original)
    assert len(result) < 25000
    _, encoded = result.split(",", 1)
    with Image.open(BytesIO(base64.b64decode(encoded))) as decoded:
        assert decoded.size == (100, 100)
        assert decoded.mode != "1"


def test_an_opaque_logo_that_resists_the_thumbnail_is_flattened_to_one_bit() -> None:
    """The RGBA case is covered above; this is the arc with no alpha to composite.

    The bus limit is 32 KB and the printer's buffer is smaller still, so a
    logo whose noise survives resizing loses its greys rather than its place.
    """
    noise = Image.frombytes("RGB", (200, 200), os.urandom(200 * 200 * 3))
    buffer = BytesIO()
    noise.save(buffer, format="PNG")
    original = f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode()}"
    assert len(original) >= 25000

    result = _downscale_logo_if_needed(original)
    assert len(result) < len(original)
    _, encoded = result.split(",", 1)
    with Image.open(BytesIO(base64.b64decode(encoded))) as decoded:
        assert decoded.mode == "1"
        assert decoded.size == (100, 100)
