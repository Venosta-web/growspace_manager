"""Integration tests for CirculationFanCoordinator."""

from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest
import time as time_module

from custom_components.growspace_manager.circulation_fan_coordinator import (
    FAN_VPD_STAGE_DEFAULTS,
    CirculationFanCoordinator,
)
from custom_components.growspace_manager.const import FanRegulationMode, PlantStage
from custom_components.growspace_manager.models import EnvironmentConfig
from custom_components.growspace_manager.models.growspace import CirculationFanConfig
from homeassistant.const import ATTR_ENTITY_ID, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
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
    vpd_sensors: list[str] | None = None,
    light_sensors: list[str] | None = None,
    circulation_fan_entities: list[str] | None = None,
    humidity_target: float = 60.0,
    humidity_tolerance: float = 5.0,
    temperature_target: float = 25.0,
    temperature_tolerance: float = 2.0,
    vpd_target: float = 1.0,
    vpd_tolerance: float = 0.2,
    critical_temp_low: float | None = None,
    critical_temp_high: float | None = None,
    critical_temp_hysteresis: float = 1.0,
    min_speed: int = 10,
    max_speed: int = 90,
    wind_enabled: bool = False,
    wind_period_seconds: int = 60,
    wind_amplitude_pct: int = 10,
    stage_vpd_enabled: bool = False,
    stage_vpd_overrides: dict[str, dict[str, float]] | None = None,
) -> EnvironmentConfig:
    fan_cfg = CirculationFanConfig(
        enabled=enabled,
        regulation_mode=mode,
        humidity_target=humidity_target,
        humidity_tolerance=humidity_tolerance,
        temperature_target=temperature_target,
        temperature_tolerance=temperature_tolerance,
        vpd_target=vpd_target,
        vpd_tolerance=vpd_tolerance,
        critical_temp_low=critical_temp_low,
        critical_temp_high=critical_temp_high,
        critical_temp_hysteresis=critical_temp_hysteresis,
        min_speed=min_speed,
        max_speed=max_speed,
        wind_enabled=wind_enabled,
        wind_period_seconds=wind_period_seconds,
        wind_amplitude_pct=wind_amplitude_pct,
        stage_vpd_enabled=stage_vpd_enabled,
        stage_vpd_overrides=stage_vpd_overrides or {},
    )
    return EnvironmentConfig(
        humidity_sensors=humidity_sensors if humidity_sensors is not None else ["sensor.humidity"],
        temperature_sensors=temperature_sensors if temperature_sensors is not None else ["sensor.temperature"],
        vpd_sensors=vpd_sensors if vpd_sensors is not None else ["sensor.vpd"],
        light_sensors=light_sensors if light_sensors is not None else [],
        circulation_fan_entities=circulation_fan_entities if circulation_fan_entities is not None else ["fan.circ"],
        circulation_fan_config=fan_cfg,
    )


def _make_growspace(env_config: EnvironmentConfig) -> MagicMock:
    gs = MagicMock()
    gs.environment_config = env_config
    return gs


def _make_coordinator(
    growspace_id: str,
    env_config: EnvironmentConfig,
    plants: list | None = None,
) -> MagicMock:
    coord = MagicMock()
    coord.growspaces = {growspace_id: _make_growspace(env_config)}
    coord.services.growspaces.get_growspace_plants.return_value = plants or []
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


# ---------------------------------------------------------------------------
# VPD mode — basic regulation
# ---------------------------------------------------------------------------


async def test_vpd_mode_at_midpoint_interpolates_speed(
    mock_hass: MagicMock,
) -> None:
    """VPD at midpoint of band → interpolated speed (tracer bullet)."""
    env = _make_env_config(
        mode=FanRegulationMode.VPD,
        vpd_target=1.0,
        vpd_tolerance=0.2,
        min_speed=0,
        max_speed=100,
    )
    mock_hass.states.get.return_value = MagicMock(state="1.0")
    main_coord = _make_coordinator("gs1", env)
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)

    await coord._async_regulate()

    mock_hass.services.async_call.assert_awaited_once_with(
        "fan",
        "set_percentage",
        {ATTR_ENTITY_ID: "fan.circ", "percentage": 50},
        blocking=False,
    )


