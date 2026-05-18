"""Tests for Plant Stage History logic."""

from datetime import datetime, timedelta

from .common import create_plant

from custom_components.growspace_manager.models import Plant, StageHistoryItem


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


def test_get_days_in_stage_uses_history() -> None:
    """Test get_days_in_stage calculation using history."""
    plant = create_plant(plant_id="p1", growspace_id="gs1", strain="Test")

    now = datetime.now()
    start_veg = (now - timedelta(days=50)).isoformat()
    end_veg = (now - timedelta(days=20)).isoformat()
    # Veg duration: 30 days

    start_flower = end_veg
    # Flower duration: 20 days (active)

    plant.stage_history = [
        StageHistoryItem(stage="veg", start=start_veg, end=end_veg),
        StageHistoryItem(stage="flower", start=start_flower, end=None),
    ]

    assert plant.get_days_in_stage("veg") == 30
    assert plant.get_days_in_stage("flower") == 20
    assert plant.get_days_in_stage("unknown") == 0


def test_get_days_in_stage_multi_segment() -> None:
    """Test summing multiple segments for same stage (e.g. reveg)."""
    plant = create_plant(plant_id="p1", growspace_id="gs1", strain="Test")
    now = datetime.now()

    # Veg 1: 10 days
    start1 = (now - timedelta(days=100)).isoformat()
    end1 = (now - timedelta(days=90)).isoformat()

    # Flower: 10 days
    start2 = end1
    end2 = (now - timedelta(days=80)).isoformat()

    # Veg 2 (Reveg): 10 days (Active)
    start3 = (now - timedelta(days=10)).isoformat()

    plant.stage_history = [
        StageHistoryItem(stage="veg", start=start1, end=end1),
        StageHistoryItem(stage="flower", start=start2, end=end2),
        StageHistoryItem(stage="veg", start=start3, end=None),
    ]

    assert plant.get_days_in_stage("veg") == 20  # 10 + 10
    assert plant.get_days_in_stage("flower") == 10
