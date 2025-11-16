"""Tests for the Bayesian environment sensor logic."""

import pytest
import threading
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from datetime import datetime, timedelta

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.util.dt import utcnow


from custom_components.growspace_manager.binary_sensor import (
    BayesianStressSensor,
    BayesianMoldRiskSensor,
    BayesianOptimalConditionsSensor,
    LightCycleVerificationSensor,
)
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

MOCK_CONFIG_ENTRY_ID = "test_entry"
DOMAIN = "growspace_manager"


@pytest.fixture
def mock_coordinator():
    """Fixture for a mock GrowspaceCoordinator instance."""
    coordinator = MagicMock(spec=GrowspaceCoordinator)
    coordinator.growspaces = {
        "gs1": MagicMock(
            name="Test Growspace",
            environment_config={},
            notification_target="notify.mobile_app_test",
        )
    }
    coordinator.get_growspace_plants = MagicMock(return_value=[])
    return coordinator


@pytest.fixture
def env_config():
    """Fixture for a sample environment configuration."""
    return {
        "temperature_sensor": "sensor.temp",
        "humidity_sensor": "sensor.humidity",
        "vpd_sensor": "sensor.vpd",
        "light_sensor": "light.grow_light",
        "co2_sensor": "sensor.co2",
        "circulation_fan": "switch.fan",
    }


def set_sensor_state(hass, entity_id, state, attributes=None):
    """Helper to set a sensor's state in the mock hass."""
    state_obj = MagicMock()
    state_obj.state = str(state)
    state_obj.attributes = attributes or {}
    state_obj.last_changed = utcnow()

    original_side_effect = getattr(hass.states.get, "side_effect", None)

    def side_effect(eid):
        if eid == entity_id:
            return state_obj
        if original_side_effect and callable(original_side_effect):
            return original_side_effect(eid)
        return None

    hass.states.get.side_effect = side_effect


@patch("custom_components.growspace_manager.binary_sensor.get_recorder_instance")
@pytest.mark.asyncio
async def test_stress_sensor_high_heat(
    mock_recorder, mock_hass, mock_coordinator, env_config
):
    """Test BayesianStressSensor for high heat."""
    mock_recorder.return_value.async_add_executor_job = AsyncMock(return_value={})
    sensor = BayesianStressSensor(mock_coordinator, "gs1", env_config)
    sensor.hass = mock_hass
    sensor.entity_id = "binary_sensor.test_stress"
    set_sensor_state(mock_hass, "sensor.temp", 31)
    set_sensor_state(mock_hass, "sensor.humidity", 60)
    set_sensor_state(mock_hass, "sensor.vpd", 1.0)

    await sensor._async_update_probability()

    assert sensor._probability > sensor.prior
    assert any("High Heat" in reason for _, reason in sensor._reasons)


@patch("custom_components.growspace_manager.binary_sensor.get_recorder_instance")
@pytest.mark.asyncio
async def test_mold_risk_sensor_late_flower(
    mock_recorder, mock_hass, mock_coordinator, env_config
):
    """Test BayesianMoldRiskSensor in late flower."""
    mock_recorder.return_value.async_add_executor_job = AsyncMock(return_value={})
    sensor = BayesianMoldRiskSensor(mock_coordinator, "gs1", env_config)
    sensor.hass = mock_hass
    sensor.entity_id = "binary_sensor.test_mold"
    plant = MagicMock(
        flower_start=(datetime.now().date() - timedelta(days=40)).isoformat(),
        veg_start=None,
    )
    mock_coordinator.get_growspace_plants.return_value = [plant]
    set_sensor_state(mock_hass, "sensor.humidity", 60)
    sensor._days_since = lambda start_date: (
        utcnow().date() - datetime.fromisoformat(start_date).date()
    ).days

    await sensor._async_update_probability()

    assert sensor._probability > sensor.prior
    assert any("Late Flower" in reason for _, reason in sensor._reasons)


@pytest.mark.asyncio
async def test_optimal_conditions_sensor(mock_hass, mock_coordinator, env_config):
    """Test BayesianOptimalConditionsSensor for optimal conditions."""
    sensor = BayesianOptimalConditionsSensor(mock_coordinator, "gs1", env_config)
    sensor.hass = mock_hass
    sensor.entity_id = "binary_sensor.test_optimal"
    set_sensor_state(mock_hass, "sensor.temp", 25)
    set_sensor_state(mock_hass, "sensor.vpd", 1.0)
    set_sensor_state(mock_hass, "light.grow_light", "on")
    sensor._days_since = MagicMock(return_value=1)

    await sensor._async_update_probability()

    assert sensor._probability > sensor.prior


@pytest.mark.asyncio
async def test_light_cycle_verification(mock_hass, mock_coordinator, env_config):
    """Test LightCycleVerificationSensor."""
    sensor = LightCycleVerificationSensor(mock_coordinator, "gs1", env_config)
    sensor.hass = mock_hass
    sensor.entity_id = "binary_sensor.test_light_cycle"
    set_sensor_state(mock_hass, "light.grow_light", "on")
    mock_coordinator._calculate_days = MagicMock(return_value=1)

    await sensor.async_update()

    assert sensor.is_on


@patch("custom_components.growspace_manager.binary_sensor.get_recorder_instance")
@pytest.mark.asyncio
async def test_notification_sending(
    mock_recorder, mock_hass, mock_coordinator, env_config
):
    """Test that notifications are sent on state change."""
    mock_recorder.return_value.async_add_executor_job = AsyncMock(return_value={})
    sensor = BayesianStressSensor(mock_coordinator, "gs1", env_config)
    sensor.hass = mock_hass
    sensor.entity_id = "binary_sensor.test_notification"

    mock_coordinator.growspaces["gs1"].notifications_enabled = True

    # Set initial state to "off" (no stress)
    set_sensor_state(mock_hass, "sensor.temp", 25)  # Optimal temp
    await sensor.async_update_and_notify()
    assert not sensor.is_on

    with (
        patch.object(
            sensor, "get_notification_title_message", return_value=("Title", "Message")
        ) as mock_get_notification,
        patch.object(sensor, "_send_notification", new_callable=AsyncMock) as mock_send,
    ):
        # First update, no state change, so no notification
        await sensor.async_update_and_notify()
        mock_get_notification.assert_not_called()
        mock_send.assert_not_called()

        # Second update, state changes to ON, triggering notification
        set_sensor_state(mock_hass, "sensor.temp", 31)  # High heat stress
        await sensor.async_update_and_notify()

        mock_get_notification.assert_called_with(True)
        mock_send.assert_awaited_once_with("Title", "Message")
