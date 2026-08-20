"""Regression test: dehumidifier retry after timer-lock with stable VPD."""

import asyncio
from datetime import date, timedelta
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.dehumidifier_coordinator import (
    DehumidifierCoordinator,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant


@pytest.fixture
def mock_hass():
    hass = MagicMock(spec=HomeAssistant)
    hass.states = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.data = {}
    hass.async_create_task = lambda coro: asyncio.get_event_loop().create_task(coro)
    return hass


@pytest.fixture
def mock_plant_flower_day_45():
    plant = MagicMock()
    plant.flower_start = (date.today() - timedelta(days=45)).isoformat()
    plant.veg_start = (date.today() - timedelta(days=75)).isoformat()
    plant.dry_start = None
    plant.cure_start = None
    plant.seedling_start = None
    plant.clone_start = None
    plant.mother_start = None
    return plant


@pytest.fixture
def mock_growspace():
    growspace = MagicMock()
    growspace.id = "gs1"
    growspace.name = "Flower Tent"

    env_config = MagicMock()
    env_config.vpd_sensor = "sensor.vpd"
    env_config.light_sensors = ["sensor.light"]
    env_config.dehumidifier_entities = ["switch.dehumidifier"]
    env_config.exhaust_fan_entities = []
    env_config.control_dehumidifier = True
    env_config.dehumidifier_thresholds = {}

    growspace.environment_config = env_config
    growspace.dehumidifier_config = {}
    return growspace


@pytest.fixture
def mock_main_coordinator(mock_plant_flower_day_45):
    coordinator = MagicMock()
    coordinator.services.growspaces.get_growspace_plants = MagicMock(
        return_value=[mock_plant_flower_day_45]
    )
    return coordinator


async def test_retry_fires_after_timer_lock_expires_with_stable_vpd(
    mock_hass, mock_main_coordinator, mock_growspace
) -> None:
    """Regression: after a timer-lock blocks a turn-off, a retry must be scheduled
    so the dehumidifier turns off once the minimum runtime expires — even if VPD
    stays stable and no sensor state-change events fire
    """
    mock_main_coordinator.growspaces = {"gs1": mock_growspace}

    # Phase 1: VPD is low → initial setup turns ON dehumidifier
    mock_hass.states.get.side_effect = lambda entity_id: {
        "sensor.vpd": MagicMock(state="1.0"),
        "sensor.light": MagicMock(state="500"),
        "switch.dehumidifier": MagicMock(state=STATE_OFF),
    }.get(entity_id)

    scheduled_calls: list = []

    def fake_async_call_later(_hass, delay, cb):
        scheduled_calls.append((delay, cb))
        return MagicMock()  # cancel handle

    with (
        patch(
            "custom_components.growspace_manager.vpd_on_off_controller.async_track_state_change_event"
        ),
        patch(
            "custom_components.growspace_manager.vpd_on_off_controller.async_call_later",
            side_effect=fake_async_call_later,
        ),
    ):
        coordinator = DehumidifierCoordinator(
            mock_hass, MagicMock(), "gs1", mock_main_coordinator
        )
        await coordinator.async_setup()

    # Dehumidifier turned ON by initial check
    mock_hass.services.async_call.assert_called_once_with(
        "switch",
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: "switch.dehumidifier"},
        blocking=False,
    )
    assert coordinator._last_turn_on_time > 0

    # Phase 2: VPD rises to 1.6 within min runtime window → timer locks the check
    mock_hass.services.async_call.reset_mock()
    mock_hass.states.get.side_effect = lambda entity_id: {
        "sensor.vpd": MagicMock(state="1.6"),
        "sensor.light": MagicMock(state="500"),
        "switch.dehumidifier": MagicMock(state=STATE_ON),
    }.get(entity_id)

    with patch(
        "custom_components.growspace_manager.vpd_on_off_controller.async_call_later",
        side_effect=fake_async_call_later,
    ):
        await coordinator.async_check_and_control()

    # Locked — no turn-off yet
    mock_hass.services.async_call.assert_not_called()

    # A retry must have been scheduled
    assert len(scheduled_calls) == 1, "Expected exactly one retry to be scheduled"
    _delay, retry_cb = scheduled_calls[0]
    assert _delay > 0

    # Phase 3: Simulate the retry firing (as if the timer elapsed).
    # VPD is still 1.6, timer has now expired.
    coordinator._last_turn_on_time = time.monotonic() - 400  # > 300s elapsed

    # retry_cb is a @callback (sync); it schedules async_check_and_control via create_task.
    retry_cb(None)
    await asyncio.sleep(0)  # let the created task run

    # Dehumidifier must now turn OFF
    mock_hass.services.async_call.assert_called_once_with(
        "switch",
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: "switch.dehumidifier"},
        blocking=False,
    )


