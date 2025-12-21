"""Tests for the data models in models.py."""

from datetime import date
from unittest.mock import patch

from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    EnvironmentState,
    Growspace,
    GrowspaceEvent,
    IrrigationStrategy,
    Plant,
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


def test_growspace_from_dict_with_legacy_created_field() -> None:
    """Test Growspace from_dict with legacy 'created' field."""
    today_iso = date.today().isoformat()
    data = {"id": "gs1", "name": "Test Growspace", "created": today_iso}
    growspace = Growspace.from_dict(data)
    assert growspace.created_at == today_iso
    assert "created" not in growspace.to_dict()


def test_growspace_from_dict_with_legacy_updated_field() -> None:
    """Test Growspace from_dict with legacy 'updated' field."""
    today_iso = date.today().isoformat()
    data = {"id": "gs1", "name": "Test Growspace", "updated": today_iso}
    growspace = Growspace.from_dict(data)
    # 'updated_at' is not a field in Growspace, so it should be filtered out
    assert "updated_at" not in growspace.to_dict()


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
    plant = Plant(plant_id="p1", growspace_id="gs1", strain="OG Kush")
    data = plant.to_dict()
    assert data["plant_id"] == "p1"
    assert data["growspace_id"] == "gs1"
    assert data["strain"] == "OG Kush"


def test_plant_from_dict_basic() -> None:
    """Test Plant from_dict with basic data."""
    data = {"plant_id": "p1", "growspace_id": "gs1", "strain": "OG Kush"}
    plant = Plant.from_dict(data)
    assert plant.plant_id == "p1"
    assert plant.growspace_id == "gs1"
    assert plant.strain == "OG Kush"


def test_plant_from_dict_with_legacy_created_field() -> None:
    """Test Plant from_dict with legacy 'created' field."""
    today_iso = date.today().isoformat()
    data = {
        "plant_id": "p1",
        "growspace_id": "gs1",
        "strain": "OG",
        "created": today_iso,
    }
    plant = Plant.from_dict(data)
    assert plant.created_at == today_iso
    assert "created" not in plant.to_dict()


def test_plant_from_dict_with_legacy_updated_field() -> None:
    """Test Plant from_dict with legacy 'updated' field."""
    today_iso = date.today().isoformat()
    data = {
        "plant_id": "p1",
        "growspace_id": "gs1",
        "strain": "OG",
        "updated": today_iso,
    }
    plant = Plant.from_dict(data)
    assert plant.updated_at == today_iso
    assert "updated" not in plant.to_dict()


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
        flower_days=0,
        is_lights_on=True,
        fan_off=False,
    )
    assert env_state.temp == 25.0
    assert env_state.humidity == 60.0
    assert env_state.vpd == 1.2
    assert env_state.co2 == 400.0
    assert env_state.veg_days == 10
    assert env_state.flower_days == 0
    assert env_state.is_lights_on is True
    assert env_state.fan_off is False


def test_environment_state_none_values() -> None:
    """Test EnvironmentState with None values for optional fields."""
    env_state = EnvironmentState(
        temp=None,
        humidity=None,
        vpd=None,
        co2=None,
        veg_days=0,
        flower_days=0,
        is_lights_on=False,
        fan_off=True,
    )
    assert env_state.temp is None
    assert env_state.humidity is None
    assert env_state.vpd is None
    assert env_state.co2 is None
    assert env_state.veg_days == 0
    assert env_state.flower_days == 0
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


def test_growspace_event_from_dict_legacy() -> None:
    """Test GrowspaceEvent from_dict handles legacy max_probability migration."""
    data = {
        "sensor_type": "test_sensor",
        "growspace_id": "gs1",
        "start_time": "2023-01-01T12:00:00",
        "end_time": "2023-01-01T12:05:00",
        "duration_sec": 300,
        "max_probability": 0.95,  # Legacy field
        "reasons": ["Reason 1"],
        # Missing category
    }
    event = GrowspaceEvent.from_dict(data)
    assert event.severity == 0.95  # Mapped to severity
    assert event.category == "alert"  # Default category


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

    # 2. Test None value (pass-through)
    # Note: default factory usually handles missing keys, but if key exists and is None:
    data_none = {"id": "gs1", "name": "GS", "irrigation_strategy": None}
    gs_none = Growspace.from_dict(data_none)
    # Since None was passed and the handler skipped it, it might remain None
    # or rely on dataclass behavior if field doesn't accept None.
    # In Growspace model: irrigation_strategy: IrrigationStrategy = field(default_factory...)
    # If from_dict passes None to cls(), it might fail if type checking is strict,
    # but let's check what the valid behavior is for coverage.
    # The code says: elif key in data and data[key] is None: pass
    # So data['irrigation_strategy'] remains None.
    # The dataclass init will then receive None for that field.
    assert gs_none.irrigation_strategy is None


def test_plant_days_and_weeks_in_stage() -> None:
    """Test Plant get_days_in_stage and get_week_in_stage."""

    # Mock utils.calculate_days_since to control time
    with patch(
        "custom_components.growspace_manager.models.calculate_days_since"
    ) as mock_calc:
        plant = Plant(
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
