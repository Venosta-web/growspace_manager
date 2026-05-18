"""Tests for the data models in models.py."""

from unittest.mock import patch

from .common import create_plant
import pytest

from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    EnvironmentState,
    Growspace,
    GrowspaceEvent,
    IrrigationStrategy,
    Plant,
    Subarea,
    VisionCheckupConfig,
    VisionCheckupResult,
)

# --------------------
# Growspace Model Tests
# --------------------


def test_growspace_to_dict() -> None:
    """Test Growspace to_dict method."""
    growspace = Growspace(id="gs1", name="Test Growspace", rows=2, plants_per_row=2)
    data = growspace.to_dict()
    assert data["id"] == "gs1"
    assert data["name"] == "Test Growspace"
    assert data["rows"] == 2
    assert data["plants_per_row"] == 2


def test_growspace_from_dict_basic() -> None:
    """Test Growspace from_dict with basic data."""
    data = {"id": "gs1", "name": "Test Growspace", "rows": 2, "plants_per_row": 2}
    growspace = Growspace.from_dict(data)
    assert growspace.id == "gs1"
    assert growspace.name == "Test Growspace"
    assert growspace.rows == 2
    assert growspace.plants_per_row == 2


def test_growspace_from_dict_with_extra_fields() -> None:
    """Test Growspace from_dict with extra, unrecognized fields."""
    data = {"id": "gs1", "name": "Test Growspace", "extra_field": "value"}
    growspace = Growspace.from_dict(data)
    assert growspace.id == "gs1"
    assert "extra_field" not in growspace.to_dict()


# --------------------
# Plant Model Tests
# --------------------


def test_plant_to_dict() -> None:
    """Test Plant to_dict method."""
    plant = create_plant(plant_id="p1", growspace_id="gs1", strain="OG Kush")
    data = plant.to_dict()
    assert data["plant_id"] == "p1"
    assert data["growspace_id"] == "gs1"
    assert data["genetics"]["strain_name"] == "OG Kush"


def test_plant_from_dict_migration() -> None:
    """Test Plant migration from legacy flat structure."""
    data = {
        "plant_id": "p1",
        "growspace_id": "gs1",
        "strain": "Legacy Strain",  # Flat field
        "phenotype": "Legacy Pheno",  # Flat field
        "stage": "veg",
    }

    plant = Plant.from_dict(data)

    # Check proper migration
    assert plant.genetics.strain_name == "Legacy Strain"
    assert plant.genetics.phenotype_name == "Legacy Pheno"

    # Check backward compatibility properties
    assert plant.strain == "Legacy Strain"
    assert plant.phenotype == "Legacy Pheno"

    # Ensure flat fields are NOT in serialized output (clean migration)
    serialized = plant.to_dict()
    assert "strain" not in serialized
    assert "phenotype" not in serialized
    assert serialized["genetics"]["strain_name"] == "Legacy Strain"


def test_plant_from_dict_basic() -> None:
    """Test Plant from_dict with basic data."""
    data = {"plant_id": "p1", "growspace_id": "gs1", "strain": "OG Kush"}
    plant = Plant.from_dict(data)
    assert plant.plant_id == "p1"
    assert plant.growspace_id == "gs1"
    assert plant.strain == "OG Kush"


def test_plant_from_dict_with_extra_fields() -> None:
    """Test Plant from_dict with extra, unrecognized fields."""
    data = {
        "plant_id": "p1",
        "growspace_id": "gs1",
        "strain": "OG",
        "extra_field": "value",
    }
    plant = Plant.from_dict(data)
    assert plant.plant_id == "p1"
    assert "extra_field" not in plant.to_dict()


# --------------------
# EnvironmentState Model Tests
# --------------------


