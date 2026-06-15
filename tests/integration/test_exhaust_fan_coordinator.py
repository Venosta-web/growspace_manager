"""Integration tests for ExhaustFanCoordinator."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.exhaust_fan_coordinator import (
    ExhaustFanCoordinator,
)
from custom_components.growspace_manager.models import EnvironmentConfig
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
        exhaust_fan_config=fan_cfg,
    )


def _make_coordinator(
    growspace_id: str,
    env_config: EnvironmentConfig,
    plants: list | None = None,
) -> MagicMock:
    coord = MagicMock()
    gs = MagicMock()
    gs.environment_config = env_config
    coord.growspaces = {growspace_id: gs}
    coord.services.growspaces.get_growspace_plants.return_value = plants or []
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
