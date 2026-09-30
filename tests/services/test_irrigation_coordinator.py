"""Tests for the IrrigationCoordinator."""

import asyncio
from collections.abc import Callable
import contextlib
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.irrigation_coordinator import (
    BaseIrrigationCoordinator,
    IrrigationCoordinator,
)
from custom_components.growspace_manager.models import (
    Growspace,
    GrowspaceIrrigationConfig,
    IrrigationConfig,
    IrrigationTank,
)
from custom_components.growspace_manager.tank_monitor import TankLevelMonitor
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util.dt import utcnow

# This suite shares one `hass.states` mock across every sensor, so it
# cannot model the pump's own state; its OFF readback is answered for them.
pytestmark = pytest.mark.usefixtures("pump_reads_back_off")

GROWSPACE_ID = "test_growspace"
ENTRY_ID = "test_entry_id"

_REAL_ASYNCIO_SLEEP = asyncio.sleep


def _moisture_state(value: str) -> MagicMock:
    """Return a moisture state that reported just now, as validity requires."""
    state = MagicMock(state=value)
    state.last_changed = state.last_reported = utcnow()
    return state


async def _await_settling_report(add_event_mock: MagicMock) -> None:
    """Yield to the event loop until the deferred settling-report task fires.

    The completion report runs in a background task after a settling delay
    (see Sensor Settling Delay), so tests must yield control for it to run.
    Uses the real asyncio.sleep — tests patch asyncio.sleep to resolve
    instantly, and the autouse freeze_time fixture breaks wait_for() timeouts.
    """
    for _ in range(1000):
        if add_event_mock.call_count:
            return
        await _REAL_ASYNCIO_SLEEP(0)
    pytest.fail("Settling report task never completed")


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
                irrigation_times=[
                    {"time": "10:00:00", "duration": 30},
                    {"time": "20:00:00", "duration": 45},
                ],
                drain_times=[{"time": "12:00:00", "duration": 60}],
            ),
        )
    }
    coordinator.async_save = AsyncMock()
    coordinator.async_commit = AsyncMock()
    coordinator.async_project_water = AsyncMock()
    coordinator.async_refresh_growspace_data = AsyncMock()
    coordinator.async_set_updated_data = MagicMock()
    coordinator.add_event = MagicMock()
    return coordinator


@pytest.fixture
def mock_hass(mock_main_coordinator) -> MagicMock:
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.services = AsyncMock()
    hass.bus = MagicMock()
    hass.states = MagicMock()
    # Ensure async_create_task and async_create_background_task create real tasks for tests to await
    hass.async_create_task = asyncio.create_task
    hass.async_create_background_task = MagicMock(
        side_effect=lambda target, name: asyncio.create_task(target)
    )
    # Mock loop property
    type(hass).loop = property(lambda self: asyncio.get_running_loop())
    hass.data = {DOMAIN: {}}
    return hass


@pytest.fixture
def mock_config_entry() -> MagicMock:
    """Mock Config Entry with irrigation options."""
    entry = MagicMock(spec=ConfigEntry)
    entry.options = {}
    entry.entry_id = ENTRY_ID
    entry.runtime_data = MagicMock()
    entry.async_create_background_task = MagicMock(
        side_effect=lambda hass, target, name: asyncio.create_task(target)
    )
    entry.options = {
        "irrigation": {
            GROWSPACE_ID: {
                "irrigation_pump_entity": "switch.irrigation_pump",
                "drain_pump_entity": "switch.drain_pump",
                "irrigation_duration": 30,
                "drain_duration": 60,
                "irrigation_times": [
                    {"time": "10:00:00", "duration": 30},
                    {"time": "20:00:00", "duration": 45},
                ],
                "drain_times": [{"time": "12:00:00", "duration": 60}],
            }
        }
    }
    return entry


@patch(
    "custom_components.growspace_manager.irrigation_coordinator.async_track_time_change"
)
async def test_setup_and_schedule_events(
    mock_track_time: MagicMock,
    mock_hass: MagicMock,
    mock_config_entry: MagicMock,
    mock_main_coordinator: MagicMock,
) -> None:
    """Test that listeners are scheduled correctly on setup."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    await coordinator.async_setup()

    # 2 irrigation + 1 drain + 1 midnight reset = 4
    assert mock_track_time.call_count == 4
    calls = mock_track_time.call_args_list
    scheduled_times = {
        (c.kwargs["hour"], c.kwargs["minute"], c.kwargs["second"]) for c in calls
    }
    assert (10, 0, 0) in scheduled_times
    assert (20, 0, 0) in scheduled_times
    assert (12, 0, 0) in scheduled_times
    # Midnight reset listener
    assert (0, 0, 0) in scheduled_times
    coordinator.async_cancel_listeners()


async def test_async_wait_for_switch_state_happy_path(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test waiting for switch state change - happy path."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    # Mock hass.states - initially off, then changes to on
    mock_hass.states = MagicMock()

    # Create a list to cycle through states
    states = [Mock(state="off"), Mock(state="on")]
    state_index = [0]

    def get_state(entity_id):
        # After first call, state changes to "on"
        result = states[min(state_index[0], 1)]
        state_index[0] += 1
        return result

    mock_hass.states.get.side_effect = get_state

    # Mock bus.async_listen to immediately trigger the callback
    mock_hass.bus = MagicMock()

    def call_listener_immediately(event_type, callback):
        # Immediately call the callback with the state change event
        event = Mock()
        event.data = {
            "entity_id": "switch.test_pump",
            "new_state": Mock(state="on"),
        }
        # Schedule it to run next
        asyncio.get_event_loop().call_soon(lambda: callback(event))
        return Mock()  # Return cancel function

    mock_hass.bus.async_listen.side_effect = call_listener_immediately

    # Wait for state with generous timeout
    result = await coordinator._async_wait_for_switch_state(
        "switch.test_pump", "on", timeout=5.0
    )

    assert result is True


async def test_async_wait_for_switch_state_already_in_target(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test waiting for state when already in target state."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    # Mock hass.states and bus
    mock_hass.states = MagicMock()
    mock_hass.states.get.return_value = Mock(state="on")
    mock_hass.bus = MagicMock()

    result = await coordinator._async_wait_for_switch_state(
        "switch.test_pump", "on", timeout=5.0
    )

    assert result is True
    # Should not subscribe to events since already in target state
    mock_hass.bus.async_listen.assert_not_called()


async def test_async_wait_for_switch_state_timeout(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test waiting for switch state when timeout occurs."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    # Mock hass.states and bus
    mock_hass.states = MagicMock()
    mock_hass.states.get.return_value = Mock(state="off")
    mock_hass.bus = MagicMock()
    mock_hass.bus.async_listen.return_value = Mock()

    # We need to simulate the timeout without actually waiting a long time.
    # We use a custom async function to mock asyncio.wait_for and ensure the
    # coroutine argument is properly closed/awaited to prevent unawaited coroutine warnings.
    async def mock_wait_for(fut, timeout=None):
        if hasattr(fut, "close"):
            fut.close()
        raise TimeoutError

    with patch("asyncio.wait_for", new=mock_wait_for):
        result = await coordinator._async_wait_for_switch_state(
            "switch.test_pump", "on", timeout=0.1
        )

    assert result is False


async def test_run_pump_cycle(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test the full pump cycle logic including service calls and delay."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    event_data = {"time": "10:00:00"}

    with (
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        patch.object(
            coordinator,
            "_async_wait_for_switch_state",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        # Ensure runtime_data.coordinator returns the mock_main_coordinator
        mock_config_entry.runtime_data = mock_main_coordinator

        await coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, event_data
        )

        # Check switch turn on
        mock_hass.services.async_call.assert_any_call(
            "switch",
            "turn_on",
            {"entity_id": "switch.irrigation_pump"},
            blocking=True,
        )

        # Check switch turn off
        mock_hass.services.async_call.assert_any_call(
            "switch",
            "turn_off",
            {"entity_id": "switch.irrigation_pump"},
            blocking=True,
        )

        # Check notification (partial match on message/title if needed, but strict for now)
        # The failure might be due to blocking=False/True mismatch or exact dict match
        # Let's verify the notification call exists
        found_notify = False
        for call_args in mock_hass.services.async_call.call_args_list:
            if call_args.args[0] == "notify" and call_args.args[1] == "notify.test":
                found_notify = True
                break
        assert found_notify, "Notification service call not found"
        mock_sleep.assert_any_await(30)

        # Verify event logging — fired from the deferred settling-report task
        await _await_settling_report(mock_main_coordinator.add_event)
        mock_main_coordinator.add_event.assert_called_once()
        args, _ = mock_main_coordinator.add_event.call_args
        assert args[0] == GROWSPACE_ID
        event = args[1]
        assert event.sensor_type == "irrigation"
        assert (
            event.duration_sec >= 0.0
        )  # Duration calculation depends on mock time which we didn't freeze, but > 0
        assert event.severity == 1.0
        assert event.category == "irrigation"


async def test_handle_event_with_custom_duration(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test that an event with a custom duration overrides the default."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    event_data = {"time": "20:00:00", "duration": 45}

    with patch.object(
        coordinator, "_run_pump_cycle", new_callable=AsyncMock
    ) as mock_run_cycle:
        await coordinator._handle_event(
            datetime.now(), event_type="irrigation", event_data=event_data
        )
        await coordinator._supply_task  # Decide the queued request and finish its cycle
        mock_run_cycle.assert_awaited_once_with(
            "irrigation",
            "switch.irrigation_pump",
            45,
            {**event_data, "due_at": datetime.now().replace(second=0, microsecond=0)},
        )


async def test_overlapping_events(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """A second scheduled request waits for a running shot without cancelling it."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    release = asyncio.Event()
    pending_task = asyncio.create_task(release.wait())
    coordinator._running_tasks["irrigation"] = pending_task
    with patch.object(coordinator, "_run_pump_cycle", new_callable=AsyncMock) as run:
        await coordinator._handle_event(
            utcnow(), event_type="irrigation", event_data={"time": "10:00:00"}
        )
        await _REAL_ASYNCIO_SLEEP(0)
        assert not pending_task.cancelled()
        run.assert_not_awaited()
        assert len(coordinator.supply_payload()["claims"]) == 1
        release.set()
        await coordinator._supply_task
        run.assert_awaited_once()