def test_environment_state_basic() -> None:
    """Test EnvironmentState dataclass basic instantiation."""
    env_state = EnvironmentState(
        temp=25.0,
        humidity=60.0,
        vpd=1.2,
        co2=400.0,
        veg_days=10,
        flower_days=-1,
        seedling_days=-1,
        clone_days=-1,
        is_lights_on=True,
        fan_off=False,
    )
    assert env_state.temp == 25.0
    assert env_state.humidity == 60.0
    assert env_state.vpd == 1.2
    assert env_state.co2 == 400.0
    assert env_state.veg_days == 10
    assert env_state.flower_days == -1
    assert env_state.seedling_days == -1
    assert env_state.clone_days == -1
    assert env_state.is_lights_on is True
    assert env_state.fan_off is False


def test_environment_state_none_values() -> None:
    """Test EnvironmentState with None values for optional fields."""
    env_state = EnvironmentState(
        temp=None,
        humidity=None,
        vpd=None,
        co2=None,
        veg_days=-1,
        flower_days=-1,
        seedling_days=-1,
        clone_days=-1,
        is_lights_on=False,
        fan_off=True,
    )
    assert env_state.temp is None
    assert env_state.humidity is None
    assert env_state.vpd is None
    assert env_state.co2 is None
    assert env_state.veg_days == -1
    assert env_state.flower_days == -1
    assert env_state.seedling_days == -1
    assert env_state.clone_days == -1
    assert env_state.is_lights_on is False
    assert env_state.fan_off is True


# --------------------
# GrowspaceEvent Model Tests
# --------------------


def test_growspace_event_to_dict() -> None:
    """Test GrowspaceEvent to_dict method."""
    event = GrowspaceEvent(
        sensor_type="test_sensor",
        growspace_id="gs1",
        start_time="2023-01-01T12:00:00",
        end_time="2023-01-01T12:05:00",
        duration_sec=300,
        severity=0.8,
        category="alert",
        reasons=["Reason 1"],
    )
    data = event.to_dict()
    assert data["sensor_type"] == "test_sensor"
    assert data["severity"] == 0.8
    assert data["category"] == "alert"


def test_growspace_event_from_dict_basic() -> None:
    """Test GrowspaceEvent from_dict with basic data."""
    data = {
        "sensor_type": "test_sensor",
        "growspace_id": "gs1",
        "start_time": "2023-01-01T12:00:00",
        "end_time": "2023-01-01T12:05:00",
        "duration_sec": 300,
        "severity": 0.8,
        "category": "alert",
        "reasons": ["Reason 1"],
    }
    event = GrowspaceEvent.from_dict(data)
    assert event.severity == 0.8
    assert event.category == "alert"


def test_growspace_event_defaults() -> None:
    """Test GrowspaceEvent defaults are applied."""
    data = {
        "sensor_type": "test_sensor",
        "growspace_id": "gs1",
        "start_time": "2023-01-01T12:00:00",
        "end_time": "2023-01-01T12:05:00",
        "duration_sec": 300,
        "severity": 0.5,
        # "category" missing, should default to "alert"
    }
    event = GrowspaceEvent.from_dict(data)
    assert event.category == "alert"


def test_growspace_event_from_dict_with_extra_fields() -> None:
    """Test GrowspaceEvent from_dict with extra, unrecognized fields."""
    data = {
        "sensor_type": "test_sensor",
        "growspace_id": "gs1",
        "start_time": "2023-01-01T12:00:00",
        "end_time": "2023-01-01T12:05:00",
        "duration_sec": 300,
        "severity": 0.8,
        "category": "alert",
        "reasons": ["Reason 1"],
        "extra_field": "value",
    }
    event = GrowspaceEvent.from_dict(data)
    assert event.severity == 0.8
    assert "extra_field" not in event.to_dict()


# --------------------
# Coverage Gaps
# --------------------


