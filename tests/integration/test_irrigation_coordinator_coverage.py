"""Additional tests for irrigation_coordinator coverage."""

import asyncio
import contextlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.domain.pump_cycle import SkipReason
from custom_components.growspace_manager.irrigation_coordinator import (
    BaseIrrigationCoordinator,
    IrrigationCoordinator,
)
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    IrrigationConfig,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

GROWSPACE_ID = "test_growspace"
ENTRY_ID = "test_entry_id"


@pytest.fixture
def mock_main_coordinator() -> MagicMock:
    """Mock the main GrowspaceCoordinator."""
    coordinator = MagicMock()
    coordinator.growspaces = {
        GROWSPACE_ID: Growspace(
            id=GROWSPACE_ID,
            name="Test Growspace",
            notification_target="notify.test",
            irrigation_config=IrrigationConfig(
                irrigation_pump_entity="switch.irrigation_pump",
                drain_pump_entity="switch.drain_pump",
                irrigation_duration=30,
                drain_duration=60,
                irrigation_times=[{"time": "10:00:00"}],
                drain_times=[{"time": "12:00:00"}],
            ),
        )
    }
    coordinator.async_save = AsyncMock()
    coordinator.async_refresh_growspace_data = AsyncMock()
    coordinator.async_commit = AsyncMock()
    coordinator.async_set_updated_data = MagicMock()
    coordinator.add_event = MagicMock()
    return coordinator


@pytest.fixture
def mock_hass(mock_main_coordinator) -> MagicMock:
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.services = AsyncMock()
    hass.async_create_task = asyncio.create_task
    type(hass).loop = property(lambda self: asyncio.get_running_loop())
    hass.data = {DOMAIN: {}}
    # Default switch state to "on" so _async_wait_for_switch_state returns
    # immediately; tests that need a different state override states.get locally.
    mock_state = MagicMock()
    mock_state.state = "on"
    hass.states = MagicMock()
    hass.states.get.return_value = mock_state
    hass.bus = MagicMock()
    return hass


@pytest.fixture
def mock_config_entry() -> MagicMock:
    """Mock Config Entry."""
    entry = MagicMock(spec=ConfigEntry)
    entry.options = {}
    entry.entry_id = ENTRY_ID
    entry.runtime_data = MagicMock()
    entry.options = {}

    def _create_bg_task(_hass, coro, _name, *args, **kwargs):
        """Wrap the coroutine into a real task so it is not leaked."""
        return asyncio.create_task(coro)

    entry.async_create_background_task = MagicMock(side_effect=_create_bg_task)
    return entry


