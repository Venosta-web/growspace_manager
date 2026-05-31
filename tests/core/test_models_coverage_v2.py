"""Additional coverage tests for models.py."""

from unittest.mock import patch

from custom_components.growspace_manager.models import Growspace, NutrientPreset, Plant


def test_growspace_irrigation_config_invalid_duration_seconds() -> None:
    """Test Growspace deserialization with invalid duration_seconds normalizes to duration=60."""
    data = {
        "id": "gs1",
        "name": "Test",
        "irrigation_config": {
            "irrigation_times": [{"start_time": "08:00", "duration_seconds": "invalid"}]
        },
    }
    gs = Growspace.from_dict(data)
    # start_time normalized to time, duration_seconds (invalid) normalized to duration=60
    assert gs.irrigation_config.irrigation_times[0]["time"] == "08:00"
    assert gs.irrigation_config.irrigation_times[0]["duration"] == 60
    assert "start_time" not in gs.irrigation_config.irrigation_times[0]
    assert "duration_seconds" not in gs.irrigation_config.irrigation_times[0]


def test_plant_get_days_since_watering_with_value() -> None:
    """Test get_days_since_watering returns calculated value when set."""
    plant = Plant(plant_id="p1", growspace_id="gs1", last_watered="2023-01-01T12:00:00")

    # We can rely on the real calculate_days_since if we don't care about the exact value return
    # or just keep mocking. The coverage issue might be related to how coverage maps lines.
    # Let's try executing it without patch to see if line is hit.
    # But calculate_days_since depends on current time.

    with patch(
        "custom_components.growspace_manager.models.plant.calculate_days_since",
        return_value=5,
    ) as mock_calc:
        val = plant.get_days_since_watering()
        assert val == 5
        mock_calc.assert_called_once()


def test_plant_get_days_in_stage_fallback() -> None:
    """Test get_days_in_stage fallback to legacy attributes."""
    plant = Plant(
        plant_id="p1",
        growspace_id="gs1",
        # Set legacy attribute directly
        veg_start="2023-01-01T00:00:00",
    )
    # Ensure stage_history is empty or doesn't have veg to force fallback
    plant.stage_history = []

    with patch(
        "custom_components.growspace_manager.models.plant.calculate_days_since",
        return_value=10,
    ) as mock_calc:
        val = plant.get_days_in_stage("veg")
        assert val == 10
        mock_calc.assert_called_with("2023-01-01T00:00:00")


def test_nutrient_preset_setter_coverage() -> None:
    """Explicitly test nutrient preset setter."""
    preset = NutrientPreset(id="np1", name="Test", items=[])
    # Access property first
    _ = preset.nutrients
    # Set property
    preset.nutrients = [{"name": "A", "dose_ml_l": 1.0}]
    assert len(preset.items) == 1
    assert preset.items[0]["name"] == "A"
    # Access again
    assert len(preset.nutrients) == 1
