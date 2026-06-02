"""Integration tests for growspace.overview sensor attributes."""

from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.models import CirculationFanConfig
from custom_components.growspace_manager.presentation.growspace_view_model import (
    GrowspaceViewModelBuilder,
)
from custom_components.growspace_manager.sensor import GrowspaceOverviewSensor


@pytest.mark.asyncio
async def test_growspace_view_model_includes_temp_hum(hass) -> None:
    """Test that GrowspaceViewModelBuilder includes temperature and humidity."""
    builder = GrowspaceViewModelBuilder(hass)

    # Mock growspace with environment config
    mock_env = MagicMock()
    mock_env.temperature_sensor = "sensor.test_temp"
    mock_env.humidity_sensor = "sensor.test_hum"
    mock_env.dehumidifier_entity = None
    mock_env.exhaust_fan_entity = None
    mock_env.humidifier_entity = None
    mock_env.circulation_fan_entity = None
    mock_env.vpd_sensor = None
    mock_env.soil_moisture_sensor = None
    mock_env.temperature_sensors = ["sensor.test_temp"]
    mock_env.humidity_sensors = ["sensor.test_hum"]
    mock_env.vpd_sensors = []
    mock_env.light_sensors = []
    mock_env.co2_sensor = None
    mock_env.exhaust_fan_entities = []
    mock_env.circulation_fan_entities = []
    mock_env.humidifier_entities = []
    mock_env.dehumidifier_entities = []
    mock_env.irrigation_tanks = []
    mock_env.sensor_groups = []
    mock_env.sensor_coordinates = {}
    mock_env.substrate_temperature_sensors = []
    mock_env.power_sensors = []
    mock_env.energy_sensors = []
    mock_env.electricity_cost_per_kwh = 0.0
    mock_env.camera_entities = []
    mock_env.ph_sensors = []
    mock_env.feed_ec_sensors = []
    mock_env.substrate_ec_sensors = []
    mock_env.runoff_ec_sensors = []
    mock_env.drain_volume_sensors = []
    mock_env.irrigation_flow_sensors = []
    mock_env.control_dehumidifier = False
    mock_env.control_humidifier = False
    mock_env.humidifier_thresholds = {}
    mock_env.dehumidifier_thresholds = {}
    mock_env.circulation_fan_config = CirculationFanConfig()

    mock_growspace = MagicMock()
    mock_growspace.environment_config = mock_env
    mock_growspace.irrigation_config = None

    # Set states in hass
    hass.states.async_set("sensor.test_temp", "25.5")
    hass.states.async_set("sensor.test_hum", "60.2")

    attributes = builder._get_environment_attributes(mock_growspace)

    assert attributes["temperature"] == "25.5"
    assert attributes["humidity"] == "60.2"


@pytest.mark.asyncio
async def test_growspace_overview_sensor_exposes_temp_hum(hass) -> None:
    """Test that GrowspaceOverviewSensor exposes temperature and humidity attributes."""
    mock_coordinator = MagicMock()
    mock_coordinator.hass = hass

    # Serialized data as it would come from ViewModelBuilder
    mock_coordinator.data = {
        "serialized_growspaces": {
            "gs1": {
                "total_plants": 5,
                "temperature": "24.8",
                "humidity": "55.5",
                "vpd": "1.2",
            }
        }
    }

    mock_growspace = MagicMock()
    mock_growspace.id = "gs1"

    sensor = GrowspaceOverviewSensor(mock_coordinator, "gs1", mock_growspace)
    sensor.hass = hass

    # Mock platform data required for extra_state_attributes
    sensor.platform = MagicMock()
    sensor.platform.platform_name = "growspace_manager"
    sensor.platform_data = sensor.platform
    sensor.platform.domain = "sensor"

    attrs = sensor.extra_state_attributes

    assert attrs["temperature"] == "24.8"
    assert attrs["humidity"] == "55.5"
    assert attrs["vpd"] == "1.2"


@pytest.mark.asyncio
async def test_environment_attributes_includes_circulation_fan_config(hass) -> None:
    """circulation_fan_config must be present in env attributes so the frontend
    dialog re-opens with the correct enabled state instead of falling back to False."""
    builder = GrowspaceViewModelBuilder(hass)

    fan_cfg = CirculationFanConfig(enabled=True, vpd_target=1.2, min_speed=30, max_speed=90)

    mock_env = MagicMock()
    mock_env.temperature_sensor = None
    mock_env.humidity_sensor = None
    mock_env.vpd_sensor = None
    mock_env.co2_sensor = None
    mock_env.soil_moisture_sensor = None
    mock_env.temperature_sensors = []
    mock_env.humidity_sensors = []
    mock_env.vpd_sensors = []
    mock_env.light_sensors = []
    mock_env.exhaust_fan_entities = []
    mock_env.exhaust_fan_entity = None
    mock_env.circulation_fan_entities = []
    mock_env.circulation_fan_entity = None
    mock_env.humidifier_entities = []
    mock_env.humidifier_entity = None
    mock_env.dehumidifier_entities = []
    mock_env.dehumidifier_entity = None
    mock_env.irrigation_tanks = []
    mock_env.sensor_groups = []
    mock_env.sensor_coordinates = {}
    mock_env.substrate_temperature_sensors = []
    mock_env.power_sensors = []
    mock_env.energy_sensors = []
    mock_env.electricity_cost_per_kwh = 0.0
    mock_env.camera_entities = []
    mock_env.ph_sensors = []
    mock_env.feed_ec_sensors = []
    mock_env.substrate_ec_sensors = []
    mock_env.runoff_ec_sensors = []
    mock_env.drain_volume_sensors = []
    mock_env.irrigation_flow_sensors = []
    mock_env.control_dehumidifier = False
    mock_env.control_humidifier = False
    mock_env.humidifier_thresholds = {}
    mock_env.dehumidifier_thresholds = {}
    mock_env.circulation_fan_config = fan_cfg

    mock_growspace = MagicMock()
    mock_growspace.environment_config = mock_env
    mock_growspace.irrigation_config = None

    attributes = builder._get_environment_attributes(mock_growspace)

    assert "circulation_fan_config" in attributes, (
        "circulation_fan_config missing from environment attributes — "
        "frontend dialog will show enabled=False on re-open"
    )
    assert attributes["circulation_fan_config"]["enabled"] is True
    assert attributes["circulation_fan_config"]["vpd_target"] == 1.2
