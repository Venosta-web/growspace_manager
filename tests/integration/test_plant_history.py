"""Tests for Plant Stage History logic."""

from datetime import datetime, timedelta

from custom_components.growspace_manager.models import Plant


def test_plant_from_dict_creates_history() -> None:
    """Test that loading a legacy plant dict creates stage history."""
    now = datetime.now()
    veg_start = (now - timedelta(days=20)).isoformat()
    flower_start = (now - timedelta(days=5)).isoformat()

    data = {
        "plant_id": "p1",
        "growspace_id": "gs1",
        "strain": "Test",
        "stage": "flower",
        "veg_start": veg_start,
        "flower_start": flower_start,
        # No stage_history
    }

    plant = Plant.from_dict(data)

    assert plant.stage_history is not None
    assert len(plant.stage_history) == 2

    # Check Veg entry
    assert plant.stage_history[0]["stage"] == "veg"
    assert plant.stage_history[0]["start"] == veg_start
    assert plant.stage_history[0]["end"] == flower_start

    # Check Flower entry
    assert plant.stage_history[1]["stage"] == "flower"
    assert plant.stage_history[1]["start"] == flower_start
    assert plant.stage_history[1]["end"] is None


def test_plant_from_dict_preserves_existing_history() -> None:
    """Test that existing history is preserved."""
    history = [
        {"stage": "veg", "start": "2023-01-01", "end": "2023-02-01"},
        {"stage": "flower", "start": "2023-02-01", "end": None},
    ]
    data = {
        "plant_id": "p1",
        "growspace_id": "gs1",
        "strain": "Test",
        "stage": "flower",
        "stage_history": history,
    }

    plant = Plant.from_dict(data)
    assert len(plant.stage_history) == 2
    assert plant.stage_history[0]["stage"] == "veg"
    # Ensure it didn't regenerate