async def test_vpd_mode_below_band_sets_min_speed(
    mock_hass: MagicMock,
) -> None:
    """VPD below (target - tolerance) → min_speed."""
    env = _make_env_config(
        mode=FanRegulationMode.VPD,
        vpd_target=1.0,
        vpd_tolerance=0.2,
        min_speed=10,
        max_speed=90,
    )
    mock_hass.states.get.return_value = MagicMock(state="0.5")
    main_coord = _make_coordinator("gs1", env)
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)

    await coord._async_regulate()

    mock_hass.services.async_call.assert_awaited_once_with(
        "fan",
        "set_percentage",
        {ATTR_ENTITY_ID: "fan.circ", "percentage": 10},
        blocking=False,
    )


async def test_vpd_mode_above_band_sets_max_speed(
    mock_hass: MagicMock,
) -> None:
    """VPD above (target + tolerance) → max_speed."""
    env = _make_env_config(
        mode=FanRegulationMode.VPD,
        vpd_target=1.0,
        vpd_tolerance=0.2,
        min_speed=10,
        max_speed=90,
    )
    mock_hass.states.get.return_value = MagicMock(state="1.5")
    main_coord = _make_coordinator("gs1", env)
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)

    await coord._async_regulate()

    mock_hass.services.async_call.assert_awaited_once_with(
        "fan",
        "set_percentage",
        {ATTR_ENTITY_ID: "fan.circ", "percentage": 90},
        blocking=False,
    )


async def test_vpd_mode_no_vpd_sensors_skips_fan_call(
    mock_hass: MagicMock,
) -> None:
    """No vpd_sensors configured → no fan.set_percentage call."""
    env = _make_env_config(mode=FanRegulationMode.VPD, vpd_sensors=[])
    main_coord = _make_coordinator("gs1", env)
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)

    await coord._async_regulate()

    mock_hass.services.async_call.assert_not_called()


# ---------------------------------------------------------------------------
# VPD mode — temperature safety override
# ---------------------------------------------------------------------------


async def test_vpd_mode_null_thresholds_no_override(
    mock_hass: MagicMock,
) -> None:
    """critical_temp_low=None and critical_temp_high=None → VPD speed used unchanged."""
    env = _make_env_config(
        mode=FanRegulationMode.VPD,
        vpd_target=1.0,
        vpd_tolerance=0.2,
        min_speed=0,
        max_speed=100,
        critical_temp_low=None,
        critical_temp_high=None,
    )
    mock_hass.states.get.return_value = MagicMock(state="1.0")
    main_coord = _make_coordinator("gs1", env)
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)

    await coord._async_regulate()

    mock_hass.services.async_call.assert_awaited_once_with(
        "fan",
        "set_percentage",
        {ATTR_ENTITY_ID: "fan.circ", "percentage": 50},
        blocking=False,
    )


async def test_vpd_mode_high_temp_breach_overrides_to_max_speed(
    mock_hass: MagicMock,
) -> None:
    """temp > critical_temp_high → override activates, fans set to max_speed."""
    env = _make_env_config(
        mode=FanRegulationMode.VPD,
        vpd_target=1.0,
        vpd_tolerance=0.2,
        min_speed=10,
        max_speed=90,
        critical_temp_high=30.0,
        critical_temp_hysteresis=2.0,
    )

    def _get_state(entity_id: str) -> MagicMock:
        if "temperature" in entity_id:
            return MagicMock(state="32.0")  # above 30.0
        return MagicMock(state="1.0")  # VPD midpoint

    mock_hass.states.get.side_effect = _get_state
    main_coord = _make_coordinator("gs1", env)
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)

    await coord._async_regulate()

    mock_hass.services.async_call.assert_awaited_once_with(
        "fan",
        "set_percentage",
        {ATTR_ENTITY_ID: "fan.circ", "percentage": 90},
        blocking=False,
    )


async def test_vpd_mode_low_temp_breach_overrides_to_min_speed(
    mock_hass: MagicMock,
) -> None:
    """temp < critical_temp_low → override activates, fans set to min_speed."""
    env = _make_env_config(
        mode=FanRegulationMode.VPD,
        vpd_target=1.0,
        vpd_tolerance=0.2,
        min_speed=10,
        max_speed=90,
        critical_temp_low=15.0,
        critical_temp_hysteresis=2.0,
    )

    def _get_state(entity_id: str) -> MagicMock:
        if "temperature" in entity_id:
            return MagicMock(state="12.0")  # below 15.0
        return MagicMock(state="1.0")

    mock_hass.states.get.side_effect = _get_state
    main_coord = _make_coordinator("gs1", env)
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)

    await coord._async_regulate()

    mock_hass.services.async_call.assert_awaited_once_with(
        "fan",
        "set_percentage",
        {ATTR_ENTITY_ID: "fan.circ", "percentage": 10},
        blocking=False,
    )


