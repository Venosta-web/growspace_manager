from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    IrrigationStrategy,
)


def test_environment_config_none_fix():
    print("Testing EnvironmentConfig None fix...")
    data = {
        "electricity_cost_per_kwh": None,
        "dli_target_veg": None,
        "dli_target_flower": None,
        "lst_offset": None,
    }
    # This should NOT crash now
    ec = EnvironmentConfig.from_dict(data)
    assert ec.electricity_cost_per_kwh == 0.0
    assert ec.dli_target_veg == 30.0
    assert ec.dli_target_flower == 45.0
    assert ec.lst_offset == -2.0


def test_growspace_none_fix():
    print("Testing Growspace None fix...")
    data = {
        "id": "test-gs",
        "name": "Test Growspace",
        "rows": None,
        "plants_per_row": None,
    }
    gs = Growspace.from_dict(data)
    # The current implementation in models.py specifically handles strings for rows/plants_per_row
    # but my new generic fix will set them to 0 (default for int) if None is passed.
    # Wait, in Growspace.__pre_deserialize__, there is:
    # try: data[field_name] = int(float(data[field_name]))
    # except (ValueError, TypeError): data[field_name] = 3
    # So if I pass None, it should be 3 because of the catch-all in Growspace.__pre_deserialize__.
    assert gs.rows == 3
    assert gs.plants_per_row == 3


def test_nested_model_none_fix():
    """Test that nested models (like IrrigationStrategy) also benefit from the fix."""

    data = {
        "p0_duration_minutes": None,  # int
        "target_vwc_percent": None,  # float
    }
    # IrrigationStrategy inherits from BaseModel and doesn't have its own __pre_deserialize__
    # so it uses the one I added to BaseModel.
    config = IrrigationStrategy.from_dict(data)
    assert config.p0_duration_minutes == 60  # Default value
    assert config.target_vwc_percent == 55.0  # Default value


def test_environment_config_float_handling():
    """Test that EnvironmentConfig handles float values for integer fields."""
    data = {
        "veg_day_hours": 18.0,
        "flower_day_hours": 12.0,
    }
    obj = EnvironmentConfig.from_dict(data)
    assert obj.veg_day_hours == 18
    assert obj.flower_day_hours == 12


def test_growspace_float_handling():
    """Test that Growspace handles float values for integer fields."""
    data = {
        "id": "test-uuid",
        "name": "test",
        "rows": 4.0,
        "plants_per_row": 5.0,
    }
    obj = Growspace.from_dict(data)
    assert obj.rows == 4
    assert obj.plants_per_row == 5
