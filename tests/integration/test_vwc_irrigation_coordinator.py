"""Tests for the VWC Irrigation Coordinator."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import EVENT_GROWSPACE_LOG_ENTRY
from custom_components.growspace_manager.domain.ec_state import (
    ec_modulation_factor_for_reading,
)
from custom_components.growspace_manager.domain.steering_phase import (
    INFILTRATION_HELD_MESSAGE,
    INFILTRATION_RELEASED_MESSAGE,
    SUPPRESSED_BY_COOLDOWN,
    SteeringTickVerdict,
)
from custom_components.growspace_manager.irrigation_coordinator import (
    BaseIrrigationCoordinator,
)
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    IrrigationConfig,
    IrrigationStrategy,
    IrrigationTank,
)
from custom_components.growspace_manager.vwc_irrigation_coordinator import (
    VWCIrrigationCoordinator,
)
from homeassistant.util import dt as dt_util


def _drive_watering(
    coord: VWCIrrigationCoordinator, strategy: IrrigationStrategy, phase: str
) -> None:
    """Drive the machine's shot evaluation plus the shell's fire path.

    Mirrors the pre-extraction ``_handle_watering`` entry point these tests
    exercised: the Steering Phase Machine decides (cooldown, sizing) and the
    coordinator fires the composed pump cycle when a shot is requested.
    """
    inputs = coord._tick_inputs(40.0, strategy, coord.growspace)
    fire, _note, _suppressed = coord._machine._evaluate_shot(
        inputs, phase, reset_pending=False
    )
    if fire is not None:
        coord._fire_shot(strategy, fire)


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
        p1_shot_duration_seconds=10,
        p1_shot_interval_minutes=15,
        p2_shot_duration_seconds=10,
        p2_shot_interval_minutes=15,
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
    """Find and await the pump cycle task.

    Works regardless of whether the method lives on VWCIrrigationCoordinator or
    BaseIrrigationCoordinator — matches on the method name alone.
    """
    await asyncio.sleep(0)

    tasks = asyncio.all_tasks()
    for task in tasks:
        if "_run_pump_cycle" in str(task.get_coro()):
            await task
            return


@pytest.fixture
def vwc_coordinator(mock_hass, mock_main_coordinator):
    mock_config_entry = MagicMock()
    # Point runtime_data at mock_main_coordinator so _async_send_cycle_notification
    # finds the real mock_growspace (notification_target=None → no extra notify call).
    mock_config_entry.runtime_data = mock_main_coordinator
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
        mock_hass.states.get.return_value = _state("40.0")

        await vwc_coordinator._update_loop(now)

        assert vwc_coordinator._machine.current_phase == "P0 - Activation"
        mock_hass.services.async_call.assert_not_called()


async def test_p1_ramp_up(vwc_coordinator, mock_hass) -> None:
    """Test P1 phase (Ramp Up) - Watering until target."""
    # Time: 09:30 (Inside P1)
    now = datetime(2023, 1, 1, 9, 30, 0, tzinfo=dt_util.UTC)

    t0 = datetime(2023, 1, 1, 9, 30, 0, tzinfo=dt_util.UTC)
    t10 = datetime(2023, 1, 1, 9, 30, 10, tzinfo=dt_util.UTC)
    with (
        patch(
            "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
            return_value=now,
        ),
        patch(
            # _run_pump_cycle now lives in irrigation_coordinator — patch there.
            # _set_phase also fires a logbook event (via _fire_logbook_event) when
            # the phase changes, adding one utcnow() call before the pump cycle.
            "custom_components.growspace_manager.irrigation_coordinator.utcnow",
            side_effect=[
                t0,  # 1. _set_phase("P1 - Ramp Up") logbook event
                t0,  # 2. _active_events["start"]
                t0,  # 3. _fire_logbook_event("Irrigation started…")
                t0,  # 4. start_dt = utcnow()
                t10,  # 5. end_dt = utcnow()
                t10,  # 6. _fire_logbook_event("Irrigation completed…")
            ],
        ),
    ):
        # Sensor value: 40% (Target 50%) -> Should Water
        mock_hass.states.get.return_value = _state("40.0")

        await vwc_coordinator._update_loop(now)
        await await_pump_task()

        assert vwc_coordinator._machine.current_phase == "P1 - Ramp Up"
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
        mock_hass.states.get.return_value = _state("50.0")

        await vwc_coordinator._update_loop(now)

        # Should NOT water, but advance internal state
        assert vwc_coordinator._machine._target_reached_today is True
        mock_hass.services.async_call.assert_not_called()


async def test_p2_maintenance(vwc_coordinator, mock_hass) -> None:
    """Test P2 phase - Water only on dryback."""
    # Set internal state to target reached (also set last_reset_date to prevent re-reset)
    vwc_coordinator._machine._target_reached_today = True
    vwc_coordinator._machine._last_reset_date = "2023-01-01"

    now = datetime(2023, 1, 1, 12, 0, 0, tzinfo=dt_util.UTC)

    t0 = datetime(2023, 1, 1, 12, 0, 0, tzinfo=dt_util.UTC)
    t10 = datetime(2023, 1, 1, 12, 0, 10, tzinfo=dt_util.UTC)
    with (
        patch(
            "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
            return_value=now,
        ),
        patch(
            "custom_components.growspace_manager.irrigation_coordinator.utcnow",
            side_effect=[
                # Case A: phase transition P3→P2 fires a logbook event
                t0,  # 1. _set_phase("P2 - Maintenance") logbook event
                # Case B: pump fires (phase stays P2, no extra logbook from _set_phase)
                t0,  # 2. _active_events["start"]
                t0,  # 3. _fire_logbook_event("Irrigation started…")
                t0,  # 4. start_dt = utcnow()
                t10,  # 5. end_dt = utcnow()
                t10,  # 6. _fire_logbook_event("Irrigation completed…")
            ],
        ),
    ):
        # Case A: VWC 49% (Target 50%, Dryback 2% -> Trigger at 48%)
        # 49 > 48 -> No Water
        mock_hass.states.get.return_value = _state("49.0")
        await vwc_coordinator._update_loop(now)
        mock_hass.services.async_call.assert_not_called()
        assert vwc_coordinator._machine.current_phase == "P2 - Maintenance"

        # Case B: VWC 47% (Below 48%) -> Water
        mock_hass.states.get.return_value = _state("47.0")
        await vwc_coordinator._update_loop(now)
        await await_pump_task()
        mock_hass.services.async_call.assert_any_call(
            "switch", "turn_on", {"entity_id": "switch.pump"}, blocking=True
        )

        mock_main_coordinator = vwc_coordinator._main_coordinator
        mock_main_coordinator.add_event.assert_called_once()
        event = mock_main_coordinator.add_event.call_args[0][1]
        assert event.duration_sec == 10


async def test_p3_dryback(vwc_coordinator, mock_hass, mock_growspace) -> None:
    """Test P3 phase (Dry Back) - Hard stop when auto_advance_p2_to_p3 is enabled."""
    mock_growspace.irrigation_config.auto_advance_p2_to_p3 = True
    # Time: 19:00 (Lights off 20:00, Stop 18:00 -> Inside early-P3 window)
    now = datetime(2023, 1, 1, 19, 0, 0, tzinfo=dt_util.UTC)

    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now,
    ):
        # Even if very dry, should NOT water
        mock_hass.states.get.return_value = _state("30.0")

        await vwc_coordinator._update_loop(now)

        assert "P3" in vwc_coordinator._machine.current_phase
        mock_hass.services.async_call.assert_not_called()


async def test_missing_sensor(vwc_coordinator, mock_hass, mock_growspace) -> None:
    """Test handling of missing sensor."""
    mock_growspace.environment_config = EnvironmentConfig()  # No sensor

    now = datetime(2023, 1, 1, 10, 0, 0, tzinfo=dt_util.UTC)

    await vwc_coordinator._update_loop(now)

    assert vwc_coordinator._machine.current_phase == "Disabled (No Sensor)"
    mock_hass.services.async_call.assert_not_called()


async def test_custom_day_hours(vwc_coordinator, mock_hass, mock_growspace) -> None:
    """Test custom day hours from environment config."""
    # Config: 10 hours day (Lights On 08:00 -> Off 18:00)
    # P2 Stop = 120 min before off -> 16:00
    mock_growspace.environment_config = EnvironmentConfig(
        soil_moisture_sensor="sensor.moisture",
        flower_day_hours=10,
    )
    mock_growspace.irrigation_config.auto_advance_p2_to_p3 = True

    # Case A: 15:00 -> Should be P2 (15 < 16)
    now_p2 = datetime(2023, 1, 1, 15, 0, 0, tzinfo=dt_util.UTC)
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now_p2,
    ):
        mock_hass.states.get.return_value = _state("45.0")
        vwc_coordinator._machine._target_reached_today = True  # Force P2
        vwc_coordinator._machine._last_reset_date = (
            "2023-01-01"  # Prevent date guard from re-resetting
        )
        await vwc_coordinator._update_loop(now_p2)
        assert vwc_coordinator._machine.current_phase == "P2 - Maintenance"

    # Case B: 17:00 -> Should be P3 (17 > 16, inside early-stop window with flag=True)
    # With default 12h (20:00 off, 18:00 stop), 17:00 would be P2.
    now_p3 = datetime(2023, 1, 1, 17, 0, 0, tzinfo=dt_util.UTC)
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now_p3,
    ):
        await vwc_coordinator._update_loop(now_p3)
        assert "P3" in vwc_coordinator._machine.current_phase


async def test_setup_unload(vwc_coordinator, mock_hass) -> None:
    """Test async_setup and async_unload."""
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.async_track_time_interval"
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
    mock_hass.states.get.return_value = _state("unavailable")
    assert vwc_coordinator._get_sensor_value("sensor.test") is None

    # 2. Unknown
    mock_hass.states.get.return_value = _state("unknown")
    assert vwc_coordinator._get_sensor_value("sensor.test") is None

    # 3. ValueError
    mock_hass.states.get.return_value = _state("not_a_number")
    assert vwc_coordinator._get_sensor_value("sensor.test") is None

    # Verify loop handles None return gracefully
    now = datetime(2023, 1, 1, 10, 0, 0, tzinfo=dt_util.UTC)
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now,
    ):
        mock_hass.states.get.return_value = _state("unavailable")
        await vwc_coordinator._update_loop(now)
        # Should log debug but not crash
        mock_hass.services.async_call.assert_not_called()


# Time-format parsing and time-period determination are pure domain logic now,
# unit-tested in tests/domain/test_steering_phase.py (the former
# test_time_parsing_formats / test_determine_time_period_night cases).


async def test_before_lights_on(vwc_coordinator, mock_hass) -> None:
    """Test P3 state before lights on time."""
    # Lights on 08:00. Current time 07:00 -> P3
    now = datetime(2023, 1, 1, 7, 0, 0, tzinfo=dt_util.UTC)
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now,
    ):
        mock_hass.states.get.return_value = _state("40.0")
        await vwc_coordinator._update_loop(now)
        assert "P3" in vwc_coordinator._machine.current_phase


async def test_shot_interval_logic(vwc_coordinator, mock_hass) -> None:
    """Test that shots are throttled by interval."""
    strategy = vwc_coordinator._main_coordinator.growspaces["gs1"].irrigation_strategy
    strategy.p1_shot_interval_minutes = 15

    # 1. Fire first shot
    vwc_coordinator._last_cycle_timestamp = None
    _drive_watering(vwc_coordinator, strategy, "P1")

    # Await the async task triggered by _handle_watering
    await await_pump_task()

    assert mock_hass.services.async_call.call_count == 2  # On then Off
    mock_hass.services.async_call.reset_mock()

    # 2. Try again 5 minutes later via _handle_watering directly
    # Need to patch now() inside the method or set _last_cycle_timestamp manually

    # Set last shot time to 12:00
    last_time = datetime(2023, 1, 1, 12, 0, 0, tzinfo=dt_util.UTC)
    vwc_coordinator._last_cycle_timestamp = last_time.isoformat()

    # Current time 12:05 (Elapsed 5 min < 15)
    current_time = datetime(2023, 1, 1, 12, 5, 0, tzinfo=dt_util.UTC)

    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=current_time,
    ):
        _drive_watering(vwc_coordinator, strategy, "P1")
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
        _drive_watering(vwc_coordinator, strategy, "P1")
        # Should return early
        mock_hass.services.async_call.assert_not_called()


async def test_loop_exception_handling(vwc_coordinator, mock_hass) -> None:
    """Test high-level exception catching in update loop."""
    # Make getting growspace raise KeyError
    vwc_coordinator._main_coordinator.growspaces = {}

    # Should not raise exception
    await vwc_coordinator._update_loop(dt_util.utcnow())


async def test_run_pump_cycle_cancelled(vwc_coordinator, mock_hass) -> None:
    """Test _run_pump_cycle handles CancelledError (covers lines 276-277)."""
    fixed_dt = datetime(2023, 1, 1, 12, 0, 0, tzinfo=dt_util.UTC)
    with (
        patch("asyncio.sleep", side_effect=asyncio.CancelledError),
        patch(
            # _run_pump_cycle now lives in irrigation_coordinator
            "custom_components.growspace_manager.irrigation_coordinator.utcnow",
            return_value=fixed_dt,
        ),
    ):
        # Should not raise or crash
        await vwc_coordinator._run_pump_cycle("irrigation", "switch.pump", 10, {})

        # Verify turn_off was still called in finally block
        mock_hass.services.async_call.assert_any_call(
            "switch", "turn_off", {"entity_id": "switch.pump"}, blocking=True
        )


# ---------------------------------------------------------------------------
# Tests for dynamic safety-guard integration (Issue #370)
# ---------------------------------------------------------------------------


async def test_vwc_skips_watering_when_tank_is_low(
    vwc_coordinator: VWCIrrigationCoordinator,
    mock_hass: MagicMock,
    mock_growspace: Growspace,
) -> None:
    """When pause_on_low_tank=True and a tank is below its warning level, VWC does not water."""
    tank = IrrigationTank(
        sensor_entity="sensor.tank_level",
        name="Main Tank",
        warning_level=30.0,
    )
    mock_growspace.environment_config = EnvironmentConfig(
        soil_moisture_sensor="sensor.moisture",
        irrigation_tanks=[tank],
    )
    mock_growspace.irrigation_config.pause_on_low_tank = True

    def states_side_effect(entity_id: str) -> MagicMock | None:
        if entity_id == "sensor.tank_level":
            return _state("20.0")  # Below 30% warning
        if entity_id == "sensor.moisture":
            return MagicMock(
                state="40.0"
            )  # VWC below target → would normally trigger P1 shot
        return None

    mock_hass.states.get.side_effect = states_side_effect

    now_dt = datetime(2023, 1, 1, 9, 30, 0, tzinfo=dt_util.UTC)
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now_dt,
    ):
        await vwc_coordinator._update_loop(now_dt)
        await await_pump_task()  # Let any queued tasks run

    # Pump switch must not have fired — only a low-tank persistent_notification may appear
    all_calls = [str(c) for c in mock_hass.services.async_call.call_args_list]
    assert not any("switch" in c and "turn_on" in c for c in all_calls)


async def test_vwc_skips_watering_when_max_cycles_reached(
    vwc_coordinator: VWCIrrigationCoordinator,
    mock_hass: MagicMock,
    mock_growspace: Growspace,
) -> None:
    """When max_cycles_per_day is reached, VWC does not water even if VWC is low."""
    mock_growspace.irrigation_config.max_cycles_per_day = 3
    vwc_coordinator._cycles_today = 3  # Already at the limit

    now_dt = datetime(2023, 1, 1, 9, 30, 0, tzinfo=dt_util.UTC)
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now_dt,
    ):
        mock_hass.states.get.return_value = _state("40.0")  # VWC below target
        await vwc_coordinator._update_loop(now_dt)
        await await_pump_task()

    mock_hass.services.async_call.assert_not_called()


async def test_vwc_skips_watering_when_dark_and_skip_enabled(
    vwc_coordinator: VWCIrrigationCoordinator,
    mock_hass: MagicMock,
    mock_growspace: Growspace,
) -> None:
    """When skip_during_dark=True and all light sensors report off, VWC does not water."""
    mock_growspace.irrigation_config.skip_during_dark = True
    mock_growspace.environment_config = EnvironmentConfig(
        soil_moisture_sensor="sensor.moisture",
        light_sensors=["binary_sensor.light"],
    )

    def states_side_effect(entity_id: str) -> MagicMock | None:
        if entity_id == "binary_sensor.light":
            return _state("off")  # Light is off → dark period
        if entity_id == "sensor.moisture":
            return _state("40.0")
        return None

    mock_hass.states.get.side_effect = states_side_effect

    now_dt = datetime(2023, 1, 1, 9, 30, 0, tzinfo=dt_util.UTC)
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now_dt,
    ):
        await vwc_coordinator._update_loop(now_dt)
        await await_pump_task()

    mock_hass.services.async_call.assert_not_called()


async def test_vwc_waters_when_numeric_light_sensor_reports_on(
    vwc_coordinator: VWCIrrigationCoordinator,
    mock_hass: MagicMock,
    mock_growspace: Growspace,
) -> None:
    """A numeric power sensor reporting a positive value means lights are ON.

    Reproduces a real-world bug: a `sensor.*_current_power` entity reporting
    "4" (watts) was misread as "off" by a binary-only on-check, permanently
    blocking VWC pulse watering via the dark-period skip guard.
    """
    mock_growspace.irrigation_config.skip_during_dark = True
    mock_growspace.environment_config = EnvironmentConfig(
        soil_moisture_sensor="sensor.moisture",
        light_sensors=["sensor.grow_light_power"],
    )

    def states_side_effect(entity_id: str) -> MagicMock | None:
        if entity_id == "sensor.grow_light_power":
            state = _state("4")
            state.domain = "sensor"
            return state  # Light draws 4W → ON
        if entity_id == "sensor.moisture":
            return _state("40.0")
        return None

    mock_hass.states.get.side_effect = states_side_effect

    now_dt = datetime(2023, 1, 1, 9, 30, 0, tzinfo=dt_util.UTC)
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now_dt,
    ):
        await vwc_coordinator._update_loop(now_dt)
        await await_pump_task()

    mock_hass.services.async_call.assert_any_call(
        "switch",
        "turn_on",
        {"entity_id": mock_growspace.irrigation_config.irrigation_pump_entity},
        blocking=True,
    )


async def test_vwc_phase_transition_fires_logbook_event(
    vwc_coordinator: VWCIrrigationCoordinator,
    mock_hass: MagicMock,
    mock_growspace: Growspace,
) -> None:
    """When log_to_logbook=True, a VWC phase transition fires a logbook event."""
    mock_growspace.irrigation_config.log_to_logbook = True
    mock_hass.bus = MagicMock()
    mock_hass.bus.async_fire = MagicMock()

    now_dt = datetime(2023, 1, 1, 8, 30, 0, tzinfo=dt_util.UTC)  # P0 window
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now_dt,
    ):
        mock_hass.states.get.return_value = _state("40.0")
        await vwc_coordinator._update_loop(now_dt)

    # Phase changed from "P3" (initial) to "P0 - Activation" → logbook must fire
    assert mock_hass.bus.async_fire.called
    fired_event = mock_hass.bus.async_fire.call_args[0][0]
    from custom_components.growspace_manager.const import EVENT_GROWSPACE_LOG_ENTRY

    assert fired_event == EVENT_GROWSPACE_LOG_ENTRY


async def test_vwc_soil_trigger_percent_overrides_p2_maintenance_threshold(
    vwc_coordinator: VWCIrrigationCoordinator,
    mock_hass: MagicMock,
    mock_growspace: Growspace,
) -> None:
    """When soil_trigger_percent is set, it replaces the calculated P2 trigger.

    Normally P2 trigger = target_vwc_percent - maintenance_dryback_percent
    = 50.0 - 2.0 = 48.0%.  With soil_trigger_percent=45.0 the threshold
    drops to 45.0%, so VWC=47% should NOT trigger watering (47 > 45).
    """
    mock_growspace.irrigation_config.soil_trigger_percent = 45.0
    vwc_coordinator._machine._target_reached_today = True
    vwc_coordinator._machine._last_reset_date = "2023-01-01"

    now_dt = datetime(2023, 1, 1, 12, 0, 0, tzinfo=dt_util.UTC)
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now_dt,
    ):
        # VWC 47%: above the soil_trigger_percent threshold of 45% → no watering
        mock_hass.states.get.side_effect = lambda eid: (
            _state("47.0") if eid == "sensor.moisture" else None
        )
        await vwc_coordinator._update_loop(now_dt)
        await await_pump_task()

    mock_hass.services.async_call.assert_not_called()


async def test_vwc_soil_trigger_percent_fires_watering_when_below(
    vwc_coordinator: VWCIrrigationCoordinator,
    mock_hass: MagicMock,
    mock_growspace: Growspace,
) -> None:
    """When VWC drops below soil_trigger_percent, P2 maintenance waters."""
    mock_growspace.irrigation_config.soil_trigger_percent = 45.0
    mock_growspace.irrigation_config.log_to_logbook = False  # Keep utcnow simple
    vwc_coordinator._machine._target_reached_today = True
    vwc_coordinator._machine._last_reset_date = "2023-01-01"

    t0 = datetime(2023, 1, 1, 12, 0, 0, tzinfo=dt_util.UTC)
    t10 = datetime(2023, 1, 1, 12, 0, 10, tzinfo=dt_util.UTC)
    now_dt = t0
    with (
        patch(
            "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
            return_value=now_dt,
        ),
        patch(
            "custom_components.growspace_manager.irrigation_coordinator.utcnow",
            side_effect=[
                t0,  # _set_phase P3→P2 (no logbook since log_to_logbook=False but
                # _active_events still calls utcnow)
                t0,  # start_dt
                t10,  # end_dt
            ],
        ),
    ):
        # VWC 44%: below soil_trigger_percent=45% → should water
        mock_hass.states.get.side_effect = lambda eid: (
            _state("44.0") if eid == "sensor.moisture" else None
        )
        await vwc_coordinator._update_loop(now_dt)
        await await_pump_task()

    mock_hass.services.async_call.assert_any_call(
        "switch", "turn_on", {"entity_id": "switch.pump"}, blocking=True
    )


async def test_vwc_no_logbook_when_disabled(
    vwc_coordinator: VWCIrrigationCoordinator,
    mock_hass: MagicMock,
    mock_growspace: Growspace,
) -> None:
    """When log_to_logbook=False, phase transitions do NOT fire logbook events."""
    mock_growspace.irrigation_config.log_to_logbook = False
    mock_hass.bus = MagicMock()
    mock_hass.bus.async_fire = MagicMock()

    now_dt = datetime(2023, 1, 1, 8, 30, 0, tzinfo=dt_util.UTC)  # P0 window
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now_dt,
    ):
        mock_hass.states.get.return_value = _state("40.0")
        await vwc_coordinator._update_loop(now_dt)

    mock_hass.bus.async_fire.assert_not_called()


# ---------------------------------------------------------------------------
# Phase Trigger tests (Issue #372)
# ---------------------------------------------------------------------------


def test_irrigation_config_phase_trigger_defaults() -> None:
    """IrrigationConfig has the three phase trigger fields with correct defaults."""
    config = IrrigationConfig()
    assert config.auto_advance_p1_to_p2 is False
    assert config.auto_advance_p2_to_p3 is False
    assert config.halt_on_runoff_ec_threshold is None


@pytest.mark.parametrize(
    ("auto_advance_p1_to_p2", "auto_advance_p2_to_p3", "halt_on_runoff_ec_threshold"),
    [
        (True, False, None),
        (False, True, None),
        (False, False, 3.5),
        (True, True, 2.0),
    ],
)
def test_irrigation_config_phase_trigger_roundtrip(
    auto_advance_p1_to_p2: bool,
    auto_advance_p2_to_p3: bool,
    halt_on_runoff_ec_threshold: float | None,
) -> None:
    """Phase trigger fields survive a dataclass round-trip."""
    config = IrrigationConfig(
        auto_advance_p1_to_p2=auto_advance_p1_to_p2,
        auto_advance_p2_to_p3=auto_advance_p2_to_p3,
        halt_on_runoff_ec_threshold=halt_on_runoff_ec_threshold,
    )
    assert config.auto_advance_p1_to_p2 == auto_advance_p1_to_p2
    assert config.auto_advance_p2_to_p3 == auto_advance_p2_to_p3
    assert config.halt_on_runoff_ec_threshold == halt_on_runoff_ec_threshold


async def test_auto_advance_p1_to_p2_flag_off_no_advance(
    vwc_coordinator: VWCIrrigationCoordinator,
    mock_hass: MagicMock,
    mock_growspace: Growspace,
) -> None:
    """With auto_advance_p1_to_p2=False (default), coordinator does NOT advance to P2 post-shot."""
    mock_growspace.irrigation_config.auto_advance_p1_to_p2 = False
    now_dt = datetime(2023, 1, 1, 9, 30, 0, tzinfo=dt_util.UTC)

    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now_dt,
    ):
        # VWC below target so shot fires
        mock_hass.states.get.return_value = _state("40.0")
        await vwc_coordinator._update_loop(now_dt)
        await await_pump_task()

    # Target NOT reached — we're still in P1
    assert vwc_coordinator._machine._target_reached_today is False


async def test_auto_advance_p1_to_p2_flag_on_advances_after_shot(
    vwc_coordinator: VWCIrrigationCoordinator,
    mock_hass: MagicMock,
    mock_growspace: Growspace,
) -> None:
    """With auto_advance_p1_to_p2=True, reaching target VWC advances phase to P2 immediately."""
    mock_growspace.irrigation_config.auto_advance_p1_to_p2 = True
    now_dt = datetime(2023, 1, 1, 9, 30, 0, tzinfo=dt_util.UTC)

    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now_dt,
    ):
        # VWC exactly at target — the existing transition should fire even without a shot
        mock_hass.states.get.return_value = _state("50.0")
        await vwc_coordinator._update_loop(now_dt)

    assert vwc_coordinator._machine._target_reached_today is True


async def test_auto_advance_p2_to_p3_flag_off_no_early_stop(
    vwc_coordinator: VWCIrrigationCoordinator,
    mock_hass: MagicMock,
    mock_growspace: Growspace,
) -> None:
    """With auto_advance_p2_to_p3=False, P2 continues past the early-stop window."""
    mock_growspace.irrigation_config.auto_advance_p2_to_p3 = False
    vwc_coordinator._machine._target_reached_today = True
    vwc_coordinator._machine._last_reset_date = "2023-01-01"

    # 19:00 — inside the default p2_stop_before_lights_off_minutes=120 window
    # (lights_off=20:00, stop=18:00).  Without the flag the coordinator should
    # remain in P2, not P3.
    now_dt = datetime(2023, 1, 1, 19, 0, 0, tzinfo=dt_util.UTC)

    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now_dt,
    ):
        mock_hass.states.get.return_value = _state("45.0")
        await vwc_coordinator._update_loop(now_dt)

    assert "P2" in vwc_coordinator._machine.current_phase


async def test_auto_advance_p2_to_p3_flag_on_enters_p3_early(
    vwc_coordinator: VWCIrrigationCoordinator,
    mock_hass: MagicMock,
    mock_growspace: Growspace,
) -> None:
    """With auto_advance_p2_to_p3=True, P3 starts p2_stop_before_lights_off_minutes before lights-off."""
    mock_growspace.irrigation_config.auto_advance_p2_to_p3 = True
    vwc_coordinator._machine._target_reached_today = True
    vwc_coordinator._machine._last_reset_date = "2023-01-01"

    # 19:00 — inside the default early-stop window (lights_off=20:00, stop=18:00)
    now_dt = datetime(2023, 1, 1, 19, 0, 0, tzinfo=dt_util.UTC)

    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now_dt,
    ):
        mock_hass.states.get.return_value = _state("45.0")
        await vwc_coordinator._update_loop(now_dt)

    assert "P3" in vwc_coordinator._machine.current_phase


async def test_halt_on_runoff_ec_threshold_not_set_no_halt(
    vwc_coordinator: VWCIrrigationCoordinator,
    mock_hass: MagicMock,
    mock_growspace: Growspace,
) -> None:
    """With halt_on_runoff_ec_threshold=None, high drain EC does not halt watering."""
    from custom_components.growspace_manager.models import DrainReading

    mock_growspace.irrigation_config.halt_on_runoff_ec_threshold = None
    mock_growspace.drain_config.readings = [
        DrainReading(timestamp="2023-01-01T09:00:00", feed_ec=2.0, drain_ec=5.0)
    ]
    now_dt = datetime(2023, 1, 1, 9, 30, 0, tzinfo=dt_util.UTC)

    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now_dt,
    ):
        mock_hass.states.get.return_value = _state("40.0")
        await vwc_coordinator._update_loop(now_dt)
        await await_pump_task()

    # Watering should have fired
    mock_hass.services.async_call.assert_any_call(
        "switch", "turn_on", {"entity_id": "switch.pump"}, blocking=True
    )


async def test_halt_on_runoff_ec_threshold_exceeded_halts_watering(
    vwc_coordinator: VWCIrrigationCoordinator,
    mock_hass: MagicMock,
    mock_growspace: Growspace,
) -> None:
    """When drain EC exceeds halt_on_runoff_ec_threshold, watering is suspended and a warning is logged."""
    from custom_components.growspace_manager.models import DrainReading

    mock_growspace.irrigation_config.halt_on_runoff_ec_threshold = 3.0
    mock_growspace.drain_config.readings = [
        DrainReading(timestamp="2023-01-01T09:00:00", feed_ec=2.0, drain_ec=3.5)
    ]
    now_dt = datetime(2023, 1, 1, 9, 30, 0, tzinfo=dt_util.UTC)

    with (
        patch(
            "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
            return_value=now_dt,
        ),
        patch("custom_components.growspace_manager.vwc_irrigation_coordinator._LOGGER"),
    ):
        mock_hass.states.get.return_value = _state("40.0")
        await vwc_coordinator._update_loop(now_dt)

    mock_hass.services.async_call.assert_not_called()


# ---------------------------------------------------------------------------
# Lights-on time resolution: detected_lights_on_time vs lights_on_time
# ---------------------------------------------------------------------------


async def test_vwc_uses_detected_lights_on_time_when_set(
    vwc_coordinator, mock_hass, mock_growspace
) -> None:
    """When detected_lights_on_time is set, VWC uses it for phase window calculation."""
    mock_growspace.irrigation_strategy.lights_on_time = "08:00:00"
    mock_growspace.irrigation_strategy.detected_lights_on_time = "09:00:00"

    # At 09:20 it should be in P0 (within 60-min activation window after detected 09:00)
    now = datetime(2023, 1, 1, 9, 20, 0, tzinfo=dt_util.UTC)
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now,
    ):
        mock_hass.states.get.return_value = _state("40.0")
        await vwc_coordinator._update_loop(now)

    assert vwc_coordinator._machine.current_phase == "P0 - Activation"


async def test_vwc_falls_back_to_lights_on_time_when_detected_is_none(
    vwc_coordinator, mock_hass, mock_growspace
) -> None:
    """When detected_lights_on_time is None, VWC uses lights_on_time as anchor."""
    mock_growspace.irrigation_strategy.lights_on_time = "08:00:00"
    mock_growspace.irrigation_strategy.detected_lights_on_time = None

    # At 08:20 it should be in P0 (within 60-min activation window after 08:00)
    now = datetime(2023, 1, 1, 8, 20, 0, tzinfo=dt_util.UTC)
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now,
    ):
        mock_hass.states.get.return_value = _state("40.0")
        await vwc_coordinator._update_loop(now)

    assert vwc_coordinator._machine.current_phase == "P0 - Activation"


async def test_handle_watering_cancels_lingering_task(
    vwc_coordinator: VWCIrrigationCoordinator,
    mock_hass: MagicMock,
    mock_growspace: Growspace,
) -> None:
    """Test that _handle_watering cancels an existing lingering irrigation task."""
    strategy = mock_growspace.irrigation_strategy

    # Place a mock lingering task in the coordinator's running tasks
    mock_task = MagicMock()
    mock_task.done.return_value = False
    vwc_coordinator._running_tasks["irrigation"] = mock_task

    # We trigger watering (ensure _last_cycle_timestamp allows it)
    vwc_coordinator._last_cycle_timestamp = None

    now_dt = datetime(2023, 1, 1, 12, 0, 0, tzinfo=dt_util.UTC)
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now_dt,
    ):
        _drive_watering(vwc_coordinator, strategy, "P1")

    # The existing lingering task should have been cancelled
    mock_task.cancel.assert_called_once()


async def test_halt_on_runoff_ec_threshold_no_readings(
    vwc_coordinator: VWCIrrigationCoordinator,
    mock_hass: MagicMock,
    mock_growspace: Growspace,
) -> None:
    """Test that when halt_on_runoff_ec_threshold is set but readings list is empty, irrigation does not halt."""
    mock_growspace.irrigation_config.halt_on_runoff_ec_threshold = 3.0
    mock_growspace.drain_config.readings = []

    now_dt = datetime(2023, 1, 1, 9, 30, 0, tzinfo=dt_util.UTC)
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now_dt,
    ):
        mock_hass.states.get.return_value = _state("40.0")
        await vwc_coordinator._update_loop(now_dt)
        await await_pump_task()

    # Watering should NOT be halted, so switch.pump should turn on
    mock_hass.services.async_call.assert_any_call(
        "switch", "turn_on", {"entity_id": "switch.pump"}, blocking=True
    )


async def test_halt_on_runoff_ec_threshold_not_exceeded(
    vwc_coordinator: VWCIrrigationCoordinator,
    mock_hass: MagicMock,
    mock_growspace: Growspace,
) -> None:
    """Test that when halt_on_runoff_ec_threshold is set and readings exist, but latest EC is not exceeded, irrigation does not halt."""
    from custom_components.growspace_manager.models import DrainReading

    mock_growspace.irrigation_config.halt_on_runoff_ec_threshold = 3.0
    mock_growspace.drain_config.readings = [
        DrainReading(timestamp="2023-01-01T09:00:00", feed_ec=2.0, drain_ec=2.5)
    ]

    now_dt = datetime(2023, 1, 1, 9, 30, 0, tzinfo=dt_util.UTC)
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now_dt,
    ):
        mock_hass.states.get.return_value = _state("40.0")
        await vwc_coordinator._update_loop(now_dt)
        await await_pump_task()

    # Watering should NOT be halted, so switch.pump should turn on
    mock_hass.services.async_call.assert_any_call(
        "switch", "turn_on", {"entity_id": "switch.pump"}, blocking=True
    )


async def test_projected_shot_window_during_active_watering_window(
    vwc_coordinator: VWCIrrigationCoordinator,
) -> None:
    """In P1/P2 with no active cooldown, the window spans now to P2 stop."""
    # 09:30 — inside the P1/P2 window (P0 ends 09:00, P2 stops 18:00)
    now_dt = datetime(2023, 1, 1, 9, 30, 0, tzinfo=dt_util.UTC)
    vwc_coordinator._machine._phase = "P2 - Maintenance"
    vwc_coordinator._last_cycle_timestamp = None

    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now_dt,
    ):
        window = vwc_coordinator.projected_shot_window

    assert window == {
        "start": now_dt.isoformat(),
        "end": datetime(2023, 1, 1, 18, 0, 0, tzinfo=dt_util.UTC).isoformat(),
    }


async def test_projected_shot_window_during_active_watering_window_with_cooldown(
    vwc_coordinator: VWCIrrigationCoordinator,
) -> None:
    """In P1/P2 with an active cooldown, the window starts when the cooldown ends."""
    # 09:30 — inside the P1/P2 window; last shot 5 minutes ago, interval is 15 minutes
    now_dt = datetime(2023, 1, 1, 9, 30, 0, tzinfo=dt_util.UTC)
    vwc_coordinator._machine._phase = "P2 - Maintenance"
    vwc_coordinator._last_cycle_timestamp = (
        datetime(2023, 1, 1, 9, 25, 0, tzinfo=dt_util.UTC)
    ).isoformat()

    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now_dt,
    ):
        window = vwc_coordinator.projected_shot_window

    assert window == {
        "start": datetime(2023, 1, 1, 9, 40, 0, tzinfo=dt_util.UTC).isoformat(),
        "end": datetime(2023, 1, 1, 18, 0, 0, tzinfo=dt_util.UTC).isoformat(),
    }


async def test_projected_shot_window_ignores_expired_cooldown(
    vwc_coordinator: VWCIrrigationCoordinator,
) -> None:
    """When the last shot's cooldown has already elapsed, the window starts at now."""
    # 09:30 — last shot 20 minutes ago, interval is 15 minutes, so cooldown has expired
    now_dt = datetime(2023, 1, 1, 9, 30, 0, tzinfo=dt_util.UTC)
    vwc_coordinator._machine._phase = "P2 - Maintenance"
    vwc_coordinator._last_cycle_timestamp = (
        datetime(2023, 1, 1, 9, 10, 0, tzinfo=dt_util.UTC)
    ).isoformat()

    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now_dt,
    ):
        window = vwc_coordinator.projected_shot_window

    assert window == {
        "start": now_dt.isoformat(),
        "end": datetime(2023, 1, 1, 18, 0, 0, tzinfo=dt_util.UTC).isoformat(),
    }