async def test_vpd_mode_override_active_ignores_vpd_sensor(
    mock_hass: MagicMock,
) -> None:
    """While high-temp override is active, VPD sensor value has no effect."""
    env = _make_env_config(
        mode=FanRegulationMode.VPD,
        vpd_target=1.0,
        vpd_tolerance=0.2,
        min_speed=10,
        max_speed=90,
        critical_temp_high=30.0,
        critical_temp_hysteresis=2.0,
    )

    def _get_state(entity_id: str) -> MagicMock:
        if "temperature" in entity_id:
            return MagicMock(state="32.0")
        return MagicMock(state="0.5")  # VPD would give min_speed without override

    mock_hass.states.get.side_effect = _get_state
    main_coord = _make_coordinator("gs1", env)
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)

    await coord._async_regulate()

    mock_hass.services.async_call.assert_awaited_once_with(
        "fan",
        "set_percentage",
        {ATTR_ENTITY_ID: "fan.circ", "percentage": 90},
        blocking=False,
    )


async def test_vpd_mode_override_deactivates_after_hysteresis(
    mock_hass: MagicMock,
) -> None:
    """Override deactivates only after temp clears threshold + hysteresis."""
    env = _make_env_config(
        mode=FanRegulationMode.VPD,
        vpd_target=1.0,
        vpd_tolerance=0.2,
        min_speed=0,
        max_speed=100,
        critical_temp_high=30.0,
        critical_temp_hysteresis=2.0,
    )
    main_coord = _make_coordinator("gs1", env)
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)

    # Tick 1: temp above threshold → override activates
    def _tick1(entity_id: str) -> MagicMock:
        if "temperature" in entity_id:
            return MagicMock(state="32.0")
        return MagicMock(state="1.0")

    mock_hass.states.get.side_effect = _tick1
    await coord._async_regulate()
    assert coord._temp_override_active is True

    # Tick 2: temp just below threshold (29.5) but not past hysteresis band (28.0) → still overriding
    def _tick2(entity_id: str) -> MagicMock:
        if "temperature" in entity_id:
            return MagicMock(state="29.5")
        return MagicMock(state="1.0")

    mock_hass.states.get.side_effect = _tick2
    mock_hass.services.async_call.reset_mock()
    await coord._async_regulate()
    mock_hass.services.async_call.assert_awaited_once_with(
        "fan",
        "set_percentage",
        {ATTR_ENTITY_ID: "fan.circ", "percentage": 100},
        blocking=False,
    )
    assert coord._temp_override_active is True

    # Tick 3: temp at exactly threshold - hysteresis (28.0) → override deactivates
    def _tick3(entity_id: str) -> MagicMock:
        if "temperature" in entity_id:
            return MagicMock(state="28.0")
        return MagicMock(state="1.0")

    mock_hass.states.get.side_effect = _tick3
    mock_hass.services.async_call.reset_mock()
    await coord._async_regulate()
    mock_hass.services.async_call.assert_awaited_once_with(
        "fan",
        "set_percentage",
        {ATTR_ENTITY_ID: "fan.circ", "percentage": 50},  # back to VPD speed
        blocking=False,
    )
    assert coord._temp_override_active is False


# ---------------------------------------------------------------------------
# Dynamic Wind Layer
# ---------------------------------------------------------------------------


async def test_wind_enabled_applies_offset_at_quarter_period(
    mock_hass: MagicMock,
) -> None:
    """wind_enabled=True at quarter period → sin=1.0 → regulation_speed + amplitude."""
    # Humidity at midpoint of [0, 100] band → regulation_speed = 50
    # At quarter period (15s of 60s period): wind_offset = 10 × sin(π/2) = 10
    # Final speed = clamp(50 + 10, 0, 100) = 60
    env = _make_env_config(
        mode=FanRegulationMode.HUMIDITY,
        humidity_target=60.0,
        humidity_tolerance=5.0,
        min_speed=0,
        max_speed=100,
        wind_enabled=True,
        wind_period_seconds=60,
        wind_amplitude_pct=10,
    )
    mock_hass.states.get.return_value = MagicMock(state="60.0")
    main_coord = _make_coordinator("gs1", env)
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)
    coord._start_time = 0.0

    with patch("custom_components.growspace_manager.circulation_fan_coordinator.time") as mock_time:
        mock_time.monotonic.return_value = 15.0  # quarter period
        await coord._async_regulate()

    mock_hass.services.async_call.assert_awaited_once_with(
        "fan",
        "set_percentage",
        {ATTR_ENTITY_ID: "fan.circ", "percentage": 60},
        blocking=False,
    )