async def test_base_coordinator_async_request_refresh(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test base class async_request_refresh (pass statement)."""
    coordinator = BaseIrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    # Should not raise
    await coordinator.async_request_refresh()


async def test_base_coordinator_async_setup(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test base class async_setup (pass statement)."""
    coordinator = BaseIrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    # Should not raise
    await coordinator.async_setup()


async def test_base_coordinator_async_unload(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test base class async_unload."""
    coordinator = BaseIrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    # Add a listener
    coordinator._listeners.append(MagicMock())

    await coordinator.async_unload()

    # Listeners should be cancelled
    assert len(coordinator._listeners) == 0


async def test_get_sensor_value_valid(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test _get_sensor_value with valid sensor."""
    coordinator = BaseIrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    # Mock state
    mock_state = MagicMock()
    mock_state.state = "25.5"
    mock_hass.states.get.return_value = mock_state

    value = coordinator._get_sensor_value("sensor.test")
    assert value == 25.5


async def test_get_sensor_value_unknown(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test _get_sensor_value with unknown state."""
    coordinator = BaseIrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    # Mock unknown state
    mock_state = MagicMock()
    mock_state.state = "unknown"
    mock_hass.states.get.return_value = mock_state

    value = coordinator._get_sensor_value("sensor.test")
    assert value is None


async def test_get_sensor_value_unavailable(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test _get_sensor_value with unavailable state."""
    coordinator = BaseIrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    # Mock unavailable state
    mock_state = MagicMock()
    mock_state.state = "unavailable"
    mock_hass.states.get.return_value = mock_state

    value = coordinator._get_sensor_value("sensor.test")
    assert value is None


async def test_get_sensor_value_invalid_float(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test _get_sensor_value with invalid float value."""
    coordinator = BaseIrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    # Mock invalid float state
    mock_state = MagicMock()
    mock_state.state = "not_a_number"
    mock_hass.states.get.return_value = mock_state

    value = coordinator._get_sensor_value("sensor.test")
    assert value is None


async def test_get_sensor_value_no_state(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test _get_sensor_value with no state."""
    coordinator = BaseIrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    # Mock no state
    mock_hass.states.get.return_value = None

    value = coordinator._get_sensor_value("sensor.test")
    assert value is None


async def test_async_request_refresh_override(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test IrrigationCoordinator async_request_refresh override."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    with patch.object(
        coordinator, "async_update_listeners", new_callable=AsyncMock
    ) as mock_update:
        await coordinator.async_request_refresh()
        mock_update.assert_awaited_once()


async def test_async_set_settings_unknown_key(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test async_set_settings with unknown setting key."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    new_settings = {
        "irrigation_duration": 45,
        "unknown_setting": "value",  # This should trigger warning
    }

    with patch.object(coordinator, "async_update_listeners", new_callable=AsyncMock):
        await coordinator.async_set_settings(new_settings)

        # Verify valid setting was applied
        growspace = coordinator._main_coordinator.growspaces[GROWSPACE_ID]
        assert growspace.irrigation_config.irrigation_duration == 45


async def test_async_add_schedule_item_invalid_key(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test async_add_schedule_item with invalid schedule key."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    # Should return early without raising
    await coordinator.async_add_schedule_item("invalid_schedule_key", "10:00", 30)

    # Should not save
    mock_main_coordinator.async_save.assert_not_awaited()


async def test_run_pump_cycle_event_logging_exception(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test exception handling in event logging during pump cycle."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    # Mock add_event to raise exception
    mock_main_coordinator.add_event.side_effect = Exception("Event logging failed")

    with patch("asyncio.sleep", new_callable=AsyncMock):
        mock_config_entry.runtime_data = mock_main_coordinator

        # Should not raise, exception is caught and logged
        await coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, {"time": "10:00:00"}
        )

        # Pump should still be turned off
        mock_hass.services.async_call.assert_any_call(
            "switch",
            "turn_off",
            {"entity_id": "switch.irrigation_pump"},
            blocking=True,
        )


async def test_base_coordinator_properties(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test base property implementations of BaseIrrigationCoordinator."""
    coordinator = BaseIrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    assert coordinator.next_scheduled_cycle is None
    assert coordinator.cycles_today == 0
    assert coordinator.volume_dispensed_today == 0.0


async def test_async_add_schedule_item_invalid_time_format(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test async_add_schedule_item raises ValueError for invalid time format."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    with pytest.raises(ValueError, match="Invalid time '25:00:00': hours must be 00-23"):
        await coordinator.async_add_schedule_item("irrigation_times", "25:00:00", 30)


async def test_compute_cycle_volume_liters_non_zero(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test _compute_cycle_volume_liters with non-zero pump flow rate."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    # Set pump flow rate
    mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config.pump_flow_rate_ml_per_sec = 10.0
    volume = coordinator._compute_cycle_volume_liters(30)
    assert volume == 0.3


async def test_is_lights_dark_no_sensors(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test _is_lights_dark returns False when no light sensors are configured."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    mock_main_coordinator.growspaces[GROWSPACE_ID].environment_config = EnvironmentConfig(
        light_sensors=[]
    )
    assert coordinator._is_lights_dark() is False


async def test_check_safety_guards_max_cycles_reached(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test _check_safety_guards returns skip reason when daily max cycles limit reached."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config.max_cycles_per_day = 2
    coordinator._cycles_today = 2

    reason = coordinator._check_safety_guards(30)
    assert reason is SkipReason.CYCLE_LIMIT


async def test_check_safety_guards_volume_cap_exceeded(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test _check_safety_guards returns skip reason when daily volume cap would be exceeded."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    # cap = 1.0 Litres
    mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config.daily_volume_cap_liters = 1.0
    # flow rate = 100 ml/s -> 30s cycle is 3.0 Litres
    mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config.pump_flow_rate_ml_per_sec = 100.0
    coordinator._volume_dispensed_today = 0.0

    reason = coordinator._check_safety_guards(30)
    assert reason is SkipReason.VOLUME_CAP


async def test_run_pump_cycle_safety_guard_blocks(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test that pump cycle is skipped when safety guard blocks execution."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    # Exceed cycles limit to trigger guard failure
    mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config.max_cycles_per_day = 2
    coordinator._cycles_today = 2

    with patch("custom_components.growspace_manager.irrigation_coordinator._LOGGER") as mock_logger:
        await coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, {"time": "10:00:00"}
        )

        # Verify skip warning is logged
        mock_logger.warning.assert_called_once_with(
            "%s (growspace %s)",
            "Irrigation skipped — Daily cycle limit reached (2/2)",
            GROWSPACE_ID,
        )

        # Verify skipped event is added via Home Assistant bus
        mock_hass.bus.async_fire.assert_called_once()
        call_args = mock_hass.bus.async_fire.call_args
        assert call_args[0][0] == "growspace_manager_log_entry"
        event_data = call_args[0][1]
        assert event_data["growspace_id"] == GROWSPACE_ID
        assert event_data["message"] == "Irrigation skipped — Daily cycle limit reached (2/2)"
        assert event_data["category"] == "irrigation_error"
        assert "timestamp" in event_data

        # Verify pump was NEVER turned on or off
        mock_hass.services.async_call.assert_not_called()


async def test_async_reset_daily_counters(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test that _async_reset_daily_counters resets daily counters."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    coordinator._cycles_today = 5
    coordinator._volume_dispensed_today = 4.2

    await coordinator._async_reset_daily_counters()

    assert coordinator._cycles_today == 0
    assert coordinator._volume_dispensed_today == 0.0


async def test_next_scheduled_cycle_no_times(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test next_scheduled_cycle returns None when no times are configured."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config.irrigation_times = []
    assert coordinator.next_scheduled_cycle is None


async def test_next_scheduled_cycle_parsing_and_skipping(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test next_scheduled_cycle handles non-string, 5-char formatting, and invalid time formats."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    # Configure mix of valid/invalid times
    mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config.irrigation_times = [
        {"time": 123},               # non-string -> skip
        {"time": "invalid_format"},  # invalid string -> raise ValueError -> skip
        {"time": "12:00"},           # 5-character string -> format to 12:00:00 -> parse
    ]

    next_cycle = coordinator.next_scheduled_cycle
    assert next_cycle is not None
    assert "12:00:00" in next_cycle


async def test_async_manual_run_no_duration(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test async_manual_run raises ServiceValidationError when no duration is provided or configured."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    # Set both configured duration and passed duration to None/0
    mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config.irrigation_duration = 0

    with pytest.raises(ServiceValidationError) as excinfo:
        await coordinator.async_manual_run(None)

    assert "No valid irrigation duration provided or configured" in str(excinfo.value)


async def test_async_manual_run_cancels_running_irrigation(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test async_manual_run cancels any active currently running irrigation task."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    class CancelableAwaitable:
        def done(self) -> bool:
            return False

        def cancel(self) -> None:
            pass

        def __await__(self) -> Any:
            async def _inner() -> None:
                raise asyncio.CancelledError
            return _inner().__await__()

    mock_running_task = CancelableAwaitable()
    coordinator._running_tasks["irrigation"] = mock_running_task

    # Provide configured pump switch entity and standard duration
    mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config.irrigation_pump_entity = "switch.pump"
    mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config.irrigation_duration = 30

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await coordinator.async_manual_run(15)

        # Verify that the old running task was replaced
        new_task = coordinator._running_tasks["irrigation"]
        assert new_task is not mock_running_task

        # Allow the background task to complete so the coroutine is not leaked
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await new_task