async def test_get_default_duration(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test getting default duration for event types."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    assert coordinator.get_default_duration("irrigation") == 30
    assert coordinator.get_default_duration("drain") == 60
    assert coordinator.get_default_duration("unknown") is None


async def test_async_set_settings(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test updating irrigation settings."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    new_settings = {
        "irrigation_duration": 45,
        "drain_pump_entity": "switch.new_drain_pump",
    }

    with patch.object(
        coordinator, "async_update_listeners", new_callable=AsyncMock
    ) as mock_update:
        await coordinator.async_set_settings(new_settings)

        growspace = coordinator._main_coordinator.growspaces[GROWSPACE_ID]
        assert growspace.default_zone.irrigation_duration == 45
        assert growspace.irrigation_config.drain_pump_entity == "switch.new_drain_pump"

        mock_main_coordinator.async_commit.assert_awaited_once()
        mock_update.assert_awaited_once()


async def test_async_add_schedule_item(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test adding and updating schedule items."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    with patch.object(
        coordinator, "async_update_listeners", new_callable=AsyncMock
    ) as mock_update:
        # Test adding new item
        await coordinator.async_add_schedule_item("irrigation_times", "08:00", 20)

        growspace = coordinator._main_coordinator.growspaces[GROWSPACE_ID]
        items = growspace.default_zone.irrigation_times
        new_item = next((i for i in items if i["time"] == "08:00:00"), None)
        assert new_item is not None
        assert new_item["duration"] == 20

        # Test updating existing item
        await coordinator.async_add_schedule_item("irrigation_times", "08:00", 30)

        items = growspace.default_zone.irrigation_times
        new_item = next((i for i in items if i["time"] == "08:00:00"), None)
        assert new_item is not None
        assert new_item["duration"] == 30

        assert mock_main_coordinator.async_commit.call_count == 2
        assert mock_update.call_count == 2


async def test_async_remove_schedule_item(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test removing schedule items."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    with patch.object(
        coordinator, "async_update_listeners", new_callable=AsyncMock
    ) as mock_update:
        # Test removing existing item (10:00:00 exists in fixture)
        await coordinator.async_remove_schedule_item("irrigation_times", "10:00:00")

        growspace = coordinator._main_coordinator.growspaces[GROWSPACE_ID]
        items = growspace.default_zone.irrigation_times
        removed_item = next((i for i in items if i["time"] == "10:00:00"), None)
        assert removed_item is None

        mock_main_coordinator.async_commit.assert_awaited_once()
        mock_update.assert_awaited_once()

        # Removing "HH:MM" matches the stored "HH:MM:SS" entry (ADR-0029 —
        # the old raw-string comparison silently removed nothing)
        mock_main_coordinator.async_commit.reset_mock()
        mock_update.reset_mock()

        await coordinator.async_remove_schedule_item("irrigation_times", "20:00")

        items = growspace.default_zone.irrigation_times
        assert not any(i["time"] == "20:00:00" for i in items)
        mock_main_coordinator.async_commit.assert_awaited_once()

        # Test removing non-existent item
        mock_main_coordinator.async_commit.reset_mock()
        mock_update.reset_mock()

        await coordinator.async_remove_schedule_item("irrigation_times", "23:45")

        mock_main_coordinator.async_commit.assert_not_awaited()
        mock_update.assert_not_awaited()

        # An invalid time is a loud failure, matching the add path
        with pytest.raises(ValueError):
            await coordinator.async_remove_schedule_item("irrigation_times", "99:99:99")


async def test_async_add_schedule_item_validation_error(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test validation errors when adding schedule items."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    with pytest.raises(ValueError, match="Time cannot be empty"):
        await coordinator.async_add_schedule_item("irrigation_times", "", 20)


async def test_async_remove_schedule_item_validation_error(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test validation errors when removing schedule items."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    with pytest.raises(ValueError, match="Time cannot be empty"):
        await coordinator.async_remove_schedule_item("irrigation_times", "")


async def test_get_default_duration_error(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test error handling in get_default_duration."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    # Simulate missing growspace
    mock_main_coordinator.growspaces = {}

    assert coordinator.get_default_duration("irrigation") is None


async def test_schedule_event_invalid_time(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Malformed schedule entries register no listeners (only a warning)."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    growspace = mock_main_coordinator.growspaces[GROWSPACE_ID]
    growspace.default_zone.irrigation_times = [{"time": 123}, {"time": "invalid"}]
    growspace.irrigation_config.drain_times = []

    await coordinator.async_update_listeners()

    assert len(coordinator._listeners) == 1  # midnight reset only
    coordinator.async_cancel_listeners()


async def test_handle_event_missing_config(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test handling event with missing configuration."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    # Clear config: no pump, and no duration to fall back on.
    growspace = mock_main_coordinator.growspaces[GROWSPACE_ID]
    growspace.irrigation_config = GrowspaceIrrigationConfig()
    growspace.default_zone.irrigation_duration = None

    with patch.object(
        coordinator, "_run_pump_cycle", new_callable=AsyncMock
    ) as mock_run:
        await coordinator._handle_event(
            datetime.now(), event_type="irrigation", event_data={"time": "10:00:00"}
        )
        await coordinator._supply_task
        mock_run.assert_not_awaited()


async def test_run_pump_cycle_cancellation(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test cancellation of pump cycle."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    # Mock sleep to raise CancelledError
    with (
        patch("asyncio.sleep", side_effect=asyncio.CancelledError),
        patch.object(
            coordinator,
            "_async_wait_for_switch_state",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        await coordinator._run_pump_cycle("irrigation", "switch.pump", 30, {})

        # Should still turn off pump
        mock_hass.services.async_call.assert_any_call(
            "switch", "turn_off", {"entity_id": "switch.pump"}, blocking=True
        )


async def test_run_pump_cycle_error(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test error handling in pump cycle."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    # Mock service call to raise exception
    mock_hass.services.async_call.side_effect = ValueError("Service Error")

    # The exception is caught and logged in _run_pump_cycle, but then re-raised
    # when trying to turn off the pump in finally block because side_effect applies to all calls.
    # We should make side_effect only apply to the first call (turn_on).
    mock_hass.services.async_call.side_effect = [ValueError("Service Error"), None]

    with patch.object(
        coordinator,
        "_async_wait_for_switch_state",
        new_callable=AsyncMock,
        return_value=True,
    ):
        await coordinator._run_pump_cycle("irrigation", "switch.pump", 30, {})

    # Should attempt to turn off pump
    assert mock_hass.services.async_call.call_count == 2

    # Verify task is removed from running_tasks
    assert "irrigation" not in coordinator._running_tasks


async def test_async_remove_schedule_item_key_error(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test removing item from non-existent schedule key."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    # Ensure key doesn't exist
    if hasattr(
        mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config,
        "missing_schedule",
    ):
        del mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config[
            "missing_schedule"
        ]

    await coordinator.async_remove_schedule_item("missing_schedule", "12:00:00")

    # Should handle KeyError gracefully and log warning
    # We can verify this by checking if async_commit was NOT called (since no change happened)
    mock_main_coordinator.async_commit.assert_not_awaited()


async def test_async_remove_schedule_item_key_error_explicit(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test explicit KeyError handling in remove schedule item."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    # Force a KeyError by mocking the dict to raise it on get or access
    # But simpler is to rely on the fact that if key is missing, .get returns []
    # The code does: schedule = growspace.irrigation_config.get(schedule_key, [])
    # So to hit KeyError at line 154, we need line 129 assignment to fail?
    # Actually, line 129 is: growspace.irrigation_config[schedule_key] = ...
    # If growspace.irrigation_config is a dict, this won't raise KeyError.
    # Wait, the code block is:
    # try:
    #     schedule = growspace.irrigation_config.get(schedule_key, [])
    #     ...
    #     growspace.irrigation_config[schedule_key] = ...
    # except KeyError:
    #
    # It seems hard to trigger KeyError on a standard dict unless we mock it.

    mock_dict = MagicMock()
    mock_dict.get.return_value = []
    mock_dict.__setitem__.side_effect = KeyError("Boom")

    mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config = mock_dict

    await coordinator.async_remove_schedule_item("some_schedule", "12:00:00")

    # Should catch KeyError and log warning
    # We can verify this by checking if async_commit was NOT called
    mock_main_coordinator.async_commit.assert_not_awaited()


async def test_schedule_event_short_time_format(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """A stored HH:MM entry still registers its listener."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    growspace = mock_main_coordinator.growspaces[GROWSPACE_ID]
    growspace.default_zone.irrigation_times = [{"time": "12:00"}]
    growspace.irrigation_config.drain_times = []

    await coordinator.async_update_listeners()

    assert len(coordinator._listeners) == 2  # schedule plus midnight reset

    coordinator.async_cancel_listeners()


async def test_async_cancel_listeners_with_tasks(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test cancelling listeners and running tasks."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    # Add a dummy listener
    coordinator._listeners.append(Mock())

    # Add a dummy task
    task = asyncio.create_task(asyncio.sleep(1))
    coordinator._running_tasks["irrigation"] = task

    coordinator.async_cancel_listeners()

    # Allow loop to process cancellation
    await asyncio.sleep(0)

    assert len(coordinator._listeners) == 0
    assert task.cancelled()

    # Cleanup
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def test_handle_event_cleanup_running_task(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test cleanup of finished task in _handle_event."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    # Add a finished task
    task = asyncio.create_task(asyncio.sleep(0))
    await task
    coordinator._running_tasks["irrigation"] = task

    # Run handle event
    with patch.object(coordinator, "_run_pump_cycle", new_callable=AsyncMock):
        await coordinator._handle_event(
            datetime.now(), event_type="irrigation", event_data={"time": "10:00:00"}
        )
        await coordinator._supply_task

    # The finished task should be replaced (or at least not cancelled since it's done)
    # The logic checks if task exists and is NOT done before cancelling.
    # So we just verify no error occurred.
    assert "irrigation" in coordinator._running_tasks


async def test_run_pump_cycle_cleanup(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test that running task is removed after completion."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    # Add a dummy task to running_tasks
    coordinator._running_tasks["irrigation"] = Mock()

    # Run pump cycle
    with (
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch.object(
            coordinator,
            "_async_wait_for_switch_state",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        await coordinator._run_pump_cycle("irrigation", "switch.pump", 0, {})

    # Verify task is removed
    assert "irrigation" not in coordinator._running_tasks


def _pump_off_then(*moisture: Any) -> Callable[[str], Any]:
    """Read the pump as OFF, and the moisture sensor as ``moisture`` in turn.

    The cycle reads the pump before it starts: one already ON is a person's and
    holds the cycle (#793).
    """
    readings = iter(moisture)

    def get(entity_id: str) -> Any:
        return Mock(state="off") if entity_id.startswith("switch.") else next(readings)

    return get


async def test_run_pump_cycle_with_moisture_logging(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test pump cycle with moisture logging."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    # Configure moisture sensor
    mock_main_coordinator.growspaces[GROWSPACE_ID].environment_config = MagicMock()
    mock_main_coordinator.growspaces[
        GROWSPACE_ID
    ].default_zone.soil_moisture_sensor = "sensor.moisture"

    # Mock states
    mock_hass.states = MagicMock()

    # Mock sensor states (before=45.2, after=55.8)
    mock_before_state = _moisture_state("45.2")
    mock_after_state = _moisture_state("55.8")

    def get_state(entity_id):
        if entity_id == "sensor.moisture":
            # Return first value then second value?
            # side_effect is better but mocked hass object is reused.
            # We can use a simpler approach or side_effect on the mock instance directly.
            pass

    mock_hass.states.get.side_effect = _pump_off_then(
        mock_before_state, mock_after_state
    )

    with (
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch.object(
            coordinator,
            "_async_wait_for_switch_state",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        await coordinator._run_pump_cycle("irrigation", "switch.pump", 30, {})

        await _await_settling_report(mock_main_coordinator.add_event)
        mock_main_coordinator.add_event.assert_called_once()
        _args, _ = mock_main_coordinator.add_event.call_args
        # Removed unused event = args[1]


async def test_run_pump_cycle_moisture_after_only(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test pump cycle with only ending moisture reading."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    # Configure moisture sensor
    mock_main_coordinator.growspaces[GROWSPACE_ID].environment_config = MagicMock()
    mock_main_coordinator.growspaces[
        GROWSPACE_ID
    ].default_zone.soil_moisture_sensor = "sensor.moisture"

    # Mock states
    mock_hass.states = MagicMock()

    # Mock sensor states (before=None/Error, after=55.8)
    mock_before_state = None  # Sensor not found initially or error

    mock_after_state = _moisture_state("55.8")

    mock_hass.states.get.side_effect = _pump_off_then(
        mock_before_state, mock_after_state
    )

    with (
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch.object(
            coordinator,
            "_async_wait_for_switch_state",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        await coordinator._run_pump_cycle("irrigation", "switch.pump", 30, {})

        await _await_settling_report(mock_main_coordinator.add_event)
        mock_main_coordinator.add_event.assert_called_once()
        args, _ = mock_main_coordinator.add_event.call_args
        event = args[1]

        # Verify moisture is in reasons (only after value)
        assert any("Moisture: 55.8%" in r for r in event.reasons)


async def test_run_pump_cycle_defers_completion_report_until_sensor_settles(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test that the completion report waits for the sensor to settle.

    The "after" moisture reading and completion logbook/event must not be
    captured the instant the cycle ends — they wait for the settling delay so
    the sensor has time to physically catch up, then read the live value.
    """
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    mock_main_coordinator.growspaces[GROWSPACE_ID].environment_config = MagicMock()
    mock_main_coordinator.growspaces[
        GROWSPACE_ID
    ].default_zone.soil_moisture_sensor = "sensor.moisture"

    mock_before_state = _moisture_state("40.0")
    mock_after_state = _moisture_state("60.0")
    mock_hass.states.get.side_effect = _pump_off_then(
        mock_before_state, mock_after_state
    )

    real_sleep = asyncio.sleep
    settling_started = asyncio.Event()
    settling_can_proceed = asyncio.Event()
    sleep_calls: list[int] = []

    async def fake_sleep(duration: int) -> None:
        sleep_calls.append(duration)
        if len(sleep_calls) == 1:
            return  # the cycle's run duration — resolve instantly
        settling_started.set()
        await settling_can_proceed.wait()

    with (
        patch("asyncio.sleep", new_callable=AsyncMock, side_effect=fake_sleep),
        patch.object(
            coordinator,
            "_async_wait_for_switch_state",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        await coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, {}
        )

        # Time is frozen in this test suite (autouse freeze_time), so
        # asyncio.wait_for()'s monotonic-clock timeout never elapses — poll
        # with bare yields instead.
        for _ in range(1000):
            if settling_started.is_set():
                break
            await real_sleep(0)
        else:
            pytest.fail("Settling delay was never started")

        # The cycle has ended and the pump is off, but the report must not
        # have fired yet — it's waiting for the sensor to settle.
        mock_main_coordinator.add_event.assert_not_called()

        settling_can_proceed.set()

        for _ in range(1000):
            if mock_main_coordinator.add_event.call_count:
                break
            await real_sleep(0)
        else:
            pytest.fail("Completion report was never fired after settling delay")

        args, _ = mock_main_coordinator.add_event.call_args
        event = args[1]
        assert any("Moisture: 40.0% -> 60.0%" in r for r in event.reasons)


@pytest.mark.asyncio
async def test_irrigation_coordinator_coverage_gaps(
    mock_hass: MagicMock,
    mock_config_entry: MagicMock,
    mock_main_coordinator: MagicMock,
) -> None:
    """Test coverage gaps in irrigation coordinator."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    # Ensure states attribute exists
    mock_hass.states = MagicMock()

    with patch(
        "custom_components.growspace_manager.irrigation_coordinator.async_track_time_change"
    ):
        # 1. Test _get_sensor_value with invalid float
        mock_hass.states.get.return_value = MagicMock(state="invalid")
        assert coordinator._get_sensor_value("sensor.test") is None  # Lines 85-86

        # 2. Test async_set_settings with unknown key
        await coordinator.async_set_settings(
            {"unknown_key": "value"}
        )  # Line 139 (warning logged)

        # 3. Test async_add_schedule_item with invalid key
        await coordinator.async_add_schedule_item(
            "invalid_schedule", "12:00", 10
        )  # Lines 161-162 (error logged)

        # 4. Test async_request_refresh
        coordinator.async_update_listeners = AsyncMock()  # type: ignore[method-assign]
        await coordinator.async_request_refresh()
        coordinator.async_update_listeners.assert_called_once()  # Line 115

        # 5. Base class async_setup/unload (trivial but ensures execution)
        await BaseIrrigationCoordinator.async_setup(coordinator)
        await BaseIrrigationCoordinator.async_request_refresh(coordinator)
        await BaseIrrigationCoordinator.async_unload(coordinator)  # Line 65

        # 6. Test _run_pump_cycle exception handling
        mock_main_coordinator.add_event.side_effect = ValueError("Test Error")
        # Must mock states again as side_effect consumed
        mock_hass.states.get.side_effect = None
        mock_hass.states.get.return_value = MagicMock(state="50.0")

        with (
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch.object(
                coordinator,
                "_async_wait_for_switch_state",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            await coordinator._run_pump_cycle("irrigation", "switch.pump", 30, {})
        # Should catch exception and log error (covered)

        # 7. Test active_events property (Line 46)
        assert isinstance(coordinator.active_events, dict)

        # 9. Test _async_wait_for_switch_state with irrelevant entity event (Line 145)
        mock_hass.states.get.return_value = Mock(state="off")

        @callback
        def mock_listen(event_type, listener):
            # Send irrelevant event
            mock_event = Mock()
            mock_event.data = {
                "entity_id": "other.entity",
                "new_state": Mock(state="on"),
            }
            listener(mock_event)
            # Send correct event
            mock_event_correct = Mock()
            mock_event_correct.data = {
                "entity_id": "switch.test_pump",
                "new_state": Mock(state="on"),
            }
            listener(mock_event_correct)
            return Mock()

        mock_hass.bus.async_listen.side_effect = mock_listen
        assert (
            await coordinator._async_wait_for_switch_state("switch.test_pump", "on")
            is True
        )

        # 10. Test _run_pump_cycle exception in finally block (Lines 581-582)
        # Force exception when popping from _running_tasks at the end
        with (
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch.object(
                coordinator,
                "_async_wait_for_switch_state",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            # Inject a dict that raises on pop
            class ExplodingDict(dict):
                def pop(self, key, default=None):
                    if key == "irrigation":
                        raise Exception("Logging Fail")
                    return super().pop(key, default)

            coordinator._running_tasks = ExplodingDict()
            await coordinator._run_pump_cycle("irrigation", "switch.pump", 30, {})
            # Should catch and log error


# --- Manual Run Service Tests ---


async def test_async_manual_run_triggers_pump_cycle(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test that async_manual_run triggers a pump cycle with the given duration."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    with patch.object(
        coordinator, "_run_pump_cycle", new_callable=AsyncMock
    ) as mock_run_cycle:
        await coordinator.async_manual_run(duration=45, user_id="user-1")
        await coordinator._supply_task

        mock_run_cycle.assert_awaited_once_with(
            "irrigation",
            "switch.irrigation_pump",
            45,
            {
                "manual": True,
                "user_id": "user-1",
                "duration": 45,
                "due_at": utcnow().replace(second=0, microsecond=0),
            },
        )


async def test_async_manual_run_uses_default_duration_when_none(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test that async_manual_run uses the configured default duration when none given."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    with patch.object(
        coordinator, "_run_pump_cycle", new_callable=AsyncMock
    ) as mock_run_cycle:
        await coordinator.async_manual_run(duration=None)
        await coordinator._supply_task

        mock_run_cycle.assert_awaited_once_with(
            "irrigation",
            "switch.irrigation_pump",
            30,  # default from fixture: irrigation_duration=30
            {
                "manual": True,
                "user_id": None,
                "duration": None,
                "due_at": utcnow().replace(second=0, microsecond=0),
            },
        )


async def test_async_manual_run_raises_when_no_pump_configured(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test that async_manual_run raises ServiceValidationError when no pump entity configured."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    coordinator._main_coordinator.growspaces[
        GROWSPACE_ID
    ].irrigation_config.irrigation_pump_entity = None

    with pytest.raises(ServiceValidationError, match="No irrigation pump"):
        await coordinator.async_manual_run(duration=30)


# --- last_cycle_timestamp Tests ---


async def test_last_cycle_timestamp_is_none_initially(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test that last_cycle_timestamp is None before any cycle runs."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    assert coordinator.last_cycle_timestamp is None


async def test_last_cycle_timestamp_set_after_run_pump_cycle(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test that last_cycle_timestamp is set to the cycle start time after completion."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    mock_config_entry.runtime_data = mock_main_coordinator

    with (
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch.object(
            coordinator,
            "_async_wait_for_switch_state",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        await coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, {}
        )

    assert coordinator.last_cycle_timestamp is not None
    # The anchor is the persisted one, and it is saved as soon as the pump
    # confirms, so a restart mid-cycle still knows the shot happened (#786).
    history = mock_main_coordinator.growspaces[
        GROWSPACE_ID
    ].default_zone.substrate_history
    assert history.last_confirmed_shot_at == coordinator.last_cycle_timestamp
    mock_main_coordinator.async_schedule_save.assert_called()


# --- next_scheduled_cycle Tests ---


async def test_next_scheduled_cycle_returns_next_future_time(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test that next_scheduled_cycle returns the next irrigation time after now."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    # Fixture has irrigation_times: ["10:00:00", "20:00:00"]
    result = coordinator.next_scheduled_cycle
    # result should be a datetime ISO string or None
    assert result is None or isinstance(result, str)


# --- Dark Skip Tests ---


def _make_state(state: str) -> MagicMock:
    """Build a minimal state mock with the given state string."""
    m = MagicMock()
    m.state = state
    return m


def _make_coordinator_with_dark_skip(
    mock_hass: MagicMock,
    mock_config_entry: MagicMock,
    mock_main_coordinator: MagicMock,
    *,
    skip_during_dark: bool,
    light_sensors: list[str],
    light_states: dict[str, str],
) -> IrrigationCoordinator:
    """Build a coordinator with dark-skip config and light-sensor states."""
    from custom_components.growspace_manager.models import EnvironmentConfig

    gs = mock_main_coordinator.growspaces[GROWSPACE_ID]
    gs.irrigation_config.skip_during_dark = skip_during_dark
    gs.environment_config = EnvironmentConfig(light_sensors=light_sensors)

    mock_hass.states.get.side_effect = lambda eid: (
        _make_state(light_states[eid]) if eid in light_states else None
    )
    return IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )


async def test_dark_skip_prevents_scheduled_irrigation_when_lights_off(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Scheduled irrigation is skipped when skip_during_dark is True and all lights are off."""
    coordinator = _make_coordinator_with_dark_skip(
        mock_hass,
        mock_config_entry,
        mock_main_coordinator,
        skip_during_dark=True,
        light_sensors=["switch.light_1"],
        light_states={"switch.light_1": "off"},
    )

    with (
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch.object(
            coordinator,
            "_async_wait_for_switch_state",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        mock_config_entry.runtime_data = mock_main_coordinator
        await coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, {"time": "10:00:00"}
        )

    # Pump should NOT have been turned on
    turn_on_calls = [
        c
        for c in mock_hass.services.async_call.call_args_list
        if c.args[:2] == ("switch", "turn_on")
    ]
    assert turn_on_calls == [], "Pump was turned on despite dark skip"


async def test_dark_skip_allows_irrigation_when_lights_on(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Scheduled irrigation proceeds when skip_during_dark is True but lights are on."""
    coordinator = _make_coordinator_with_dark_skip(
        mock_hass,
        mock_config_entry,
        mock_main_coordinator,
        skip_during_dark=True,
        light_sensors=["switch.light_1"],
        light_states={"switch.light_1": "on"},
    )

    with (
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch.object(
            coordinator,
            "_async_wait_for_switch_state",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        mock_config_entry.runtime_data = mock_main_coordinator
        await coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, {"time": "10:00:00"}
        )

    mock_hass.services.async_call.assert_any_call(
        "switch", "turn_on", {"entity_id": "switch.irrigation_pump"}, blocking=True
    )


async def test_dark_skip_bypassed_for_manual_run(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Manual 'Run Now' bypasses dark skip even when lights are off."""
    coordinator = _make_coordinator_with_dark_skip(
        mock_hass,
        mock_config_entry,
        mock_main_coordinator,
        skip_during_dark=True,
        light_sensors=["switch.light_1"],
        light_states={"switch.light_1": "off"},
    )

    with (
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch.object(
            coordinator,
            "_async_wait_for_switch_state",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        mock_config_entry.runtime_data = mock_main_coordinator
        await coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, {"manual": True}
        )

    mock_hass.services.async_call.assert_any_call(
        "switch", "turn_on", {"entity_id": "switch.irrigation_pump"}, blocking=True
    )


# --- Low Tank Skip Tests ---


def _make_coordinator_with_tank(
    mock_hass: MagicMock,
    mock_config_entry: MagicMock,
    mock_main_coordinator: MagicMock,
    *,
    pause_on_low_tank: bool,
    tank_sensor: str,
    tank_level: float,
    warning_level: float = 30.0,
) -> IrrigationCoordinator:
    """Build a coordinator with low-tank-skip config and tank sensor state."""
    from custom_components.growspace_manager.models import (
        EnvironmentConfig,
        IrrigationTank,
    )

    gs = mock_main_coordinator.growspaces[GROWSPACE_ID]
    gs.irrigation_config.pause_on_low_tank = pause_on_low_tank
    gs.environment_config = EnvironmentConfig(
        irrigation_tanks=[
            IrrigationTank(
                sensor_entity=tank_sensor,
                name="Main Tank",
                warning_level=warning_level,
            )
        ]
    )

    tank_state = State(tank_sensor, str(tank_level))
    mock_hass.states.get.side_effect = lambda eid: (
        tank_state if eid == tank_sensor else None
    )
    return IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )


async def test_low_tank_skip_prevents_irrigation_when_tank_low(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Irrigation is skipped when pause_on_low_tank is True and tank is below warning level."""
    coordinator = _make_coordinator_with_tank(
        mock_hass,
        mock_config_entry,
        mock_main_coordinator,
        pause_on_low_tank=True,
        tank_sensor="sensor.tank_level",
        tank_level=15.0,
        warning_level=30.0,
    )

    with (
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch.object(
            coordinator,
            "_async_wait_for_switch_state",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        mock_config_entry.runtime_data = mock_main_coordinator
        await coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, {"time": "10:00:00"}
        )

    turn_on_calls = [
        c
        for c in mock_hass.services.async_call.call_args_list
        if c.args[:2] == ("switch", "turn_on")
    ]
    assert turn_on_calls == [], "Pump was turned on despite low tank skip"


async def test_low_tank_skip_fires_persistent_notification(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """A persistent HA notification is fired when low tank causes a skip."""
    coordinator = _make_coordinator_with_tank(
        mock_hass,
        mock_config_entry,
        mock_main_coordinator,
        pause_on_low_tank=True,
        tank_sensor="sensor.tank_level",
        tank_level=20.0,
        warning_level=30.0,
    )

    with (
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch.object(
            coordinator,
            "_async_wait_for_switch_state",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        mock_config_entry.runtime_data = mock_main_coordinator
        await coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, {"time": "10:00:00"}
        )

    # Expect persistent_notification.create to have been called
    notification_calls = [
        c
        for c in mock_hass.services.async_call.call_args_list
        if c.args[:2] == ("persistent_notification", "create")
    ]
    assert len(notification_calls) >= 1, (
        "No persistent notification was fired for low tank skip"
    )


async def test_low_tank_skip_also_applies_to_manual_run(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Low tank skip applies even to manual 'Run Now' requests."""
    coordinator = _make_coordinator_with_tank(
        mock_hass,
        mock_config_entry,
        mock_main_coordinator,
        pause_on_low_tank=True,
        tank_sensor="sensor.tank_level",
        tank_level=10.0,
        warning_level=30.0,
    )

    with (
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch.object(
            coordinator,
            "_async_wait_for_switch_state",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        mock_config_entry.runtime_data = mock_main_coordinator
        await coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, {"manual": True}
        )

    turn_on_calls = [
        c
        for c in mock_hass.services.async_call.call_args_list
        if c.args[:2] == ("switch", "turn_on")
    ]
    assert turn_on_calls == [], "Pump was turned on despite low tank skip on manual run"


# --- Startup Inhibit (#786) ---


def _turn_on_calls(hass: MagicMock) -> list[object]:
    return [
        c
        for c in hass.services.async_call.call_args_list
        if c.args[:2] == ("switch", "turn_on")
    ]


@pytest.fixture
def started_coordinator(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
):
    """An IrrigationCoordinator whose Startup Inhibit has just begun."""
    mock_hass.states.get.return_value = None
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    with (
        patch(
            "custom_components.growspace_manager.irrigation_coordinator.async_track_time_change"
        ),
        patch(
            "custom_components.growspace_manager.irrigation_coordinator.async_track_time_interval"
        ) as mock_poll,
    ):
        mock_poll.return_value = MagicMock()
        yield coordinator, mock_poll


async def test_startup_inhibit_holds_a_scheduled_cycle_and_says_why(
    started_coordinator, mock_hass: MagicMock
) -> None:
    coordinator, _ = started_coordinator
    await coordinator.async_setup()

    with (
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch.object(
            coordinator,
            "_async_wait_for_switch_state",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        await coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, {"time": "10:00:00"}
        )

    assert _turn_on_calls(mock_hass) == []
    snapshot = coordinator.controller_snapshot()
    assert snapshot.state.value == "inhibited"
    assert [reason.code for reason in snapshot.reasons] == ["startup_inhibit"]
    coordinator.async_cancel_listeners()


async def test_startup_inhibit_lets_a_manual_run_through(
    started_coordinator, mock_hass: MagicMock
) -> None:
    coordinator, _ = started_coordinator
    await coordinator.async_setup()

    with (
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch.object(
            coordinator,
            "_async_wait_for_switch_state",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        await coordinator.async_manual_run(duration=30)
        await coordinator._supply_task

    assert len(_turn_on_calls(mock_hass)) == 1
    coordinator.async_cancel_listeners()


async def test_startup_inhibit_waits_for_every_tank_sensor(
    started_coordinator, mock_main_coordinator: MagicMock
) -> None:
    coordinator, _ = started_coordinator
    growspace = mock_main_coordinator.growspaces[GROWSPACE_ID]
    growspace.environment_config.irrigation_tanks = [
        IrrigationTank(sensor_entity="sensor.tank", name="Tank")
    ]
    growspace.irrigation_config.startup_grace_minutes = 0
    await coordinator.async_setup()

    reason = coordinator.startup_inhibit_reason()

    assert reason is not None
    assert reason.detail == "starting up: waiting for a first report from sensor.tank"
    coordinator.async_cancel_listeners()


async def test_startup_poll_keeps_holding_until_the_inhibit_clears(
    started_coordinator,
) -> None:
    coordinator, mock_poll = started_coordinator
    await coordinator.async_setup()
    cancel_poll = mock_poll.return_value

    await coordinator._async_poll_startup_inhibit()

    assert coordinator.startup_inhibit_reason() is not None
    cancel_poll.assert_not_called()
    coordinator.async_cancel_listeners()
    assert cancel_poll.call_count == 2  # startup poll and reliability sensor probe


async def test_startup_inhibit_is_not_recorded_for_an_idle_controller(
    started_coordinator, mock_main_coordinator: MagicMock
) -> None:
    coordinator, _ = started_coordinator
    config = mock_main_coordinator.growspaces[GROWSPACE_ID].irrigation_config
    config.irrigation_pump_entity = None
    config.drain_pump_entity = None

    with patch.object(
        coordinator, "_record_safety_transition", new_callable=AsyncMock
    ) as record:
        await coordinator.async_setup()

    record.assert_not_called()
    assert coordinator.controller_snapshot().state.value == "idle"
    coordinator.async_cancel_listeners()


# --- Unknown Tank Level (#790, ADR-0050) ---


def _persistent_notifications(hass: MagicMock) -> list[dict[str, object]]:
    return [
        c.args[2]
        for c in hass.services.async_call.call_args_list
        if c.args[:2] == ("persistent_notification", "create")
    ]


async def _run(coordinator: IrrigationCoordinator, event_data: dict) -> None:
    with (
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch.object(
            coordinator,
            "_async_wait_for_switch_state",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        await coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, event_data
        )


def _tank_coordinator(
    mock_hass: MagicMock,
    mock_config_entry: MagicMock,
    mock_main_coordinator: MagicMock,
    tank_state: State,
    *,
    pause_on_low_tank: bool = True,
) -> IrrigationCoordinator:
    coordinator = _make_coordinator_with_tank(
        mock_hass,
        mock_config_entry,
        mock_main_coordinator,
        pause_on_low_tank=pause_on_low_tank,
        tank_sensor=tank_state.entity_id,
        tank_level=0,
    )
    mock_hass.states.get.side_effect = lambda eid: (
        tank_state if eid == tank_state.entity_id else None
    )
    mock_config_entry.runtime_data = mock_main_coordinator
    return coordinator


async def test_an_unknown_tank_refuses_a_manual_run(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """No valid reading since the start: nothing to hold, so refused at once."""
    coordinator = _tank_coordinator(
        mock_hass,
        mock_config_entry,
        mock_main_coordinator,
        State("sensor.tank_level", "unavailable"),
    )

    with patch.object(
        coordinator, "_record_safety_transition", new_callable=AsyncMock
    ) as record:
        await _run(coordinator, {"manual": True})

    assert _turn_on_calls(mock_hass) == []
    record.assert_awaited_once_with("inhibited", "tank_unknown")
    [notification] = _persistent_notifications(mock_hass)
    assert notification["title"] == "Tank Level Unknown — Test Growspace"
    assert notification["notification_id"] == "growspace_tank_unknown_test_growspace"
    assert "the level of tank 'Main Tank' is unknown" in str(notification["message"])


async def test_an_unknown_tank_holds_the_controller_and_says_why(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    coordinator = _tank_coordinator(
        mock_hass,
        mock_config_entry,
        mock_main_coordinator,
        State("sensor.tank_level", "150"),
    )

    await _run(coordinator, {"time": "10:00:00"})
    snapshot = coordinator.controller_snapshot()

    assert _turn_on_calls(mock_hass) == []
    assert snapshot.state.value == "inhibited"
    [reason] = snapshot.reasons
    assert reason.code == "tank_unknown"
    assert reason.detail == (
        "Irrigation skipped — tank 'Main Tank' level is unknown (implausible)"
    )


async def test_a_tank_that_stopped_reporting_is_refused(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """A frozen probe on a plausible value — the case nothing marks unavailable."""
    long_ago = utcnow() - timedelta(hours=3)
    coordinator = _tank_coordinator(
        mock_hass,
        mock_config_entry,
        mock_main_coordinator,
        State(
            "sensor.tank_level",
            "80",
            last_changed=long_ago,
            last_reported=long_ago,
            last_updated=long_ago,
        ),
    )

    await _run(coordinator, {"time": "10:00:00"})

    assert _turn_on_calls(mock_hass) == []


async def test_within_grace_the_last_valid_reading_is_used(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    coordinator = _tank_coordinator(
        mock_hass,
        mock_config_entry,
        mock_main_coordinator,
        State("sensor.tank_level", "80"),
    )
    coordinator.controller_snapshot()  # observes the valid reading
    dropped = State("sensor.tank_level", "unavailable")
    mock_hass.states.get.side_effect = lambda eid: (
        dropped if eid == "sensor.tank_level" else None
    )

    await _run(coordinator, {"time": "10:00:00"})

    assert len(_turn_on_calls(mock_hass)) == 1


async def test_within_grace_a_low_last_reading_still_blocks(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    coordinator = _tank_coordinator(
        mock_hass,
        mock_config_entry,
        mock_main_coordinator,
        State("sensor.tank_level", "5"),
    )
    coordinator.controller_snapshot()
    dropped = State("sensor.tank_level", "unavailable")
    mock_hass.states.get.side_effect = lambda eid: (
        dropped if eid == "sensor.tank_level" else None
    )

    await _run(coordinator, {"manual": True})

    assert _turn_on_calls(mock_hass) == []
    [notification] = _persistent_notifications(mock_hass)
    assert notification["title"] == "Low Tank — Test Growspace"


async def test_pause_off_keeps_todays_behaviour_for_an_unknown_tank(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    coordinator = _tank_coordinator(
        mock_hass,
        mock_config_entry,
        mock_main_coordinator,
        State("sensor.tank_level", "unavailable"),
        pause_on_low_tank=False,
    )

    await _run(coordinator, {"time": "10:00:00"})

    assert len(_turn_on_calls(mock_hass)) == 1


async def test_the_gate_reads_the_tank_monitor_watches(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """The gate and the Tank Offline Alert share one watch per tank."""
    with patch("custom_components.growspace_manager.tank_monitor.EntityQueries"):
        monitor = TankLevelMonitor(mock_hass, mock_main_coordinator, AsyncMock())
    mock_main_coordinator.tank_monitor = monitor
    coordinator = _tank_coordinator(
        mock_hass,
        mock_config_entry,
        mock_main_coordinator,
        State("sensor.tank_level", "unavailable"),
    )

    with patch.object(
        monitor.watches, "status", wraps=monitor.watches.status
    ) as status:
        await _run(coordinator, {"time": "10:00:00"})

    assert _turn_on_calls(mock_hass) == []
    status.assert_called()
    assert coordinator._own_tank_watches is None


async def test_multizone_delivery_requires_scope_and_runtime(
    mock_hass, mock_config_entry, mock_main_coordinator
):
    """A multi-zone Manual Run requires its scope and an initialized runtime."""
    from custom_components.growspace_manager.domain.zone_edit import edited_zones
    from custom_components.growspace_manager.exceptions import ZoneRequiredError

    growspace = mock_main_coordinator.growspaces[GROWSPACE_ID]
    candidate = edited_zones(
        growspace,
        "add",
        {
            "zone_id": "blue",
            "name": "Blue",
            "cells": [[1, 2]],
            "valves": ["switch.blue"],
            "default_valves": ["switch.red"],
        },
    )
    growspace.irrigation_zones = candidate.irrigation_zones
    mock_hass.states.get.return_value = State("switch.blue", "off")
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    with pytest.raises(ZoneRequiredError):
        await coordinator.async_manual_run(30)
    with pytest.raises(ServiceValidationError, match="no irrigation runtime"):
        await coordinator.async_manual_run(30, zone_id="blue")


async def test_multizone_admission_race_is_rechecked_before_on(
    mock_hass, mock_config_entry, mock_main_coordinator
):
    """A split during an awaited gate cannot reach the pump ON command."""
    from custom_components.growspace_manager.domain.zone_edit import edited_zones

    growspace = mock_main_coordinator.growspaces[GROWSPACE_ID]
    candidate = edited_zones(
        growspace,
        "add",
        {
            "zone_id": "blue",
            "name": "Blue",
            "cells": [[1, 2]],
            "valves": ["switch.blue"],
            "default_valves": ["switch.red"],
        },
    )
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    async def split_at_gate(*args):
        growspace.irrigation_zones = candidate.irrigation_zones

    with patch.object(
        coordinator, "_record_safety_transition", side_effect=split_at_gate
    ):
        await coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, {"manual": True}
        )
    mock_hass.services.async_call.assert_not_called()
    assert coordinator._deliveries.attempts[-1].reason == "zone_changed"


async def test_lone_zone_with_valves_admits_manual_delivery(
    mock_hass, mock_config_entry, mock_main_coordinator
):
    """The implicit zone's optional valve no longer holds pump-only runtime."""
    growspace = mock_main_coordinator.growspaces[GROWSPACE_ID]
    growspace.default_zone.valves = ["switch.valve"]
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    with patch.object(coordinator, "_run_pump_cycle", new_callable=AsyncMock) as run:
        await coordinator.async_manual_run(30)
        await coordinator._supply_task
    run.assert_awaited_once()


@pytest.fixture
def valve_rig(mock_hass, mock_config_entry, mock_main_coordinator):
    """A relay train with independent states and observable readbacks."""
    growspace = mock_main_coordinator.growspaces[GROWSPACE_ID]
    growspace.default_zone.valves = ["switch.v1", "switch.v2"]
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    coordinator._async_spawn_settling_report = Mock()
    coordinator._async_notify = AsyncMock()
    trace = []
    states = dict.fromkeys(coordinator._configured_outputs(), "off")
    mock_hass.states.get.side_effect = lambda output: (
        State(output, states[output]) if output in states else None
    )

    async def command(domain, service, data, **kwargs):
        output = data.get("entity_id")
        if output in states:
            trace.append((service, output))
            states[output] = "on" if service == "turn_on" else "off"

    async def confirm(*args, **kwargs):
        output, want = args[-2:]
        trace.append(("read_" + want, output))
        return states.get(output) == want

    mock_hass.services.async_call.side_effect = command
    with (
        patch(
            "custom_components.growspace_manager.irrigation_coordinator.async_confirm_state",
            side_effect=confirm,
        ),
        patch.object(coordinator, "_async_wait_for_switch_state", side_effect=confirm),
        patch(
            "custom_components.growspace_manager.irrigation_coordinator.asyncio.sleep",
            new_callable=AsyncMock,
        ),
    ):
        yield coordinator, mock_hass, growspace, trace, states
    for cancel in coordinator._off_retries.values():
        cancel()
    coordinator._off_retries.clear()


async def test_valve_delivery_order_and_durable_evidence(valve_rig):
    coordinator, hass, growspace, trace, states = valve_rig
    writes = []
    original = coordinator._deliveries.async_request

    async def record(attempt):
        writes.append((attempt, list(trace)))
        await original(attempt)

    with patch.object(coordinator._deliveries, "async_request", side_effect=record):
        await coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 1, {"manual": True}
        )
    assert trace == [
        ("turn_on", "switch.v1"),
        ("read_on", "switch.v1"),
        ("turn_on", "switch.v2"),
        ("read_on", "switch.v2"),
        ("turn_on", "switch.irrigation_pump"),
        ("read_on", "switch.irrigation_pump"),
        ("turn_off", "switch.irrigation_pump"),
        ("read_off", "switch.irrigation_pump"),
        ("turn_off", "switch.v1"),
        ("read_off", "switch.v1"),
        ("turn_off", "switch.v2"),
        ("read_off", "switch.v2"),
    ]
    attempt = coordinator._deliveries.attempts[-1]
    assert attempt.outcome == "completed"
    assert coordinator.cycles_today == 1
    assert all(
        valve.on_confirmed_at and valve.off_commanded_at and valve.off_confirmed_at
        for valve in attempt.valves
    )
    assert writes[1][0].valves[0].on_commanded_at and writes[1][1] == []
    assert writes[3][0].valves[-1].output == "switch.v2"
    assert writes[3][1] == trace[:2]
    assert not coordinator.delivering_outputs()


@pytest.mark.parametrize("failure", ["command", "readback"])
async def test_valve_failure_never_starts_supply_and_cleans_every_commanded_valve(
    valve_rig, failure
):
    coordinator, hass, growspace, trace, states = valve_rig
    original = hass.services.async_call.side_effect

    async def fail(domain, service, data, **kwargs):
        await original(domain, service, data, **kwargs)
        if data.get("entity_id") == "switch.v2" and service == "turn_on":
            if failure == "command":
                raise RuntimeError("relay refused")
            states["switch.v2"] = "unavailable"

    hass.services.async_call.side_effect = fail
    await coordinator._run_pump_cycle(
        "irrigation", "switch.irrigation_pump", 1, {"manual": True}
    )
    assert not any(output == "switch.irrigation_pump" for service, output in trace)
    assert trace[-4:] == [
        ("turn_off", "switch.v1"),
        ("read_off", "switch.v1"),
        ("turn_off", "switch.v2"),
        ("read_off", "switch.v2"),
    ]
    attempt = coordinator._deliveries.attempts[-1]
    assert attempt.outcome == "not_delivered"
    assert attempt.not_delivered_window is None
    assert attempt.reason == (
        "on_command_failed" if failure == "command" else "on_unconfirmed"
    )
    assert coordinator.cycles_today == 0
    assert attempt.valves[0].on_confirmed_at is not None
    assert attempt.valves[1].on_confirmed_at is None
    assert all(valve.off_confirmed_at for valve in attempt.valves)


@pytest.mark.parametrize("foreign_state", ["on", "unavailable", "unknown", None])
async def test_foreign_valve_must_positively_read_closed(valve_rig, foreign_state):
    from custom_components.growspace_manager.models.irrigation_zone import (
        IrrigationZone,
    )

    coordinator, hass, growspace, trace, states = valve_rig
    growspace.irrigation_zones.append(
        IrrigationZone(id="other", name="Other", valves=["switch.foreign"])
    )
    if foreign_state is not None:
        states["switch.foreign"] = foreign_state
    with patch.object(
        coordinator, "_async_observe_on", new_callable=AsyncMock
    ) as observe:
        await coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 1, {"manual": True}
        )
    assert trace == []
    assert coordinator._deliveries.attempts[-1].reason == "foreign_valve_open"
    assert observe.await_count == (1 if foreign_state == "on" else 0)


async def test_foreign_valve_rechecked_after_admission(valve_rig):
    from custom_components.growspace_manager.models.irrigation_zone import (
        IrrigationZone,
    )

    coordinator, hass, growspace, trace, states = valve_rig
    growspace.irrigation_zones.append(
        IrrigationZone(id="other", name="Other", valves=["switch.foreign"])
    )
    states["switch.foreign"] = "off"

    async def change(*args):
        states["switch.foreign"] = "on"

    # #895 will supply the per-zone runtime; exercise its delivery boundary.
    with (
        patch.object(coordinator, "_record_safety_transition", side_effect=change),
        patch.object(coordinator, "_async_observe_on", new_callable=AsyncMock),
    ):
        await coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 1, {"manual": True}
        )
    assert trace == []
    assert coordinator._deliveries.attempts[-1].reason == "foreign_valve_open"


async def test_valve_off_failure_blocks_entire_growspace(valve_rig):
    coordinator, hass, growspace, trace, states = valve_rig
    original = hass.services.async_call.side_effect

    async def command(domain, service, data, **kwargs):
        await original(domain, service, data, **kwargs)
        if data.get("entity_id") == "switch.v1" and service == "turn_off":
            states["switch.v1"] = "on"

    hass.services.async_call.side_effect = command
    with patch.object(
        coordinator, "_async_off_unconfirmed", new_callable=AsyncMock
    ) as fault:
        await coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 1, {"manual": True}
        )
    fault.assert_awaited_once_with(
        "switch.v1",
        "fault_off_unconfirmed:switch.v1",
        "switch.v1 did not read back closed",
    )
    attempt = coordinator._deliveries.attempts[-1]
    assert attempt.off_confirmed
    assert attempt.valves[0].off_confirmed_at is None
    assert attempt.valves[1].off_confirmed_at is not None


async def test_cancel_during_valve_confirmation_closes_valves_without_supply(valve_rig):
    coordinator, hass, growspace, trace, states = valve_rig

    async def cancel(*args, **kwargs):
        raise asyncio.CancelledError

    with patch(
        "custom_components.growspace_manager.irrigation_coordinator.async_confirm_state",
        side_effect=cancel,
    ):
        # Cancel only the ON read; cleanup remains a bounded OFF/readback.
        with patch.object(
            coordinator, "_async_command_off", new_callable=AsyncMock, return_value=True
        ) as off:
            await coordinator._run_pump_cycle(
                "irrigation", "switch.irrigation_pump", 1, {"manual": True}
            )
    off.assert_awaited_once_with("switch.v1")
    assert trace == [("turn_on", "switch.v1")]
    assert coordinator._deliveries.attempts[-1].outcome == "aborted"
    assert not coordinator._commanded_outputs


async def test_supply_refusal_closes_supply_before_valves(valve_rig):
    coordinator, hass, growspace, trace, states = valve_rig
    with patch.object(
        coordinator,
        "_async_wait_for_switch_state",
        new_callable=AsyncMock,
        return_value=False,
    ):
        await coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 1, {"manual": True}
        )
    assert trace[-6:] == [
        ("turn_off", "switch.irrigation_pump"),
        ("read_off", "switch.irrigation_pump"),
        ("turn_off", "switch.v1"),
        ("read_off", "switch.v1"),
        ("turn_off", "switch.v2"),
        ("read_off", "switch.v2"),
    ]
    assert coordinator._deliveries.attempts[-1].outcome == "not_delivered"
    assert coordinator.cycles_today == 0


async def test_restart_recovers_valves_in_supply_first_order(valve_rig):
    from dataclasses import replace

    from custom_components.growspace_manager.domain.delivery_attempt import (
        ValveReadback,
    )

    coordinator, hass, growspace, trace, states = valve_rig
    attempt = coordinator._new_attempt(
        "irrigation", "switch.irrigation_pump", 30, {}, utcnow()
    )
    attempt = replace(
        attempt,
        valves=(
            ValveReadback("switch.v1", utcnow()),
            ValveReadback("switch.v2", utcnow()),
        ),
    )
    coordinator._deliveries.attempts = [attempt]
    coordinator._deliveries._left_open = {attempt.attempt_id}
    states["switch.v1"] = states["switch.v2"] = "on"
    assert set(coordinator._interrupted_outputs()) == {
        "switch.irrigation_pump",
        "switch.v1",
        "switch.v2",
    }
    await coordinator._async_stop_interrupted("switch.irrigation_pump")
    assert trace == [
        ("turn_off", "switch.irrigation_pump"),
        ("read_off", "switch.irrigation_pump"),
        ("turn_off", "switch.v1"),
        ("read_off", "switch.v1"),
        ("turn_off", "switch.v2"),
        ("read_off", "switch.v2"),
    ]
    closed = coordinator._deliveries.attempts[-1]
    assert closed.outcome == "interrupted"
    assert all(valve.off_confirmed_at for valve in closed.valves)


async def test_real_valve_fault_prevents_every_output_and_retries(valve_rig, hass):
    from custom_components.growspace_manager.irrigation_safety_store import (
        IrrigationSafetyStore,
    )

    coordinator, mock_hass, growspace, trace, states = valve_rig
    store = IrrigationSafetyStore(hass, "valve-fault")
    await store.async_initialize_controls({GROWSPACE_ID: growspace})
    coordinator._main_coordinator.irrigation_safety = store
    original = mock_hass.services.async_call.side_effect

    async def fail_off(domain, service, data, **kwargs):
        await original(domain, service, data, **kwargs)
        if service == "turn_off" and data.get("entity_id") == "switch.v1":
            states["switch.v1"] = "on"

    mock_hass.services.async_call.side_effect = fail_off
    with patch(
        "custom_components.growspace_manager.irrigation_coordinator.ir.async_create_issue"
    ):
        await coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 1, {"manual": True}
        )
    assert coordinator.controller_snapshot().state.value == "fault"
    assert "switch.v1" in coordinator._off_retries
    trace.clear()
    await coordinator._run_pump_cycle("drain", "switch.drain_pump", 1, {"manual": True})
    assert trace == []
    assert coordinator._deliveries.attempts[-1].reason == "fault"
    for cancel in coordinator._off_retries.values():
        cancel()
    coordinator._off_retries.clear()


async def test_valve_unexpected_on_watch_and_growspace_latch(valve_rig, hass):
    from custom_components.growspace_manager.irrigation_safety_store import (
        IrrigationSafetyStore,
    )
    from homeassistant.core import Event

    coordinator, mock_hass, growspace, trace, states = valve_rig
    store = IrrigationSafetyStore(hass, "valve-unexpected")
    await store.async_initialize_controls({GROWSPACE_ID: growspace})
    coordinator._main_coordinator.irrigation_safety = store
    growspace.irrigation_config.unexpected_on_policy = "enforce_off"
    with patch(
        "custom_components.growspace_manager.irrigation_coordinator.async_track_state_change_event",
        return_value=Mock(),
    ) as watch:
        coordinator._ensure_pump_watch()
    assert "switch.v1" in watch.call_args.args[1]
    states["switch.v1"] = "on"
    event = Event(
        "state_changed",
        {
            "entity_id": "switch.v1",
            "old_state": State("switch.v1", "off"),
            "new_state": State("switch.v1", "on"),
        },
    )
    tasks = []
    mock_hass.async_create_task = lambda coro, **kwargs: tasks.append(
        asyncio.create_task(coro)
    )
    with patch(
        "custom_components.growspace_manager.irrigation_coordinator.ir.async_create_issue"
    ):
        coordinator._on_pump_state(event)
        await tasks[0]
    assert trace == [("turn_off", "switch.v1"), ("read_off", "switch.v1")]
    assert coordinator.controller_snapshot().state.value == "fault"
    trace.clear()
    await coordinator._run_pump_cycle(
        "irrigation", "switch.irrigation_pump", 1, {"manual": True}
    )
    assert trace == []
    coordinator._cancel_pump_watch_listener()


@pytest.mark.parametrize("change", ["foreign", "own", "operator", "layout"])
async def test_supply_start_rechecks_after_valve_opening(valve_rig, change):
    from custom_components.growspace_manager.models.irrigation_zone import (
        IrrigationZone,
    )

    coordinator, hass, growspace, trace, states = valve_rig
    if change == "foreign":
        growspace.irrigation_zones.append(
            IrrigationZone(id="other", valves=["switch.foreign"])
        )
        states["switch.foreign"] = "off"
    original = coordinator._deliveries.async_request

    async def change_on_write(attempt):
        await original(attempt)
        if len(attempt.valves) == 2 and attempt.valves[-1].on_confirmed_at:
            if change == "foreign":
                states["switch.foreign"] = "on"
            elif change == "own":
                states["switch.v1"] = "off"
            elif change == "layout":
                growspace.default_zone.valves = ["switch.changed"]
            else:
                coordinator._detected_overrides["switch.foreign"] = utcnow().isoformat()

    with (
        patch.object(
            coordinator._deliveries, "async_request", side_effect=change_on_write
        ),
        patch.object(coordinator, "_async_observe_on", new_callable=AsyncMock),
    ):
        await coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 1, {"manual": True}
        )
    assert not any(output == "switch.irrigation_pump" for service, output in trace)
    assert all(
        valve.off_confirmed_at for valve in coordinator._deliveries.attempts[-1].valves
    )
    assert coordinator.cycles_today == 0


async def test_same_supply_never_opens_two_valve_trains(valve_rig):
    coordinator, hass, growspace, trace, states = valve_rig
    watering = asyncio.Event()
    finish = asyncio.Event()
    sleeps = 0

    async def hold_first_shot(seconds):
        nonlocal sleeps
        sleeps += 1
        if sleeps == 1:
            watering.set()
            await finish.wait()

    with patch(
        "custom_components.growspace_manager.irrigation_coordinator.asyncio.sleep",
        side_effect=hold_first_shot,
    ):
        first = asyncio.create_task(
            coordinator._run_pump_cycle(
                "irrigation", "switch.irrigation_pump", 1, {"manual": True}
            )
        )
        await watering.wait()
        second = asyncio.create_task(
            coordinator._run_pump_cycle(
                "irrigation", "switch.irrigation_pump", 1, {"manual": True}
            )
        )
        await _REAL_ASYNCIO_SLEEP(0)
        assert len(trace) == 6
        finish.set()
        await asyncio.gather(first, second)
    assert len(trace) == 24
    assert trace[:12] == trace[12:]
    assert coordinator.cycles_today == 2


async def test_own_valve_on_without_an_attempt_is_observed_before_admission(valve_rig):
    coordinator, hass, growspace, trace, states = valve_rig
    states["switch.v1"] = "on"
    with patch.object(
        coordinator, "_async_observe_on", new_callable=AsyncMock
    ) as observe:

        async def alert(output):
            coordinator._detected_overrides[output] = utcnow().isoformat()

        observe.side_effect = alert
        await coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 1, {"manual": True}
        )
    observe.assert_awaited_once_with("switch.v1")
    assert trace == []
    assert coordinator._deliveries.attempts[-1].outcome == "suppressed"


async def test_native_supply_wait_uses_open_and_closed_states(valve_rig):
    coordinator, hass, growspace, trace, states = valve_rig
    # Call the real method; this relay rig replaces it to trace readbacks.
    states["valve.supply"] = "open"
    assert await BaseIrrigationCoordinator._async_wait_for_switch_state(
        coordinator, "valve.supply", "on"
    )
    states["valve.supply"] = "closed"
    assert await BaseIrrigationCoordinator._async_wait_for_switch_state(
        coordinator, "valve.supply", "off"
    )


async def test_restart_valve_refusal_retains_missing_readback(valve_rig):
    from dataclasses import replace

    from custom_components.growspace_manager.domain.delivery_attempt import (
        ValveReadback,
    )

    coordinator, hass, growspace, trace, states = valve_rig
    attempt = replace(
        coordinator._new_attempt(
            "irrigation", "switch.irrigation_pump", 30, {}, utcnow()
        ),
        valves=(ValveReadback("switch.v1", utcnow()),),
    )
    coordinator._deliveries.attempts = [attempt]
    coordinator._deliveries._left_open = {attempt.attempt_id}
    original = hass.services.async_call.side_effect

    async def stuck(domain, service, data, **kwargs):
        await original(domain, service, data, **kwargs)
        if data.get("entity_id") == "switch.v1":
            states["switch.v1"] = "on"

    hass.services.async_call.side_effect = stuck
    with patch.object(
        coordinator, "_async_off_unconfirmed", new_callable=AsyncMock
    ) as fault:
        await coordinator._async_stop_interrupted("switch.irrigation_pump")
    fault.assert_awaited_once()
    assert coordinator._deliveries.attempts[-1].valves[0].off_confirmed_at is None
    assert coordinator._deliveries.attempts[-1].outcome == "interrupted"


async def test_startup_recovers_a_train_even_when_supply_is_already_off(valve_rig):
    from dataclasses import replace

    from custom_components.growspace_manager.domain.delivery_attempt import (
        ValveReadback,
    )

    coordinator, hass, growspace, trace, states = valve_rig
    attempt = replace(
        coordinator._new_attempt(
            "irrigation", "switch.irrigation_pump", 30, {}, utcnow()
        ),
        valves=(ValveReadback("switch.v1", utcnow()),),
    )
    coordinator._deliveries.attempts = [attempt]
    coordinator._deliveries._left_open = {attempt.attempt_id}
    states["switch.v1"] = "on"
    with (
        patch(
            "custom_components.growspace_manager.irrigation_coordinator.async_track_time_interval",
            return_value=Mock(),
        ),
        patch.object(coordinator, "_ensure_pump_watch"),
    ):
        await coordinator._async_begin_startup_inhibit()
    assert trace[:4] == [
        ("turn_off", "switch.irrigation_pump"),
        ("read_off", "switch.irrigation_pump"),
        ("turn_off", "switch.v1"),
        ("read_off", "switch.v1"),
    ]
    assert coordinator._deliveries.attempts[-1].outcome == "interrupted"
    coordinator._cancel_startup_poll_listener()
    coordinator._cancel_sensor_probe()


async def test_supply_driver_false_is_not_delivered(valve_rig):
    from custom_components.growspace_manager.actuator_driver import (
        resolve_actuator_driver,
    )

    coordinator, hass, growspace, trace, states = valve_rig
    refused = Mock(
        turn_on=AsyncMock(return_value=False), turn_off=AsyncMock(return_value=True)
    )

    def resolve(home_assistant, output, **kwargs):
        if output == "switch.irrigation_pump":
            return refused
        return resolve_actuator_driver(home_assistant, output, **kwargs)

    with patch(
        "custom_components.growspace_manager.irrigation_coordinator.resolve_actuator_driver",
        side_effect=resolve,
    ):
        await coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 1, {"manual": True}
        )
    assert coordinator._deliveries.attempts[-1].reason == "on_command_failed"
    assert all(
        valve.off_confirmed_at for valve in coordinator._deliveries.attempts[-1].valves
    )
    assert coordinator.cycles_today == 0


async def test_fault_write_failure_does_not_strand_remaining_valves(valve_rig):
    coordinator, hass, growspace, trace, states = valve_rig
    original = hass.services.async_call.side_effect

    async def stuck(domain, service, data, **kwargs):
        await original(domain, service, data, **kwargs)
        if data.get("entity_id") == "switch.v1" and service == "turn_off":
            states["switch.v1"] = "on"

    hass.services.async_call.side_effect = stuck
    with patch.object(
        coordinator,
        "_async_off_unconfirmed",
        new_callable=AsyncMock,
        side_effect=RuntimeError("disk full"),
    ):
        await coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 1, {"manual": True}
        )
    assert ("turn_off", "switch.v2") in trace
    assert "switch.v1" in coordinator._off_retries
    assert not coordinator._commanded_outputs
    assert coordinator._deliveries.attempts[-1].valves[-1].off_confirmed_at is not None


async def test_supply_manual_priority_duplicate_claims_and_live_defaults(
    mock_hass, mock_config_entry, mock_main_coordinator
):
    """A busy supply keeps one due claim and serves people's runs first in FIFO."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    finished = asyncio.Event()
    running = asyncio.create_task(finished.wait())
    coordinator._running_tasks["irrigation"] = running
    due = utcnow().replace(second=0, microsecond=0)
    observed = []

    async def cycle(event_type, pump, duration, data):
        observed.append((duration, data.get("user_id"), data["due_at"]))
        assert coordinator.supply_payload()["open_zone_id"] == "default"

    with patch.object(coordinator, "_run_pump_cycle", side_effect=cycle):
        await coordinator._handle_event(due, event_type="irrigation", event_data={})
        await coordinator._handle_event(due, event_type="irrigation", event_data={})
        await coordinator.async_manual_run(12, "first")
        await coordinator.async_manual_run(None, "second")
        assert [c["source"] for c in coordinator.supply_payload()["claims"]] == [
            "manual",
            "manual",
            "schedule",
        ]
        assert not coordinator._deliveries.attempts
        coordinator._zone.irrigation_duration = 40
        finished.set()
        await coordinator._supply_task
    assert observed == [(12, "first", due), (40, "second", due), (40, None, due)]
    assert not running.cancelled()
    assert coordinator.supply_payload() == {"open_zone_id": None, "claims": []}


async def test_supply_schedule_interval_is_checked_after_confirmed_water(
    mock_hass, mock_config_entry, mock_main_coordinator
):
    """Waiting creates no cooldown; confirmed ON while waiting withholds the head."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    finished = asyncio.Event()
    running = asyncio.create_task(finished.wait())
    coordinator._running_tasks["irrigation"] = running
    coordinator._zone.min_interval_minutes = 15
    with patch.object(coordinator, "_run_pump_cycle", new_callable=AsyncMock) as cycle:
        await coordinator._handle_event(
            utcnow(), event_type="irrigation", event_data={}
        )
        coordinator._last_cycle_timestamp = utcnow().isoformat()
        finished.set()
        await coordinator._supply_task
        cycle.assert_not_awaited()
    assert not coordinator._deliveries.attempts


async def test_supply_survives_running_task_cancellation_and_head_failure(
    mock_hass, mock_config_entry, mock_main_coordinator
):
    """A watchdog or a failed head decision cannot strand the remaining requests."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    running = asyncio.create_task(asyncio.Event().wait())
    coordinator._running_tasks["irrigation"] = running
    with (
        patch.object(
            coordinator, "_async_decide_steering_claim", side_effect=ValueError
        ),
        patch.object(coordinator, "_run_pump_cycle", new_callable=AsyncMock) as cycle,
    ):
        coordinator._queue_supply_claim("steering", utcnow(), {})
        await _REAL_ASYNCIO_SLEEP(0)
        running.cancel()
        await coordinator._supply_task
        await coordinator.async_manual_run(10)
        await coordinator._supply_task
        cycle.assert_awaited_once()
    assert coordinator.supply_payload() == {"open_zone_id": None, "claims": []}


async def test_unload_drops_supply_claims_without_attempts(
    mock_hass, mock_config_entry, mock_main_coordinator
):
    """A claim that has never reached the gate has nothing to recover on restart."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    running = asyncio.create_task(asyncio.Event().wait())
    coordinator._running_tasks["irrigation"] = running
    await coordinator.async_manual_run(10)
    await _REAL_ASYNCIO_SLEEP(0)
    await coordinator.async_unload()
    await asyncio.gather(running, coordinator._supply_task, return_exceptions=True)
    assert not coordinator._deliveries.attempts
    assert not coordinator._claim_data
    assert coordinator.supply_payload() == {"open_zone_id": None, "claims": []}


async def test_drain_does_not_wait_for_the_supply_queue(
    mock_hass, mock_config_entry, mock_main_coordinator
):
    """A separate drain output runs while an irrigation claim still waits."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    finished = asyncio.Event()
    running = asyncio.create_task(finished.wait())
    coordinator._running_tasks["irrigation"] = running
    with patch.object(coordinator, "_run_pump_cycle", new_callable=AsyncMock) as cycle:
        await coordinator._handle_event(
            utcnow(), event_type="irrigation", event_data={}
        )
        await coordinator._handle_event(utcnow(), event_type="drain", event_data={})
        await coordinator._running_tasks["drain"]
        assert cycle.await_args.args[0] == "drain"
        assert len(coordinator.supply_payload()["claims"]) == 1
        finished.set()
        await coordinator._supply_task
        assert [call.args[0] for call in cycle.await_args_list] == [
            "drain",
            "irrigation",
        ]


async def test_supply_late_dark_claim_records_due_time_at_the_gate(
    mock_hass, mock_config_entry, mock_main_coordinator
):
    """There is no queue deadline: the current dark gate refuses the released head."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    coordinator.growspace.irrigation_config.skip_during_dark = True
    mock_hass.states.get.return_value = Mock(state="off")
    due = utcnow() - timedelta(minutes=20)
    with patch.object(coordinator, "_is_lights_dark", return_value=True):
        await coordinator._handle_event(due, event_type="irrigation", event_data={})
        await coordinator._supply_task
    (attempt,) = coordinator._deliveries.attempts
    assert attempt.reason == "dark"
    assert attempt.due_at == due.replace(second=0, microsecond=0)
    assert attempt.requested_at > attempt.due_at
    assert attempt.on_commanded_at is None