async def test_projected_shot_window_during_p0_activation(
    vwc_coordinator: VWCIrrigationCoordinator,
) -> None:
    """In P0 with no active cooldown, the window spans now to the P0→P1 boundary."""
    # 08:30 — inside P0 (lights on 08:00, P0 ends 09:00)
    now_dt = datetime(2023, 1, 1, 8, 30, 0, tzinfo=dt_util.UTC)
    vwc_coordinator._machine._phase = "P0 - Activation"
    vwc_coordinator._last_cycle_timestamp = None

    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now_dt,
    ):
        window = vwc_coordinator.projected_shot_window

    assert window == {
        "start": now_dt.isoformat(),
        "end": datetime(2023, 1, 1, 9, 0, 0, tzinfo=dt_util.UTC).isoformat(),
    }


async def test_projected_shot_window_rolls_to_tomorrow_during_dryback(
    vwc_coordinator: VWCIrrigationCoordinator,
) -> None:
    """In P3 (Dry-back), the window rolls forward to tomorrow's P1 start / P2 stop."""
    # 22:00 — in P3 (lights off at 20:00)
    now_dt = datetime(2023, 1, 1, 22, 0, 0, tzinfo=dt_util.UTC)
    vwc_coordinator._machine._phase = "P3 - Dry Back"

    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now_dt,
    ):
        window = vwc_coordinator.projected_shot_window

    # Tomorrow: lights on 08:00 + p0_duration 60min = P1 start 09:00; P2 stop 18:00
    assert window == {
        "start": datetime(2023, 1, 2, 9, 0, 0, tzinfo=dt_util.UTC).isoformat(),
        "end": datetime(2023, 1, 2, 18, 0, 0, tzinfo=dt_util.UTC).isoformat(),
    }