async def test_wind_output_clamped_to_max_speed(
    mock_hass: MagicMock,
) -> None:
    """Wind offset pushing past max_speed is clamped to max_speed."""
    # regulation_speed = 90 (humidity above band), amplitude=20 × sin(1.0) → 110 → clamped to 90
    env = _make_env_config(
        mode=FanRegulationMode.HUMIDITY,
        humidity_target=60.0,
        humidity_tolerance=5.0,
        min_speed=10,
        max_speed=90,
        wind_enabled=True,
        wind_period_seconds=60,
        wind_amplitude_pct=20,
    )
    mock_hass.states.get.return_value = MagicMock(state="70.0")  # above band → max_speed=90
    main_coord = _make_coordinator("gs1", env)
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)
    coord._start_time = 0.0

    with patch("custom_components.growspace_manager.circulation_fan_coordinator.time") as mock_time:
        mock_time.monotonic.return_value = 15.0  # quarter period → sin=1.0
        await coord._async_regulate()

    mock_hass.services.async_call.assert_awaited_once_with(
        "fan",
        "set_percentage",
        {ATTR_ENTITY_ID: "fan.circ", "percentage": 90},
        blocking=False,
    )


async def test_wind_output_clamped_to_min_speed(
    mock_hass: MagicMock,
) -> None:
    """Wind offset pushing below min_speed is clamped to min_speed."""
    # regulation_speed = 10 (humidity below band), amplitude=20 at 3/4 period → 10 - 20 = -10 → clamped to 10
    env = _make_env_config(
        mode=FanRegulationMode.HUMIDITY,
        humidity_target=60.0,
        humidity_tolerance=5.0,
        min_speed=10,
        max_speed=90,
        wind_enabled=True,
        wind_period_seconds=60,
        wind_amplitude_pct=20,
    )
    mock_hass.states.get.return_value = MagicMock(state="50.0")  # below band → min_speed=10
    main_coord = _make_coordinator("gs1", env)
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)
    coord._start_time = 0.0

    with patch("custom_components.growspace_manager.circulation_fan_coordinator.time") as mock_time:
        mock_time.monotonic.return_value = 45.0  # 3/4 period → sin=-1.0
        await coord._async_regulate()

    mock_hass.services.async_call.assert_awaited_once_with(
        "fan",
        "set_percentage",
        {ATTR_ENTITY_ID: "fan.circ", "percentage": 10},
        blocking=False,
    )


async def test_wind_disabled_produces_stable_speed(
    mock_hass: MagicMock,
) -> None:
    """wind_enabled=False → speed is unaffected by elapsed time (no oscillation)."""
    env = _make_env_config(
        mode=FanRegulationMode.HUMIDITY,
        humidity_target=60.0,
        humidity_tolerance=5.0,
        min_speed=0,
        max_speed=100,
        wind_enabled=False,
    )
    mock_hass.states.get.return_value = MagicMock(state="60.0")  # midpoint → speed=50
    main_coord = _make_coordinator("gs1", env)
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)
    coord._start_time = 0.0

    # At quarter period — if wind were enabled speed would be 60, not 50
    with patch("custom_components.growspace_manager.circulation_fan_coordinator.time") as mock_time:
        mock_time.monotonic.return_value = 15.0
        await coord._async_regulate()

    mock_hass.services.async_call.assert_awaited_once_with(
        "fan",
        "set_percentage",
        {ATTR_ENTITY_ID: "fan.circ", "percentage": 50},
        blocking=False,
    )


