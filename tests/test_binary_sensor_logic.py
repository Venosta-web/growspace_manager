"""Tests for the Bayesian environment sensor logic."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util.dt import utcnow

from custom_components.growspace_manager.binary_sensor import (
    BayesianMoldRiskSensor,
    BayesianOptimalConditionsSensor,
    BayesianStressSensor,
)
from custom_components.growspace_manager.const import DOMAIN

MOCK_CONFIG_ENTRY_ID = "test_entry"


@pytest.fixture
def mock_coordinator():
    """Fixture for a mock GrowspaceCoordinator instance."""
    coordinator = MagicMock()
    coordinator.growspaces = {
        "gs1": MagicMock(
            name="Test Growspace",
            environment_config={
                "temperature_sensor": "sensor.temp",
                "humidity_sensor": "sensor.humidity",
                "vpd_sensor": "sensor.vpd",
                "co2_sensor": "sensor.co2",
                "circulation_fan": "switch.fan",
                "light_sensor": "light.grow_light",
                "stress_threshold": 0.7,
                "mold_threshold": 0.75,
                "optimal_threshold": 0.8,
                "prior_stress": 0.15,
                "prior_mold_risk": 0.10,
                "prior_optimal": 0.40,
            },
            notification_target="notify.mobile_app_test",
        )
    }
    coordinator.get_growspace_plants = MagicMock(return_value=[])
    return coordinator


@pytest.fixture
def env_config(mock_coordinator):
    """Fixture for a sample environment configuration."""
    return mock_coordinator.growspaces["gs1"].environment_config


def set_sensor_state(hass: HomeAssistant, entity_id, state, attributes=None):
    """Helper to set a sensor's state in hass."""
    attrs = attributes or {}
    attrs.pop("last_changed", None)
    hass.states.async_set(entity_id, state, attrs)


@patch("custom_components.growspace_manager.trend_analyzer.get_recorder_instance")
@pytest.mark.asyncio
async def test_stress_sensor_high_heat(
    mock_recorder, hass: HomeAssistant, mock_coordinator, env_config
):
    """Test BayesianStressSensor for high heat."""
    hass.data[DOMAIN] = {MOCK_CONFIG_ENTRY_ID: {"coordinator": mock_coordinator}}

    mock_recorder.return_value.async_add_executor_job = AsyncMock(return_value={})
    # Corrected instantiation
    sensor = BayesianStressSensor(
        mock_coordinator,
        "gs1",
        env_config,
    )
    sensor.hass = hass
    sensor.entity_id = "binary_sensor.test_stress"
    sensor.platform = MagicMock()

    set_sensor_state(hass, "sensor.temp", 31)
    set_sensor_state(hass, "sensor.humidity", 60)
    set_sensor_state(hass, "sensor.vpd", 1.0)
    set_sensor_state(hass, "light.grow_light", "on")
    await hass.async_block_till_done()

    with (
        patch(
            "custom_components.growspace_manager.bayesian_evaluator.async_evaluate_stress_trend",
            return_value=([("High Heat", 0.9)], []),
        ),
        patch.object(
            sensor,
            "_get_growth_stage_info",
            return_value={"veg_days": 1, "flower_days": 0},
        ),
        patch.object(sensor, "async_write_ha_state", new_callable=MagicMock),
    ):
        await sensor._async_update_probability()

    assert sensor._probability > sensor.prior
    assert any("High Heat" in reason for _, reason in sensor._reasons)


@patch("custom_components.growspace_manager.trend_analyzer.get_recorder_instance")
@pytest.mark.asyncio
async def test_mold_risk_sensor_late_flower(
    mock_recorder, hass: HomeAssistant, mock_coordinator, env_config
):
    """Test BayesianMoldRiskSensor in late flower."""
    hass.data[DOMAIN] = {MOCK_CONFIG_ENTRY_ID: {"coordinator": mock_coordinator}}

    mock_recorder.return_value.async_add_executor_job = AsyncMock(return_value={})
    # Corrected instantiation
    sensor = BayesianMoldRiskSensor(
        mock_coordinator,
        "gs1",
        env_config,
    )
    sensor.hass = hass
    sensor.entity_id = "binary_sensor.test_mold"
    sensor.platform = MagicMock()
    sensor.threshold = 0.49  # Lower threshold for single observation

    plant = MagicMock(
        flower_start=(datetime.now().date() - timedelta(days=40)).isoformat(),
        veg_start=None,
    )
    mock_coordinator.get_growspace_plants.return_value = [plant]
    set_sensor_state(hass, "sensor.humidity", 60)
    set_sensor_state(hass, "light.grow_light", "off")  # Mold risk is higher at night
    set_sensor_state(hass, "switch.fan", "on")
    set_sensor_state(hass, "sensor.temp", 22)
    set_sensor_state(hass, "sensor.vpd", 1.0)  # Low VPD at night
    await hass.async_block_till_done()

    with (
        patch.object(
            sensor,
            "_days_since",
            side_effect=lambda date_str: (
                utcnow().date() - datetime.fromisoformat(date_str).date()
            ).days,
        ),
        patch(
            "custom_components.growspace_manager.binary_sensor.BayesianEnvironmentSensor._async_analyze_sensor_trend",
            new_callable=AsyncMock,
            return_value={"trend": "stable", "crossed_threshold": False},
        ),
        patch.object(sensor, "async_write_ha_state", new_callable=MagicMock),
    ):
        await sensor._async_update_probability()

    assert sensor._probability > sensor.prior
    assert any("Late Flower" in reason for _, reason in sensor._reasons)


@pytest.mark.asyncio
async def test_optimal_conditions_sensor(
    hass: HomeAssistant, mock_coordinator, env_config
):
    """Test BayesianOptimalConditionsSensor for optimal conditions."""
    hass.data[DOMAIN] = {MOCK_CONFIG_ENTRY_ID: {"coordinator": mock_coordinator}}

    # Corrected instantiation
    sensor = BayesianOptimalConditionsSensor(
        mock_coordinator,
        "gs1",
        env_config,
    )
    sensor.hass = hass
    sensor.entity_id = "binary_sensor.test_optimal"
    sensor.platform = MagicMock()

    set_sensor_state(hass, "sensor.temp", 25)
    set_sensor_state(hass, "sensor.vpd", 1.0)
    set_sensor_state(hass, "light.grow_light", "on")
    set_sensor_state(hass, "sensor.co2", 1200)
    await hass.async_block_till_done()

    # Mock stage info to be in veg
    with (
        patch.object(
            sensor,
            "_get_growth_stage_info",
            return_value={"veg_days": 20, "flower_days": 0},
        ),
        patch.object(sensor, "async_write_ha_state", new_callable=MagicMock),
    ):
        await sensor._async_update_probability()

    assert sensor._probability > sensor.prior
