"""Tests for the Growspace Manager binary_sensor platform."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.growspace_manager.binary_sensor import (
    BayesianMoldRiskSensor,
    BayesianOptimalConditionsSensor,
    BayesianStressSensor,
    async_setup_entry,
)
from custom_components.growspace_manager.const import DOMAIN

MOCK_CONFIG_ENTRY_ID = "test_entry"


@pytest.fixture
def mock_growspace():
    """Fixture for a mock growspace."""
    growspace = MagicMock()
    growspace.name = "Test Growspace"
    growspace.environment_config = {
        "temperature_sensor": "sensor.temp",
        "humidity_sensor": "sensor.humidity",
        "vpd_sensor": "sensor.vpd",
        "co2_sensor": "sensor.co2",
        "circulation_fan": "switch.fan",
        "stress_threshold": 0.7,
        "mold_threshold": 0.75,
    }
    growspace.notification_target = "notify.test" # Added for notification tests
    return growspace


@pytest.fixture
def mock_coordinator(mock_growspace):
    """Fixture for a mock coordinator."""
    coordinator = MagicMock()
    coordinator.hass = MagicMock()
    coordinator.growspaces = {"gs1": mock_growspace}
    coordinator.plants = {
        "p1": MagicMock(
            veg_start=(date.today() - timedelta(days=10)).isoformat(),
            flower_start=None,
        ),
        "p2": MagicMock(
            veg_start=(date.today() - timedelta(days=30)).isoformat(),
            flower_start=(date.today() - timedelta(days=5)).isoformat(),
        ),
    }
    coordinator.get_growspace_plants.return_value = list(coordinator.plants.values())
    coordinator.is_notifications_enabled.return_value = True
    coordinator.async_add_listener = Mock() # Ensure this is mocked
    return coordinator


@pytest.fixture
def mock_hass(mock_coordinator):
    """Fixture for a mock Home Assistant."""
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {
        DOMAIN: {
            MOCK_CONFIG_ENTRY_ID: {
                "coordinator": mock_coordinator,
            }
        }
    }
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()  # Mock the service call
    return hass


@pytest.mark.asyncio
async def test_async_setup_entry(mock_hass: HomeAssistant):
    """Test the binary sensor platform setup."""
    async_add_entities = AsyncMock()
    config_entry = MagicMock()
    config_entry.entry_id = MOCK_CONFIG_ENTRY_ID

    await async_setup_entry(mock_hass, config_entry, async_add_entities)

    # Asserts that entities are created and added
    async_add_entities.assert_called_once()
    entities = async_add_entities.call_args[0][0]
    assert len(entities) == 3
    assert any(isinstance(e, BayesianStressSensor) for e in entities)
    assert any(isinstance(e, BayesianMoldRiskSensor) for e in entities)
    assert any(isinstance(e, BayesianOptimalConditionsSensor) for e in entities)


@pytest.mark.asyncio
async def test_async_setup_entry_no_env_config(mock_hass: HomeAssistant):
    """Test setup when growspace has no environment config."""
    mock_hass.data[DOMAIN][MOCK_CONFIG_ENTRY_ID]["coordinator"].growspaces[
        "gs1"
    ].environment_config = None
    async_add_entities = AsyncMock()
    config_entry = MagicMock()
    config_entry.entry_id = MOCK_CONFIG_ENTRY_ID

    await async_setup_entry(mock_hass, config_entry, async_add_entities)

    async_add_entities.assert_not_called()


def test_get_growth_stage_info(mock_coordinator):
    """Test _get_growth_stage_info calculates days correctly."""
    sensor = BayesianStressSensor(
        mock_coordinator, "gs1", mock_coordinator.growspaces["gs1"].environment_config
    )
    info = sensor._get_growth_stage_info()

    assert info["veg_days"] == 30
    assert info["flower_days"] == 5


@pytest.mark.asyncio
async def test_send_notification(mock_coordinator, mock_hass):
    """Test that notifications are sent correctly."""
    growspace = mock_coordinator.growspaces["gs1"]
    growspace.notification_target = "notify.test"
    sensor = BayesianStressSensor(
        mock_coordinator, "gs1", growspace.environment_config
    )
    sensor.hass = mock_hass # Assign the mocked hass to the sensor

    # Call the method to test
    sensor._send_notification("stress", 0.85)

    # Check that the notify service was called
    mock_hass.services.async_call.assert_called_once_with(
        "notify",
        "notify.test",
        {
            "title": "Growspace: Test Growspace",
            "message": "Plants may be under stress. Current probability: 0.85",
            "data": {
                "growspace_id": "gs1",
                "condition": "stress",
                "probability": 0.85,
            },
        },
    )


@pytest.mark.asyncio
async def test_stress_sensor_notification_on_state_change(
    mock_coordinator, mock_hass
):
    """Test that stress sensor sends notification only when state changes to on."""
    sensor = BayesianStressSensor(
        mock_coordinator, "gs1", mock_coordinator.growspaces["gs1"].environment_config
    )
    sensor.hass = mock_hass
    sensor._probability = 0.1  # Start below threshold

    # Mock get_sensor_value to return values that will trigger stress
    with patch.object(
        sensor, "_get_sensor_value", side_effect=[31, 75, 1.5, 1900]
    ):  # temp, humidity, vpd, co2
        await sensor._async_update_probability()

    # is_on should now be true and notification should have been sent
    assert sensor.is_on
    mock_hass.services.async_call.assert_called_once_with(
        "notify",
        "notify.test",
        {
            "title": "Growspace: Test Growspace",
            "message": "Plants may be under stress. Current probability: 0.95", # Updated probability based on mock values
            "data": {
                "growspace_id": "gs1",
                "condition": "stress",
                "probability": 0.95, # Updated probability based on mock values
            },
        },
    )

    # Reset mock and run again, probability should still be high
    mock_hass.services.async_call.reset_mock()
    with patch.object(
        sensor, "_get_sensor_value", side_effect=[31, 75, 1.5, 1900]
    ):
        await sensor._async_update_probability()

    # Notification should NOT be sent again
    assert sensor.is_on
    mock_hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_mold_risk_sensor_notification_on_state_change(
    mock_coordinator, mock_hass
):
    """Test that mold risk sensor sends notification only when state changes to on."""
    sensor = BayesianMoldRiskSensor(
        mock_coordinator, "gs1", mock_coordinator.growspaces["gs1"].environment_config
    )
    sensor.hass = mock_hass
    sensor._probability = 0.1  # Start below threshold

    # Mock values to trigger mold risk
    with patch.object(
        sensor, "_get_sensor_value", side_effect=[25, 60, 1.1]
    ), patch.object(
        sensor, "_get_growth_stage_info", return_value={"flower_days": 40}
    ):
        await sensor._async_update_probability()

    assert sensor.is_on
    mock_hass.services.async_call.assert_called_once_with(
        "notify",
        "notify.test",
        {
            "title": "Growspace: Test Growspace",
            "message": "High mold risk detected. Current probability: 0.99", # Updated probability based on mock values
            "data": {
                "growspace_id": "gs1",
                "condition": "mold_risk",
                "probability": 0.99, # Updated probability based on mock values
            },
        },
    )


@pytest.mark.asyncio
async def test_optimal_conditions_sensor_notification_on_state_change(
    mock_coordinator, mock_hass
):
    """Test that optimal conditions sensor sends notification only when state changes to on."""
    sensor = BayesianOptimalConditionsSensor(
        mock_coordinator, "gs1", mock_coordinator.growspaces["gs1"].environment_config
    )
    sensor.hass = mock_hass
    sensor._probability = 0.1  # Start below threshold

    # Mock values to trigger optimal conditions
    with patch.object(
        sensor, "_get_sensor_value", side_effect=[25, 1.2, 1000]
    ), patch.object(
        sensor,
        "_get_growth_stage_info",
        return_value={"veg_days": 20, "flower_days": 0},
    ):
        await sensor._async_update_probability()

    assert sensor.is_on
    mock_hass.services.async_call.assert_called_once_with(
        "notify",
        "notify.test",
        {
            "title": "Growspace: Test Growspace",
            "message": "Growing conditions are optimal. Current probability: 0.95", # Updated probability based on mock values
            "data": {
                "growspace_id": "gs1",
                "condition": "optimal",
                "probability": 0.95, # Updated probability based on mock values
            },
        },
    )