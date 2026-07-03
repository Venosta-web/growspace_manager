"""Tests for the AC Infinity grow light configurator (ADR-0023/0024)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.grow_light_ac_infinity import (
    push_ac_infinity_schedule,
)
from custom_components.growspace_manager.models import ACInfinityGrowLight
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant


@pytest.fixture
def mock_hass() -> MagicMock:
    """Return mock HomeAssistant with an async service caller."""
    hass = MagicMock(spec=HomeAssistant)
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    return hass


def _device() -> ACInfinityGrowLight:
    return ACInfinityGrowLight(
        mode_entity="select.port_mode",
        on_time_entity="time.port_on",
        off_time_entity="time.port_off",
        power_entity="number.port_power",
    )


async def test_push_writes_schedule_mode_times_and_power(mock_hass: MagicMock) -> None:
    """The configurator sets Schedule mode, both time entities, and on_power."""
    await push_ac_infinity_schedule(
        mock_hass, _device(), on_time="06:00:00", off_time="18:00:00", power=100
    )

    mock_hass.services.async_call.assert_any_await(
        "select",
        "select_option",
        {ATTR_ENTITY_ID: "select.port_mode", "option": "Schedule"},
        blocking=False,
    )
    mock_hass.services.async_call.assert_any_await(
        "time",
        "set_value",
        {ATTR_ENTITY_ID: "time.port_on", "time": "06:00:00"},
        blocking=False,
    )
    mock_hass.services.async_call.assert_any_await(
        "time",
        "set_value",
        {ATTR_ENTITY_ID: "time.port_off", "time": "18:00:00"},
        blocking=False,
    )
    mock_hass.services.async_call.assert_any_await(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: "number.port_power", "value": 10},
        blocking=False,
    )
    assert mock_hass.services.async_call.await_count == 4


@pytest.mark.parametrize(
    ("power", "intensity"),
    [(100, 10), (50, 5), (5, 1), (0, 1)],
)
async def test_push_scales_power_to_intensity(
    mock_hass: MagicMock, power: int, intensity: int
) -> None:
    """The 0-100 power maps onto the clamped 1-10 AC Infinity intensity."""
    await push_ac_infinity_schedule(
        mock_hass, _device(), on_time="06:00:00", off_time="18:00:00", power=power
    )
    mock_hass.services.async_call.assert_any_await(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: "number.port_power", "value": intensity},
        blocking=False,
    )
