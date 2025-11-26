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
                    }
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


@patch(
    "custom_components.growspace_manager.irrigation_coordinator.async_track_time_change"
)
async def test_setup_and_schedule_events(
    mock_track_time: MagicMock, mock_hass: MagicMock, mock_config_entry: MagicMock
):
    """Test that listeners are scheduled correctly on setup."""
    coordinator = IrrigationCoordinator(mock_hass, mock_config_entry, GROWSPACE_ID)
    await coordinator.async_setup()

    assert mock_track_time.call_count == 3
    calls = mock_track_time.call_args_list
    scheduled_times = {
        (c.kwargs["hour"], c.kwargs["minute"], c.kwargs["second"]) for c in calls
    }
    assert (10, 0, 0) in scheduled_times
    assert (20, 0, 0) in scheduled_times
    assert (12, 0, 0) in scheduled_times


async def test_run_pump_cycle(mock_hass: MagicMock, mock_config_entry: MagicMock):
    """Test the full pump cycle logic including service calls and delay."""
    coordinator = IrrigationCoordinator(mock_hass, mock_config_entry, GROWSPACE_ID)
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
    mock_hass: MagicMock, mock_config_entry: MagicMock
):
    """Test that an event with a custom duration overrides the default."""
    coordinator = IrrigationCoordinator(mock_hass, mock_config_entry, GROWSPACE_ID)
    event_data = {"time": "20:00:00", "duration": 45}

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


async def test_overlapping_events(mock_hass: MagicMock, mock_config_entry: MagicMock):
    """Test that a new event cancels a running event of the same type."""
    coordinator = IrrigationCoordinator(mock_hass, mock_config_entry, GROWSPACE_ID)
    event_data = {"time": "10:00:00"}

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