def test_environment_config_catch_all() -> None:
    """Test EnvironmentConfig catch-all field (bayesian_options)."""
    # Create from dict with extra fields, which should go into bayesian_options
    data = {
        "temperature_sensor": "sensor.temp",
        "extra_option_1": "value1",
        "extra_option_2": 123,
    }

    config = EnvironmentConfig.from_dict(data)

    assert config.temperature_sensor == "sensor.temp"
    # Verify extra fields ended up in bayesian_options
    assert "extra_option_1" in config.bayesian_options
    assert config.bayesian_options["extra_option_1"] == "value1"
    assert config.bayesian_options["extra_option_2"] == 123

    # Test when catch-all field is already present in input
    data_with_existing = {
        "temperature_sensor": "sensor.temp",
        "bayesian_options": {"existing_opt": True},
        "extra_option_1": "value1",
    }
    config_existing = EnvironmentConfig.from_dict(data_with_existing)
    assert config_existing.bayesian_options["existing_opt"] is True
    assert config_existing.bayesian_options["extra_option_1"] == "value1"

    # Test when catch-all field is None in input
    data_none = {
        "temperature_sensor": "sensor.temp",
        "bayesian_options": None,
        "extra_option_1": "value1",
    }
    config_none = EnvironmentConfig.from_dict(data_none)
    assert config_none.bayesian_options["extra_option_1"] == "value1"

    # Test when catch-all field is invalid type in input
    data_invalid = {
        "temperature_sensor": "sensor.temp",
        "bayesian_options": "invalid_string",
        "extra_option_1": "value1",
    }
    config_invalid = EnvironmentConfig.from_dict(data_invalid)
    assert config_invalid.bayesian_options["extra_option_1"] == "value1"
    assert isinstance(config_invalid.bayesian_options, dict)


def test_growspace_nested_handlers() -> None:
    """Test nested handlers in Growspace.from_dict."""
    # 1. Test dictionary conversion for nested field
    data = {
        "id": "gs1",
        "name": "GS",
        "irrigation_strategy": {"enabled": True, "target_vwc_percent": 60.0},
    }
    gs = Growspace.from_dict(data)
    assert isinstance(gs.irrigation_strategy, IrrigationStrategy)
    assert gs.irrigation_strategy.enabled is True
    assert gs.irrigation_strategy.target_vwc_percent == 60.0


def test_plant_days_and_weeks_in_stage() -> None:
    """Test Plant get_days_in_stage and get_week_in_stage."""

    # Mock utils.calculate_days_since to control time
    with patch(
        "custom_components.growspace_manager.models.calculate_days_since"
    ) as mock_calc:
        plant = create_plant(
            plant_id="p1",
            growspace_id="gs1",
            strain="Strain",
            veg_start="2023-01-01T12:00:00",
        )

        # 1. Test stage that exists
        mock_calc.return_value = 14
        assert plant.get_days_in_stage("veg") == 14
        mock_calc.assert_called_with("2023-01-01T12:00:00")

        # 14 days = 2 weeks
        # Implementation of days_to_week usually: days // 7 + 1 or similar logic
        # models.py imports days_to_week from utils. Let's assume standard behavior.
        # If models.py calls utils.days_to_week(14), we implicitly test integration.
        # But we mocked calculate_days_since, not days_to_week.

        # We need to control days_to_week return if we want to isolate models.py logic fully,
        # but models.py just delegates. Let's trust utils or patch it too if needed.
        # Actually simplest is just to verify the call flow.

        # Test get_week_in_stage
        with patch(
            "custom_components.growspace_manager.models.days_to_week"
        ) as mock_week:
            mock_week.return_value = 3
            assert plant.get_week_in_stage("veg") == 3
            mock_week.assert_called_with(14)  # Passed result from get_days_in_stage

        # 2. Test stage that does not exist (date is None)
        assert plant.get_days_in_stage("flower") == 0

        # 3. Test stage that exists but value is None/Empty (just in case)
        plant.veg_start = None
        assert plant.get_days_in_stage("veg") == 0


