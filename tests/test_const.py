"""Tests for the constants and validation functions in const.py."""

import pytest
from datetime import date
import voluptuous as vol

from custom_components.growspace_manager.const import (
    valid_date_or_none,
    valid_growspace_id,
    ADD_PLANT_SCHEMA,
)

# --------------------
# valid_date_or_none
# --------------------

def test_valid_date_or_none_with_valid_date():
    """Test valid_date_or_none with a valid date object."""
    today = date.today()
    assert valid_date_or_none(today) == today

def test_valid_date_or_none_with_none():
    """Test valid_date_or_none with None."""
    assert valid_date_or_none(None) is None

def test_valid_date_or_none_with_empty_string():
    """Test valid_date_or_none with an empty string."""
    assert valid_date_or_none("") is None

def test_valid_date_or_none_with_iso_string():
    """Test valid_date_or_none with a valid ISO date string."""
    today = date.today()
    iso_date = today.isoformat()
    assert valid_date_or_none(iso_date) == today

def test_valid_date_or_none_with_iso_string_with_z():
    """Test valid_date_or_none with a valid ISO date string ending in Z."""
    today = date.today()
    iso_date = today.isoformat() + "Z"
    assert valid_date_or_none(iso_date) == today

def test_valid_date_or_none_with_invalid_string():
    """Test valid_date_or_none with an invalid date string."""
    with pytest.raises(vol.Invalid):
        valid_date_or_none("not a date")

# --------------------
# valid_growspace_id
# --------------------

def test_valid_growspace_id_with_valid_id():
    """Test valid_growspace_id with a valid ID."""
    assert valid_growspace_id("gs1") == "gs1"

def test_valid_growspace_id_with_empty_string():
    """Test valid_growspace_id with an empty string."""
    with pytest.raises(vol.Invalid):
        valid_growspace_id("")

def test_valid_growspace_id_with_non_string():
    """Test valid_growspace_id with a non-string value."""
    with pytest.raises(vol.Invalid):
        valid_growspace_id(123)

# --------------------
# Service Schemas
# --------------------

def test_add_plant_schema_with_optional_fields():
    """Test ADD_PLANT_SCHEMA with all optional fields."""
    today = date.today()
    data = {
        "growspace_id": "gs1",
        "strain": "OG",
        "row": 1,
        "col": 1,
        "phenotype": "A",
        "seedling_start": today,
        "mother_start": today,
        "clone_start": today,
        "veg_start": today,
        "flower_start": today,
        "dry_start": today,
        "cure_start": today,
    }
    validated = ADD_PLANT_SCHEMA(data)
    assert validated == data