async def test_projected_shot_window_rolls_to_tomorrow_near_end_of_active_window(
    vwc_coordinator: VWCIrrigationCoordinator,
) -> None:
    """When an active cooldown would push the start past today's P2 stop, it rolls to tomorrow."""
    # 17:50 — still in P2; last shot 5 minutes ago means cooldown ends 18:05, past P2 stop (18:00)
    now_dt = datetime(2023, 1, 1, 17, 50, 0, tzinfo=dt_util.UTC)
    vwc_coordinator._machine._phase = "P2 - Maintenance"
    vwc_coordinator._last_cycle_timestamp = datetime(
        2023, 1, 1, 17, 45, 0, tzinfo=dt_util.UTC
    ).isoformat()

    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now_dt,
    ):
        window = vwc_coordinator.projected_shot_window

    assert window == {
        "start": datetime(2023, 1, 2, 9, 0, 0, tzinfo=dt_util.UTC).isoformat(),
        "end": datetime(2023, 1, 2, 18, 0, 0, tzinfo=dt_util.UTC).isoformat(),
    }


async def test_projected_shot_window_none_when_steering_disabled(
    vwc_coordinator: VWCIrrigationCoordinator, mock_growspace: Growspace
) -> None:
    """Returns None when crop steering is not enabled, mirroring next_scheduled_cycle."""
    mock_growspace.irrigation_strategy.enabled = False
    now_dt = datetime(2023, 1, 1, 9, 30, 0, tzinfo=dt_util.UTC)

    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now_dt,
    ):
        assert vwc_coordinator.projected_shot_window is None