def test_environment_config_migration() -> None:
    """Test EnvironmentConfig migration from single entities to lists."""
    data = {
        "light_sensor": "sensor.light",
        "exhaust_fan_entity": "fan.exhaust",
        "circulation_fan_entity": "fan.circulation",
        "humidifier_entity": "humidifier.test",
        "dehumidifier_entity": "switch.dehumidifier",
        # New fields missing, should be populated from above
    }

    config = EnvironmentConfig.from_dict(data)

    # Check migration to lists
    assert config.light_sensors == ["sensor.light"]
    assert config.exhaust_fan_entities == ["fan.exhaust"]
    assert config.circulation_fan_entities == ["fan.circulation"]
    assert config.humidifier_entities == ["humidifier.test"]
    assert config.dehumidifier_entities == ["switch.dehumidifier"]

    # Check backward compatibility properties
    assert config.light_sensor == "sensor.light"
    assert config.exhaust_fan_entity == "fan.exhaust"
    assert config.circulation_fan_entity == "fan.circulation"
    assert config.humidifier_entity == "humidifier.test"
    assert config.dehumidifier_entity == "switch.dehumidifier"

    # Test initialization with lists already present
    data_lists = {
        "light_sensors": ["sensor.light_1", "sensor.light_2"],
        "exhaust_fan_entities": ["fan.exhaust_1", "fan.exhaust_2"],
    }
    config_lists = EnvironmentConfig.from_dict(data_lists)

    # Lists should be preserved
    assert len(config_lists.light_sensors) == 2
    assert "sensor.light_1" in config_lists.light_sensors
    assert "sensor.light_2" in config_lists.light_sensors

    # Properties should return first element
    assert config_lists.light_sensor == "sensor.light_1"
    assert config_lists.exhaust_fan_entity == "fan.exhaust_1"


@pytest.mark.asyncio
async def test_growspace_migration_redundant_irrigation_fields() -> None:
    """Test Growspace migration when redundant legacy fields exist."""
    data = {
        "id": "gs1",
        "name": "GS",
        "irrigation_config": {
            "irrigation_times": [
                {
                    "time": "10:00",
                    "start_time": "10:00",
                    "duration": 60,
                    "duration_seconds": 60,
                }
            ]
        },
    }
    gs = Growspace.from_dict(data)
    # The migration should delete 'start_time' and 'duration_seconds'
    # because 'time' and 'duration' already exist.
    assert gs.irrigation_config.irrigation_times[0]["time"] == "10:00"
    assert "start_time" not in gs.irrigation_config.irrigation_times[0]
    assert gs.irrigation_config.irrigation_times[0]["duration"] == 60
    assert "duration_seconds" not in gs.irrigation_config.irrigation_times[0]


# --------------------
# VisionCheckup Model Tests
# --------------------


def test_vision_checkup_result_creation():
    """Test VisionCheckupResult dataclass creation."""
    result = VisionCheckupResult(
        timestamp="2026-03-21T07:00:00",
        growspace_id="tent1",
        check_type="early",
        snapshot_paths=["/local/growspace_manager/snapshots/tent1/20260321_070000_cam1.jpg"],
        analysis="Plants look healthy, no issues detected.",
        issues_detected=[],
        severity="none",
        recommendations=[],
    )
    assert result.growspace_id == "tent1"
    assert result.check_type == "early"
    assert result.severity == "none"
    assert result.issues_detected == []


def test_vision_checkup_result_defaults():
    """Test VisionCheckupResult default values."""
    result = VisionCheckupResult(
        timestamp="2026-03-21T07:00:00",
        growspace_id="tent1",
        check_type="mid",
    )
    assert result.snapshot_paths == []
    assert result.analysis == ""
    assert result.issues_detected == []
    assert result.severity == "none"
    assert result.recommendations == []


def test_vision_checkup_config_creation():
    """Test VisionCheckupConfig dataclass creation."""
    config = VisionCheckupConfig()
    assert config.enabled is False
    assert config.early_check_offset_minutes == 60
    assert config.mid_check_hours == 6
    assert config.late_check_offset_minutes == 60
    assert config.history_limit == 10


def test_vision_checkup_config_serialization():
    """Test VisionCheckupConfig round-trips through mashumaro."""
    config = VisionCheckupConfig(enabled=True, history_limit=5)
    data = config.to_dict()
    restored = VisionCheckupConfig.from_dict(data)
    assert restored.enabled is True
    assert restored.history_limit == 5


