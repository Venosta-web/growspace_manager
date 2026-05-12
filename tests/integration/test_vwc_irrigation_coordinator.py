"""Tests for the VWC Irrigation Coordinator."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    IrrigationConfig,
    IrrigationStrategy,
)
from custom_components.growspace_manager.vwc_irrigation_coordinator import (
    VWCIrrigationCoordinator,
)
from homeassistant.util import dt as dt_util


# Patch asyncio.sleep globally for this test module to avoid lingering tasks
@pytest.fixture(autouse=True)
def mock_sleep():
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        yield mock_sleep


# Patch _async_wait_for_switch_state globally for this test module
@pytest.fixture(autouse=True)
def mock_wait_for_switch_state():
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.VWCIrrigationCoordinator._async_wait_for_switch_state",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock:
        yield mock


@pytest.fixture
def mock_hass():
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.states = MagicMock()
    # Schedule the coroutine on the loop to avoid "never awaited" warning and actually run it
    hass.async_create_task = MagicMock(side_effect=asyncio.create_task)
    hass.async_create_background_task = MagicMock(
        side_effect=lambda target, name: asyncio.create_task(target)
    )
    return hass


@pytest.fixture
def mock_growspace():
    growspace = Growspace(
        id="gs1",
        name="Test Growspace",
        environment_config=EnvironmentConfig(soil_moisture_sensor="sensor.moisture"),
        irrigation_config=IrrigationConfig(irrigation_pump_entity="switch.pump"),
    )
    growspace.irrigation_strategy = IrrigationStrategy(
        enabled=True,
        lights_on_time="08:00:00",
        p0_duration_minutes=60,  # Ends 09:00
        target_vwc_percent=50.0,
        maintenance_dryback_percent=2.0,
        shot_duration_seconds=10,
        shot_interval_minutes=15,
        p2_stop_before_lights_off_minutes=120,  # Lights off 20:00 (12h default) -> Stop 18:00
    )
    return growspace


@pytest.fixture
def mock_main_coordinator(mock_growspace):
    coordinator = MagicMock()
    coordinator.growspaces = {"gs1": mock_growspace}
    # Allow add_event to be called
    coordinator.add_event = MagicMock()
    return coordinator


async def await_pump_task():
    """Find and await the pump cycle task."""
    # Give the loop a moment to start the task
    await asyncio.sleep(0)

    tasks = asyncio.all_tasks()
    for task in tasks:
        if "VWCIrrigationCoordinator._run_pump_cycle" in str(task.get_coro()):
            await task
            return
    # If not found, that's okay, maybe it finished instantly or didn't start (if logic was wrong)
    # But for our tests expecting watering, it should be found unless we are too slow/fast.


@pytest.fixture
def vwc_coordinator(mock_hass, mock_main_coordinator):
    mock_config_entry = MagicMock()
    mock_config_entry.async_create_background_task.side_effect = (
        lambda hass, target, name: asyncio.create_task(target)
    )
    return VWCIrrigationCoordinator(
        mock_hass, mock_config_entry, "gs1", mock_main_coordinator
    )


async def test_p0_activation(vwc_coordinator, mock_hass, mock_growspace) -> None:
    """Test P0 phase (Activation) - No watering."""
    # Time: 08:30 (Inside P0)
    now = datetime(2023, 1, 1, 8, 30, 0, tzinfo=dt_util.UTC)

    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now,
    ):
        # Sensor value low, but P0 shouldn't water
        mock_hass.states.get.return_value = MagicMock(state="40.0")

        await vwc_coordinator._update_loop(now)

        assert vwc_coordinator._current_phase == "P0 - Activation"
        mock_hass.services.async_call.assert_not_called()


async def test_p1_ramp_up(vwc_coordinator, mock_hass) -> None:
    """Test P1 phase (Ramp Up) - Watering until target."""
    # Time: 09:30 (Inside P1)
    now = datetime(2023, 1, 1, 9, 30, 0, tzinfo=dt_util.UTC)

    with (
        patch(
            "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
            return_value=now,
        ),
        patch(
            "custom_components.growspace_manager.vwc_irrigation_coordinator.utcnow",
            side_effect=[
                datetime(2023, 1, 1, 9, 30, 0, tzinfo=dt_util.UTC),  # 1. Event Start
                datetime(
                    2023, 1, 1, 9, 30, 0, tzinfo=dt_util.UTC
                ),  # 2. pump start_time
                datetime(2023, 1, 1, 9, 30, 10, tzinfo=dt_util.UTC),  # 3. pump end_time
            ],
        ),
    ):
        # Sensor value: 40% (Target 50%) -> Should Water
        mock_hass.states.get.return_value = MagicMock(state="40.0")

        await vwc_coordinator._update_loop(now)
        await await_pump_task()

        assert vwc_coordinator._current_phase == "P1 - Ramp Up"
        mock_hass.services.async_call.assert_any_call(
            "switch", "turn_on", {"entity_id": "switch.pump"}, blocking=True
        )

        # Verify log event called
        mock_main_coordinator = vwc_coordinator._main_coordinator
        mock_main_coordinator.add_event.assert_called_once()
        # Verify timestamps in event
        event = mock_main_coordinator.add_event.call_args[0][1]
        assert event.category == "irrigation"
        assert event.duration_sec == 10
        assert event.start_time is not None
        assert event.end_time is not None


async def test_p1_target_reached(vwc_coordinator, mock_hass) -> None:
    """Test switching from P1 to P2 when target reached."""
    now = datetime(2023, 1, 1, 9, 30, 0, tzinfo=dt_util.UTC)

    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now,
    ):
        # Sensor value: 50% (Target 50%) -> Target Reached
        mock_hass.states.get.return_value = MagicMock(state="50.0")

        await vwc_coordinator._update_loop(now)

        # Should NOT water, but advance internal state
        assert vwc_coordinator._target_reached_today is True
        mock_hass.services.async_call.assert_not_called()


async def test_p2_maintenance(vwc_coordinator, mock_hass) -> None:
    """Test P2 phase - Water only on dryback."""
    # Set internal state to target reached (also set last_reset_date to prevent re-reset)
    vwc_coordinator._target_reached_today = True
    vwc_coordinator._last_reset_date = "2023-01-01"

    now = datetime(2023, 1, 1, 12, 0, 0, tzinfo=dt_util.UTC)

    with (
        patch(
            "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
            return_value=now,
        ),
        patch(
            "custom_components.growspace_manager.vwc_irrigation_coordinator.utcnow",
            side_effect=[
                datetime(2023, 1, 1, 12, 0, 0, tzinfo=dt_util.UTC),  # 1. Event Start
                datetime(
                    2023, 1, 1, 12, 0, 0, tzinfo=dt_util.UTC
                ),  # 2. pump start_time
                datetime(2023, 1, 1, 12, 0, 10, tzinfo=dt_util.UTC),  # 3. pump end_time
            ],
        ),
    ):
        # Case A: VWC 49% (Target 50%, Dryback 2% -> Trigger at 48%)
        # 49 > 48 -> No Water
        mock_hass.states.get.return_value = MagicMock(state="49.0")
        await vwc_coordinator._update_loop(now)
        mock_hass.services.async_call.assert_not_called()
        assert vwc_coordinator._current_phase == "P2 - Maintenance"

        # Case B: VWC 47% (Below 48%) -> Water
        mock_hass.states.get.return_value = MagicMock(state="47.0")
        await vwc_coordinator._update_loop(now)
        await await_pump_task()
        mock_hass.services.async_call.assert_any_call(
            "switch", "turn_on", {"entity_id": "switch.pump"}, blocking=True
        )

        mock_main_coordinator = vwc_coordinator._main_coordinator
        mock_main_coordinator.add_event.assert_called_once()
        event = mock_main_coordinator.add_event.call_args[0][1]
        assert event.duration_sec == 10


async def test_p3_dryback(vwc_coordinator, mock_hass) -> None:
    """Test P3 phase (Dry Back) - Hard stop."""
    # Time: 19:00 (Lights off 20:00, Stop 18:00 -> Inside P3)
    now = datetime(2023, 1, 1, 19, 0, 0, tzinfo=dt_util.UTC)

    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now,
    ):
        # Even if very dry, should NOT water
        mock_hass.states.get.return_value = MagicMock(state="30.0")

        await vwc_coordinator._update_loop(now)

        assert "P3" in vwc_coordinator._current_phase
        mock_hass.services.async_call.assert_not_called()


async def test_missing_sensor(vwc_coordinator, mock_hass, mock_growspace) -> None:
    """Test handling of missing sensor."""
    mock_growspace.environment_config = EnvironmentConfig()  # No sensor

    now = datetime(2023, 1, 1, 10, 0, 0, tzinfo=dt_util.UTC)

    await vwc_coordinator._update_loop(now)

    assert vwc_coordinator._current_phase == "Disabled (No Sensor)"
    mock_hass.services.async_call.assert_not_called()


async def test_custom_day_hours(vwc_coordinator, mock_hass, mock_growspace) -> None:
    """Test custom day hours from environment config."""
    # Config: 10 hours day (Lights On 08:00 -> Off 18:00)
    # P2 Stop = 120 min before off -> 16:00
    mock_growspace.environment_config = EnvironmentConfig(
        soil_moisture_sensor="sensor.moisture",
        flower_day_hours=10,
    )

    # Case A: 15:00 -> Should be P2 (15 < 16)
    now_p2 = datetime(2023, 1, 1, 15, 0, 0, tzinfo=dt_util.UTC)
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now_p2,
    ):
        mock_hass.states.get.return_value = MagicMock(state="45.0")
        vwc_coordinator._target_reached_today = True  # Force P2
        vwc_coordinator._last_reset_date = (
            "2023-01-01"  # Prevent date guard from re-resetting
        )
        await vwc_coordinator._update_loop(now_p2)
        assert vwc_coordinator._current_phase == "P2 - Maintenance"

    # Case B: 17:00 -> Should be P3 (17 > 16)
    # With default 12h (20:00 off, 18:00 stop), 17:00 would be P2.
    now_p3 = datetime(2023, 1, 1, 17, 0, 0, tzinfo=dt_util.UTC)
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now_p3,
    ):
        await vwc_coordinator._update_loop(now_p3)
        assert "P3" in vwc_coordinator._current_phase


async def test_setup_unload(vwc_coordinator, mock_hass) -> None:
    """Test async_setup and async_unload."""
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.services.track_time_interval"
    ) as mock_track:
        mock_remove = MagicMock()
        mock_track.return_value = mock_remove

        await vwc_coordinator.async_setup()
        mock_track.assert_called_once()
        assert vwc_coordinator._remove_update_listener is not None

        await vwc_coordinator.async_unload()
        mock_remove.assert_called_once()
        assert vwc_coordinator._remove_update_listener is None


async def test_cancel_listeners(vwc_coordinator, mock_hass) -> None:
    """Test async_cancel_listeners alias."""
    mock_remove = MagicMock()
    vwc_coordinator._remove_update_listener = mock_remove

    vwc_coordinator.async_cancel_listeners()

    mock_remove.assert_called_once()
    assert vwc_coordinator._remove_update_listener is None


async def test_strategy_disabled(vwc_coordinator, mock_growspace, mock_hass) -> None:
    """Test when irrigation strategy is disabled."""
    mock_growspace.irrigation_strategy.enabled = False

    await vwc_coordinator._update_loop(dt_util.utcnow())

    # Should return early, no sensor check or phase logic
    mock_hass.states.get.assert_not_called()


async def test_sensor_states_invalid(vwc_coordinator, mock_hass) -> None:
    """Test sensor returning invalid values."""
    # 1. Unavailable
    mock_hass.states.get.return_value = MagicMock(state="unavailable")
    assert vwc_coordinator._get_sensor_value("sensor.test") is None

    # 2. Unknown
    mock_hass.states.get.return_value = MagicMock(state="unknown")
    assert vwc_coordinator._get_sensor_value("sensor.test") is None

    # 3. ValueError
    mock_hass.states.get.return_value = MagicMock(state="not_a_number")
    assert vwc_coordinator._get_sensor_value("sensor.test") is None

    # Verify loop handles None return gracefully
    now = datetime(2023, 1, 1, 10, 0, 0, tzinfo=dt_util.UTC)
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now,
    ):
        mock_hass.states.get.return_value = MagicMock(state="unavailable")
        await vwc_coordinator._update_loop(now)
        # Should log debug but not crash
        mock_hass.services.async_call.assert_not_called()


async def test_time_parsing_formats(vwc_coordinator, mock_growspace) -> None:
    """Test different time formats in strategy."""
    # Test HH:MM format (no seconds)
    mock_growspace.irrigation_strategy.lights_on_time = "08:00"
    period = vwc_coordinator._determine_time_period(
        mock_growspace.irrigation_strategy, mock_growspace
    )
    # 8:00 start, default now() is likely different, but method calls now() internally.
    # We should patch now() to verify the period calculation relative to 8:00.

    now_p0 = datetime(2023, 1, 1, 8, 30, 0, tzinfo=dt_util.UTC)
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now_p0,
    ):
        period = vwc_coordinator._determine_time_period(
            mock_growspace.irrigation_strategy, mock_growspace
        )
        assert period == "P0"


async def test_before_lights_on(vwc_coordinator, mock_hass) -> None:
    """Test P3 state before lights on time."""
    # Lights on 08:00. Current time 07:00 -> P3
    now = datetime(2023, 1, 1, 7, 0, 0, tzinfo=dt_util.UTC)
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now,
    ):
        mock_hass.states.get.return_value = MagicMock(state="40.0")
        await vwc_coordinator._update_loop(now)
        assert "P3" in vwc_coordinator._current_phase


async def test_shot_interval_logic(vwc_coordinator, mock_hass) -> None:
    """Test that shots are throttled by interval."""
    strategy = vwc_coordinator._main_coordinator.growspaces["gs1"].irrigation_strategy
    strategy.shot_interval_minutes = 15

    # 1. Fire first shot
    vwc_coordinator._last_shot_time = None
    vwc_coordinator._handle_watering(strategy, "P1")

    # Await the async task triggered by _handle_watering
    await await_pump_task()

    assert mock_hass.services.async_call.call_count == 2  # On then Off
    mock_hass.services.async_call.reset_mock()

    # 2. Try again 5 minutes later via _handle_watering directly
    # Need to patch now() inside the method or set _last_shot_time manually

    # Set last shot time to 12:00
    last_time = datetime(2023, 1, 1, 12, 0, 0, tzinfo=dt_util.UTC)
    vwc_coordinator._last_shot_time = last_time

    # Current time 12:05 (Elapsed 5 min < 15)
    current_time = datetime(2023, 1, 1, 12, 5, 0, tzinfo=dt_util.UTC)

    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=current_time,
    ):
        vwc_coordinator._handle_watering(strategy, "P1")
        mock_hass.services.async_call.assert_not_called()


async def test_missing_pump_entity(vwc_coordinator, mock_growspace, mock_hass) -> None:
    """Test logic when pump entity is configured as empty/None."""
    # Remove pump entity
    mock_growspace.irrigation_config.irrigation_pump_entity = None

    strategy = mock_growspace.irrigation_strategy

    # Attempt watering
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=datetime(2023, 1, 1, 12, 0, 0, tzinfo=dt_util.UTC),
    ):
        vwc_coordinator._handle_watering(strategy, "P1")
        # Should return early
        mock_hass.services.async_call.assert_not_called()


async def test_loop_exception_handling(vwc_coordinator, mock_hass) -> None:
    """Test high-level exception catching in update loop."""
    # Make getting growspace raise KeyError
    vwc_coordinator._main_coordinator.growspaces = {}

    # Should not raise exception
    await vwc_coordinator._update_loop(dt_util.utcnow())


async def test_determine_time_period_night(vwc_coordinator, mock_growspace) -> None:
    """Test _determine_time_period for deep night (covers line 186)."""
    # Lights On 08:00, Off 20:00. Current 22:00
    now = datetime(2023, 1, 1, 22, 0, 0, tzinfo=dt_util.UTC)
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now,
    ):
        period = vwc_coordinator._determine_time_period(
            mock_growspace.irrigation_strategy, mock_growspace
        )
        assert period == "P3"


async def test_run_pump_cycle_cancelled(vwc_coordinator, mock_hass) -> None:
    """Test _run_pump_cycle handles CancelledError (covers lines 276-277)."""
    with (
        patch("asyncio.sleep", side_effect=asyncio.CancelledError),
        patch(
            "custom_components.growspace_manager.vwc_irrigation_coordinator.utcnow",
            return_value=datetime(2023, 1, 1, 12, 0, 0, tzinfo=dt_util.UTC),
        ),
    ):
        # Should not raise or crash
        await vwc_coordinator._run_pump_cycle("switch.pump", 10, "P1")

        # Verify turn_off was still called in finally block
        mock_hass.services.async_call.assert_any_call(
            "switch", "turn_off", {"entity_id": "switch.pump"}, blocking=True
        )