# The Adaptive Shot Control feedback math now lives in the ShotComposer and is
# unit-tested in tests/domain/test_shot_composer.py. The cases below verify the
# coordinator *wires* the composer correctly: triggering reset() on the phase
# events it owns, and feeding settled cycles into observe().


async def test_phase_transition_resets_composer_factors(
    vwc_coordinator: VWCIrrigationCoordinator,
    mock_growspace: Growspace,
) -> None:
    """A verdict flagging the P1->P2 transition resets both composer factors."""
    vwc_coordinator._composer.size_factor = 0.6
    vwc_coordinator._composer.interval_factor = 1.4

    verdict = SteeringTickVerdict(
        phase="P2 - Maintenance",
        canonical="p2",
        phase_changed=True,
        transition_message="VWC phase transition: P1 - Ramp Up → P2 - Maintenance",
        reset_composer=True,
        fire=None,
        volume_change_note=None,
    )
    vwc_coordinator._apply_verdict(verdict, mock_growspace.irrigation_strategy)

    assert vwc_coordinator._composer.size_factor == 1.0
    assert vwc_coordinator._composer.interval_factor == 1.0


async def test_daily_reset_resets_composer_factors(
    vwc_coordinator: VWCIrrigationCoordinator,
) -> None:
    """The midnight daily-state reset returns both composer factors to 1.0."""
    vwc_coordinator._composer.size_factor = 0.6
    vwc_coordinator._composer.interval_factor = 1.4

    vwc_coordinator._reset_extra_daily_state()

    assert vwc_coordinator._composer.size_factor == 1.0
    assert vwc_coordinator._composer.interval_factor == 1.0


