"""Tests for the IrrigationCoordinator."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.irrigation_coordinator import (
    IrrigationCoordinator,
)
from custom_components.growspace_manager.models import Growspace

GROWSPACE_ID = "test_growspace"
ENTRY_ID = "test_entry_id"


@pytest.fixture
def mock_hass() -> MagicMock:
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.services = AsyncMock()
    # Ensure async_create_task creates a real task for tests to await
    hass.async_create_task = asyncio.create_task
    hass.data = {
        DOMAIN: {
            ENTRY_ID: {
                "coordinator": MagicMock(
                    growspaces={
                        GROWSPACE_ID: Growspace(
                            id=GROWSPACE_ID,
                            name="Test Growspace",
                            notification_target="notify.test",
                        )
                    },
                    async_save=AsyncMock(),
                )
            }
        }
    }
    return hass


@pytest.fixture
def mock_config_entry() -> MagicMock:
    """Mock Config Entry with irrigation options."""
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = ENTRY_ID
    entry.options = {
        "irrigation": {
            GROWSPACE_ID: {
                "irrigation_pump_entity": "switch.irrigation_pump",
                "drain_pump_entity": "switch.drain_pump",
                "irrigation_duration": 30,
                "drain_duration": 60,
                "irrigation_times": [
                    {"time": "10:00:00"},
                    {"time": "20:00:00", "duration": 45},
                ],
                "drain_times": [{"time": "12:00:00"}],
            }
        }
    }
    return entry


@pytest.fixture
def mock_main_coordinator(mock_hass):
    """Fixture for main coordinator."""
    return mock_hass.data[DOMAIN][ENTRY_ID]["coordinator"]


@patch(
    "custom_components.growspace_manager.irrigation_coordinator.async_track_time_change"
)
async def test_setup_and_schedule_events(
    mock_track_time: MagicMock,
    mock_hass: MagicMock,
    mock_config_entry: MagicMock,
    mock_main_coordinator: MagicMock,
):
    """Test that listeners are scheduled correctly on setup."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    mock_main_coordinator.async_save = AsyncMock()
    await coordinator.async_setup()

    assert mock_track_time.call_count == 3
    calls = mock_track_time.call_args_list
    scheduled_times = {
        (c.kwargs["hour"], c.kwargs["minute"], c.kwargs["second"]) for c in calls
    }
    assert (10, 0, 0) in scheduled_times
    assert (20, 0, 0) in scheduled_times
    assert (12, 0, 0) in scheduled_times


async def test_run_pump_cycle(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
):
    """Test the full pump cycle logic including service calls and delay."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    event_data = {"time": "10:00:00"}

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, event_data
        )

        mock_hass.services.async_call.assert_has_calls(
            [
                call(
                    "switch",
                    "turn_on",
                    {"entity_id": "switch.irrigation_pump"},
                    blocking=True,
                ),
                call(
                    "notify",
                    "notify.test",
                    {
                        "message": "Irrigation Event Started at 10:00:00, running for 30 seconds.",
                        "title": "Growspace: Test Growspace",
                    },
                    blocking=False,
                ),
                call(
                    "switch",
                    "turn_off",
                    {"entity_id": "switch.irrigation_pump"},
                    blocking=True,
                ),
            ]
        )
        mock_sleep.assert_awaited_once_with(30)


async def test_handle_event_with_custom_duration(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
):
    """Test that an event with a custom duration overrides the default."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    event_data = {"time": "20:00:00", "duration": 45}

    # Ensure irrigation config is present
    mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config = {
        "irrigation_pump_entity": "switch.irrigation_pump",
    }

    with patch.object(
        coordinator, "_run_pump_cycle", new_callable=AsyncMock
    ) as mock_run_cycle:
        await coordinator._handle_event(
            datetime.now(), event_type="irrigation", event_data=event_data
        )
        await asyncio.sleep(0)  # Allow the created task to run
        mock_run_cycle.assert_awaited_once_with(
            "irrigation", "switch.irrigation_pump", 45, event_data
        )