async def test_wind_applies_on_top_of_temp_override_speed(
    mock_hass: MagicMock,
) -> None:
    """Wind offset applies to the temp override speed, not the VPD regulation speed."""
    # VPD override active (high temp) → speed = max_speed = 90
    # Wind at quarter period with amplitude=5 → 90 + 5 = 95 → clamped to 90
    env = _make_env_config(
        mode=FanRegulationMode.VPD,
        vpd_target=1.0,
        vpd_tolerance=0.2,
        min_speed=10,
        max_speed=90,
        critical_temp_high=30.0,
        wind_enabled=True,
        wind_period_seconds=60,
        wind_amplitude_pct=5,
    )

    def _get_state(entity_id: str) -> MagicMock:
        if "temperature" in entity_id:
            return MagicMock(state="32.0")  # above threshold → override to max_speed=90
        return MagicMock(state="0.5")  # VPD below band → would be min_speed without override

    mock_hass.states.get.side_effect = _get_state
    main_coord = _make_coordinator("gs1", env)
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)
    coord._start_time = 0.0

    with patch("custom_components.growspace_manager.circulation_fan_coordinator.time") as mock_time:
        mock_time.monotonic.return_value = 15.0  # quarter period → wind_offset = +5
        await coord._async_regulate()

    # Override speed (90) + wind (+5) = 95, clamped to 90
    mock_hass.services.async_call.assert_awaited_once_with(
        "fan",
        "set_percentage",
        {ATTR_ENTITY_ID: "fan.circ", "percentage": 90},
        blocking=False,
    )


# ---------------------------------------------------------------------------
# _on_tick dispatches a background task (line 156)
# ---------------------------------------------------------------------------


async def test_on_tick_creates_background_task(
    mock_hass: MagicMock,
    mock_track_time_interval: MagicMock,
) -> None:
    """_on_tick schedules _async_regulate as a background task."""
    env = _make_env_config()
    main_coord = _make_coordinator("gs1", env)
    config_entry = MagicMock()
    config_entry.async_create_background_task = MagicMock()

    coord = CirculationFanCoordinator(mock_hass, config_entry, "gs1", main_coord)
    coord._on_tick(object())

    config_entry.async_create_background_task.assert_called_once()
    _, kwargs = config_entry.async_create_background_task.call_args_list[0][0], config_entry.async_create_background_task.call_args_list[0][1]
    call_args = config_entry.async_create_background_task.call_args
    assert call_args[0][0] is mock_hass
    assert call_args[0][2] == "circulation_fan_regulate"


# ---------------------------------------------------------------------------
# _async_regulate when _env_config is None (line 163)
# ---------------------------------------------------------------------------


async def test_async_regulate_no_env_config_returns_early(
    mock_hass: MagicMock,
) -> None:
    """_async_regulate returns immediately when _env_config is None (missing growspace)."""
    main_coord = MagicMock()
    main_coord.growspaces = {}

    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "nonexistent", main_coord)
    assert coord._env_config is None

    await coord._async_regulate()

    mock_hass.services.async_call.assert_not_called()


# ---------------------------------------------------------------------------
# Unknown regulation mode (line 214)
# ---------------------------------------------------------------------------


async def test_async_regulate_unknown_mode_returns_early(
    mock_hass: MagicMock,
) -> None:
    """An unrecognised regulation_mode value → no fan.set_percentage call."""
    env = _make_env_config(mode=FanRegulationMode.HUMIDITY)
    main_coord = _make_coordinator("gs1", env)
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)

    # Patch the regulation_mode to an unexpected value and mock _read_sensor to
    # return a float so execution reaches the if-elif-else branch (not the
    # earlier sensor_value is None guard).
    coord._env_config.circulation_fan_config.regulation_mode = "unknown_mode"
    with patch.object(coord, "_read_sensor", return_value=42.0):
        await coord._async_regulate()

    mock_hass.services.async_call.assert_not_called()


# ---------------------------------------------------------------------------
# Exception handling in fan service call (lines 231-232)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("exc", [Exception("ha error"), TimeoutError()])
async def test_fan_service_call_exception_is_logged_not_raised(
    mock_hass: MagicMock, exc: Exception
) -> None:
    """HomeAssistantError or TimeoutError from fan.set_percentage is caught and logged."""
    from homeassistant.exceptions import HomeAssistantError

    env = _make_env_config(
        mode=FanRegulationMode.HUMIDITY,
        humidity_target=60.0,
        humidity_tolerance=5.0,
        min_speed=0,
        max_speed=100,
    )
    mock_hass.states.get.return_value = MagicMock(state="70.0")
    mock_hass.services.async_call = AsyncMock(side_effect=HomeAssistantError("fail"))
    main_coord = _make_coordinator("gs1", env)
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)

    # Should not raise
    await coord._async_regulate()

    mock_hass.services.async_call.assert_awaited_once()


