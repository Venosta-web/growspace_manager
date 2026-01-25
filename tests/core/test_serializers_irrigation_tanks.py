"""Tests for serializer irrigation tank support."""

from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.models import IrrigationTank
from custom_components.growspace_manager.serializers import GrowspaceSerializer
from homeassistant.core import HomeAssistant


@pytest.fixture
def serializer(hass: HomeAssistant):
    return GrowspaceSerializer(hass)


@pytest.fixture
def mock_growspace():
    gs = MagicMock()
    # Initialize list fields
    gs.environment_config.irrigation_tanks = []
    gs.environment_config.temperature_sensors = []
    gs.environment_config.humidity_sensors = []
    gs.environment_config.vpd_sensors = []
    gs.environment_config.light_sensors = []
    gs.environment_config.exhaust_fan_entities = []
    gs.environment_config.circulation_fan_entities = []
    gs.environment_config.humidifier_entities = []
    gs.environment_config.dehumidifier_entities = []

    # Initialize singular fields
    gs.environment_config.temperature_sensor = None
    gs.environment_config.humidity_sensor = None
    gs.environment_config.vpd_sensor = None
    gs.environment_config.co2_sensor = None
    gs.environment_config.soil_moisture_sensor = None

    # Initialize irrigation config
    gs.irrigation_config.irrigation_pump_entity = None
    gs.irrigation_config.drain_pump_entity = None

    return gs


def test_get_sensor_types_with_tanks_simple(serializer, mock_growspace):
    """Test that irrigation tanks are added to sensor_types."""
    # Add a tank
    tank1 = IrrigationTank(sensor_entity="sensor.tank_1", name="Main Tank")
    mock_growspace.environment_config.irrigation_tanks = [tank1]

    sensor_types = serializer._get_sensor_types(mock_growspace)

    assert "sensor.tank_1" in sensor_types
    assert sensor_types["sensor.tank_1"] == "irrigation_tank"


def test_get_sensor_types_with_multiple_tanks(serializer, mock_growspace):
    """Test with multiple tanks."""
    tank1 = IrrigationTank(sensor_entity="sensor.tank_A", name="A")
    tank2 = IrrigationTank(sensor_entity="sensor.tank_B", name="B")
    mock_growspace.environment_config.irrigation_tanks = [tank1, tank2]

    sensor_types = serializer._get_sensor_types(mock_growspace)

    assert sensor_types.get("sensor.tank_A") == "irrigation_tank"
    assert sensor_types.get("sensor.tank_B") == "irrigation_tank"


def test_get_sensor_types_mixed_with_other_sensors(serializer, mock_growspace):
    """Test that tanks coexist with other sensor types."""
    # Setup a normal sensor
    mock_growspace.environment_config.temperature_sensors = ["sensor.temp"]
    mock_growspace.environment_config.temperature_sensor = "sensor.temp"

    # Setup a tank
    tank1 = IrrigationTank(sensor_entity="sensor.water_level", name="Water")
    mock_growspace.environment_config.irrigation_tanks = [tank1]

    sensor_types = serializer._get_sensor_types(mock_growspace)

    assert sensor_types["sensor.temp"] == "temperature"
    assert sensor_types["sensor.water_level"] == "irrigation_tank"
