"""Coverage tests for models.py."""

from custom_components.growspace_manager.models import Growspace, NutrientPreset, Plant


def test_growspace_deserialize_invalid_integers() -> None:
    """Test Growspace deserialization with invalid integer strings."""
    data = {
        "id": "gs1",
        "name": "Test",
        "rows": "invalid",
        "plants_per_row": "invalid",
        "irrigation_strategy": {
            "p0_duration_minutes": "invalid",
            "p2_stop_before_lights_off_minutes": "invalid",
            "shot_duration_seconds": "invalid",
            "shot_interval_minutes": "invalid",
        },
    }
    gs = Growspace.from_dict(data)
    assert gs.rows == 3  # Default
    assert gs.plants_per_row == 3  # Default

    # Check strategy fields kept defaults or passed through if that was the logic?
    # The code says:
    # try: strat[f] = int(float(strat[f])) except: pass
    # So if it fails, it keeps the "invalid" string in the dict passed to __init__?
    # Wait, if it's passed to __init__, Mashumaro might complain if types don't match.
    # But let's see. The dataclass has defaults.
    # If the dict has "invalid", Mashumaro tries to coerce?

    # Let's check the code in models.py again.
    # It updates data["irrigation_strategy"] = strat
    # Then returns data.
    # Mashumaro then deserializes.

    # Actually, if the type in dataclass is int, and we pass "invalid",
    # Mashumaro might raise an error if Config is not set to ignore.
    # But let's try running this test to see behavior.


def test_plant_deserialize_invalid_integers() -> None:
    """Test Plant deserialization with invalid integer strings."""
    data = {
        "plant_id": "p1",
        "growspace_id": "gs1",
        "row": "invalid",
        "col": "invalid",
    }
    plant = Plant.from_dict(data)
    assert plant.row == 1  # Default
    assert plant.col == 1  # Default


def test_plant_stage_history_end_date() -> None:
    """Test Plant stage history generation with end dates."""
    data = {
        "plant_id": "p1",
        "growspace_id": "gs1",
        "veg_start": "2023-01-01T00:00:00",
        "flower_start": "2023-02-01T00:00:00",
        "dry_start": "2023-04-01T00:00:00",
    }
    plant = Plant.from_dict(data)

    history = plant.stage_history
    assert len(history) == 3

    # Veg should end when Flower starts
    veg = next(h for h in history if h["stage"] == "veg")
    assert veg["start"] == "2023-01-01T00:00:00"
    assert veg["end"] == "2023-02-01T00:00:00"

    # Flower should end when Dry starts
    flower = next(h for h in history if h["stage"] == "flower")
    assert flower["start"] == "2023-02-01T00:00:00"
    assert flower["end"] == "2023-04-01T00:00:00"

    # Dry is last, so end is None
    dry = next(h for h in history if h["stage"] == "dry")
    assert dry["start"] == "2023-04-01T00:00:00"
    assert dry["end"] is None


def test_plant_get_days_since_watering_none() -> None:
    """Test get_days_since_watering returns None when never watered."""
    plant = Plant(plant_id="p1", growspace_id="gs1")
    assert plant.get_days_since_watering() is None


def test_plant_get_days_in_stage_not_found() -> None:
    """Test get_days_in_stage returns 0 when stage not found in history or attributes."""
    plant = Plant(plant_id="p1", growspace_id="gs1")
    # No history, no attributes
    assert plant.get_days_in_stage("unknown_stage") == 0

    # History exists but not for this stage
    plant.stage_history = [{"stage": "veg", "start": "2023-01-01"}]
    assert plant.get_days_in_stage("flower") == 0


def test_nutrient_preset_nutrients_setter() -> None:
    """Test NutrientPreset.nutrients setter."""
    preset = NutrientPreset(
        id="np1", name="Test", items=[{"name": "A", "dose_ml_l": 1.0}]
    )

    assert len(preset.nutrients) == 1

    new_items = [{"name": "B", "dose_ml_l": 2.0}]
    preset.nutrients = new_items

    assert len(preset.items) == 1
    assert preset.items[0]["name"] == "B"
    assert preset.nutrients[0]["name"] == "B"


def test_irrigation_config_deserialize_migration() -> None:
    """Test IrrigationConfig migration normalizes to time/duration format."""
    data = {
        "id": "gs1",
        "name": "Test",
        "irrigation_config": {
            "veg_day_hours": "18.5",  # String float
            "irrigation_times": [
                # Old format with time/duration keys - kept as-is
                {"time": "08:00", "duration": "60.5"},
                # New format with start_time/duration_seconds - normalized to time/duration
                {"start_time": "09:00", "duration_seconds": "120.5"},
            ],
            "drain_times": [
                {"duration": "invalid"}  # Should default to 60
            ],
        },
    }
    gs = Growspace.from_dict(data)

    assert gs.irrigation_config.veg_day_hours == 18

    # Check irrigation_times normalization - all items should use time/duration keys
    times = gs.irrigation_config.irrigation_times
    assert len(times) == 2
    # Old format entry: time/duration keys kept, values coerced to int
    assert times[0]["time"] == "08:00"
    assert times[0]["duration"] == 60
    assert "start_time" not in times[0]
    assert "duration_seconds" not in times[0]
    # New format entry: start_time/duration_seconds normalized to time/duration
    assert times[1]["time"] == "09:00"
    assert times[1]["duration"] == 120
    assert "start_time" not in times[1]
    assert "duration_seconds" not in times[1]

    # Check drain_times defaults
    drains = gs.irrigation_config.drain_times
    assert len(drains) == 1
    assert drains[0]["duration"] == 60