async def test_retry_not_duplicated_on_repeated_locked_checks(
    mock_hass, mock_main_coordinator, mock_growspace
) -> None:
    """Only one retry is scheduled even if the locked check is hit multiple times."""
    mock_main_coordinator.growspaces = {"gs1": mock_growspace}

    scheduled_calls: list = []

    def fake_async_call_later(_hass, delay, cb):
        scheduled_calls.append((delay, cb))
        return MagicMock()

    mock_hass.states.get.side_effect = lambda entity_id: {
        "sensor.vpd": MagicMock(state="1.6"),
        "sensor.light": MagicMock(state="500"),
        "switch.dehumidifier": MagicMock(state=STATE_ON),
    }.get(entity_id)

    with (
        patch(
            "custom_components.growspace_manager.vpd_on_off_controller.async_track_state_change_event"
        ),
        patch(
            "custom_components.growspace_manager.vpd_on_off_controller.async_call_later",
            side_effect=fake_async_call_later,
        ),
    ):
        coordinator = DehumidifierCoordinator(
            mock_hass, MagicMock(), "gs1", mock_main_coordinator
        )
        await coordinator.async_setup()

    # Manually set timer lock
    coordinator._last_turn_on_time = time.monotonic() - 60  # 60s < 300s
    scheduled_calls.clear()

    with patch(
        "custom_components.growspace_manager.vpd_on_off_controller.async_call_later",
        side_effect=fake_async_call_later,
    ):
        await coordinator.async_check_and_control()
        await coordinator.async_check_and_control()
        await coordinator.async_check_and_control()

    assert len(scheduled_calls) == 1, "Retry should only be scheduled once"


async def test_retry_cancelled_on_unload(
    mock_hass, mock_main_coordinator, mock_growspace
) -> None:
    """Pending retry is cancelled when the coordinator unloads."""
    mock_main_coordinator.growspaces = {"gs1": mock_growspace}

    cancel_mock = MagicMock()

    mock_hass.states.get.side_effect = lambda entity_id: {
        "sensor.vpd": MagicMock(state="1.6"),
        "sensor.light": MagicMock(state="500"),
        "switch.dehumidifier": MagicMock(state=STATE_ON),
    }.get(entity_id)

    with (
        patch(
            "custom_components.growspace_manager.vpd_on_off_controller.async_track_state_change_event"
        ),
        patch(
            "custom_components.growspace_manager.vpd_on_off_controller.async_call_later",
            return_value=cancel_mock,
        ),
    ):
        coordinator = DehumidifierCoordinator(
            mock_hass, MagicMock(), "gs1", mock_main_coordinator
        )
        await coordinator.async_setup()

    coordinator._last_turn_on_time = time.monotonic() - 60
    with patch(
        "custom_components.growspace_manager.vpd_on_off_controller.async_call_later",
        return_value=cancel_mock,
    ):
        await coordinator.async_check_and_control()

    assert coordinator._retry_cancel is not None
    coordinator.unload()

    cancel_mock.assert_called_once()
    assert coordinator._retry_cancel is None