async def test_cycle_completion_feeds_composer(
    vwc_coordinator: VWCIrrigationCoordinator,
) -> None:
    """A settled irrigation cycle feeds the moisture delta to the ShotComposer.

    Target 50.0, before 40.0, settled after 55.0 -> ratio 1.5 -> size factor 0.5.
    The base completion behaviour is stubbed so only the wiring is exercised.
    """
    now_dt = datetime(2023, 1, 1, 12, 0, 0, tzinfo=dt_util.UTC)
    with (
        patch.object(
            BaseIrrigationCoordinator,
            "_async_report_cycle_completion",
            new_callable=AsyncMock,
        ),
        patch.object(vwc_coordinator, "_get_sensor_value", return_value=55.0),
    ):
        await vwc_coordinator._async_report_cycle_completion(
            event_type="irrigation",
            start_dt=now_dt,
            end_dt=now_dt,
            duration_sec=1.0,
            moisture_before=40.0,
            volume_dispensed_today=0.0,
            wait_seconds=0.0,
        )

    assert vwc_coordinator._composer.size_factor == 0.5
    assert vwc_coordinator._composer.interval_factor == 1.5


@pytest.mark.parametrize(
    ("phase", "expected_scaled_duration"),
    [("P1", 6), ("P2", 12)],
)
async def test_dynamic_shot_scaled_duration_applied(
    vwc_coordinator: VWCIrrigationCoordinator,
    mock_hass: MagicMock,
    mock_growspace: Growspace,
    mock_sleep: AsyncMock,
    phase: str,
    expected_scaled_duration: int,
) -> None:
    """The VWC feedback scale factor applies to whichever phase's shot is firing."""
    strategy = mock_growspace.irrigation_strategy
    strategy.p1_shot_duration_seconds = 10
    strategy.p2_shot_duration_seconds = 20
    vwc_coordinator._composer.size_factor = 0.6

    vwc_coordinator._last_cycle_timestamp = None
    now_dt = datetime(2023, 1, 1, 12, 0, 0, tzinfo=dt_util.UTC)

    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now_dt,
    ):
        _drive_watering(vwc_coordinator, strategy, phase)

    # Await the pump task to execute
    await await_pump_task()

    # Verify that sleep was called with the phase duration times the scale factor
    mock_sleep.assert_any_call(expected_scaled_duration)