async def test_overlapping_events(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
):
    """Test that a new event cancels a running event of the same type."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    event_data = {"time": "10:00:00"}

    # Ensure irrigation config is present
    mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config = {
        "irrigation_pump_entity": "switch.irrigation_pump",
        "irrigation_duration": 30,
    }

    # Create a task that will stay pending
    pending_task = asyncio.create_task(asyncio.sleep(5))
    coordinator._running_tasks["irrigation"] = pending_task

    with patch.object(
        coordinator, "_run_pump_cycle", new_callable=AsyncMock
    ) as mock_run_cycle:
        await coordinator._handle_event(
            datetime.now(), event_type="irrigation", event_data=event_data
        )
        await asyncio.sleep(0)  # allow task creation and cancellation to run

        # Assert the old task was cancelled and a new one was started
        assert pending_task.cancelled()
        mock_run_cycle.assert_awaited()

    # cleanup lingering task
    try:
        await pending_task
    except asyncio.CancelledError:
        pass


# =============================================================================
# Tests for get_default_duration
# =============================================================================


async def test_get_default_duration_irrigation(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
):
    """Test getting default duration for irrigation."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config = {
        "irrigation_duration": 30,
        "drain_duration": 60,
    }

    result = coordinator.get_default_duration("irrigation")
    assert result == 30


async def test_get_default_duration_drain(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
):
    """Test getting default duration for drain."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config = {
        "irrigation_duration": 30,
        "drain_duration": 60,
    }

    result = coordinator.get_default_duration("drain")
    assert result == 60


async def test_get_default_duration_missing_key(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
):
    """Test get_default_duration returns None when key is missing."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config = {}

    result = coordinator.get_default_duration("irrigation")
    assert result is None


async def test_get_default_duration_attribute_error(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
):
    """Test get_default_duration returns None on AttributeError."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    # Set irrigation_config to None to trigger AttributeError
    mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config = None

    result = coordinator.get_default_duration("irrigation")
    assert result is None


# =============================================================================
# Tests for async_set_settings
# =============================================================================


@patch(
    "custom_components.growspace_manager.irrigation_coordinator.async_track_time_change"
)
async def test_async_set_settings(
    mock_track_time: MagicMock,
    mock_hass: MagicMock,
    mock_config_entry: MagicMock,
    mock_main_coordinator: MagicMock,
):
    """Test setting irrigation settings."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    mock_main_coordinator.async_save = AsyncMock()
    mock_main_coordinator.async_set_updated_data = MagicMock()
    mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config = {}

    new_settings = {
        "irrigation_duration": 45,
        "drain_duration": 90,
    }

    await coordinator.async_set_settings(new_settings)

    # Verify settings were updated
    assert (
        mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config[
            "irrigation_duration"
        ]
        == 45
    )
    assert (
        mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config[
            "drain_duration"
        ]
        == 90
    )
    mock_main_coordinator.async_save.assert_awaited_once()


# =============================================================================
# Tests for async_add_schedule_item
# =============================================================================


@patch(
    "custom_components.growspace_manager.irrigation_coordinator.async_track_time_change"
)
async def test_async_add_schedule_item_new(
    mock_track_time: MagicMock,
    mock_hass: MagicMock,
    mock_config_entry: MagicMock,
    mock_main_coordinator: MagicMock,
):
    """Test adding a new schedule item."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    mock_main_coordinator.async_save = AsyncMock()
    mock_main_coordinator.async_set_updated_data = MagicMock()
    mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config = {
        "irrigation_times": []
    }

    await coordinator.async_add_schedule_item("irrigation_times", "10:00:00", 30)

    schedule = mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config[
        "irrigation_times"
    ]
    assert len(schedule) == 1
    assert schedule[0] == {"time": "10:00:00", "duration": 30}


@patch(
    "custom_components.growspace_manager.irrigation_coordinator.async_track_time_change"
)
async def test_async_add_schedule_item_update_existing(
    mock_track_time: MagicMock,
    mock_hass: MagicMock,
    mock_config_entry: MagicMock,
    mock_main_coordinator: MagicMock,
):
    """Test updating an existing schedule item."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    mock_main_coordinator.async_save = AsyncMock()
    mock_main_coordinator.async_set_updated_data = MagicMock()
    mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config = {
        "irrigation_times": [{"time": "10:00:00", "duration": 30}]
    }

    await coordinator.async_add_schedule_item("irrigation_times", "10:00:00", 60)

    schedule = mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config[
        "irrigation_times"
    ]
    assert len(schedule) == 1
    assert schedule[0]["duration"] == 60


@patch(
    "custom_components.growspace_manager.irrigation_coordinator.async_track_time_change"
)
async def test_async_add_schedule_item_short_time_format(
    mock_track_time: MagicMock,
    mock_hass: MagicMock,
    mock_config_entry: MagicMock,
    mock_main_coordinator: MagicMock,
):
    """Test adding schedule item with short time format (HH:MM)."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    mock_main_coordinator.async_save = AsyncMock()
    mock_main_coordinator.async_set_updated_data = MagicMock()
    mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config = {}

    await coordinator.async_add_schedule_item("irrigation_times", "10:00", 30)

    schedule = mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config[
        "irrigation_times"
    ]
    assert schedule[0]["time"] == "10:00:00"


async def test_async_add_schedule_item_empty_time(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
):
    """Test adding schedule item with empty time raises error."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    with pytest.raises(ValueError) as exc_info:
        await coordinator.async_add_schedule_item("irrigation_times", "", 30)
    assert "Time cannot be empty" in str(exc_info.value)


