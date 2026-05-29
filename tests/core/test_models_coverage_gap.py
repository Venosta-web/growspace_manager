"""Targeted tests to cover missing lines in models.py."""

from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    Plant,
    PlantGenetics,
    SeedBatch,
    _sanitize_numeric_fields,
)


def test_environment_config_migration_none_value() -> None:
    """Test migration with None value (Line 289)."""
    # Line 284: if old_key in data and new_key not in data
    # Line 286: if val: (is False for None/empty)
    # Line 289: data[new_key] = []
    data = {
        "temperature_sensor": None,
    }
    # We need to trigger __pre_deserialize__ via from_dict
    config = EnvironmentConfig.from_dict(data)
    assert config.temperature_sensors == []


def test_growspace_invalid_veg_day_hours() -> None:
    """Test Growspace deserialization with invalid non-numeric veg_day_hours (Lines 397-398)."""
    data = {
        "id": "gs1",
        "name": "Test",
        "irrigation_config": {"veg_day_hours": "not_a_number"},
    }
    gs = Growspace.from_dict(data)
    assert gs.irrigation_config.veg_day_hours == 12


def test_plant_genetics_key_property() -> None:
    """Test PlantGenetics key property (Line 470)."""
    # Coverage for: return f"{self.strain_name}_{self.phenotype_name}" if self.phenotype_name else self.strain_name

    # Case 1: With phenotype
    gen = PlantGenetics(strain_name="Blue Dream", phenotype_name="Pheno 1")
    assert gen.key == "Blue Dream_Pheno 1"

    # Case 2: Without phenotype
    gen2 = PlantGenetics(strain_name="Blue Dream", phenotype_name="")
    assert gen2.key == "Blue Dream"


def test_seed_batch_none_quantity_uses_zero() -> None:
    """Test SeedBatch.from_dict with None quantity hits the no-default fallback (models.py:143)."""
    data = {
        "batch_id": "b1",
        "strain_name": "Test Strain",
        "breeder": "TestBreeder",
        "quantity": None,
        "acquisition_date": "2024-01-01",
        "generation": "F1",
        "lineage": "unknown",
    }
    batch = SeedBatch.from_dict(data)
    assert batch.quantity == 0


def test_seed_batch_invalid_quantity_uses_zero() -> None:
    """Test SeedBatch.from_dict with invalid string quantity hits conversion-error fallback (models.py:152)."""
    data = {
        "batch_id": "b1",
        "strain_name": "Test Strain",
        "breeder": "TestBreeder",
        "quantity": "not_a_number",
        "acquisition_date": "2024-01-01",
        "generation": "F1",
        "lineage": "unknown",
    }
    batch = SeedBatch.from_dict(data)
    assert batch.quantity == 0


def test_growspace_dict_rows_uses_default() -> None:
    """Test Growspace.from_dict with non-numeric rows (dict) hits except fallback (models.py:597-598).

    _sanitize_numeric_fields only coerces float/str; passing a dict bypasses it
    and reaches the Growspace-level try/except which then falls back to 3.
    """
    data = {
        "id": "gs1",
        "name": "Test",
        "rows": {"bad": "value"},
        "plants_per_row": [1, 2, 3],
    }
    gs = Growspace.from_dict(data)
    assert gs.rows == 3
    assert gs.plants_per_row == 3


def test_environment_config_null_list_fields_coerced_to_empty() -> None:
    """Null list fields in stored JSON are coerced to [] by __post_init__."""
    data = {
        "ph_sensors": None,
        "feed_ec_sensors": None,
        "runoff_ec_sensors": None,
        "temperature_sensors": None,
        "irrigation_tanks": None,
    }
    config = EnvironmentConfig.from_dict(data)
    assert config.ph_sensors == []
    assert config.feed_ec_sensors == []
    assert config.runoff_ec_sensors == []
    assert config.temperature_sensors == []
    assert config.irrigation_tanks == []


def test_growspace_null_environment_config_uses_default() -> None:
    """Test that null environment_config in stored JSON is coerced to empty EnvironmentConfig."""
    data = {"id": "gs1", "name": "Tent 1", "environment_config": None}
    gs = Growspace.from_dict(data)
    assert isinstance(gs.environment_config, EnvironmentConfig)
    assert gs.environment_config.ph_sensors == []
    assert gs.environment_config.temperature_sensors == []


def test_plant_dict_row_col_uses_default() -> None:
    """Test Plant.from_dict with non-numeric row/col (dict) hits except fallback (models.py:818-819).

    _sanitize_numeric_fields only coerces float/str; passing a dict bypasses it
    and reaches the Plant-level try/except which then falls back to 1.
    """
    data = {
        "plant_id": "p1",
        "growspace_id": "gs1",
        "row": {"bad": "value"},
        "col": [1, 2],
    }
    plant = Plant.from_dict(data)
    assert plant.row == 1
    assert plant.col == 1
