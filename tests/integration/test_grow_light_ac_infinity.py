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
    hass.states = MagicMock()
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


def _hass_with_states(mock_hass: MagicMock, states: dict[str, str | None]) -> None:
    """Wire mock_hass.states.get to return the given per-entity state values."""

    def _get(entity_id: str) -> MagicMock | None:
        value = states.get(entity_id)
        if value is None:
            return None
        st = MagicMock()
        st.state = value
        return st

    mock_hass.states.get.side_effect = _get


def _matching_states() -> dict[str, str]:
    return {
        "select.port_mode": "Schedule",
        "time.port_on": "06:00:00",
        "time.port_off": "18:00:00",
        "number.port_power": "10.0",
    }


async def test_schedule_matches_when_device_already_holds_it(
    mock_hass: MagicMock,
) -> None:
    """No re-push is needed when the device already holds the desired schedule."""
    from custom_components.growspace_manager.grow_light_ac_infinity import (
        ac_infinity_schedule_matches,
    )

    _hass_with_states(mock_hass, _matching_states())
    assert (
        ac_infinity_schedule_matches(
            mock_hass, _device(), on_time="06:00:00", off_time="18:00:00", power=100
        )
        is True
    )


@pytest.mark.parametrize(
    "override",
    [
        {"select.port_mode": "On"},  # not in Schedule mode
        {"time.port_on": "07:00:00"},  # on-time drifted
        {"time.port_off": "20:00:00"},  # off-time drifted (e.g. missed flip)
        {"number.port_power": "8.0"},  # power drifted
        {"select.port_mode": None},  # entity unavailable
        {"number.port_power": "unknown"},  # unparseable power
    ],
)
async def test_schedule_mismatch_requires_push(
    mock_hass: MagicMock, override: dict[str, str | None]
) -> None:
    """Any drift from the desired schedule (or a missing reading) needs a push."""
    from custom_components.growspace_manager.grow_light_ac_infinity import (
        ac_infinity_schedule_matches,
    )

    states = _matching_states() | override
    _hass_with_states(mock_hass, states)
    assert (
        ac_infinity_schedule_matches(
            mock_hass, _device(), on_time="06:00:00", off_time="18:00:00", power=100
        )
        is False
    )