@patch(
    "custom_components.growspace_manager.irrigation_coordinator.async_track_time_change"
)
async def test_async_add_schedule_item_creates_list(
    mock_track_time: MagicMock,
    mock_hass: MagicMock,
    mock_config_entry: MagicMock,
    mock_main_coordinator: MagicMock,
):
    """Test adding schedule item creates list if missing."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    mock_main_coordinator.async_save = AsyncMock()
    mock_main_coordinator.async_set_updated_data = MagicMock()
    mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config = {}

    await coordinator.async_add_schedule_item("irrigation_times", "10:00:00", 30)

    assert (
        "irrigation_times"
        in mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config
    )


# =============================================================================
# Tests for async_remove_schedule_item
# =============================================================================


@patch(
    "custom_components.growspace_manager.irrigation_coordinator.async_track_time_change"
)
async def test_async_remove_schedule_item_success(
    mock_track_time: MagicMock,
    mock_hass: MagicMock,
    mock_config_entry: MagicMock,
    mock_main_coordinator: MagicMock,
):
    """Test removing a schedule item."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    mock_main_coordinator.async_save = AsyncMock()
    mock_main_coordinator.async_set_updated_data = MagicMock()
    mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config = {
        "irrigation_times": [
            {"time": "10:00:00", "duration": 30},
            {"time": "14:00:00", "duration": 45},
        ]
    }

    await coordinator.async_remove_schedule_item("irrigation_times", "10:00:00")

    schedule = mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config[
        "irrigation_times"
    ]
    assert len(schedule) == 1
    assert schedule[0]["time"] == "14:00:00"


async def test_async_remove_schedule_item_empty_time(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
):
    """Test removing schedule item with empty time raises error."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    with pytest.raises(ValueError) as exc_info:
        await coordinator.async_remove_schedule_item("irrigation_times", "")
    assert "Time cannot be empty" in str(exc_info.value)


async def test_async_remove_schedule_item_not_found(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
):
    """Test removing schedule item that doesn't exist."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config = {
        "irrigation_times": [{"time": "10:00:00", "duration": 30}]
    }

    # Should not raise, just log warning
    await coordinator.async_remove_schedule_item("irrigation_times", "12:00:00")


# =============================================================================
# Tests for _schedule_event
# =============================================================================


@patch(
    "custom_components.growspace_manager.irrigation_coordinator.async_track_time_change"
)
async def test_schedule_event_invalid_time_format(
    mock_track_time: MagicMock,
    mock_hass: MagicMock,
    mock_config_entry: MagicMock,
    mock_main_coordinator: MagicMock,
):
    """Test _schedule_event with invalid time format."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    # Invalid time (not a string)
    coordinator._schedule_event({"time": 123}, "irrigation")
    mock_track_time.assert_not_called()


@patch(
    "custom_components.growspace_manager.irrigation_coordinator.async_track_time_change"
)
async def test_schedule_event_short_time(
    mock_track_time: MagicMock,
    mock_hass: MagicMock,
    mock_config_entry: MagicMock,
    mock_main_coordinator: MagicMock,
):
    """Test _schedule_event with short time format (HH:MM)."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    coordinator._schedule_event({"time": "10:00"}, "irrigation")

    # Should have been converted and scheduled
    mock_track_time.assert_called_once()
    call_kwargs = mock_track_time.call_args.kwargs
    assert call_kwargs["hour"] == 10
    assert call_kwargs["minute"] == 0
    assert call_kwargs["second"] == 0


@patch(
    "custom_components.growspace_manager.irrigation_coordinator.async_track_time_change"
)
async def test_schedule_event_invalid_time_value(
    mock_track_time: MagicMock,
    mock_hass: MagicMock,
    mock_config_entry: MagicMock,
    mock_main_coordinator: MagicMock,
):
    """Test _schedule_event with invalid time value."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    # Invalid time string
    coordinator._schedule_event({"time": "invalid"}, "irrigation")
    mock_track_time.assert_not_called()


# =============================================================================
# Tests for async_cancel_listeners
# =============================================================================


async def test_async_cancel_listeners(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
):
    """Test cancelling all listeners."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    # Add mock listeners
    mock_listener1 = MagicMock()
    mock_listener2 = MagicMock()
    coordinator._listeners = [mock_listener1, mock_listener2]

    # Add mock running task
    mock_task = MagicMock()
    mock_task.done.return_value = False
    coordinator._running_tasks = {"irrigation": mock_task}

    coordinator.async_cancel_listeners()

    # Verify listeners were called (cancelled)
    mock_listener1.assert_called_once()
    mock_listener2.assert_called_once()
    assert coordinator._listeners == []

    # Verify task was cancelled
    mock_task.cancel.assert_called_once()
    assert coordinator._running_tasks == {}