async def test_fan_service_timeout_is_caught(
    mock_hass: MagicMock,
) -> None:
    """TimeoutError from fan.set_percentage is caught without raising."""
    env = _make_env_config(
        mode=FanRegulationMode.HUMIDITY,
        humidity_target=60.0,
        humidity_tolerance=5.0,
        min_speed=0,
        max_speed=100,
    )
    mock_hass.states.get.return_value = MagicMock(state="70.0")
    mock_hass.services.async_call = AsyncMock(side_effect=TimeoutError())
    main_coord = _make_coordinator("gs1", env)
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)

    await coord._async_regulate()

    mock_hass.services.async_call.assert_awaited_once()


# ---------------------------------------------------------------------------
# _read_sensor with unknown mode (line 245)
# ---------------------------------------------------------------------------


def test_read_sensor_unknown_mode_returns_none(
    mock_hass: MagicMock,
) -> None:
    """_read_sensor returns None for an unrecognised FanRegulationMode."""
    env = _make_env_config()
    main_coord = _make_coordinator("gs1", env)
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)

    result = coord._read_sensor("completely_unknown_mode")  # type: ignore[arg-type]

    assert result is None
    mock_hass.states.get.assert_not_called()


# ---------------------------------------------------------------------------
# Stage-based VPD — FAN_VPD_STAGE_DEFAULTS coverage
# ---------------------------------------------------------------------------


def test_fan_vpd_stage_defaults_covers_all_coordinator_stages() -> None:
    """FAN_VPD_STAGE_DEFAULTS has entries for every stage determine_coordinator_stage can return."""
    from custom_components.growspace_manager.circulation_fan_coordinator import FAN_VPD_STAGE_DEFAULTS
    from custom_components.growspace_manager.const import PlantStage

    coordinator_stages = {
        PlantStage.SEEDLING,
        PlantStage.CLONE,
        PlantStage.MOTHER,
        PlantStage.VEG,
        PlantStage.FLOWER_EARLY,
        PlantStage.FLOWER_MID,
        PlantStage.FLOWER_LATE,
        PlantStage.DRY,
        PlantStage.CURE,
    }
    assert coordinator_stages == set(FAN_VPD_STAGE_DEFAULTS.keys())
    for stage, entry in FAN_VPD_STAGE_DEFAULTS.items():
        assert "day" in entry, f"Missing 'day' for {stage}"
        assert "night" in entry, f"Missing 'night' for {stage}"


# ---------------------------------------------------------------------------
# Stage-based VPD — runtime behaviour
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stage,is_day,expected_target", [
    (PlantStage.VEG, True, FAN_VPD_STAGE_DEFAULTS[PlantStage.VEG]["day"]),
    (PlantStage.VEG, False, FAN_VPD_STAGE_DEFAULTS[PlantStage.VEG]["night"]),
    (PlantStage.FLOWER_EARLY, True, FAN_VPD_STAGE_DEFAULTS[PlantStage.FLOWER_EARLY]["day"]),
    (PlantStage.FLOWER_MID, False, FAN_VPD_STAGE_DEFAULTS[PlantStage.FLOWER_MID]["night"]),
    (PlantStage.FLOWER_LATE, True, FAN_VPD_STAGE_DEFAULTS[PlantStage.FLOWER_LATE]["day"]),
    (PlantStage.DRY, False, FAN_VPD_STAGE_DEFAULTS[PlantStage.DRY]["night"]),
    (PlantStage.CURE, True, FAN_VPD_STAGE_DEFAULTS[PlantStage.CURE]["day"]),
    (PlantStage.SEEDLING, False, FAN_VPD_STAGE_DEFAULTS[PlantStage.SEEDLING]["night"]),
    (PlantStage.CLONE, True, FAN_VPD_STAGE_DEFAULTS[PlantStage.CLONE]["day"]),
    (PlantStage.MOTHER, True, FAN_VPD_STAGE_DEFAULTS[PlantStage.MOTHER]["day"]),
])
def test_get_stage_vpd_target_returns_correct_value(
    mock_hass: MagicMock,
    stage: PlantStage,
    is_day: bool,
    expected_target: float,
) -> None:
    """_get_stage_vpd_target returns the correct day/night target for each stage."""
    env = _make_env_config(
        mode=FanRegulationMode.VPD,
        vpd_target=99.9,  # should NOT be returned when plants are present
        stage_vpd_enabled=True,
    )
    plant = MagicMock()
    with patch(
        "custom_components.growspace_manager.circulation_fan_coordinator.determine_coordinator_stage",
        return_value=stage,
    ):
        main_coord = _make_coordinator("gs1", env, plants=[plant])
        coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)
        result = coord._get_stage_vpd_target(env.circulation_fan_config, is_day)

    assert result == expected_target


