"""Tests for the data models in models.py."""

import pytest
from datetime import date
from custom_components.growspace_manager.models import Growspace, Plant, EnvironmentState

# --------------------
# Growspace Model Tests
# --------------------

def test_growspace_to_dict():
    """Test Growspace to_dict method."""
    growspace = Growspace(id="gs1", name="Test Growspace", rows=2, plants_per_row=2)
    data = growspace.to_dict()
    assert data["id"] == "gs1"
    assert data["name"] == "Test Growspace"
    assert data["rows"] == 2
    assert data["plants_per_row"] == 2

def test_growspace_from_dict_basic():
    """Test Growspace from_dict with basic data."""
    data = {"id": "gs1", "name": "Test Growspace", "rows": 2, "plants_per_row": 2}
    growspace = Growspace.from_dict(data)
    assert growspace.id == "gs1"
    assert growspace.name == "Test Growspace"
    assert growspace.rows == 2
    assert growspace.plants_per_row == 2

def test_growspace_from_dict_with_legacy_created_field():
    """Test Growspace from_dict with legacy 'created' field."""
    today_iso = date.today().isoformat()
    data = {"id": "gs1", "name": "Test Growspace", "created": today_iso}
    growspace = Growspace.from_dict(data)
    assert growspace.created_at == today_iso
    assert "created" not in growspace.to_dict()

def test_growspace_from_dict_with_legacy_updated_field():
    """Test Growspace from_dict with legacy 'updated' field."""
    today_iso = date.today().isoformat()
    data = {"id": "gs1", "name": "Test Growspace", "updated": today_iso}
    growspace = Growspace.from_dict(data)
    # 'updated_at' is not a field in Growspace, so it should be filtered out
    assert "updated_at" not in growspace.to_dict()

def test_growspace_from_dict_with_extra_fields():
    """Test Growspace from_dict with extra, unrecognized fields."""
    data = {"id": "gs1", "name": "Test Growspace", "extra_field": "value"}
    growspace = Growspace.from_dict(data)
    assert growspace.id == "gs1"
    assert "extra_field" not in growspace.to_dict()

# --------------------
# Plant Model Tests
# --------------------

def test_plant_to_dict():
    """Test Plant to_dict method."""
    plant = Plant(plant_id="p1", growspace_id="gs1", strain="OG Kush")
    data = plant.to_dict()
    assert data["plant_id"] == "p1"
    assert data["growspace_id"] == "gs1"
    assert data["strain"] == "OG Kush"

def test_plant_from_dict_basic():
    """Test Plant from_dict with basic data."""
    data = {"plant_id": "p1", "growspace_id": "gs1", "strain": "OG Kush"}
    plant = Plant.from_dict(data)
    assert plant.plant_id == "p1"
    assert plant.growspace_id == "gs1"
    assert plant.strain == "OG Kush"

def test_plant_from_dict_with_legacy_created_field():
    """Test Plant from_dict with legacy 'created' field."""
    today_iso = date.today().isoformat()
    data = {"plant_id": "p1", "growspace_id": "gs1", "strain": "OG", "created": today_iso}
    plant = Plant.from_dict(data)
    assert plant.created_at == today_iso
    assert "created" not in plant.to_dict()

def test_plant_from_dict_with_legacy_updated_field():
    """Test Plant from_dict with legacy 'updated' field."""
    today_iso = date.today().isoformat()
    data = {"plant_id": "p1", "growspace_id": "gs1", "strain": "OG", "updated": today_iso}
    plant = Plant.from_dict(data)
    assert plant.updated_at == today_iso
    assert "updated" not in plant.to_dict()

def test_plant_from_dict_with_extra_fields():
    """Test Plant from_dict with extra, unrecognized fields."""
    data = {"plant_id": "p1", "growspace_id": "gs1", "strain": "OG", "extra_field": "value"}
    plant = Plant.from_dict(data)
    assert plant.plant_id == "p1"
    assert "extra_field" not in plant.to_dict()

# --------------------
# EnvironmentState Model Tests
# --------------------

def test_environment_state_basic():
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

def test_environment_state_none_values():
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