def test_vision_checkup_result_serialization():
    """Test VisionCheckupResult serializes and deserializes correctly."""
    original = VisionCheckupResult(
        timestamp="2026-03-21T07:00:00",
        growspace_id="tent1",
        check_type="mid",
        analysis="Spider mites detected on lower leaves.",
        issues_detected=["spider_mites"],
        severity="medium",
        recommendations=["Apply neem oil spray immediately."],
    )
    data = original.to_dict()
    restored = VisionCheckupResult.from_dict(data)
    assert restored.analysis == "Spider mites detected on lower leaves."
    assert restored.issues_detected == ["spider_mites"]
    assert restored.severity == "medium"


def test_environment_config_has_vision_checkup_config():
    """Test EnvironmentConfig includes vision checkup config."""
    env = EnvironmentConfig()
    assert isinstance(env.vision_checkup_config, VisionCheckupConfig)
    assert env.vision_checkup_config.enabled is False


def test_growspace_has_vision_checkup_history():
    """Test Growspace model includes vision checkup history defaulting to empty."""
    gs = Growspace(id="tent1", name="Tent 1")
    assert gs.vision_checkup_history == []


def test_growspace_vision_checkup_history_serialization():
    """Test Growspace with vision checkup history round-trips through serialization."""
    result = VisionCheckupResult(
        timestamp="2026-03-21T07:00:00",
        growspace_id="tent1",
        check_type="early",
        analysis="All good.",
        issues_detected=[],
        severity="none",
        recommendations=[],
    )
    gs = Growspace(id="tent1", name="Tent 1")
    gs.vision_checkup_history = [result]

    data = gs.to_dict()
    restored = Growspace.from_dict(data)
    assert len(restored.vision_checkup_history) == 1
    assert restored.vision_checkup_history[0].growspace_id == "tent1"
    assert restored.vision_checkup_history[0].severity == "none"


# --------------------
# Subarea Model Tests
# --------------------


def test_subarea_creation() -> None:
    """Test Subarea dataclass creation with defaults."""
    sub = Subarea(id="sub1", name="Undercanopy")
    assert sub.id == "sub1"
    assert sub.name == "Undercanopy"
    assert isinstance(sub.environment_config, EnvironmentConfig)


def test_subarea_to_dict() -> None:
    """Test Subarea serializes to dict correctly."""
    sub = Subarea(id="sub1", name="Undercanopy")
    data = sub.to_dict()
    assert data["id"] == "sub1"
    assert data["name"] == "Undercanopy"
    assert "environment_config" in data


def test_subarea_from_dict() -> None:
    """Test Subarea deserializes from dict correctly."""
    data = {"id": "sub1", "name": "Undercanopy"}
    sub = Subarea.from_dict(data)
    assert sub.id == "sub1"
    assert sub.name == "Undercanopy"
    assert isinstance(sub.environment_config, EnvironmentConfig)


def test_subarea_from_dict_with_environment_config() -> None:
    """Test Subarea deserializes with nested environment_config."""
    data = {
        "id": "sub1",
        "name": "Undercanopy",
        "environment_config": {"temperature_sensors": ["sensor.under_temp"]},
    }
    sub = Subarea.from_dict(data)
    assert sub.environment_config.temperature_sensors == ["sensor.under_temp"]


def test_growspace_subareas_default_empty() -> None:
    """Test that Growspace.subareas defaults to an empty list."""
    gs = Growspace(id="gs1", name="Tent 1")
    assert gs.subareas == []


def test_growspace_with_subareas_roundtrip() -> None:
    """Test Growspace with subareas round-trips through serialization."""
    gs = Growspace(id="gs1", name="Tent 1")
    gs.subareas = [Subarea(id="sub1", name="Undercanopy")]
    data = gs.to_dict()
    restored = Growspace.from_dict(data)
    assert len(restored.subareas) == 1
    assert restored.subareas[0].name == "Undercanopy"
    assert restored.subareas[0].id == "sub1"


def test_growspace_from_dict_legacy_no_subareas() -> None:
    """Test that loading legacy Growspace data without subareas defaults to []."""
    data = {"id": "gs1", "name": "Old Tent"}
    gs = Growspace.from_dict(data)
    assert gs.subareas == []