async def test_async_cancel_listeners_completed_task(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
):
    """Test cancelling listeners with already completed task."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    # Add mock completed task
    mock_task = MagicMock()
    mock_task.done.return_value = True
    coordinator._running_tasks = {"irrigation": mock_task}

    coordinator.async_cancel_listeners()

    # Completed task should not be cancelled
    mock_task.cancel.assert_not_called()


# =============================================================================
# Tests for _handle_event - missing configuration
# =============================================================================


async def test_handle_event_missing_pump_entity(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
):
    """Test _handle_event when pump entity is missing."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config = {
        "irrigation_duration": 30,
        # Missing irrigation_pump_entity
    }

    event_data = {"time": "10:00:00"}

    with patch.object(
        coordinator, "_run_pump_cycle", new_callable=AsyncMock
    ) as mock_run:
        await coordinator._handle_event(
            datetime.now(), event_type="irrigation", event_data=event_data
        )
        # Should not call _run_pump_cycle
        mock_run.assert_not_awaited()


async def test_handle_event_missing_duration(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
):
    """Test _handle_event when duration is missing."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config = {
        "irrigation_pump_entity": "switch.pump",
        # Missing irrigation_duration and event has no duration
    }

    event_data = {"time": "10:00:00"}

    with patch.object(
        coordinator, "_run_pump_cycle", new_callable=AsyncMock
    ) as mock_run:
        await coordinator._handle_event(
            datetime.now(), event_type="irrigation", event_data=event_data
        )
        # Should not call _run_pump_cycle
        mock_run.assert_not_awaited()


# =============================================================================
# Tests for _run_pump_cycle - exception handling
# =============================================================================


async def test_run_pump_cycle_cancelled(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
):
    """Test _run_pump_cycle when cancelled."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    event_data = {"time": "10:00:00"}

    # Mock sleep to raise CancelledError
    with patch("asyncio.sleep", side_effect=asyncio.CancelledError()):
        await coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, event_data
        )

    # Should still turn off the pump in finally block
    calls = mock_hass.services.async_call.call_args_list
    assert any(
        c[0] == ("switch", "turn_off", {"entity_id": "switch.irrigation_pump"})
        for c in calls
    )


async def test_run_pump_cycle_exception(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
):
    """Test _run_pump_cycle when exception occurs."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    event_data = {"time": "10:00:00"}

    # Mock sleep to raise exception
    with patch("asyncio.sleep", side_effect=Exception("Test error")):
        await coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, event_data
        )

    # Should still turn off the pump in finally block
    calls = mock_hass.services.async_call.call_args_list
    assert any(
        c[0] == ("switch", "turn_off", {"entity_id": "switch.irrigation_pump"})
        for c in calls
    )


async def test_run_pump_cycle_no_notification_target(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
):
    """Test _run_pump_cycle when notification target is not set."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    # Remove notification target
    mock_main_coordinator.growspaces[GROWSPACE_ID].notification_target = None

    event_data = {"time": "10:00:00"}

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, event_data
        )

    # Should not call notify service
    calls = mock_hass.services.async_call.call_args_list
    notify_calls = [c for c in calls if c[0][0] == "notify"]
    assert len(notify_calls) == 0


# =============================================================================
# Tests for async_setup with migration
# =============================================================================


@patch(
    "custom_components.growspace_manager.irrigation_coordinator.async_track_time_change"
)
async def test_async_setup_migration(
    mock_track_time: MagicMock,
    mock_hass: MagicMock,
    mock_config_entry: MagicMock,
    mock_main_coordinator: MagicMock,
):
    """Test async_setup migrates legacy options."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    mock_main_coordinator.async_save = AsyncMock()

    # Set empty irrigation_config but have legacy options
    mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config = {}
    mock_config_entry.options = {
        "irrigation": {
            GROWSPACE_ID: {
                "irrigation_pump_entity": "switch.pump",
                "irrigation_duration": 30,
            }
        }
    }

    await coordinator.async_setup()

    # Should have migrated settings
    config = mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config
    assert config.get("irrigation_pump_entity") == "switch.pump"
    mock_main_coordinator.async_save.assert_awaited()
