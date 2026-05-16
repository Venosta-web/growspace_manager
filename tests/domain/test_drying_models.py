"""Tests for DryingData model defaults and serialization."""

import pytest

from custom_components.growspace_manager.models import (
    DryingData,
    MoistureEntry,
    WeightEntry,
)


def test_drying_data_defaults() -> None:
    """DryingData initializes with empty logs and no visual tag."""
    data = DryingData()
    assert data.weight_log == []
    assert data.moisture_log == []
    assert data.visual_tag is None


def test_weight_entry_roundtrip() -> None:
    """WeightEntry serializes and deserializes correctly."""
    entry = WeightEntry(date="2026-05-16", weight_grams=120.5)
    as_dict = entry.to_dict()
    restored = WeightEntry.from_dict(as_dict)
    assert restored.date == "2026-05-16"
    assert restored.weight_grams == 120.5


def test_moisture_entry_roundtrip() -> None:
    """MoistureEntry serializes and deserializes correctly."""
    entry = MoistureEntry(date="2026-05-16", moisture_percent=14.2)
    as_dict = entry.to_dict()
    restored = MoistureEntry.from_dict(as_dict)
    assert restored.date == "2026-05-16"
    assert restored.moisture_percent == 14.2


def test_drying_data_roundtrip_with_logs() -> None:
    """DryingData with logs and visual_tag serializes correctly."""
    data = DryingData(
        weight_log=[WeightEntry(date="2026-05-15", weight_grams=200.0)],
        moisture_log=[MoistureEntry(date="2026-05-15", moisture_percent=18.0)],
        visual_tag="Red Velcro",
    )
    as_dict = data.to_dict()
    restored = DryingData.from_dict(as_dict)
    assert len(restored.weight_log) == 1
    assert restored.weight_log[0].weight_grams == 200.0
    assert len(restored.moisture_log) == 1
    assert restored.moisture_log[0].moisture_percent == 18.0
    assert restored.visual_tag == "Red Velcro"


def test_plant_has_drying_data_field() -> None:
    """Plant.drying_data defaults to an empty DryingData instance."""
    from custom_components.growspace_manager.models import Plant

    plant = Plant(plant_id="p1", growspace_id="g1")
    assert isinstance(plant.drying_data, DryingData)
    assert plant.drying_data.visual_tag is None


def test_plant_deserializes_without_drying_data_key() -> None:
    """Plant deserializes from legacy data missing the drying_data key."""
    from custom_components.growspace_manager.models import Plant

    raw = {"plant_id": "p1", "growspace_id": "g1", "stage": "dry"}
    plant = Plant.from_dict(raw)
    assert isinstance(plant.drying_data, DryingData)
    assert plant.drying_data.weight_log == []