@pytest.mark.parametrize(
    ("phase", "expected_duration"),
    [("P1", 7), ("P2", 13)],
)
async def test_per_phase_shot_duration_used(
    vwc_coordinator: VWCIrrigationCoordinator,
    mock_hass: MagicMock,
    mock_growspace: Growspace,
    mock_sleep: AsyncMock,
    phase: str,
    expected_duration: int,
) -> None:
    """P1 shots use the P1 duration and P2 shots use the P2 duration."""
    strategy = mock_growspace.irrigation_strategy
    strategy.p1_shot_duration_seconds = 7
    strategy.p2_shot_duration_seconds = 13
    vwc_coordinator._last_cycle_timestamp = None

    _drive_watering(vwc_coordinator, strategy, phase)
    await await_pump_task()

    mock_sleep.assert_any_call(expected_duration)


@pytest.mark.parametrize(
    ("phase", "expected_call_count"),
    [("P1", 0), ("P2", 2)],
)
async def test_per_phase_shot_cooldown(
    vwc_coordinator: VWCIrrigationCoordinator,
    mock_hass: MagicMock,
    mock_growspace: Growspace,
    mock_sleep: AsyncMock,
    phase: str,
    expected_call_count: int,
) -> None:
    """The cooldown check uses the firing phase's interval.

    With 10 minutes elapsed since the last shot, a P1 shot (15 min interval)
    is throttled while a P2 shot (5 min interval) fires.
    """
    strategy = mock_growspace.irrigation_strategy
    strategy.p1_shot_interval_minutes = 15
    strategy.p2_shot_interval_minutes = 5

    last_time = datetime(2023, 1, 1, 12, 0, 0, tzinfo=dt_util.UTC)
    vwc_coordinator._last_cycle_timestamp = last_time.isoformat()
    current_time = datetime(2023, 1, 1, 12, 10, 0, tzinfo=dt_util.UTC)

    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=current_time,
    ):
        _drive_watering(vwc_coordinator, strategy, phase)

    await await_pump_task()
    assert mock_hass.services.async_call.call_count == expected_call_count


@pytest.mark.parametrize(
    ("current_phase", "expected_start"),
    [
        ("P1 - Ramp Up", datetime(2023, 1, 1, 9, 45, 0, tzinfo=dt_util.UTC)),
        ("P2 - Maintenance", datetime(2023, 1, 1, 9, 55, 0, tzinfo=dt_util.UTC)),
    ],
)
async def test_projected_shot_window_uses_active_phase_interval(
    vwc_coordinator: VWCIrrigationCoordinator,
    mock_growspace: Growspace,
    current_phase: str,
    expected_start: datetime,
) -> None:
    """The cooldown anchor uses the active phase's interval (P1 15 min, P2 25 min)."""
    strategy = mock_growspace.irrigation_strategy
    strategy.p1_shot_interval_minutes = 15
    strategy.p2_shot_interval_minutes = 25

    now_dt = datetime(2023, 1, 1, 9, 35, 0, tzinfo=dt_util.UTC)
    vwc_coordinator._machine._phase = current_phase
    vwc_coordinator._last_cycle_timestamp = (
        datetime(2023, 1, 1, 9, 30, 0, tzinfo=dt_util.UTC)
    ).isoformat()

    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now_dt,
    ):
        window = vwc_coordinator.projected_shot_window

    assert window == {
        "start": expected_start.isoformat(),
        "end": datetime(2023, 1, 1, 18, 0, 0, tzinfo=dt_util.UTC).isoformat(),
    }


def _state(value: str, last_updated: datetime | None = None) -> MagicMock:
    """Build a mock HA state with a given string state.

    ``last_updated`` is the sensor's own update time, which the Infiltration
    Monitor samples on; a bare MagicMock attribute is not orderable, so callers
    exercising the monitor pass a real datetime.
    """
    state = MagicMock()
    state.state = value
    state.last_updated = last_updated
    return state


def test_average_pore_ec_no_sensors_returns_none(
    vwc_coordinator, mock_growspace
) -> None:
    """With no pore-EC sensors configured the average is None (unavailable)."""
    mock_growspace.environment_config.pore_ec_sensors = []
    assert vwc_coordinator._average_pore_ec(mock_growspace) is None


def test_average_pore_ec_averages_valid_sensors(
    vwc_coordinator, mock_hass, mock_growspace
) -> None:
    """Pore-EC sensors are averaged across their valid numeric states."""
    mock_growspace.environment_config.pore_ec_sensors = [
        "sensor.ec_a",
        "sensor.ec_b",
    ]
    mock_hass.states.get.side_effect = lambda eid: {
        "sensor.ec_a": _state("2.0"),
        "sensor.ec_b": _state("3.0"),
    }[eid]
    assert vwc_coordinator._average_pore_ec(mock_growspace) == pytest.approx(2.5)


def test_average_pore_ec_skips_unusable_states(
    vwc_coordinator, mock_hass, mock_growspace
) -> None:
    """Unavailable/unknown/non-numeric sensors are skipped before averaging."""
    mock_growspace.environment_config.pore_ec_sensors = [
        "sensor.ec_a",
        "sensor.ec_b",
        "sensor.ec_c",
        "sensor.ec_d",
    ]
    mock_hass.states.get.side_effect = lambda eid: {
        "sensor.ec_a": _state("2.0"),
        "sensor.ec_b": _state("unavailable"),
        "sensor.ec_c": _state("unknown"),
        "sensor.ec_d": _state("not_a_number"),
    }[eid]
    # Only the single valid 2.0 reading survives.
    assert vwc_coordinator._average_pore_ec(mock_growspace) == pytest.approx(2.0)


def test_average_pore_ec_all_unusable_returns_none(
    vwc_coordinator, mock_hass, mock_growspace
) -> None:
    """A full sensor dropout yields None (unavailable), not a stale value."""
    mock_growspace.environment_config.pore_ec_sensors = ["sensor.ec_a"]
    mock_hass.states.get.return_value = _state("unavailable")
    assert vwc_coordinator._average_pore_ec(mock_growspace) is None


# ── EC Modulation factor (pure mapping) ──────────────────────────────────────


@pytest.mark.parametrize(
    ("measured_ec", "expected_factor"),
    [
        # Within band → exactly 1.0 (band 2.0–3.0).
        (2.0, 1.0),
        (2.5, 1.0),
        (3.0, 1.0),
        # Above band → >1.0, proportional to excursion, full-scale delta 1.0.
        (3.5, 1.125),  # 0.5 past max → 1 + 0.25*0.5
        (4.0, 1.25),  # 1.0 past max → saturates at max bound
        (10.0, 1.25),  # far above → clamped to max bound
        # Below band → <1.0.
        (1.5, 0.875),  # 0.5 below min → 1 - 0.25*0.5
        (1.0, 0.75),  # 1.0 below min → saturates at min bound
        (0.0, 0.75),  # far below → clamped to min bound
    ],
)
def test_ec_modulation_factor_for_reading(
    measured_ec: float, expected_factor: float
) -> None:
    """The pure factor map responds above/within/below the band, bounded ±25%."""
    factor = ec_modulation_factor_for_reading(measured_ec, 2.0, 3.0)
    assert factor == pytest.approx(expected_factor)


# ── EC Modulation gating (capability) ────────────────────────────────────────


def _set_band(growspace: Growspace, enabled: bool) -> None:
    """Configure a 2.0–3.0 pore-EC band with the given opt-in flag."""
    growspace.irrigation_strategy.pore_ec_target_min = 2.0
    growspace.irrigation_strategy.pore_ec_target_max = 3.0
    growspace.irrigation_strategy.ec_modulation_enabled = enabled


def test_ec_modulation_disabled_factor_one_unavailable(
    vwc_coordinator, mock_hass, mock_growspace
) -> None:
    """Opt-in off → factor exactly 1.0 and capability False, even with sensors."""
    _set_band(mock_growspace, enabled=False)
    mock_growspace.environment_config.pore_ec_sensors = ["sensor.ec_a"]
    mock_hass.states.get.return_value = _state("5.0")  # well above band

    factor, available = vwc_coordinator._compute_ec_modulation(
        mock_growspace.irrigation_strategy, mock_growspace
    )
    assert factor == 1.0
    assert available is False


def test_ec_modulation_no_sensors_factor_one_unavailable(
    vwc_coordinator, mock_growspace
) -> None:
    """Enabled but no pore-EC sensors → factor 1.0, capability False (gated)."""
    _set_band(mock_growspace, enabled=True)
    mock_growspace.environment_config.pore_ec_sensors = []

    factor, available = vwc_coordinator._compute_ec_modulation(
        mock_growspace.irrigation_strategy, mock_growspace
    )
    assert factor == 1.0
    assert available is False


