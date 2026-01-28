"""Targeted tests to cover missing lines in models.py."""

from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    PlantGenetics,
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
