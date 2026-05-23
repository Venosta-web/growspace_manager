"""Tests for irrigation safety guard enforcement: daily volume caps and cycle limits."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from custom_components.growspace_manager.const import (
    ATTR_GROWSPACE_ID,
    CATEGORY_ALERT,
    DOMAIN,
    EVENT_GROWSPACE_LOG_ENTRY,
)
from custom_components.growspace_manager.irrigation_coordinator import (
    IrrigationCoordinator,
)
from custom_components.growspace_manager.models import Growspace, IrrigationConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

GROWSPACE_ID = "test_growspace"
ENTRY_ID = "test_entry_id"


@pytest.fixture
def base_irrigation_config() -> IrrigationConfig:
    """Create an IrrigationConfig with safety guards configured."""
    return IrrigationConfig(
        irrigation_pump_entity="switch.irrigation_pump",
        irrigation_duration=30,
        pump_flow_rate_ml_per_sec=10.0,  # 10 ml/s → 30s = 0.3 L per cycle
        max_cycles_per_day=3,
        daily_volume_cap_liters=1.0,
        log_to_logbook=True,
    )


@pytest.fixture
def mock_main_coordinator(base_irrigation_config: IrrigationConfig) -> MagicMock:
    """Mock the main GrowspaceCoordinator."""
    coordinator = MagicMock()
    coordinator.growspaces = {
        GROWSPACE_ID: Growspace(
            id=GROWSPACE_ID,
            name="Test Growspace",
            irrigation_config=base_irrigation_config,
        )
    }
    coordinator.async_refresh_growspace_data = AsyncMock()
    coordinator.async_commit = AsyncMock()
    coordinator.async_set_updated_data = MagicMock()
    coordinator.add_event = MagicMock()
    return coordinator


@pytest.fixture
def mock_hass(mock_main_coordinator: MagicMock) -> MagicMock:
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.services = AsyncMock()
    hass.async_create_task = asyncio.create_task
    type(hass).loop = property(lambda self: asyncio.get_running_loop())
    hass.data = {DOMAIN: {}}
    # Report switch as already "on" so _async_wait_for_switch_state returns immediately
    mock_state = MagicMock()
    mock_state.state = "on"
    hass.states = MagicMock()
    hass.states.get.return_value = mock_state
    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()
    return hass


@pytest.fixture
def mock_config_entry() -> MagicMock:
    """Mock Config Entry."""
    entry = MagicMock(spec=ConfigEntry)
    entry.options = {}
    entry.entry_id = ENTRY_ID
    return entry


@pytest.fixture
def irrigation_coordinator(
    mock_hass: MagicMock,
    mock_config_entry: MagicMock,
    mock_main_coordinator: MagicMock,
) -> IrrigationCoordinator:
    """Create an IrrigationCoordinator for testing."""
    coord = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    mock_config_entry.runtime_data = mock_main_coordinator
    return coord


# ---------------------------------------------------------------------------
# Cycle counter increments
# ---------------------------------------------------------------------------


async def test_cycles_today_increments_after_successful_run(
    irrigation_coordinator: IrrigationCoordinator,
) -> None:
    """Completing an irrigation cycle increments cycles_today by 1."""
    assert irrigation_coordinator.cycles_today == 0

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await irrigation_coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, {}
        )

    assert irrigation_coordinator.cycles_today == 1


async def test_cycles_today_increments_per_cycle(
    irrigation_coordinator: IrrigationCoordinator,
) -> None:
    """Each completed irrigation cycle increments cycles_today."""
    with patch("asyncio.sleep", new_callable=AsyncMock):
        await irrigation_coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, {}
        )
        await irrigation_coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, {}
        )

    assert irrigation_coordinator.cycles_today == 2


# ---------------------------------------------------------------------------
# Cycle limit enforcement
# ---------------------------------------------------------------------------


async def test_cycle_skipped_when_max_cycles_reached(
    irrigation_coordinator: IrrigationCoordinator,
    mock_hass: MagicMock,
) -> None:
    """When cycles_today >= max_cycles_per_day, the cycle is skipped."""
    irrigation_coordinator._cycles_today = 3  # Already at the configured limit of 3

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await irrigation_coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, {}
        )

    # Pump must NOT be turned on when skipped
    mock_hass.services.async_call.assert_not_called()
    # sleep should not be called either (no cycle ran)
    mock_sleep.assert_not_called()
    # Counter must remain unchanged
    assert irrigation_coordinator.cycles_today == 3


async def test_cycle_runs_when_below_max_cycles(
    irrigation_coordinator: IrrigationCoordinator,
    mock_hass: MagicMock,
) -> None:
    """Cycle runs normally when cycles_today < max_cycles_per_day."""
    irrigation_coordinator._cycles_today = 2  # Below limit of 3

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await irrigation_coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, {}
        )

    mock_hass.services.async_call.assert_any_call(
        "switch", "turn_on", {"entity_id": "switch.irrigation_pump"}, blocking=True
    )
    assert irrigation_coordinator.cycles_today == 3


async def test_max_cycles_limit_not_applied_to_drain(
    irrigation_coordinator: IrrigationCoordinator,
    mock_hass: MagicMock,
) -> None:
    """Drain cycles are NOT subject to max_cycles_per_day."""
    irrigation_coordinator._cycles_today = 999  # Way above the limit

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await irrigation_coordinator._run_pump_cycle(
            "drain", "switch.drain_pump", 30, {}
        )

    mock_hass.services.async_call.assert_any_call(
        "switch", "turn_on", {"entity_id": "switch.drain_pump"}, blocking=True
    )


# ---------------------------------------------------------------------------
# Volume tracking
# ---------------------------------------------------------------------------


async def test_volume_dispensed_today_accumulates(
    irrigation_coordinator: IrrigationCoordinator,
) -> None:
    """volume_dispensed_today increases by duration × flow_rate after each cycle."""
    # 30s × 10 ml/s = 300 ml = 0.3 L
    with patch("asyncio.sleep", new_callable=AsyncMock):
        await irrigation_coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, {}
        )

    assert irrigation_coordinator.volume_dispensed_today == pytest.approx(0.3)


async def test_volume_dispensed_today_accumulates_over_multiple_cycles(
    irrigation_coordinator: IrrigationCoordinator,
) -> None:
    """Volume accumulates correctly over multiple cycles."""
    with patch("asyncio.sleep", new_callable=AsyncMock):
        await irrigation_coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, {}
        )
        await irrigation_coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, {}
        )

    assert irrigation_coordinator.volume_dispensed_today == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# Volume cap enforcement
# ---------------------------------------------------------------------------


async def test_cycle_skipped_when_volume_cap_would_be_exceeded(
    irrigation_coordinator: IrrigationCoordinator,
    mock_hass: MagicMock,
) -> None:
    """Cycle is skipped when running it would push volume_dispensed_today over the cap."""
    # Cap is 1.0 L, flow = 10 ml/s, duration = 30s → 0.3 L per cycle
    # Pre-fill to 0.8 L — adding 0.3 L would exceed the 1.0 L cap
    irrigation_coordinator._volume_dispensed_today = 0.8

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await irrigation_coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, {}
        )

    mock_hass.services.async_call.assert_not_called()
    mock_sleep.assert_not_called()
    assert irrigation_coordinator.volume_dispensed_today == pytest.approx(0.8)


async def test_cycle_runs_when_volume_fits_within_cap(
    irrigation_coordinator: IrrigationCoordinator,
    mock_hass: MagicMock,
) -> None:
    """Cycle runs normally when its volume fits within the remaining cap."""
    # 0.7 L used, cap = 1.0 L, cycle = 0.3 L → 1.0 L exactly, allowed
    irrigation_coordinator._volume_dispensed_today = 0.7

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await irrigation_coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, {}
        )

    mock_hass.services.async_call.assert_any_call(
        "switch", "turn_on", {"entity_id": "switch.irrigation_pump"}, blocking=True
    )
    assert irrigation_coordinator.volume_dispensed_today == pytest.approx(1.0)


async def test_volume_cap_not_applied_to_drain(
    irrigation_coordinator: IrrigationCoordinator,
    mock_hass: MagicMock,
) -> None:
    """Volume cap only guards irrigation cycles, not drain cycles."""
    irrigation_coordinator._volume_dispensed_today = 999.0  # Way over cap

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await irrigation_coordinator._run_pump_cycle(
            "drain", "switch.drain_pump", 30, {}
        )

    mock_hass.services.async_call.assert_any_call(
        "switch", "turn_on", {"entity_id": "switch.drain_pump"}, blocking=True
    )


async def test_volume_cap_not_applied_when_flow_rate_is_zero(
    irrigation_coordinator: IrrigationCoordinator,
    mock_hass: MagicMock,
    mock_main_coordinator: MagicMock,
) -> None:
    """When pump_flow_rate_ml_per_sec == 0, volume cap check is skipped (unknown flow)."""
    mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config.pump_flow_rate_ml_per_sec = 0.0
    irrigation_coordinator._volume_dispensed_today = 0.99  # Near the cap

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await irrigation_coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, {}
        )

    mock_hass.services.async_call.assert_any_call(
        "switch", "turn_on", {"entity_id": "switch.irrigation_pump"}, blocking=True
    )


# ---------------------------------------------------------------------------
# Midnight reset
# ---------------------------------------------------------------------------


async def test_counters_reset_at_midnight(
    irrigation_coordinator: IrrigationCoordinator,
) -> None:
    """Calling _async_reset_daily_counters resets both counters to zero."""
    irrigation_coordinator._cycles_today = 5
    irrigation_coordinator._volume_dispensed_today = 2.5

    await irrigation_coordinator._async_reset_daily_counters()

    assert irrigation_coordinator.cycles_today == 0
    assert irrigation_coordinator.volume_dispensed_today == 0.0


# ---------------------------------------------------------------------------
# Logbook integration
# ---------------------------------------------------------------------------


async def test_logbook_start_event_fired_when_enabled(
    irrigation_coordinator: IrrigationCoordinator,
    mock_hass: MagicMock,
) -> None:
    """A logbook start event is fired before the pump turns on when log_to_logbook=True."""
    with patch("asyncio.sleep", new_callable=AsyncMock):
        await irrigation_coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, {}
        )

    fire_calls = mock_hass.bus.async_fire.call_args_list
    event_types = [c.args[0] for c in fire_calls]
    assert EVENT_GROWSPACE_LOG_ENTRY in event_types

    # At least the start event should carry the growspace_id
    start_events = [
        c for c in fire_calls
        if c.args[0] == EVENT_GROWSPACE_LOG_ENTRY
        and c.args[1].get(ATTR_GROWSPACE_ID) == GROWSPACE_ID
    ]
    assert len(start_events) >= 1


async def test_logbook_skip_event_fired_on_cycle_limit_skip(
    irrigation_coordinator: IrrigationCoordinator,
    mock_hass: MagicMock,
) -> None:
    """A logbook safety-skip event is fired when a cycle is skipped due to cycle limit."""
    irrigation_coordinator._cycles_today = 3

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await irrigation_coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, {}
        )

    fire_calls = mock_hass.bus.async_fire.call_args_list
    skip_events = [
        c for c in fire_calls
        if c.args[0] == EVENT_GROWSPACE_LOG_ENTRY
        and c.args[1].get(ATTR_GROWSPACE_ID) == GROWSPACE_ID
    ]
    assert len(skip_events) >= 1


async def test_logbook_skip_event_fired_on_volume_cap_skip(
    irrigation_coordinator: IrrigationCoordinator,
    mock_hass: MagicMock,
) -> None:
    """A logbook safety-skip event is fired when a cycle is skipped due to volume cap."""
    irrigation_coordinator._volume_dispensed_today = 0.8

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await irrigation_coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, {}
        )

    fire_calls = mock_hass.bus.async_fire.call_args_list
    skip_events = [
        c for c in fire_calls
        if c.args[0] == EVENT_GROWSPACE_LOG_ENTRY
        and c.args[1].get(ATTR_GROWSPACE_ID) == GROWSPACE_ID
    ]
    assert len(skip_events) >= 1


async def test_no_logbook_events_when_disabled(
    irrigation_coordinator: IrrigationCoordinator,
    mock_hass: MagicMock,
    mock_main_coordinator: MagicMock,
) -> None:
    """No logbook events are fired when log_to_logbook=False."""
    mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config.log_to_logbook = False

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await irrigation_coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, {}
        )

    # No logbook events should be fired
    logbook_calls = [
        c for c in mock_hass.bus.async_fire.call_args_list
        if c.args[0] == EVENT_GROWSPACE_LOG_ENTRY
    ]
    assert len(logbook_calls) == 0
