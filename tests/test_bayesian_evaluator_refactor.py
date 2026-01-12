"""Tests for the bayesian_evaluator module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.growspace_manager.bayesian_evaluator import (
    _async_evaluate_external_mold_trend_sensor,
    _async_evaluate_fallback_mold_trend_analysis,
    async_evaluate_mold_risk_trend,
)
from custom_components.growspace_manager.binary_sensor import BayesianEnvironmentSensor
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    EnvironmentState,
)


@pytest.fixture
def mock_sensor_instance(hass: HomeAssistant):
    """Fixture for a mock BayesianEnvironmentSensor."""
    sensor = MagicMock(spec=BayesianEnvironmentSensor)
    sensor.hass = hass
    sensor.env_config = EnvironmentConfig(
        "sensor.temp", "sensor.humidity", "sensor.vpd", "sensor.co2"
    )
    sensor.async_analyze_sensor_trend = AsyncMock()
    return sensor


@pytest.fixture
def mock_env_state():
    """Fixture for EnvironmentState."""
    state = MagicMock(spec=EnvironmentState)
    state.flower_days = 0  # Default to Veg
    state.temp = 25.0
    state.humidity = 60.0
    state.vpd = 1.0
    state.is_lights_on = True
    return state


@pytest.mark.asyncio
async def test_fallback_mold_trend_vpd_falling_veg_danger(
    mock_sensor_instance, mock_env_state
) -> None:
    """Test VPD falling trend in Veg stage approaching danger zone."""
    mock_env_state.flower_days = 0  # Veg
    mock_env_state.vpd = 0.4  # Below 0.5 danger zone

    # Mock analysis returning "falling"
    async def mock_analyze(sensor, duration, threshold):
        return {"trend": "falling", "crossed_threshold": True}

    observations = []
    reasons = []
    trend_states = {}

    await _async_evaluate_fallback_mold_trend_analysis(
        mock_sensor_instance,
        mock_sensor_instance.env_config.to_dict(),
        "vpd",
        "vpd_trend",
        observations,
        reasons,
        trend_states,
        mock_analyze,
        mock_env_state,
    )

    assert trend_states["vpd_trend"] == "falling"
    assert len(observations) == 1
    assert "Approaching 0.5kPa" in reasons[0][1]


@pytest.mark.asyncio
async def test_fallback_mold_trend_vpd_falling_veg_safe(
    mock_sensor_instance, mock_env_state
) -> None:
    """Test VPD falling trend in Veg stage in safe zone."""
    mock_env_state.flower_days = 0  # Veg
    mock_env_state.vpd = 0.8  # Above 0.5 danger zone

    async def mock_analyze(sensor, duration, threshold):
        return {"trend": "falling", "crossed_threshold": True}

    observations = []
    reasons = []
    trend_states = {}

    await _async_evaluate_fallback_mold_trend_analysis(
        mock_sensor_instance,
        mock_sensor_instance.env_config.to_dict(),
        "vpd",
        "vpd_trend",
        observations,
        reasons,
        trend_states,
        mock_analyze,
        mock_env_state,
    )

    assert trend_states["vpd_trend"] == "falling"
    assert len(observations) == 0  # Should be ignored


@pytest.mark.asyncio
async def test_fallback_mold_trend_vpd_falling_flower_danger(
    mock_sensor_instance, mock_env_state
) -> None:
    """Test VPD falling trend in Flower stage approaching danger zone."""
    mock_env_state.flower_days = 30  # Flower
    mock_env_state.vpd = 0.7  # Below 0.8 danger zone

    async def mock_analyze(sensor, duration, threshold):
        return {"trend": "falling", "crossed_threshold": True}

    observations = []
    reasons = []
    trend_states = {}

    await _async_evaluate_fallback_mold_trend_analysis(
        mock_sensor_instance,
        mock_sensor_instance.env_config.to_dict(),
        "vpd",
        "vpd_trend",
        observations,
        reasons,
        trend_states,
        mock_analyze,
        mock_env_state,
    )

    assert len(observations) == 1
    assert "Approaching 0.8kPa" in reasons[0][1]


@pytest.mark.asyncio
async def test_external_mold_trend_sensor_humidity_rising(
    mock_sensor_instance, hass: HomeAssistant, mock_env_state
) -> None:
    """Test external trend sensor for humidity rising."""
    env_config = {"humidity_trend_sensor": "binary_sensor.humid_trend"}
    hass.states.async_set("binary_sensor.humid_trend", "on")

    observations = []
    reasons = []
    trend_states = {}

    await _async_evaluate_external_mold_trend_sensor(
        mock_sensor_instance,
        env_config,
        "humidity",
        "humidity_trend",
        observations,
        reasons,
        trend_states,
        mock_env_state,
    )

    assert trend_states["humidity_trend"] == "rising"
    assert len(observations) == 1
    assert "Humidity rising" in reasons[0][1]


@pytest.mark.asyncio
async def test_external_mold_stats_sensor_vpd_falling(
    mock_sensor_instance, hass: HomeAssistant, mock_env_state
) -> None:
    """Test external stats sensor for VPD falling."""
    env_config = {"vpd_stats_sensor": "sensor.vpd_stats"}
    hass.states.async_set("sensor.vpd_stats", "1.0", {"change": -0.2})

    # Set dangerous VPD so gating passes
    mock_env_state.vpd = 0.4

    observations = []
    reasons = []
    trend_states = {}

    await _async_evaluate_external_mold_trend_sensor(
        mock_sensor_instance,
        env_config,
        "vpd",
        "vpd_trend",
        observations,
        reasons,
        trend_states,
        mock_env_state,
    )

    assert trend_states["vpd_trend"] == "falling"
    assert len(observations) == 1
    assert "Vpd falling" in reasons[0][1]


@pytest.mark.asyncio
async def test_async_evaluate_mold_risk_trend_integration(
    mock_sensor_instance, mock_env_state
) -> None:
    """Test the full evaluation function ignores humidity trends but passes VPD."""
    # Setup mocks
    mock_env_state.flower_days = 0
    mock_env_state.vpd = 0.4  # Danger

    async def mock_analyze(sensor, duration, threshold):
        if "humidity" in sensor:
            return {"trend": "rising", "crossed_threshold": True}
        if "vpd" in sensor:
            return {"trend": "falling", "crossed_threshold": True}
        return {"trend": "stable", "crossed_threshold": False}

    mock_sensor_instance.async_analyze_sensor_trend.side_effect = mock_analyze
    mock_sensor_instance.env_config.humidity_sensor = "sensor.humidity"
    mock_sensor_instance.env_config.vpd_sensor = "sensor.vpd"

    # We need to mock _async_evaluate_external_mold_trend_sensor to do nothing
    # or let it run (it won't find external sensors in default config)

    obs, reasons, trends = await async_evaluate_mold_risk_trend(
        mock_sensor_instance, mock_env_state
    )

    # Humidity trend should be rising in trends map...
    assert trends["humidity_trend"] == "rising"
    # ...but ignored in observations (list length 1, only VPD)
    # VPD makes 1 observation
    assert len(obs) == 1
    assert "Vpd trend falling" in reasons[0][1]


@pytest.mark.asyncio
async def test_external_mold_trend_sensor_vpd_falling_safe(
    mock_sensor_instance, hass: HomeAssistant, mock_env_state
) -> None:
    """Test external trend sensor for VPD falling but in safe zone."""
    env_config = {"vpd_trend_sensor": "binary_sensor.vpd_falling"}
    # For VPD, "off" means falling in the code logic
    hass.states.async_set("binary_sensor.vpd_falling", "off")

    mock_env_state.vpd = 1.0  # Safe (above 0.8/0.5)
    mock_env_state.flower_days = 30  # Flower

    observations = []
    reasons = []
    trend_states = {}

    await _async_evaluate_external_mold_trend_sensor(
        mock_sensor_instance,
        env_config,
        "vpd",
        "vpd_trend",
        observations,
        reasons,
        trend_states,
        mock_env_state,
    )

    # Should be ignored due to gating
    assert len(observations) == 0
    assert len(reasons) == 0


@pytest.mark.asyncio
async def test_external_mold_stats_sensor_vpd_falling_safe(
    mock_sensor_instance, hass: HomeAssistant, mock_env_state
) -> None:
    """Test external stats sensor for VPD falling but in safe zone."""
    env_config = {"vpd_stats_sensor": "sensor.vpd_stats"}
    hass.states.async_set("sensor.vpd_stats", "1.0", {"change": -0.2})

    mock_env_state.vpd = 1.0  # Safe
    mock_env_state.flower_days = 30

    observations = []
    reasons = []
    trend_states = {}

    await _async_evaluate_external_mold_trend_sensor(
        mock_sensor_instance,
        env_config,
        "vpd",
        "vpd_trend",
        observations,
        reasons,
        trend_states,
        mock_env_state,
    )

    # Should be ignored due to gating
    assert len(observations) == 0
    assert len(reasons) == 0