async def test_stage_vpd_enabled_regulate_uses_stage_target(
    mock_hass: MagicMock,
) -> None:
    """_async_regulate with stage_vpd_enabled=True passes the stage target to compute_fan_speed."""
    env = _make_env_config(
        mode=FanRegulationMode.VPD,
        vpd_target=99.9,  # must NOT be used
        vpd_tolerance=0.2,
        min_speed=0,
        max_speed=100,
        stage_vpd_enabled=True,
        light_sensors=["sensor.light"],
    )
    flower_mid_day = FAN_VPD_STAGE_DEFAULTS[PlantStage.FLOWER_MID]["day"]  # 1.2

    def _get_state(entity_id: str) -> MagicMock:
        if "light" in entity_id:
            return MagicMock(state="1.0")  # day
        # VPD well above stage target → max_speed
        return MagicMock(state=str(flower_mid_day + 1.0))

    mock_hass.states.get.side_effect = _get_state
    with patch(
        "custom_components.growspace_manager.circulation_fan_coordinator.determine_coordinator_stage",
        return_value=PlantStage.FLOWER_MID,
    ):
        main_coord = _make_coordinator("gs1", env, plants=[MagicMock()])
        coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)
        await coord._async_regulate()

    mock_hass.services.async_call.assert_awaited_once_with(
        "fan",
        "set_percentage",
        {ATTR_ENTITY_ID: "fan.circ", "percentage": 100},
        blocking=False,
    )


async def test_stage_vpd_disabled_uses_static_target(
    mock_hass: MagicMock,
) -> None:
    """stage_vpd_enabled=False → static vpd_target is used unchanged."""
    env = _make_env_config(
        mode=FanRegulationMode.VPD,
        vpd_target=1.0,
        vpd_tolerance=0.2,
        min_speed=0,
        max_speed=100,
        stage_vpd_enabled=False,
    )
    mock_hass.states.get.return_value = MagicMock(state="1.0")
    main_coord = _make_coordinator("gs1", env)
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)

    await coord._async_regulate()

    mock_hass.services.async_call.assert_awaited_once_with(
        "fan",
        "set_percentage",
        {ATTR_ENTITY_ID: "fan.circ", "percentage": 50},
        blocking=False,
    )


async def test_stage_vpd_no_plants_falls_back_to_static_target(
    mock_hass: MagicMock,
) -> None:
    """stage_vpd_enabled=True with no plants falls back to cfg.vpd_target."""
    env = _make_env_config(
        mode=FanRegulationMode.VPD,
        vpd_target=1.0,
        vpd_tolerance=0.2,
        min_speed=0,
        max_speed=100,
        stage_vpd_enabled=True,
    )
    mock_hass.states.get.return_value = MagicMock(state="1.0")
    # plants=[] → fallback to static target
    main_coord = _make_coordinator("gs1", env, plants=[])
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)

    await coord._async_regulate()

    mock_hass.services.async_call.assert_awaited_once_with(
        "fan",
        "set_percentage",
        {ATTR_ENTITY_ID: "fan.circ", "percentage": 50},
        blocking=False,
    )


# ---------------------------------------------------------------------------
# _determine_is_day
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("light_state,expected_day", [
    ("1.0", True),
    ("0.0", False),
    (STATE_ON, True),
    (STATE_UNAVAILABLE, True),   # no valid sensors → default True
    (STATE_UNKNOWN, True),       # no valid sensors → default True
])
def test_determine_is_day(
    mock_hass: MagicMock,
    light_state: str,
    expected_day: bool,
) -> None:
    """_determine_is_day reads light sensor state and returns correct bool."""
    env = _make_env_config(light_sensors=["sensor.light"])
    main_coord = _make_coordinator("gs1", env)
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)
    mock_hass.states.get.return_value = MagicMock(state=light_state)

    result = coord._determine_is_day()

    assert result is expected_day


def test_determine_is_day_no_light_sensors_returns_true(
    mock_hass: MagicMock,
) -> None:
    """_determine_is_day returns True when no light sensors are configured."""
    env = _make_env_config(light_sensors=[])
    main_coord = _make_coordinator("gs1", env)
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)

    assert coord._determine_is_day() is True
    mock_hass.states.get.assert_not_called()