def test_ec_modulation_no_band_factor_one_unavailable(
    vwc_coordinator, mock_hass, mock_growspace
) -> None:
    """Enabled with sensors but no band configured → factor 1.0, capability False."""
    mock_growspace.irrigation_strategy.ec_modulation_enabled = True
    mock_growspace.irrigation_strategy.pore_ec_target_min = None
    mock_growspace.irrigation_strategy.pore_ec_target_max = None
    mock_growspace.environment_config.pore_ec_sensors = ["sensor.ec_a"]
    mock_hass.states.get.return_value = _state("5.0")

    factor, available = vwc_coordinator._compute_ec_modulation(
        mock_growspace.irrigation_strategy, mock_growspace
    )
    assert factor == 1.0
    assert available is False


@pytest.mark.parametrize(
    ("measured", "expected_factor"),
    [("2.5", 1.0), ("4.0", 1.25), ("1.0", 0.75)],
)
def test_ec_modulation_available_within_above_below(
    vwc_coordinator, mock_hass, mock_growspace, measured: str, expected_factor: float
) -> None:
    """Enabled + band + reading → capability True; within band still factor 1.0.

    Distinguishes "within band → 1.0" (available True) from the gated cases
    above where 1.0 comes with available False.
    """
    _set_band(mock_growspace, enabled=True)
    mock_growspace.environment_config.pore_ec_sensors = ["sensor.ec_a"]
    mock_hass.states.get.return_value = _state(measured)

    factor, available = vwc_coordinator._compute_ec_modulation(
        mock_growspace.irrigation_strategy, mock_growspace
    )
    assert factor == pytest.approx(expected_factor)
    assert available is True


def test_ec_modulation_runoff_flush_actuates_from_runoff_ec(
    vwc_coordinator, mock_hass, mock_growspace
) -> None:
    """Sustained over-target runoff delta enlarges a within-band-pore P2 shot.

    Pore EC (2.5) sits within the 2.0–3.0 band → base HOLD (factor 1.0). Two drain
    readings with delta 1.0 (> max_ec_delta 0.5) escalate HOLD→FLUSH, and the
    magnitude comes from the runoff EC (4.0, above band) through the one helper:
    factor 1.25 (ADR-0016).
    """
    from custom_components.growspace_manager.models import DrainReading

    _set_band(mock_growspace, enabled=True)
    mock_growspace.environment_config.pore_ec_sensors = ["sensor.ec_a"]
    mock_hass.states.get.return_value = _state("2.5")  # within band → HOLD
    mock_growspace.drain_config.max_ec_delta = 0.5
    mock_growspace.drain_config.readings = [
        DrainReading(timestamp="t1", feed_ec=3.0, drain_ec=4.0),
        DrainReading(timestamp="t2", feed_ec=3.0, drain_ec=4.0),
    ]

    factor, available = vwc_coordinator._compute_ec_modulation(
        mock_growspace.irrigation_strategy, mock_growspace
    )
    assert available is True
    assert factor == pytest.approx(1.25)  # driven by runoff EC 4.0 vs band max 3.0


def test_ec_modulation_single_high_runoff_does_not_actuate(
    vwc_coordinator, mock_hass, mock_growspace
) -> None:
    """A single over-target runoff reading is not 'sustained' → stays HOLD (1.0)."""
    from custom_components.growspace_manager.models import DrainReading

    _set_band(mock_growspace, enabled=True)
    mock_growspace.environment_config.pore_ec_sensors = ["sensor.ec_a"]
    mock_hass.states.get.return_value = _state("2.5")
    mock_growspace.drain_config.max_ec_delta = 0.5
    mock_growspace.drain_config.readings = [
        DrainReading(timestamp="t1", feed_ec=3.0, drain_ec=4.0)
    ]

    factor, _ = vwc_coordinator._compute_ec_modulation(
        mock_growspace.irrigation_strategy, mock_growspace
    )
    assert factor == pytest.approx(1.0)


# ── Shot Size Composition (VWC × EC) and caps last ───────────────────────────


async def test_ec_modulation_only_applies_to_p2(
    vwc_coordinator, mock_hass, mock_growspace, mock_sleep
) -> None:
    """EC modulation applies to P2 shots only; P1 keeps a neutral EC factor."""
    _set_band(mock_growspace, enabled=True)
    mock_growspace.environment_config.pore_ec_sensors = ["sensor.ec_a"]
    mock_hass.states.get.return_value = _state("4.0")  # above band → EC 1.25
    strategy = mock_growspace.irrigation_strategy
    strategy.p1_shot_duration_seconds = 20
    vwc_coordinator._last_cycle_timestamp = None

    _drive_watering(vwc_coordinator, strategy, "P1")
    await await_pump_task()

    comp = vwc_coordinator._composer.last_composition
    assert comp.ec_factor == 1.0
    assert comp.ec_modulation_available is False
    mock_sleep.assert_any_call(20)


async def test_shot_composition_multiplies_vwc_and_ec(
    vwc_coordinator, mock_hass, mock_growspace, mock_sleep
) -> None:
    """P2 effective duration = base × VWC factor × EC factor (partial cancel)."""
    _set_band(mock_growspace, enabled=True)
    mock_growspace.environment_config.pore_ec_sensors = ["sensor.ec_a"]
    mock_hass.states.get.return_value = _state("4.0")  # above band → EC 1.25
    strategy = mock_growspace.irrigation_strategy
    strategy.p2_shot_duration_seconds = 100
    # VWC feedback factor pulls down while EC pulls up: 100 × 0.85 × 1.25 = 106.
    vwc_coordinator._composer.size_factor = 0.85
    vwc_coordinator._last_cycle_timestamp = None

    _drive_watering(vwc_coordinator, strategy, "P2")
    await await_pump_task()

    comp = vwc_coordinator._composer.last_composition
    assert comp.base_seconds == 100
    assert comp.vwc_factor == pytest.approx(0.85)
    assert comp.ec_factor == pytest.approx(1.25)
    assert comp.ec_modulation_available is True
    assert comp.effective_seconds == 106  # round(100 * 0.85 * 1.25)
    assert comp.capped is False
    mock_sleep.assert_any_call(106)


async def test_shot_composition_below_band_stacks_down(
    vwc_coordinator, mock_hass, mock_growspace, mock_sleep
) -> None:
    """Below-band pore EC scales the P2 shot DOWN (stacking)."""
    _set_band(mock_growspace, enabled=True)
    mock_growspace.environment_config.pore_ec_sensors = ["sensor.ec_a"]
    mock_hass.states.get.return_value = _state("1.0")  # below band → EC 0.75
    strategy = mock_growspace.irrigation_strategy
    strategy.p2_shot_duration_seconds = 100
    vwc_coordinator._last_cycle_timestamp = None

    _drive_watering(vwc_coordinator, strategy, "P2")
    await await_pump_task()

    comp = vwc_coordinator._composer.last_composition
    assert comp.ec_factor == pytest.approx(0.75)
    assert comp.effective_seconds == 75
    mock_sleep.assert_any_call(75)


async def test_composed_shot_blocked_by_volume_cap_never_exceeds(
    vwc_coordinator, mock_hass, mock_growspace, mock_sleep
) -> None:
    """A composed (EC-amplified) shot that would breach the daily volume cap is
    clamped LAST: the safety guard blocks the cycle, no pump runs, and the
    composition records capped=True with effective_seconds 0.
    """
    _set_band(mock_growspace, enabled=True)
    mock_growspace.environment_config.pore_ec_sensors = ["sensor.ec_a"]
    mock_hass.states.get.return_value = _state("4.0")  # above band → EC 1.25
    strategy = mock_growspace.irrigation_strategy
    strategy.p2_shot_duration_seconds = 100
    # Flow rate so the composed 125 s shot pushes past a tiny daily cap.
    mock_growspace.irrigation_config.pump_flow_rate_ml_per_sec = 10.0  # 1.25 L
    mock_growspace.irrigation_config.daily_volume_cap_liters = 0.5
    vwc_coordinator._last_cycle_timestamp = None

    _drive_watering(vwc_coordinator, strategy, "P2")
    await await_pump_task()

    comp = vwc_coordinator._composer.last_composition
    assert comp.composed_seconds == 125  # base 100 × EC 1.25
    assert comp.capped is True
    assert comp.effective_seconds == 0
    # Caps are applied last and never exceeded: the pump never ran its on-cycle
    # for the composed 125 s duration, and the switch was never turned on.
    pump_durations = [c.args[0] for c in mock_sleep.call_args_list if c.args]
    assert 125 not in pump_durations
    mock_hass.services.async_call.assert_not_called()


def _suppressed_verdict(reason: str | None) -> SteeringTickVerdict:
    """A no-transition P1 verdict that fires nothing, carrying only a reason."""
    return SteeringTickVerdict(
        phase="P1 - Ramp Up",
        canonical="p1",
        phase_changed=False,
        transition_message=None,
        reset_composer=False,
        fire=None,
        volume_change_note=None,
        suppressed_by=reason,
    )


