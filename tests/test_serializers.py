"""Tests for serializers."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.growspace_manager.const import PlantStage
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    IrrigationConfig,
    IrrigationStrategy,
    Plant,
)
from custom_components.growspace_manager.serializers import GrowspaceSerializer


@pytest.fixture
def serializer(hass):
    """Return a serializer instance."""
    return GrowspaceSerializer(hass)


@pytest.fixture
def mock_growspace():
    """Return a mock growspace."""
    gs = MagicMock(spec=Growspace)
    gs.id = "gs1"
    gs.name = "Test Growspace"
    gs.rows = 2
    gs.plants_per_row = 2
    gs.notification_target = "notify.mobile_app"
    gs.irrigation_config = IrrigationConfig()
    # Ensure to_dict works or use attributes
    # The serializer expects objects now? The serializer uses getattr/properties?
    # Serializer code:
    # env_config = growspace.environment_config
    # dehumidifier_entity = env_config.dehumidifier_entity
    # So it expects objects.

    strategy = MagicMock(spec=IrrigationStrategy)
    strategy.to_dict.return_value = {"enabled": False}
    strategy.enabled = False
    gs.irrigation_strategy = strategy

    gs.environment_config = EnvironmentConfig(
        temperature_sensor="sensor.temp",
        humidity_sensor="sensor.hum",
        vpd_sensor="sensor.vpd",
        light_sensor="binary_sensor.light",
        soil_moisture_sensor="sensor.moisture",
    )
    return gs


@pytest.fixture
def mock_plant():
    """Return a mock plant."""
    plant = MagicMock(spec=Plant)
    plant.plant_id = "plant1"
    plant.growspace_id = "gs1"
    plant.strain = "Test Strain"
    plant.phenotype = "Alpha"
    plant.row = 1
    plant.col = 1
    plant.stage = PlantStage.VEG

    # Dates
    plant.seedling_start = dt_util.now() - timedelta(days=20)
    plant.veg_start = dt_util.now() - timedelta(days=10)
    plant.flower_start = None
    plant.dry_start = None
    plant.cure_start = None
    plant.mother_start = None
    plant.clone_start = None

    return plant


def test_determine_granular_stage(serializer):
    """Test granular stage determination."""
    # Veg Early
    assert serializer._determine_granular_stage(10, 0, 0, 0) == "veg_early"
    # Veg Late (assuming default early is 14 days)
    assert serializer._determine_granular_stage(20, 0, 0, 0) == "veg_late"

    # Flower Early
    assert serializer._determine_granular_stage(30, 10, 0, 0) == "flower_early"
    # Flower Mid (assuming early is 21, so < 21+21 = 42)
    assert serializer._determine_granular_stage(40, 30, 0, 0) == "flower_mid"
    # Flower Late
    assert serializer._determine_granular_stage(80, 60, 0, 0) == "flower_late"

    # Dry
    assert serializer._determine_granular_stage(80, 60, 5, 0) == "dry"

    # Cure
    assert serializer._determine_granular_stage(80, 60, 5, 5) == "cure"


def test_calculate_days_in_stage(serializer, mock_plant):
    """Test days in stage calculation."""
    # Veg
    days = serializer.calculate_days_in_stage(mock_plant, PlantStage.VEG)
    assert days == 10

    # Seedling (ended at veg start)
    # seedling start -20, veg start -10 -> 10 days duration
    seedling_days = serializer.calculate_days_in_stage(mock_plant, PlantStage.SEEDLING)
    assert seedling_days == 10


def test_determine_is_day(hass, serializer, mock_growspace):
    """Test is_day determination."""
    # Non-existent sensor -> default True
    mock_growspace.environment_config = EnvironmentConfig()
    assert serializer._determine_is_day(mock_growspace) is True

    # Binary Sensor On
    mock_growspace.environment_config = EnvironmentConfig(
        light_sensor="binary_sensor.light"
    )
    hass.states.async_set("binary_sensor.light", "on")
    assert serializer._determine_is_day(mock_growspace) is True

    # Binary Sensor Off
    hass.states.async_set("binary_sensor.light", "off")
    assert serializer._determine_is_day(mock_growspace) is False

    # Numeric Sensor > 0
    mock_growspace.environment_config = EnvironmentConfig(light_sensor="sensor.lux")
    hass.states.async_set("sensor.lux", "100")
    assert serializer._determine_is_day(mock_growspace) is True

    # Numeric Sensor 0
    hass.states.async_set("sensor.lux", "0")
    assert serializer._determine_is_day(mock_growspace) is False


def test_get_sensor_value(hass, serializer):
    """Test getting numeric sensor value."""
    assert serializer._get_sensor_value(None) is None
    assert serializer._get_sensor_value("sensor.missing") is None

    hass.states.async_set("sensor.test", "12.5")
    assert serializer._get_sensor_value("sensor.test") == 12.5

    hass.states.async_set("sensor.test", "unavailable")
    assert serializer._get_sensor_value("sensor.test") is None

    hass.states.async_set("sensor.test", "invalid")
    assert serializer._get_sensor_value("sensor.test") is None


def test_get_environment_attributes(hass, serializer, mock_growspace):
    """Test fetching environment attributes."""
    hass.states.async_set("sensor.temp", "25")
    hass.states.async_set("sensor.hum", "60")
    hass.states.async_set("sensor.vpd", "1.2")

    # Mock Dehumidifier with attributes
    hass.states.async_set(
        "switch.dehum",
        "on",
        attributes={"humidity": 50, "current_humidity": 60, "mode": "auto"},
    )
    mock_growspace.environment_config.dehumidifier_entity = "switch.dehum"
    mock_growspace.environment_config.control_dehumidifier = True

    attrs = serializer._get_environment_attributes(mock_growspace)

    assert attrs["temperature_sensor"] == "sensor.temp"
    assert attrs["vpd"] == "1.2"
    assert attrs["dehumidifier_state"] == "on"
    assert attrs["dehumidifier_current_humidity"] == 60
    assert attrs["dehumidifier_control_enabled"] is True


def test_serialize_growspace(hass, serializer, mock_growspace, mock_plant):
    """Test full serialization."""
    # Setup dependencies
    hass.states.async_set("sensor.vpd", "1.0")

    plants = [mock_plant]

    with patch("homeassistant.helpers.entity_registry.async_get") as mock_registry_get:
        mock_registry = MagicMock()
        mock_registry.async_get_entity_id.return_value = (
            "sensor.growspace_manager_plant1"
        )
        mock_registry_get.return_value = mock_registry

        data = serializer.serialize_growspace(mock_growspace, plants)

        assert data["growspace_id"] == "gs1"
        assert data["total_plants"] == 1
        assert data["veg_week"] >= 1
        assert "grid" in data
        assert data["grid"]["position_1_1"]["plant_id"] == "plant1"
        assert data["vpd_status"] in ["optimal", "warning", "danger"]
