"""Integration tests for ExhaustFanCoordinator."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.exhaust_fan_coordinator import (
    ExhaustFanCoordinator,
)
from custom_components.growspace_manager.models import (
    ACInfinityDevice,
    EnvironmentConfig,
)
from custom_components.growspace_manager.models.growspace import ExhaustFanConfig
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant


@pytest.fixture
def mock_hass() -> MagicMock:
    """Return mock HomeAssistant."""
    hass = MagicMock(spec=HomeAssistant)
    hass.states = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    return hass


@pytest.fixture
def mock_track_time_interval():
    """Patch async_track_time_interval and capture the registered callback."""
    with patch(
        "custom_components.growspace_manager.exhaust_fan_coordinator.async_track_time_interval"
    ) as mock:
        mock.return_value = MagicMock()
        yield mock


def _make_env_config(
    *,
    enabled: bool = True,
    temperature_sensors: list[str] | None = None,
    humidity_sensors: list[str] | None = None,
    vpd_sensors: list[str] | None = None,
    light_sensors: list[str] | None = None,
    exhaust_fan_entities: list[str] | None = None,
    exhaust_fan_ac_infinity_devices: list[ACInfinityDevice] | None = None,
    temperature_target: float = 25.0,
    temperature_tolerance: float = 2.0,
    humidity_target: float = 60.0,
    humidity_tolerance: float = 5.0,
    vpd_target: float = 1.0,
    vpd_tolerance: float = 0.2,
    min_speed: int = 10,
    max_speed: int = 90,
    stage_vpd_enabled: bool = False,
    stage_vpd_overrides: dict[str, dict[str, float]] | None = None,
    critical_temp_low: float | None = None,
    critical_temp_high: float | None = None,
    critical_temp_hysteresis: float = 1.0,
) -> EnvironmentConfig:
    fan_cfg = ExhaustFanConfig(
        enabled=enabled,
        min_speed=min_speed,
        max_speed=max_speed,
        temperature_target=temperature_target,
        temperature_tolerance=temperature_tolerance,
        humidity_target=humidity_target,
        humidity_tolerance=humidity_tolerance,
        vpd_target=vpd_target,
        vpd_tolerance=vpd_tolerance,
        stage_vpd_enabled=stage_vpd_enabled,
        stage_vpd_overrides=stage_vpd_overrides or {},
        critical_temp_low=critical_temp_low,
        critical_temp_high=critical_temp_high,
        critical_temp_hysteresis=critical_temp_hysteresis,
    )
    return EnvironmentConfig(
        temperature_sensors=temperature_sensors
        if temperature_sensors is not None
        else ["sensor.temperature"],
        humidity_sensors=humidity_sensors
        if humidity_sensors is not None
        else ["sensor.humidity"],
        vpd_sensors=vpd_sensors if vpd_sensors is not None else ["sensor.vpd"],
        light_sensors=light_sensors if light_sensors is not None else [],
        exhaust_fan_entities=exhaust_fan_entities
        if exhaust_fan_entities is not None
        else ["fan.exhaust"],
        exhaust_fan_ac_infinity_devices=exhaust_fan_ac_infinity_devices or [],
        exhaust_fan_config=fan_cfg,
    )


def _make_coordinator(
    growspace_id: str,
    env_config: EnvironmentConfig,
    plants: list | None = None,
    global_settings: dict | None = None,
) -> MagicMock:
    coord = MagicMock()
    gs = MagicMock()
    gs.environment_config = env_config
    coord.growspaces = {growspace_id: gs}
    coord.services.growspaces.get_growspace_plants.return_value = plants or []
    coord.options = {"global_settings": global_settings or {}}
    return coord


def _state(value: str) -> MagicMock:
    state = MagicMock()
    state.state = value
    return state


def _states_from(mapping: dict[str, str]):
    def _get(entity_id: str):
        if entity_id in mapping:
            return _state(mapping[entity_id])
        return None

    return _get


# ---------------------------------------------------------------------------
# async_setup / lifecycle
# ---------------------------------------------------------------------------


async def test_async_setup_starts_tick_when_enabled(
    mock_hass: MagicMock, mock_track_time_interval: MagicMock
) -> None:
    """Enabled config with exhaust entities starts the polling tick."""
    env = _make_env_config(enabled=True)
    coord = ExhaustFanCoordinator(
        mock_hass, MagicMock(), "gs1", _make_coordinator("gs1", env)
    )
    await coord.async_setup()
    mock_track_time_interval.assert_called_once()


async def test_async_setup_skips_when_disabled(
    mock_hass: MagicMock, mock_track_time_interval: MagicMock
) -> None:
    """Disabled config does not start the tick."""
    env = _make_env_config(enabled=False)
    coord = ExhaustFanCoordinator(
        mock_hass, MagicMock(), "gs1", _make_coordinator("gs1", env)
    )
    await coord.async_setup()
    mock_track_time_interval.assert_not_called()


async def test_async_setup_skips_when_no_exhaust_entities(
    mock_hass: MagicMock, mock_track_time_interval: MagicMock
) -> None:
    """No exhaust entities configured → tick is not started."""
    env = _make_env_config(enabled=True, exhaust_fan_entities=[])
    coord = ExhaustFanCoordinator(
        mock_hass, MagicMock(), "gs1", _make_coordinator("gs1", env)
    )
    await coord.async_setup()
    mock_track_time_interval.assert_not_called()


async def test_unload_cancels_tick(
    mock_hass: MagicMock, mock_track_time_interval: MagicMock
) -> None:
    """Unload cancels the registered tick."""
    cancel_mock = MagicMock()
    mock_track_time_interval.return_value = cancel_mock
    env = _make_env_config(enabled=True)
    coord = ExhaustFanCoordinator(
        mock_hass, MagicMock(), "gs1", _make_coordinator("gs1", env)
    )
    await coord.async_setup()
    coord.unload()
    cancel_mock.assert_called_once()
    assert coord._remove_tick is None


async def test_async_restart_restarts_tick(
    mock_hass: MagicMock, mock_track_time_interval: MagicMock
) -> None:
    """Restart stops then starts the tick again under the new config."""
    cancel_mock = MagicMock()
    mock_track_time_interval.return_value = cancel_mock
    env = _make_env_config(enabled=True)
    coord = ExhaustFanCoordinator(
        mock_hass, MagicMock(), "gs1", _make_coordinator("gs1", env)
    )
    await coord.async_setup()
    await coord.async_restart()
    cancel_mock.assert_called_once()
    assert mock_track_time_interval.call_count == 2


# ---------------------------------------------------------------------------
# Combined demand + dispatch
# ---------------------------------------------------------------------------


async def test_fan_entity_driven_by_percentage(mock_hass: MagicMock) -> None:
    """A fan entity receives the combined demand as a percentage."""
    env = _make_env_config(exhaust_fan_entities=["fan.exhaust"])
    mock_hass.states.get.side_effect = _states_from(
        {
            "sensor.temperature": "30.0",  # hot → temp term = max_speed (90)
            "sensor.humidity": "60.0",
            "sensor.vpd": "1.0",
        }
    )
    coord = ExhaustFanCoordinator(
        mock_hass, MagicMock(), "gs1", _make_coordinator("gs1", env)
    )
    await coord._async_regulate()
    mock_hass.services.async_call.assert_awaited_once_with(
        "fan",
        "set_percentage",
        {ATTR_ENTITY_ID: "fan.exhaust", "percentage": 90},
        blocking=False,
    )


async def test_switch_entity_turned_on_above_min_speed(mock_hass: MagicMock) -> None:
    """A switch device is turned on when demand exceeds min_speed."""
    env = _make_env_config(exhaust_fan_entities=["switch.exhaust"])
    mock_hass.states.get.side_effect = _states_from(
        {
            "sensor.temperature": "30.0",  # demand = 90 > min_speed (10)
            "sensor.humidity": "60.0",
            "sensor.vpd": "1.0",
        }
    )
    coord = ExhaustFanCoordinator(
        mock_hass, MagicMock(), "gs1", _make_coordinator("gs1", env)
    )
    await coord._async_regulate()
    mock_hass.services.async_call.assert_awaited_once_with(
        "switch",
        "turn_on",
        {ATTR_ENTITY_ID: "switch.exhaust"},
        blocking=False,
    )


async def test_switch_entity_turned_off_at_min_speed(mock_hass: MagicMock) -> None:
    """A switch device is turned off when demand is at the min_speed floor."""
    env = _make_env_config(exhaust_fan_entities=["switch.exhaust"])
    mock_hass.states.get.side_effect = _states_from(
        {
            "sensor.temperature": "20.0",  # cool → temp term = min_speed
            "sensor.humidity": "50.0",  # dry → humidity term = min_speed
            "sensor.vpd": "1.5",  # high vpd → inverted = min_speed
        }
    )
    coord = ExhaustFanCoordinator(
        mock_hass, MagicMock(), "gs1", _make_coordinator("gs1", env)
    )
    await coord._async_regulate()
    mock_hass.services.async_call.assert_awaited_once_with(
        "switch",
        "turn_off",
        {ATTR_ENTITY_ID: "switch.exhaust"},
        blocking=False,
    )


async def test_input_boolean_entity_turned_on_above_min_speed(
    mock_hass: MagicMock,
) -> None:
    """An input_boolean device is driven on/off like a switch."""
    env = _make_env_config(exhaust_fan_entities=["input_boolean.exhaust"])
    mock_hass.states.get.side_effect = _states_from(
        {
            "sensor.temperature": "30.0",
            "sensor.humidity": "60.0",
            "sensor.vpd": "1.0",
        }
    )
    coord = ExhaustFanCoordinator(
        mock_hass, MagicMock(), "gs1", _make_coordinator("gs1", env)
    )
    await coord._async_regulate()
    mock_hass.services.async_call.assert_awaited_once_with(
        "input_boolean",
        "turn_on",
        {ATTR_ENTITY_ID: "input_boolean.exhaust"},
        blocking=False,
    )


async def test_no_sensor_readings_skips_dispatch(mock_hass: MagicMock) -> None:
    """All sensors unavailable → no service call, no exception."""
    env = _make_env_config()
    mock_hass.states.get.side_effect = _states_from(
        {
            "sensor.temperature": STATE_UNAVAILABLE,
            "sensor.humidity": STATE_UNAVAILABLE,
            "sensor.vpd": STATE_UNAVAILABLE,
        }
    )
    coord = ExhaustFanCoordinator(
        mock_hass, MagicMock(), "gs1", _make_coordinator("gs1", env)
    )
    await coord._async_regulate()
    mock_hass.services.async_call.assert_not_called()


async def test_disabled_config_skips_dispatch(mock_hass: MagicMock) -> None:
    """A disabled controller does nothing even if regulate is invoked."""
    env = _make_env_config(enabled=False)
    mock_hass.states.get.side_effect = _states_from(
        {"sensor.temperature": "30.0", "sensor.humidity": "60.0", "sensor.vpd": "1.0"}
    )
    coord = ExhaustFanCoordinator(
        mock_hass, MagicMock(), "gs1", _make_coordinator("gs1", env)
    )
    await coord._async_regulate()
    mock_hass.services.async_call.assert_not_called()


async def test_all_exhaust_entities_receive_dispatch(mock_hass: MagicMock) -> None:
    """Every configured exhaust entity is driven, dispatched by its domain."""
    env = _make_env_config(exhaust_fan_entities=["fan.exhaust", "switch.damper"])
    mock_hass.states.get.side_effect = _states_from(
        {"sensor.temperature": "30.0", "sensor.humidity": "60.0", "sensor.vpd": "1.0"}
    )
    coord = ExhaustFanCoordinator(
        mock_hass, MagicMock(), "gs1", _make_coordinator("gs1", env)
    )
    await coord._async_regulate()
    assert mock_hass.services.async_call.await_count == 2
    domains = {call[0][0] for call in mock_hass.services.async_call.await_args_list}
    assert domains == {"fan", "switch"}


# ---------------------------------------------------------------------------
# Stage-aware VPD
# ---------------------------------------------------------------------------


async def test_stage_vpd_enabled_uses_stage_target(mock_hass: MagicMock) -> None:
    """With stage_vpd_enabled, the VPD term uses the resolved stage target.

    flower_late day target is 1.25; a VPD reading of 1.25 sits exactly at the
    inverted-VPD midpoint → demand of 50 (between min 10 and max 90).
    """
    env = _make_env_config(
        stage_vpd_enabled=True,
        exhaust_fan_entities=["fan.exhaust"],
        # Keep temp/humidity terms at the floor so VPD dominates.
        temperature_target=25.0,
        humidity_target=60.0,
    )
    mock_hass.states.get.side_effect = _states_from(
        {
            "sensor.temperature": "20.0",  # min term
            "sensor.humidity": "50.0",  # min term
            "sensor.vpd": "1.25",  # at flower_late day target → inverted midpoint
        }
    )
    coord = ExhaustFanCoordinator(
        mock_hass,
        MagicMock(),
        "gs1",
        _make_coordinator("gs1", env, plants=[MagicMock()]),
    )
    with patch(
        "custom_components.growspace_manager.exhaust_fan_coordinator.resolve_stage_vpd_target",
        return_value=1.25,
    ) as mock_resolve:
        await coord._async_regulate()

    mock_resolve.assert_called_once()
    mock_hass.services.async_call.assert_awaited_once_with(
        "fan",
        "set_percentage",
        {ATTR_ENTITY_ID: "fan.exhaust", "percentage": 50},
        blocking=False,
    )


# ---------------------------------------------------------------------------
# Source-air gate
# ---------------------------------------------------------------------------

_LUNG_GLOBAL_SETTINGS = {
    "lung_room_temp_sensor": "sensor.lung_temp",
    "lung_room_humidity_sensor": "sensor.lung_hum",
}


async def test_source_air_gate_suppresses_cooling_when_source_air_too_warm(
    mock_hass: MagicMock,
) -> None:
    """A hot tent stays off when the lung-room air is no cooler than the tent.

    The temperature term would drive the switch on, but source air at tent
    temperature cannot cool, so that term is dropped. Humidity/VPD sit at the
    floor (and the source air is dry enough not to gate them), leaving demand at
    min_speed → the device is turned off.
    """
    env = _make_env_config(exhaust_fan_entities=["switch.exhaust"])
    mock_hass.states.get.side_effect = _states_from(
        {
            "sensor.temperature": "30.0",  # hot tent → temp term = max_speed
            "sensor.humidity": "50.0",  # dry → floor
            "sensor.vpd": "1.5",  # above band → inverted floor
            "sensor.lung_temp": "30.0",  # source air not cooler than tent
            "sensor.lung_hum": "76.0",  # source VPD ~1.02 → moisture NOT gated
        }
    )
    coord = ExhaustFanCoordinator(
        mock_hass,
        MagicMock(),
        "gs1",
        _make_coordinator("gs1", env, global_settings=_LUNG_GLOBAL_SETTINGS),
    )
    await coord._async_regulate()
    mock_hass.services.async_call.assert_awaited_once_with(
        "switch",
        "turn_off",
        {ATTR_ENTITY_ID: "switch.exhaust"},
        blocking=False,
    )


async def test_source_air_gate_inert_with_no_lung_room_sensor(
    mock_hass: MagicMock,
) -> None:
    """With no lung-room sensor configured the demand is ungated (current behavior)."""
    env = _make_env_config(exhaust_fan_entities=["switch.exhaust"])
    mock_hass.states.get.side_effect = _states_from(
        {
            "sensor.temperature": "30.0",  # hot tent → temp term = max_speed
            "sensor.humidity": "50.0",
            "sensor.vpd": "1.5",
        }
    )
    coord = ExhaustFanCoordinator(
        mock_hass,
        MagicMock(),
        "gs1",
        _make_coordinator("gs1", env, global_settings={}),
    )
    await coord._async_regulate()
    mock_hass.services.async_call.assert_awaited_once_with(
        "switch",
        "turn_on",
        {ATTR_ENTITY_ID: "switch.exhaust"},
        blocking=False,
    )


async def test_source_air_gate_suppresses_dehumidify_when_source_air_not_drier(
    mock_hass: MagicMock,
) -> None:
    """A humid tent is turned off when the lung-room air is not drier than it.

    Only humidity/VPD would drive the fan (no temperature sensor), but the
    source air is wetter (its VPD is further from target), so both moisture
    terms are dropped. Readings exist, so suppressed demand drives the switch
    to min_speed (off) rather than leaving it running.
    """
    env = _make_env_config(
        temperature_sensors=[],  # isolate the moisture terms
        exhaust_fan_entities=["switch.exhaust"],
    )
    mock_hass.states.get.side_effect = _states_from(
        {
            "sensor.humidity": "70.0",  # humid → humidity term = max_speed
            "sensor.vpd": "0.5",  # too humid → inverted term = max_speed
            "sensor.lung_temp": "25.0",
            "sensor.lung_hum": "95.0",  # source VPD ~0.16 → not drier than tent
        }
    )
    coord = ExhaustFanCoordinator(
        mock_hass,
        MagicMock(),
        "gs1",
        _make_coordinator("gs1", env, global_settings=_LUNG_GLOBAL_SETTINGS),
    )
    await coord._async_regulate()
    mock_hass.services.async_call.assert_awaited_once_with(
        "switch",
        "turn_off",
        {ATTR_ENTITY_ID: "switch.exhaust"},
        blocking=False,
    )


# ---------------------------------------------------------------------------
# Critical-temperature safety override
# ---------------------------------------------------------------------------


async def test_high_temp_breach_forces_max_speed_bypassing_gate(
    mock_hass: MagicMock,
) -> None:
    """A high-temp breach vents at max_speed even when the source-air gate
    has suppressed the cooling demand.

    Source air at tent temperature gates the temperature term (gated demand
    floors at min_speed), but a breach of ``critical_temp_high`` overrides that
    and forces the fan to max_speed — a heat emergency vents regardless of
    whether incoming air is ideal.
    """
    env = _make_env_config(
        exhaust_fan_entities=["fan.exhaust"],
        critical_temp_high=30.0,
    )
    mock_hass.states.get.side_effect = _states_from(
        {
            "sensor.temperature": "35.0",  # breaches critical_temp_high (30)
            "sensor.humidity": "50.0",
            "sensor.vpd": "1.5",
            "sensor.lung_temp": "35.0",  # not cooler → cooling term gated
            "sensor.lung_hum": "50.0",
        }
    )
    coord = ExhaustFanCoordinator(
        mock_hass,
        MagicMock(),
        "gs1",
        _make_coordinator("gs1", env, global_settings=_LUNG_GLOBAL_SETTINGS),
    )
    await coord._async_regulate()
    mock_hass.services.async_call.assert_awaited_once_with(
        "fan",
        "set_percentage",
        {ATTR_ENTITY_ID: "fan.exhaust", "percentage": 90},  # max_speed
        blocking=False,
    )


async def test_low_temp_breach_forces_min_speed_over_humidity_demand(
    mock_hass: MagicMock,
) -> None:
    """A low-temp breach forces min_speed even against a high humidity demand.

    Humid air would normally drive the fan to max_speed, but a breach of
    ``critical_temp_low`` forces min_speed (switch off): cold air holds little
    moisture and chill protection takes precedence over venting.
    """
    env = _make_env_config(
        exhaust_fan_entities=["switch.exhaust"],
        critical_temp_low=15.0,
    )
    mock_hass.states.get.side_effect = _states_from(
        {
            "sensor.temperature": "10.0",  # breaches critical_temp_low (15)
            "sensor.humidity": "80.0",  # humid → demand would be max_speed
            "sensor.vpd": "1.0",
        }
    )
    coord = ExhaustFanCoordinator(
        mock_hass, MagicMock(), "gs1", _make_coordinator("gs1", env)
    )
    await coord._async_regulate()
    mock_hass.services.async_call.assert_awaited_once_with(
        "switch",
        "turn_off",  # forced to min_speed → off
        {ATTR_ENTITY_ID: "switch.exhaust"},
        blocking=False,
    )


async def test_high_temp_override_latches_until_hysteresis_release(
    mock_hass: MagicMock,
) -> None:
    """The high-temp override latches at max_speed and releases per hysteresis.

    Demand is parked at the floor (unreachable temperature target) so only the
    latch holds the fan at max. With critical_temp_high=30 and hysteresis=2 the
    override releases only once temperature drops to 28 (30 − 2).
    """
    env = _make_env_config(
        exhaust_fan_entities=["fan.exhaust"],
        temperature_target=100.0,  # park the temp term at the floor
        temperature_tolerance=2.0,
        critical_temp_high=30.0,
        critical_temp_hysteresis=2.0,
    )
    coord = ExhaustFanCoordinator(
        mock_hass, MagicMock(), "gs1", _make_coordinator("gs1", env)
    )

    def _percentage_of_last_call() -> int:
        return mock_hass.services.async_call.await_args[0][2]["percentage"]

    # Tick 1: breach → latch at max_speed.
    mock_hass.states.get.side_effect = _states_from(
        {"sensor.temperature": "31.0", "sensor.humidity": "50.0", "sensor.vpd": "1.5"}
    )
    await coord._async_regulate()
    assert _percentage_of_last_call() == 90

    # Tick 2: temperature falls inside the hysteresis band → still latched.
    mock_hass.states.get.side_effect = _states_from(
        {"sensor.temperature": "29.0", "sensor.humidity": "50.0", "sensor.vpd": "1.5"}
    )
    await coord._async_regulate()
    assert _percentage_of_last_call() == 90

    # Tick 3: temperature reaches the release point (30 − 2) → demand floors.
    mock_hass.states.get.side_effect = _states_from(
        {"sensor.temperature": "28.0", "sensor.humidity": "50.0", "sensor.vpd": "1.5"}
    )
    await coord._async_regulate()
    assert _percentage_of_last_call() == 10


async def test_no_breach_passes_gated_demand_through(mock_hass: MagicMock) -> None:
    """With critical temps configured but unbreached, the gated demand wins.

    A hot tent (temp term = max_speed) within the critical bounds is dispatched
    as-is — the override neither forces nor suppresses anything.
    """
    env = _make_env_config(
        exhaust_fan_entities=["fan.exhaust"],
        critical_temp_low=10.0,
        critical_temp_high=40.0,
    )
    mock_hass.states.get.side_effect = _states_from(
        {
            "sensor.temperature": "35.0",  # hot → demand 90, but within [10, 40]
            "sensor.humidity": "60.0",
            "sensor.vpd": "1.0",
        }
    )
    coord = ExhaustFanCoordinator(
        mock_hass, MagicMock(), "gs1", _make_coordinator("gs1", env)
    )
    await coord._async_regulate()
    mock_hass.services.async_call.assert_awaited_once_with(
        "fan",
        "set_percentage",
        {ATTR_ENTITY_ID: "fan.exhaust", "percentage": 90},
        blocking=False,
    )


async def test_override_inert_when_temp_unavailable(mock_hass: MagicMock) -> None:
    """Critical temps configured but the temp sensor is unavailable → no override.

    The override cannot evaluate a breach without a reading, so the gated demand
    (here humidity-driven) passes through unchanged rather than being forced.
    """
    env = _make_env_config(
        exhaust_fan_entities=["switch.exhaust"],
        critical_temp_high=30.0,
    )
    mock_hass.states.get.side_effect = _states_from(
        {
            "sensor.temperature": STATE_UNAVAILABLE,
            "sensor.humidity": "80.0",  # humid → demand = max_speed
            "sensor.vpd": "1.0",
        }
    )
    coord = ExhaustFanCoordinator(
        mock_hass, MagicMock(), "gs1", _make_coordinator("gs1", env)
    )
    await coord._async_regulate()
    mock_hass.services.async_call.assert_awaited_once_with(
        "switch",
        "turn_on",
        {ATTR_ENTITY_ID: "switch.exhaust"},
        blocking=False,
    )


# ---------------------------------------------------------------------------
# AC Infinity exhaust devices (ADR-0022)
# ---------------------------------------------------------------------------


async def test_ac_infinity_device_driven_by_mode_and_intensity(
    mock_hass: MagicMock,
) -> None:
    """An AC Infinity exhaust port is driven via its mode select and speed number."""
    env = _make_env_config(
        exhaust_fan_entities=[],
        exhaust_fan_ac_infinity_devices=[
            ACInfinityDevice(
                mode_entity="select.tent_port1_mode",
                speed_entity="number.tent_port1_on_speed",
            )
        ],
    )
    mock_hass.states.get.side_effect = _states_from(
        {
            "sensor.temperature": "30.0",  # hot → demand = max_speed (90)
            "sensor.humidity": "60.0",
            "sensor.vpd": "1.0",
        }
    )
    coord = ExhaustFanCoordinator(
        mock_hass, MagicMock(), "gs1", _make_coordinator("gs1", env)
    )
    await coord._async_regulate()
    mock_hass.services.async_call.assert_any_await(
        "select",
        "select_option",
        {ATTR_ENTITY_ID: "select.tent_port1_mode", "option": "On"},
        blocking=False,
    )
    mock_hass.services.async_call.assert_any_await(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: "number.tent_port1_on_speed", "value": 9},
        blocking=False,
    )
    assert mock_hass.services.async_call.await_count == 2


async def test_ac_infinity_and_plain_entities_both_dispatched(
    mock_hass: MagicMock,
) -> None:
    """Plain entities and AC Infinity bundles for the exhaust role are all driven."""
    env = _make_env_config(
        exhaust_fan_entities=["fan.exhaust"],
        exhaust_fan_ac_infinity_devices=[
            ACInfinityDevice(
                mode_entity="select.tent_port1_mode",
                speed_entity="number.tent_port1_on_speed",
            )
        ],
    )
    mock_hass.states.get.side_effect = _states_from(
        {
            "sensor.temperature": "30.0",
            "sensor.humidity": "60.0",
            "sensor.vpd": "1.0",
        }
    )
    coord = ExhaustFanCoordinator(
        mock_hass, MagicMock(), "gs1", _make_coordinator("gs1", env)
    )
    await coord._async_regulate()
    domains = {call[0][0] for call in mock_hass.services.async_call.await_args_list}
    assert domains == {"fan", "select", "number"}


async def test_async_setup_starts_tick_for_ac_infinity_only(
    mock_hass: MagicMock, mock_track_time_interval: MagicMock
) -> None:
    """A growspace with only AC Infinity exhaust devices still starts the tick."""
    env = _make_env_config(
        enabled=True,
        exhaust_fan_entities=[],
        exhaust_fan_ac_infinity_devices=[
            ACInfinityDevice(
                mode_entity="select.tent_port1_mode",
                speed_entity="number.tent_port1_on_speed",
            )
        ],
    )
    coord = ExhaustFanCoordinator(
        mock_hass, MagicMock(), "gs1", _make_coordinator("gs1", env)
    )
    await coord.async_setup()
    mock_track_time_interval.assert_called_once()
