"""Tests for serializers."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
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
def serializer(hass: HomeAssistant):
    """Return a serializer instance."""
    return GrowspaceSerializer(hass)


@pytest.fixture
def mock_growspace(hass: HomeAssistant):
    """Return a mock growspace."""
    gs = MagicMock(spec=Growspace)
    gs.id = "gs1"
    gs.name = "Test Growspace"
    gs.rows = 2
    gs.plants_per_row = 2
    gs.notification_target = "notify.mobile_app"
    gs.irrigation_config = IrrigationConfig()

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


def test_calculate_days_in_stage(serializer, mock_plant) -> None:
    """Test days in stage calculation."""
    # Veg
    days = serializer.calculate_days_in_stage(mock_plant, PlantStage.VEG)
    assert days == 10

    # Seedling (ended at veg start)
    # seedling start -20, veg start -10 -> 10 days duration
    seedling_days = serializer.calculate_days_in_stage(mock_plant, PlantStage.SEEDLING)
    assert seedling_days == 10


def test_get_sensor_value(hass: HomeAssistant, serializer: GrowspaceSerializer) -> None:
    """Test getting numeric sensor value."""
    assert serializer._get_sensor_value(None) is None
    assert serializer._get_sensor_value("sensor.missing") is None

    hass.states.async_set("sensor.test", "12.5")
    assert serializer._get_sensor_value("sensor.test") == 12.5

    hass.states.async_set("sensor.test", "unavailable")
    assert serializer._get_sensor_value("sensor.test") is None

    hass.states.async_set("sensor.test", "invalid")
    assert serializer._get_sensor_value("sensor.test") is None


def test_get_environment_attributes(
    hass: HomeAssistant, serializer: GrowspaceSerializer, mock_growspace: Growspace
) -> None:
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


def test_serialize_growspace(
    hass: HomeAssistant, serializer, mock_growspace, mock_plant
) -> None:
    """Test full serialization."""
    # Setup dependencies
    plants = [mock_plant]

    mock_analyzer = MagicMock()
    mock_analyzer.calculate_biological_metrics.return_value = {
        "granular_stage": "veg_early",
        "is_day": True,
        "vpd_target_min": 0.8,
        "vpd_target_max": 1.2,
        "vpd_danger_min": 0.6,
        "vpd_danger_max": 1.4,
        "vpd_status": "optimal",
    }

    with patch("homeassistant.helpers.entity_registry.async_get") as mock_registry_get:
        mock_registry = MagicMock()
        mock_registry.async_get_entity_id.return_value = (
            "sensor.growspace_manager_plant1"
        )
        mock_registry_get.return_value = mock_registry

        data = serializer.serialize_growspace(mock_growspace, plants, mock_analyzer)

        assert data["growspace_id"] == "gs1"
        assert data["total_plants"] == 1
        assert data["veg_week"] >= 1
        assert "grid" in data
        assert data["grid"]["position_1_1"]["plant_id"] == "plant1"
        assert data["vpd_status"] == "optimal"

        # Verify analyzer call
        mock_analyzer.calculate_biological_metrics.assert_called_once()


def test_get_environment_attributes_with_thresholds(
    hass: HomeAssistant, serializer: GrowspaceSerializer, mock_growspace: Growspace
) -> None:
    """Test fetching environment attributes with dehumidifier thresholds."""
    # Mock Dehumidifier with attributes including thresholds
    thresholds = {"veg": {"day": {"on": 1.2, "off": 1.5}}}

    hass.states.async_set(
        "switch.dehum",
        "on",
        attributes={"dehumidifier_control_enabled": True},
    )
    mock_growspace.environment_config.dehumidifier_entity = "switch.dehum"
    mock_growspace.environment_config.control_dehumidifier = True
    mock_growspace.environment_config.dehumidifier_thresholds = thresholds

    attrs = serializer._get_environment_attributes(mock_growspace)

    # Serializer code reads 'dehumidifier_thresholds' attribute from the environment_config property
    assert "dehumidifier_thresholds" in attrs
    assert attrs["dehumidifier_thresholds"] == thresholds


# --------------------
# Coverage Gaps
# --------------------


def test_get_environment_attributes_extended(
    hass: HomeAssistant, serializer: GrowspaceSerializer, mock_growspace: Growspace
) -> None:
    """Test environment attributes with exhaust, humidifier, and circulation fan."""
    # Setup Entity IDs
    mock_growspace.environment_config.exhaust_fan_entity = "fan.exhaust"
    mock_growspace.environment_config.humidifier_entity = "humidifier.room"
    mock_growspace.environment_config.circulation_fan_entity = "fan.circulation"
    mock_growspace.environment_config.soil_moisture_sensor = "sensor.moisture"

    # Setup States
    hass.states.async_set("fan.exhaust", "on")
    hass.states.async_set("humidifier.room", "off")
    hass.states.async_set("fan.circulation", "on")
    hass.states.async_set("sensor.moisture", "45")

    attrs = serializer._get_environment_attributes(mock_growspace)

    # Exhaust
    assert attrs["exhaust_entity"] == "fan.exhaust"
    assert attrs["exhaust_state"] == "on"

    # Humidifier
    assert attrs["humidifier_entity"] == "humidifier.room"
    assert attrs["humidifier_state"] == "off"

    # Circulation Fan
    assert attrs["circulation_fan_entity"] == "fan.circulation"
    assert attrs["circulation_fan_state"] == "on"

    # Soil Moisture
    assert attrs["soil_moisture_sensor"] == "sensor.moisture"
    assert attrs["soil_moisture_value"] == "45"


def test_get_environment_attributes_missing_states(
    hass: HomeAssistant, serializer, mock_growspace
) -> None:
    """Test environment attributes when entities are missing states."""
    # Setup Entity IDs
    mock_growspace.environment_config.exhaust_fan_entity = "fan.exhaust_missing"
    mock_growspace.environment_config.humidifier_entity = "humidifier.missing"
    mock_growspace.environment_config.circulation_fan_entity = "fan.circulation_missing"
    mock_growspace.environment_config.soil_moisture_sensor = "sensor.moisture_missing"

    # DO NOT set states (simulate missing)

    attrs = serializer._get_environment_attributes(mock_growspace)

    # Exhaust
    assert attrs["exhaust_entity"] == "fan.exhaust_missing"
    assert attrs["exhaust_state"] is None

    # Humidifier
    assert attrs["humidifier_entity"] == "humidifier.missing"
    assert attrs["humidifier_state"] is None

    # Circulation Fan
    assert attrs["circulation_fan_entity"] == "fan.circulation_missing"
    assert attrs["circulation_fan_state"] is None

    # Soil Moisture
    assert attrs["soil_moisture_sensor"] == "sensor.moisture_missing"
    assert attrs["soil_moisture_value"] is None


def test_serialize_special_growspace_types(
    hass: HomeAssistant, serializer, mock_growspace
) -> None:
    """Test serialization of special growspace types."""
    special_types = ["mother", "clone", "dry", "cure"]
    plants = []
    analyzer = MagicMock()
    analyzer.calculate_biological_metrics.return_value = {}

    with patch("homeassistant.helpers.entity_registry.async_get") as mock_reg:
        mock_reg.return_value.async_get_entity_id.return_value = "sensor.overview"

        for gs_type in special_types:
            mock_growspace.id = gs_type
            data = serializer.serialize_growspace(mock_growspace, plants, analyzer)
            assert data["type"] == gs_type


def test_serialize_growspace_legacy_entity_id(
    hass: HomeAssistant, serializer, mock_growspace
) -> None:
    """Test legacy entity ID generation fallback."""
    plants = []
    analyzer = MagicMock()
    analyzer.calculate_biological_metrics.return_value = {}

    with patch("homeassistant.helpers.entity_registry.async_get") as mock_reg:
        # Simulate registry returning None (not found)
        mock_reg.return_value.async_get_entity_id.return_value = None

        mock_growspace.name = "My Grow Room"
        mock_growspace.id = "gs_legacy"

        data = serializer.serialize_growspace(mock_growspace, plants, analyzer)

        # Should fallback to slugified name
        assert data["overview_entity_id"] == "sensor.my_grow_room"


def test_serialize_plant_lookup_entity_id(
    hass: HomeAssistant, serializer, mock_plant
) -> None:
    """Test serialize_plant looking up entity ID when not provided."""
    with patch("homeassistant.helpers.entity_registry.async_get") as mock_reg_get:
        mock_reg = MagicMock()
        mock_reg.async_get_entity_id.return_value = "sensor.found_entity_id"
        mock_reg_get.return_value = mock_reg

        data = serializer.serialize_plant(mock_plant, entity_id=None)

        assert data["entity_id"] == "sensor.found_entity_id"
        mock_reg.async_get_entity_id.assert_called_with(
            "sensor", "growspace_manager", "growspace_manager_plant1"
        )


def test_serialize_plant_with_training_and_watering(
    serializer: GrowspaceSerializer, mock_plant: Plant
) -> None:
    """Test that serialize_plant includes training and watering fields."""
    timestamp = dt_util.now().isoformat()
    mock_plant.last_watered = timestamp
    mock_plant.last_trained = timestamp
    mock_plant.last_training_technique = "Topping"
    mock_plant.get_days_since_watering.return_value = 5

    data = serializer.serialize_plant(mock_plant, entity_id="sensor.plant1")

    # format_date returns only the date part
    assert data["last_watered"] == timestamp.split("T")[0]
    assert data["last_trained"] == timestamp.split("T")[0]
    assert data["last_training_technique"] == "Topping"
    assert data["days_since_last_watering"] == 5