def test_shot_composition_payload_capability_and_band(
    vwc_coordinator, mock_hass, mock_growspace
) -> None:
    """The payload carries the band, opt-in, and live capability flag."""
    _set_band(mock_growspace, enabled=True)
    mock_growspace.environment_config.pore_ec_sensors = ["sensor.ec_a"]
    mock_hass.states.get.return_value = _state("2.5")

    payload = vwc_coordinator.shot_composition_payload()
    assert payload["ec_modulation_enabled"] is True
    assert payload["ec_modulation_available"] is True
    assert payload["pore_ec_target_min"] == 2.0
    assert payload["pore_ec_target_max"] == 3.0
    assert payload["last_shot"] is None  # no shot fired yet
    assert payload["suppressed_by"] is None  # no tick applied yet


async def test_infiltration_state_reaches_the_payload(
    vwc_coordinator, mock_hass
) -> None:
    """Two rising readings from distinct sensor updates surface as infiltrating.

    Drives the real minute loop, so this covers the whole path: the
    freshness-aware read, the monitor, and the shot-composition payload the card
    renders (ADR-0031).
    """
    tick_one = datetime(2023, 1, 1, 9, 30, 0, tzinfo=dt_util.UTC)
    tick_two = datetime(2023, 1, 1, 9, 35, 0, tzinfo=dt_util.UTC)

    for tick, vwc in ((tick_one, "50.0"), (tick_two, "54.0")):
        mock_hass.states.get.return_value = _state(vwc, last_updated=tick)
        with patch(
            "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
            return_value=tick,
        ):
            await vwc_coordinator._update_loop(tick)

    infiltration = vwc_coordinator.shot_composition_payload()["infiltration"]
    assert infiltration == "infiltrating"
    # A plain str, not the StrEnum: this payload is serialized to the card over
    # the WebSocket and re-emitted as a crop-steering entity attribute.
    assert type(infiltration) is str


async def test_a_rising_reading_withholds_the_shot_the_cooldown_would_allow(
    vwc_coordinator, mock_hass
) -> None:
    """The measured state reaches the tick and gates the pump (ADR-0031).

    Drives the real minute loop with two rising readings from distinct sensor
    updates, with the configured cooldown already expired, so only the
    Infiltration Gate can be what withholds the shot.
    """
    tick_one = datetime(2023, 1, 1, 9, 30, 0, tzinfo=dt_util.UTC)
    tick_two = datetime(2023, 1, 1, 9, 35, 0, tzinfo=dt_util.UTC)
    vwc_coordinator._last_cycle_timestamp = datetime(
        2023, 1, 1, 9, 10, 0, tzinfo=dt_util.UTC
    ).isoformat()  # 25 min: past the 15 min cooldown, inside the 45 min backstop

    for tick, vwc in ((tick_one, "40.0"), (tick_two, "44.0")):
        mock_hass.states.get.return_value = _state(vwc, last_updated=tick)
        with patch(
            "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
            return_value=tick,
        ):
            await vwc_coordinator._update_loop(tick)

    assert vwc_coordinator._machine.current_phase == "P1 - Ramp Up"
    mock_hass.services.async_call.assert_not_called()
    assert vwc_coordinator.shot_composition_payload()["suppressed_by"] == "infiltrating"


async def test_midnight_reset_leaves_the_infiltration_measurement_intact(
    vwc_coordinator, mock_hass
) -> None:
    """The daily reset must not discard a live in-flight measurement.

    Infiltration is a physical process spanning minutes with no daily state, so
    unlike the phase machine and the composer the monitor is deliberately absent
    from the midnight reset — clearing it there would open a nightly blind spot
    (ADR-0031).
    """
    tick_one = datetime(2023, 1, 1, 23, 55, 0, tzinfo=dt_util.UTC)
    tick_two = datetime(2023, 1, 1, 23, 59, 0, tzinfo=dt_util.UTC)

    for tick, vwc in ((tick_one, "50.0"), (tick_two, "54.0")):
        mock_hass.states.get.return_value = _state(vwc, last_updated=tick)
        with patch(
            "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
            return_value=tick,
        ):
            await vwc_coordinator._update_loop(tick)

    await vwc_coordinator._async_reset_daily_counters()

    assert vwc_coordinator.shot_composition_payload()["infiltration"] == "infiltrating"


async def test_sensor_dropout_discards_the_infiltration_measurement(
    vwc_coordinator, mock_hass
) -> None:
    """An unavailable sensor clears the buffer: readings across a gap are not a slope."""
    tick_one = datetime(2023, 1, 1, 9, 30, 0, tzinfo=dt_util.UTC)
    tick_two = datetime(2023, 1, 1, 9, 35, 0, tzinfo=dt_util.UTC)
    tick_three = datetime(2023, 1, 1, 9, 40, 0, tzinfo=dt_util.UTC)

    for tick, vwc in (
        (tick_one, "50.0"),
        (tick_two, "54.0"),
        (tick_three, "unavailable"),
    ):
        mock_hass.states.get.return_value = _state(vwc, last_updated=tick)
        with patch(
            "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
            return_value=tick,
        ):
            await vwc_coordinator._update_loop(tick)

    assert vwc_coordinator.shot_composition_payload()["infiltration"] == "unknown"


async def test_no_sensor_configured_discards_the_infiltration_measurement(
    vwc_coordinator, mock_hass, mock_growspace
) -> None:
    """Removing the moisture sensor clears the buffer alongside mark_no_sensor."""
    tick_one = datetime(2023, 1, 1, 9, 30, 0, tzinfo=dt_util.UTC)
    tick_two = datetime(2023, 1, 1, 9, 35, 0, tzinfo=dt_util.UTC)

    for tick, vwc in ((tick_one, "50.0"), (tick_two, "54.0")):
        mock_hass.states.get.return_value = _state(vwc, last_updated=tick)
        with patch(
            "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
            return_value=tick,
        ):
            await vwc_coordinator._update_loop(tick)

    mock_growspace.environment_config.soil_moisture_sensor = None
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=tick_two,
    ):
        await vwc_coordinator._update_loop(tick_two)

    assert vwc_coordinator.shot_composition_payload()["infiltration"] == "unknown"


def test_shot_composition_payload_surfaces_suppression_reason(
    vwc_coordinator, mock_growspace
) -> None:
    """Applying a verdict publishes its suppression reason, and clears it again."""
    strategy = mock_growspace.irrigation_strategy

    vwc_coordinator._apply_verdict(
        _suppressed_verdict(SUPPRESSED_BY_COOLDOWN), strategy
    )
    assert vwc_coordinator.shot_composition_payload()["suppressed_by"] == "cooldown"

    vwc_coordinator._apply_verdict(_suppressed_verdict(None), strategy)
    assert vwc_coordinator.shot_composition_payload()["suppressed_by"] is None


def _logbook_messages(mock_hass: MagicMock) -> list[str]:
    """Return the messages of every growspace logbook event fired so far."""
    return [
        call.args[1]["message"]
        for call in mock_hass.bus.async_fire.call_args_list
        if call.args[0] == EVENT_GROWSPACE_LOG_ENTRY
    ]


async def _drive_hold_and_release(
    coordinator: VWCIrrigationCoordinator, mock_hass: MagicMock
) -> None:
    """Drive the real minute loop through a sustained hold and its release.

    The first two ticks sit inside the 15 min cooldown and build the rising
    measurement; the third clears the cooldown and is held by the gate (well
    inside the 45 min backstop); the flat fourth settles the substrate and
    releases it. Only that last tick fires a pump cycle.
    """
    mock_hass.bus = MagicMock()
    coordinator._last_cycle_timestamp = datetime(
        2023, 1, 1, 9, 25, 0, tzinfo=dt_util.UTC
    ).isoformat()

    for minute, vwc in ((30, "40.0"), (35, "44.0"), (40, "48.0"), (45, "40.0")):
        tick = datetime(2023, 1, 1, 9, minute, 0, tzinfo=dt_util.UTC)
        mock_hass.states.get.return_value = _state(vwc, last_updated=tick)
        with patch(
            "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
            return_value=tick,
        ):
            await coordinator._update_loop(tick)
    await await_pump_task()


async def test_the_gate_logs_one_held_and_one_released_entry(
    vwc_coordinator, mock_hass
) -> None:
    """A hold sustained across ticks is one logbook entry, and its release is one more."""
    await _drive_hold_and_release(vwc_coordinator, mock_hass)

    messages = _logbook_messages(mock_hass)
    assert messages.count(INFILTRATION_HELD_MESSAGE) == 1
    assert messages.count(INFILTRATION_RELEASED_MESSAGE) == 1
    assert messages.index(INFILTRATION_HELD_MESSAGE) < messages.index(
        INFILTRATION_RELEASED_MESSAGE
    )


async def test_the_gate_writes_no_logbook_entries_when_logging_is_off(
    vwc_coordinator, mock_hass, mock_growspace
) -> None:
    """Both edges respect log_to_logbook, like every other steering write."""
    mock_growspace.irrigation_config.log_to_logbook = False

    await _drive_hold_and_release(vwc_coordinator, mock_hass)

    messages = _logbook_messages(mock_hass)
    assert INFILTRATION_HELD_MESSAGE not in messages
    assert INFILTRATION_RELEASED_MESSAGE not in messages
