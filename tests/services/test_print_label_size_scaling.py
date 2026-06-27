"""TDD tests for print_label label-size coordinate scaling (issue #402)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.services.strain_library import (
    handle_print_label,
)
from homeassistant.core import HomeAssistant, ServiceCall


@pytest.fixture
def mock_hass() -> MagicMock:
    hass = MagicMock(spec=HomeAssistant)
    hass.config = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock(return_value={"status": "ok"})
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    return hass


@pytest.fixture
def mock_coordinator() -> MagicMock:
    coordinator = MagicMock()
    coordinator.plants = {}
    return coordinator


@pytest.fixture
def mock_strain_library() -> MagicMock:
    lib = MagicMock()
    lib.load = AsyncMock()
    lib.get_all = MagicMock(return_value={})
    return lib


def _make_call(data: dict) -> MagicMock:
    call = MagicMock(spec=ServiceCall)
    call.data = data
    return call


def _niimbot_service_data(mock_hass: MagicMock) -> dict:
    return mock_hass.services.async_call.call_args.args[2]


# ---------------------------------------------------------------------------
# Tracer bullet: default (no label_size) uses 400×240 canvas
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_label_size_uses_400x240_canvas(
    mock_hass: MagicMock,
    mock_coordinator: MagicMock,
    mock_strain_library: MagicMock,
) -> None:
    """Omitting label_size produces the current 400×240 canvas."""
    call = _make_call({"strain": "Blue Dream"})
    await handle_print_label(mock_hass, mock_coordinator, mock_strain_library, call)
    sd = _niimbot_service_data(mock_hass)
    assert sd["width"] == 400
    assert sd["height"] == 240


# ---------------------------------------------------------------------------
# One test per size ID: canvas dimensions + coordinate spot-check
# ---------------------------------------------------------------------------
#
# Spot-check target: strain-header element (first new_multiline in payload).
# Reference values (50x30 canvas):  x=0, y=20, x_end=260, width=250, height=50
#
# 50x30: scale 1:1  → y=20  (unchanged, regression guard)
# 40x30: scale_x=0.8, scale_y=1.0  → x_end=round(260*0.8)=208
# 50x50: scale_x=1.0, scale_y≈1.667  → y=round(20*400/240)=33
# 50x80: scale_x=1.0, scale_y≈2.667  → y=round(20*640/240)=53
# 50x15: scale_x=1.0, scale_y=0.5    → y=round(20*120/240)=10


@pytest.mark.parametrize(
    "label_size, expected_w, expected_h, spot_field, spot_value",
    [
        ("50x30", 400, 240, "y", 20),
        ("40x30", 320, 240, "x_end", 208),
        ("50x50", 400, 400, "y", 33),
        ("50x80", 400, 640, "y", 53),
        ("50x15", 400, 120, "y", 10),
    ],
)
@pytest.mark.asyncio
async def test_label_size_canvas_and_scaled_coordinates(
    mock_hass: MagicMock,
    mock_coordinator: MagicMock,
    mock_strain_library: MagicMock,
    label_size: str,
    expected_w: int,
    expected_h: int,
    spot_field: str,
    spot_value: int,
) -> None:
    """Each size ID maps to the correct canvas and scales element coordinates."""
    call = _make_call({"strain": "Blue Dream", "label_size": label_size})
    await handle_print_label(mock_hass, mock_coordinator, mock_strain_library, call)
    sd = _niimbot_service_data(mock_hass)

    assert sd["width"] == expected_w
    assert sd["height"] == expected_h

    header = next(el for el in sd["payload"] if el.get("type") == "new_multiline")
    assert header[spot_field] == spot_value


# ---------------------------------------------------------------------------
# Backwards compatibility: explicit 50x30 == omitted label_size
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_explicit_50x30_matches_default_output(
    mock_hass: MagicMock,
    mock_coordinator: MagicMock,
    mock_strain_library: MagicMock,
) -> None:
    """Explicit label_size='50x30' produces the same output as omitting label_size."""
    call_default = _make_call({"strain": "Blue Dream"})
    await handle_print_label(mock_hass, mock_coordinator, mock_strain_library, call_default)
    sd_default = _niimbot_service_data(mock_hass)

    mock_hass.services.async_call.reset_mock()

    call_explicit = _make_call({"strain": "Blue Dream", "label_size": "50x30"})
    await handle_print_label(mock_hass, mock_coordinator, mock_strain_library, call_explicit)
    sd_explicit = _niimbot_service_data(mock_hass)

    assert sd_explicit["width"] == sd_default["width"]
    assert sd_explicit["height"] == sd_default["height"]
    assert sd_explicit["payload"] == sd_default["payload"]