def test_determine_is_day_uses_last_known_when_unavailable(
    mock_hass: MagicMock,
) -> None:
    """_determine_is_day uses cached state when all sensors are unavailable."""
    env = _make_env_config(light_sensors=["sensor.light"])
    main_coord = _make_coordinator("gs1", env)
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)

    # Prime cache with a valid reading
    coord._last_known_is_day = False

    mock_hass.states.get.return_value = MagicMock(state=STATE_UNAVAILABLE)
    assert coord._determine_is_day() is False


# ---------------------------------------------------------------------------
# Stage VPD Overrides — coordinator lookup
# ---------------------------------------------------------------------------


def test_get_stage_vpd_target_override_present_uses_override(
    mock_hass: MagicMock,
) -> None:
    """When an override exists for the current stage, it takes precedence over FAN_VPD_STAGE_DEFAULTS."""
    override_day = 0.95
    override_night = 0.80
    env = _make_env_config(
        mode=FanRegulationMode.VPD,
        vpd_target=99.9,
        stage_vpd_enabled=True,
        stage_vpd_overrides={"veg": {"day": override_day, "night": override_night}},
    )
    plant = MagicMock()
    with patch(
        "custom_components.growspace_manager.circulation_fan_coordinator.determine_coordinator_stage",
        return_value=PlantStage.VEG,
    ):
        main_coord = _make_coordinator("gs1", env, plants=[plant])
        coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)
        assert coord._get_stage_vpd_target(env.circulation_fan_config, is_day=True) == override_day
        assert coord._get_stage_vpd_target(env.circulation_fan_config, is_day=False) == override_night


def test_get_stage_vpd_target_override_absent_uses_default(
    mock_hass: MagicMock,
) -> None:
    """When no override exists for the current stage, FAN_VPD_STAGE_DEFAULTS is used."""
    env = _make_env_config(
        mode=FanRegulationMode.VPD,
        vpd_target=99.9,
        stage_vpd_enabled=True,
        stage_vpd_overrides={"flower_early": {"day": 1.3, "night": 1.1}},
    )
    plant = MagicMock()
    with patch(
        "custom_components.growspace_manager.circulation_fan_coordinator.determine_coordinator_stage",
        return_value=PlantStage.VEG,
    ):
        main_coord = _make_coordinator("gs1", env, plants=[plant])
        coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)
        assert coord._get_stage_vpd_target(env.circulation_fan_config, is_day=True) == FAN_VPD_STAGE_DEFAULTS[PlantStage.VEG]["day"]


def test_get_stage_vpd_target_no_plants_falls_back_to_vpd_target(
    mock_hass: MagicMock,
) -> None:
    """With no plants, _get_stage_vpd_target returns the static vpd_target regardless of overrides."""
    static_target = 1.1
    env = _make_env_config(
        mode=FanRegulationMode.VPD,
        vpd_target=static_target,
        stage_vpd_enabled=True,
        stage_vpd_overrides={"veg": {"day": 0.9, "night": 0.75}},
    )
    main_coord = _make_coordinator("gs1", env, plants=[])
    coord = CirculationFanCoordinator(mock_hass, MagicMock(), "gs1", main_coord)
    assert coord._get_stage_vpd_target(env.circulation_fan_config, is_day=True) == static_target


# ---------------------------------------------------------------------------
# Stage VPD Overrides — validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_overrides,match", [
    (
        {"veg": {"day": 0.0, "night": 0.7}},
        "out of range",
    ),
    (
        {"veg": {"day": 3.1, "night": 0.7}},
        "out of range",
    ),
    (
        {"not_a_stage": {"day": 0.8, "night": 0.7}},
        "Unknown stage key",
    ),
    (
        {"veg": {"day": 0.8}},
        "both 'day' and 'night'",
    ),
])
def test_stage_vpd_overrides_validation(
    bad_overrides: dict,
    match: str,
) -> None:
    """_validate_stage_vpd_overrides rejects out-of-range values, unknown keys, and incomplete entries."""
    from custom_components.growspace_manager.services.environment import _validate_stage_vpd_overrides
    from homeassistant.exceptions import ServiceValidationError

    with pytest.raises(ServiceValidationError, match=match):
        _validate_stage_vpd_overrides(bad_overrides)
