"""Tests for serializers."""

from datetime import timedelta
from unittest.mock import MagicMock, Mock, patch

from common import create_plant
import pytest

from custom_components.growspace_manager.const import PlantStage
from custom_components.growspace_manager.models import (
    DehumidifierThresholds,
    EnvironmentConfig,
    Growspace,
    IrrigationConfig,
    IrrigationStrategy,
    Plant,
)
from custom_components.growspace_manager.serializers import GrowspaceSerializer
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util


@pytest.fixture
def serializer(hass: HomeAssistant):
    """Return a serializer instance."""
    return GrowspaceSerializer(hass)


@pytest.fixture
def mock_growspace(hass: HomeAssistant):
    """Return a mock growspace."""
    gs = MagicMock()
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
        light_sensors=["binary_sensor.light"],
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
    mock_growspace.environment_config.dehumidifier_entities = ["switch.dehum"]
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

    biological_metrics = {
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

        data = serializer.serialize_growspace(
            mock_growspace,
            plants,
            biological_metrics,
            max_veg_days=10,
        )

        assert data["growspace_id"] == "gs1"
        assert data["total_plants"] == 1
        assert data["veg_week"] >= 1
        assert "grid" in data
        assert data["grid"]["position_1_1"]["plant_id"] == "plant1"
        assert data["vpd_status"] == "optimal"


def test_get_environment_attributes_with_thresholds(
    hass: HomeAssistant, serializer: GrowspaceSerializer, mock_growspace: Growspace
) -> None:
    """Test fetching environment attributes with dehumidifier thresholds."""
    # Mock Dehumidifier with attributes including thresholds
    thresholds: DehumidifierThresholds = {"veg": {"day": {"on": 1.2, "off": 1.5}}}

    hass.states.async_set(
        "switch.dehum",
        "on",
        attributes={"dehumidifier_control_enabled": True},
    )
    mock_growspace.environment_config.dehumidifier_entities = ["switch.dehum"]
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
    mock_growspace.environment_config.exhaust_fan_entities = ["fan.exhaust"]
    mock_growspace.environment_config.humidifier_entities = ["humidifier.room"]
    mock_growspace.environment_config.circulation_fan_entities = ["fan.circulation"]
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
    mock_growspace.environment_config.exhaust_fan_entities = ["fan.exhaust_missing"]
    mock_growspace.environment_config.humidifier_entities = ["humidifier.missing"]
    mock_growspace.environment_config.circulation_fan_entities = [
        "fan.circulation_missing"
    ]
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
    plants: list[Plant] = []
    analyzer = MagicMock()
    analyzer.calculate_biological_metrics.return_value = {}

    with patch("homeassistant.helpers.entity_registry.async_get") as mock_reg:
        mock_reg.return_value.async_get_entity_id.return_value = "sensor.overview"

        for gs_type in special_types:
            mock_growspace.id = gs_type
            data = serializer.serialize_growspace(mock_growspace, plants, {})
            assert data["type"] == gs_type


def test_serialize_growspace_legacy_entity_id(
    hass: HomeAssistant, serializer, mock_growspace
) -> None:
    """Test legacy entity ID generation fallback."""
    plants: list[Plant] = []
    analyzer = MagicMock()
    analyzer.calculate_biological_metrics.return_value = {}

    with patch("homeassistant.helpers.entity_registry.async_get") as mock_reg:
        # Simulate registry returning None (not found)
        mock_reg.return_value.async_get_entity_id.return_value = None

        mock_growspace.name = "My Grow Room"
        mock_growspace.id = "gs_legacy"

        data = serializer.serialize_growspace(
            mock_growspace, plants, analyzer.calculate_biological_metrics.return_value
        )

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
    mock_plant.last_trained = timestamp
    mock_plant.last_training_technique = "Topping"
    mock_plant.last_watered = timestamp
    mock_plant.get_days_since_watering = Mock(return_value=5)  # type: ignore[method-assign]

    data = serializer.serialize_plant(mock_plant, entity_id="sensor.plant1")

    # format_date returns only the date part
    assert data["last_watered"] == timestamp.split("T")[0]
    assert data["last_trained"] == timestamp.split("T")[0]
    assert data["last_training_technique"] == "Topping"
    assert data["days_since_last_watering"] == 5


def test_deserialize_plants(serializer: GrowspaceSerializer) -> None:
    """Test deserialize_plants."""
    raw_data = {
        "plant1": {
            "plant_id": "plant1",
            "growspace_id": "gs1",
            "strain": "Test Strain",
            "phenotype": "Alpha",
            "row": 1,
            "col": 1,
            "stage": "veg",
        },
        "plant2": create_plant(
            plant_id="plant2",
            growspace_id="gs1",
            strain="Strain 2",
            phenotype="Beta",
            row=1,
            col=2,
            stage=PlantStage.FLOWER,
        ),
        "invalid_plant": "invalid_string_data",
        "error_causing_plant": {"missing_required_fields": "true"},
    }

    plants = serializer.deserialize_plants(raw_data)

    assert len(plants) == 2
    assert "plant1" in plants
    assert isinstance(plants["plant1"], Plant)
    assert plants["plant1"].strain == "Test Strain"

    assert "plant2" in plants
    assert isinstance(plants["plant2"], Plant)
    assert plants["plant2"].strain == "Strain 2"

    assert "invalid_plant" not in plants
    assert "error_causing_plant" not in plants


def test_deserialize_growspaces(serializer: GrowspaceSerializer) -> None:
    """Test deserialize_growspaces."""
    raw_data = {
        "gs1": {
            "id": "gs1",
            "name": "GS 1",
            "rows": 2,
            "plants_per_row": 3,
        },
        "gs2": Growspace(id="gs2", name="GS 2", rows=1, plants_per_row=1),
        "invalid_gs": 12345,
        "error_causing_gs": {"rows": "invalid_number_format"},
    }

    growspaces = serializer.deserialize_growspaces(raw_data)

    assert len(growspaces) == 2
    assert "gs1" in growspaces
    assert isinstance(growspaces["gs1"], Growspace)
    assert growspaces["gs1"].name == "GS 1"

    assert "gs2" in growspaces
    assert isinstance(growspaces["gs2"], Growspace)
    assert growspaces["gs2"].name == "GS 2"

    assert "invalid_gs" not in growspaces
    assert "error_causing_gs" not in growspaces


def test_deserialize_growspaces_irrigation_migration(
    serializer: GrowspaceSerializer,
) -> None:
    """Test data migration for old irrigation config format."""
    raw_data = {
        "gs1": {
            "id": "gs1",
            "name": "GS 1",
            "rows": 2,
            "plants_per_row": 3,
            "irrigation_config": {
                "irrigation_times": [
                    {"time": "08:00:00", "duration": 60},  # Old format
                    {"start_time": "12:00:00", "duration_seconds": 120},  # New format
                ],
                "drain_times": [
                    {"time": "08:10:00", "duration": 30},  # Old format
                ],
            },
        }
    }

    growspaces = serializer.deserialize_growspaces(raw_data)

    assert "gs1" in growspaces
    gs = growspaces["gs1"]

    # Check Irrigation Times
    assert len(gs.irrigation_config.irrigation_times) == 2

    # Item 1 (Migrated)
    item1 = gs.irrigation_config.irrigation_times[0]
    assert item1["start_time"] == "08:00:00"
    assert item1["duration_seconds"] == 60
    assert "time" not in item1
    assert "duration" not in item1

    # Item 2 (Already correct)
    item2 = gs.irrigation_config.irrigation_times[1]
    assert item2["start_time"] == "12:00:00"
    assert item2["duration_seconds"] == 120

    # Check Drain Times (Migrated)
    assert len(gs.irrigation_config.drain_times) == 1
    drain = gs.irrigation_config.drain_times[0]
    assert drain["start_time"] == "08:10:00"
    assert drain["duration_seconds"] == 30


def test_deserialize_growspaces_irrigation_migration_float_strings(
    serializer: GrowspaceSerializer,
) -> None:
    """Test data migration for old irrigation config format with float strings."""
    raw_data = {
        "gs1": {
            "id": "gs1",
            "name": "GS 1",
            "rows": 2,
            "plants_per_row": 3,
            "irrigation_config": {
                "irrigation_times": [
                    {"time": "08:00:00", "duration": "30.0"},  # Str float
                    {
                        "start_time": "12:00:00",
                        "duration_seconds": "45.0",
                    },  # Str float new key
                    {"time": "14:00:00", "duration": 60.0},  # Real float
                ],
            },
        }
    }

    growspaces = serializer.deserialize_growspaces(raw_data)

    assert "gs1" in growspaces
    gs = growspaces["gs1"]

    times = gs.irrigation_config.irrigation_times
    assert len(times) == 3

    # Item 1: "30.0" -> 30
    assert times[0]["duration_seconds"] == 30

    # Item 2: "45.0" -> 45
    assert times[1]["duration_seconds"] == 45

    # Item 3: 60.0 -> 60
    assert times[2]["duration_seconds"] == 60


def test_get_sensor_types(
    serializer: GrowspaceSerializer, mock_growspace: Growspace
) -> None:
    """Test mapping of entity IDs to sensor types."""
    # Setup mixed sensors
    mock_growspace.environment_config.temperature_sensor = "sensor.t1"
    mock_growspace.environment_config.temperature_sensors = ["sensor.t1", "sensor.t2"]
    mock_growspace.environment_config.humidity_sensors = ["sensor.h1"]
    mock_growspace.environment_config.light_sensors = ["sensor.l1"]
    mock_growspace.environment_config.exhaust_fan_entities = ["fan.e1"]
    mock_growspace.environment_config.co2_sensor = "sensor.co2"
    mock_growspace.irrigation_config.irrigation_pump_entity = "switch.irrigation"
    mock_growspace.irrigation_config.drain_pump_entity = "switch.drain"

    sensor_types = serializer._get_sensor_types(mock_growspace)

    assert sensor_types["sensor.t1"] == "temperature"
    assert sensor_types["sensor.t2"] == "temperature"
    assert sensor_types["sensor.h1"] == "humidity"
    assert sensor_types["sensor.l1"] == "light"
    assert sensor_types["fan.e1"] == "exhaust"
    assert sensor_types["sensor.co2"] == "co2"
    assert sensor_types["switch.irrigation"] == "irrigation_pump"
    assert sensor_types["switch.drain"] == "drain_pump"


def test_serialize_growspace_includes_sensor_types(
    hass: HomeAssistant, serializer, mock_growspace, mock_plant
) -> None:
    """Test that serialize_growspace includes the sensor_types map."""
    mock_growspace.environment_config.temperature_sensor = "sensor.temp"

    with patch("homeassistant.helpers.entity_registry.async_get") as mock_registry_get:
        mock_registry = MagicMock()
        mock_registry_get.return_value = mock_registry

        data = serializer.serialize_growspace(
            mock_growspace,
            [mock_plant],
            {},
            max_veg_days=10,
        )

        assert "sensor_types" in data
        assert data["sensor_types"]["sensor.temp"] == "temperature"
