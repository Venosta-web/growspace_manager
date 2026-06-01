"""Integration tests for CirculationFanCoordinator."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.circulation_fan_coordinator import (
    CirculationFanCoordinator,
)
from custom_components.growspace_manager.const import FanRegulationMode
from custom_components.growspace_manager.models import EnvironmentConfig
from custom_components.growspace_manager.models.growspace import CirculationFanConfig
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant


@pytest.fixture
def mock_hass() -> MagicMock:
    """Return mock HomeAssistant."""
    hass = MagicMock(spec=HomeAssistant)
    hass.states = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()

    def _create_task(coro):
        if hasattr(coro, "close"):
            coro.close()
        return MagicMock()

    hass.async_create_task = MagicMock(side_effect=_create_task)
    return hass


@pytest.fixture
def mock_track_time_interval():
    """Patch async_track_time_interval and capture the registered callback."""
    with patch(
        "custom_components.growspace_manager.circulation_fan_coordinator.async_track_time_interval"
    ) as mock:
        mock.return_value = MagicMock()
        yield mock


def _make_env_config(
    *,
    enabled: bool = True,
    mode: FanRegulationMode = FanRegulationMode.HUMIDITY,
    humidity_sensors: list[str] | None = None,
    temperature_sensors: list[str] | None = None,
    circulation_fan_entities: list[str] | None = None,
    humidity_target: float = 60.0,
    humidity_tolerance: float = 5.0,
    temperature_target: float = 25.0,
    temperature_tolerance: float = 2.0,
    min_speed: int = 10,
    max_speed: int = 90,
) -> EnvironmentConfig:
    fan_cfg = CirculationFanConfig(
        enabled=enabled,
        regulation_mode=mode,
        humidity_target=humidity_target,
        humidity_tolerance=humidity_tolerance,
        temperature_target=temperature_target,
        temperature_tolerance=temperature_tolerance,
        min_speed=min_speed,
        max_speed=max_speed,
    )
    return EnvironmentConfig(
        humidity_sensors=humidity_sensors if humidity_sensors is not None else ["sensor.humidity"],
        temperature_sensors=temperature_sensors if temperature_sensors is not None else ["sensor.temperature"],
        circulation_fan_entities=circulation_fan_entities if circulation_fan_entities is not None else ["fan.circ"],
        circulation_fan_config=fan_cfg,
    )


def _make_growspace(env_config: EnvironmentConfig) -> MagicMock:
    gs = MagicMock()
    gs.environment_config = env_config
    return gs


def _make_coordinator(
    growspace_id: str, env_config: EnvironmentConfig
) -> MagicMock:
    coord = MagicMock()
    coord.growspaces = {growspace_id: _make_growspace(env_config)}
    return coord


# ---------------------------------------------------------------------------
# async_setup / lifecycle
# ---------------------------------------------------------------------------


async def test_async_setup_starts_tick_when_enabled(
    mock_hass: MagicMock,
    mock_track_time_interval: MagicMock,
) -> None:
    """Coordinator registers a 10-second interval when enabled with fan entities."""
    env = _make_env_config()
    main_coord = _make_coordinator("gs1", env)

    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)
    await coord.async_setup()

    mock_track_time_interval.assert_called_once()
    args = mock_track_time_interval.call_args
    from datetime import timedelta

    assert args[0][2] == timedelta(seconds=10)


async def test_async_setup_skips_when_disabled(
    mock_hass: MagicMock,
    mock_track_time_interval: MagicMock,
) -> None:
    """Coordinator does not register a tick when enabled=False."""
    env = _make_env_config(enabled=False)
    main_coord = _make_coordinator("gs1", env)

    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)
    await coord.async_setup()

    mock_track_time_interval.assert_not_called()


async def test_async_setup_skips_when_no_fan_entities(
    mock_hass: MagicMock,
    mock_track_time_interval: MagicMock,
) -> None:
    """Coordinator does not register a tick when circulation_fan_entities is empty."""
    env = _make_env_config(circulation_fan_entities=[])
    main_coord = _make_coordinator("gs1", env)

    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)
    await coord.async_setup()

    mock_track_time_interval.assert_not_called()


async def test_unload_cancels_tick(
    mock_hass: MagicMock,
    mock_track_time_interval: MagicMock,
) -> None:
    """unload() cancels the interval listener."""
    env = _make_env_config()
    main_coord = _make_coordinator("gs1", env)

    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)
    await coord.async_setup()

    cancel_mock = mock_track_time_interval.return_value
    coord.unload()

    cancel_mock.assert_called_once()
    assert coord._remove_tick is None


# ---------------------------------------------------------------------------
# Humidity mode
# ---------------------------------------------------------------------------


async def test_humidity_mode_below_band_sets_min_speed(
    mock_hass: MagicMock,
) -> None:
    """Humidity below (target - tolerance) → fan.set_percentage called with min_speed."""
    env = _make_env_config(
        mode=FanRegulationMode.HUMIDITY,
        humidity_target=60.0,
        humidity_tolerance=5.0,
        min_speed=10,
        max_speed=90,
    )
    mock_hass.states.get.return_value = MagicMock(state="50.0")
    main_coord = _make_coordinator("gs1", env)
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)

    await coord._async_regulate()

    mock_hass.services.async_call.assert_awaited_once_with(
        "fan",
        "set_percentage",
        {ATTR_ENTITY_ID: "fan.circ", "percentage": 10},
        blocking=False,
    )


async def test_humidity_mode_above_band_sets_max_speed(
    mock_hass: MagicMock,
) -> None:
    """Humidity above (target + tolerance) → fan.set_percentage called with max_speed."""
    env = _make_env_config(
        mode=FanRegulationMode.HUMIDITY,
        humidity_target=60.0,
        humidity_tolerance=5.0,
        min_speed=10,
        max_speed=90,
    )
    mock_hass.states.get.return_value = MagicMock(state="70.0")
    main_coord = _make_coordinator("gs1", env)
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)

    await coord._async_regulate()

    mock_hass.services.async_call.assert_awaited_once_with(
        "fan",
        "set_percentage",
        {ATTR_ENTITY_ID: "fan.circ", "percentage": 90},
        blocking=False,
    )


async def test_humidity_mode_in_band_interpolates_speed(
    mock_hass: MagicMock,
) -> None:
    """Humidity at midpoint of band → interpolated speed."""
    env = _make_env_config(
        mode=FanRegulationMode.HUMIDITY,
        humidity_target=60.0,
        humidity_tolerance=5.0,
        min_speed=0,
        max_speed=100,
    )
    mock_hass.states.get.return_value = MagicMock(state="60.0")
    main_coord = _make_coordinator("gs1", env)
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)

    await coord._async_regulate()

    mock_hass.services.async_call.assert_awaited_once_with(
        "fan",
        "set_percentage",
        {ATTR_ENTITY_ID: "fan.circ", "percentage": 50},
        blocking=False,
    )


# ---------------------------------------------------------------------------
# Temperature mode
# ---------------------------------------------------------------------------


async def test_temperature_mode_below_band_sets_min_speed(
    mock_hass: MagicMock,
) -> None:
    """Temperature below (target - tolerance) → min_speed."""
    env = _make_env_config(
        mode=FanRegulationMode.TEMPERATURE,
        temperature_target=25.0,
        temperature_tolerance=2.0,
        min_speed=20,
        max_speed=80,
    )
    mock_hass.states.get.return_value = MagicMock(state="22.0")
    main_coord = _make_coordinator("gs1", env)
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)

    await coord._async_regulate()

    mock_hass.services.async_call.assert_awaited_once_with(
        "fan",
        "set_percentage",
        {ATTR_ENTITY_ID: "fan.circ", "percentage": 20},
        blocking=False,
    )


async def test_temperature_mode_above_band_sets_max_speed(
    mock_hass: MagicMock,
) -> None:
    """Temperature above (target + tolerance) → max_speed."""
    env = _make_env_config(
        mode=FanRegulationMode.TEMPERATURE,
        temperature_target=25.0,
        temperature_tolerance=2.0,
        min_speed=20,
        max_speed=80,
    )
    mock_hass.states.get.return_value = MagicMock(state="28.0")
    main_coord = _make_coordinator("gs1", env)
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)

    await coord._async_regulate()

    mock_hass.services.async_call.assert_awaited_once_with(
        "fan",
        "set_percentage",
        {ATTR_ENTITY_ID: "fan.circ", "percentage": 80},
        blocking=False,
    )


# ---------------------------------------------------------------------------
# Multiple fan entities
# ---------------------------------------------------------------------------


async def test_all_fan_entities_receive_set_percentage(
    mock_hass: MagicMock,
) -> None:
    """All entities in circulation_fan_entities receive the same fan.set_percentage call."""
    env = _make_env_config(
        mode=FanRegulationMode.HUMIDITY,
        humidity_target=60.0,
        humidity_tolerance=5.0,
        min_speed=0,
        max_speed=100,
        circulation_fan_entities=["fan.circ_1", "fan.circ_2", "fan.circ_3"],
    )
    mock_hass.states.get.return_value = MagicMock(state="65.0")
    main_coord = _make_coordinator("gs1", env)
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)

    await coord._async_regulate()

    assert mock_hass.services.async_call.await_count == 3
    for call in mock_hass.services.async_call.await_args_list:
        assert call[0][0] == "fan"
        assert call[0][1] == "set_percentage"
        assert call[1]["blocking"] is False


# ---------------------------------------------------------------------------
# Missing / unavailable sensor
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sensor_state", [STATE_UNAVAILABLE, STATE_UNKNOWN, "invalid"])
async def test_unavailable_sensor_skips_fan_call(
    mock_hass: MagicMock, sensor_state: str
) -> None:
    """Missing or unavailable sensor → no fan.set_percentage call, no exception."""
    env = _make_env_config(mode=FanRegulationMode.HUMIDITY)
    mock_hass.states.get.return_value = MagicMock(state=sensor_state)
    main_coord = _make_coordinator("gs1", env)
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)

    await coord._async_regulate()

    mock_hass.services.async_call.assert_not_called()


async def test_no_sensor_entities_skips_fan_call(
    mock_hass: MagicMock,
) -> None:
    """No humidity_sensors configured → no fan.set_percentage call."""
    env = _make_env_config(
        mode=FanRegulationMode.HUMIDITY, humidity_sensors=[]
    )
    main_coord = _make_coordinator("gs1", env)
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)

    await coord._async_regulate()

    mock_hass.services.async_call.assert_not_called()


async def test_sensor_state_none_skips_fan_call(
    mock_hass: MagicMock,
) -> None:
    """hass.states.get returning None → no fan.set_percentage call."""
    env = _make_env_config(mode=FanRegulationMode.HUMIDITY)
    mock_hass.states.get.return_value = None
    main_coord = _make_coordinator("gs1", env)
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)

    await coord._async_regulate()

    mock_hass.services.async_call.assert_not_called()


# ---------------------------------------------------------------------------
# enabled=False
# ---------------------------------------------------------------------------


async def test_disabled_coordinator_skips_fan_call(
    mock_hass: MagicMock,
) -> None:
    """enabled=False → no fan.set_percentage call even if sensor is valid."""
    env = _make_env_config(enabled=False)
    mock_hass.states.get.return_value = MagicMock(state="70.0")
    main_coord = _make_coordinator("gs1", env)
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)

    await coord._async_regulate()

    mock_hass.services.async_call.assert_not_called()


# ---------------------------------------------------------------------------
# Missing growspace
# ---------------------------------------------------------------------------


async def test_missing_growspace_does_not_raise(
    mock_hass: MagicMock,
    mock_track_time_interval: MagicMock,
) -> None:
    """Constructor with unknown growspace_id logs an error but does not raise."""
    main_coord = MagicMock()
    main_coord.growspaces = {}

    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "nonexistent", main_coord)
    await coord.async_setup()

    mock_track_time_interval.assert_not_called()
