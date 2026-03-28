"""Tests for numeric field sanitization in models."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from custom_components.growspace_manager.models import (
    Growspace,
    _sanitize_numeric_fields,
)


@dataclass
class SanitizationTestModel:
    """Mock model for testing sanitization."""

    int_field: int
    float_field: float
    default_int: int = 42
    default_float: float = 3.14
    optional_int: int | None = None


def test_sanitize_none_to_default_or_zero():
    """Test sanitizing None values to defaults or zero."""
    # float_field and int_field have no default, so should become zero
    data = {"int_field": None, "float_field": None}
    sanitized = _sanitize_numeric_fields(SanitizationTestModel, data)
    assert sanitized["int_field"] == 0
    assert sanitized["float_field"] == 0.0

    # default_int and default_float have defaults, so should use them
    data = {"default_int": None, "default_float": None}
    sanitized = _sanitize_numeric_fields(SanitizationTestModel, data)
    assert sanitized["default_int"] == 42
    assert sanitized["default_float"] == pytest.approx(3.14)


def test_sanitize_coercion():
    """Test coercing float and string values to int."""
    # Float to int
    data = {"int_field": 12.7}
    sanitized = _sanitize_numeric_fields(SanitizationTestModel, data)
    assert sanitized["int_field"] == 12

    # String to int
    data = {"int_field": "123"}
    sanitized = _sanitize_numeric_fields(SanitizationTestModel, data)
    assert sanitized["int_field"] == 123

    # String float to int
    data = {"int_field": "123.9"}
    sanitized = _sanitize_numeric_fields(SanitizationTestModel, data)
    assert sanitized["int_field"] == 123


def test_sanitize_conversion_error_fallback():
    """Test fallback to default or zero on conversion error."""
    # invalid string for int_field (no default)
    data = {"int_field": "invalid"}
    sanitized = _sanitize_numeric_fields(SanitizationTestModel, data)
    assert sanitized["int_field"] == 0

    # invalid string for default_int (has default)
    data = {"default_int": "invalid"}
    sanitized = _sanitize_numeric_fields(SanitizationTestModel, data)
    assert sanitized["default_int"] == 42


def test_sanitize_no_change_for_valid_values():
    """Test that valid values are untouched."""
    data = {"int_field": 10, "float_field": 20.5, "optional_int": 5}
    sanitized = _sanitize_numeric_fields(SanitizationTestModel, data)
    assert sanitized["int_field"] == 10
    assert sanitized["float_field"] == 20.5
    assert sanitized["optional_int"] == 5


def test_sanitize_optional_field_none():
    """Test that non-numeric (optional) fields are NOT sanitized to zero if they allow None."""

    @dataclass
    class OptionalModel:
        opt_int: int | None = None

    data = {"opt_int": None}
    sanitized = _sanitize_numeric_fields(OptionalModel, data)
    assert sanitized["opt_int"] is None


def test_growspace_pre_deserialize_sanitization_failures():
    """Test Growspace.__pre_deserialize__ failure paths for coverage."""

    # Test invalid duration in irrigation_config (Lines 644-645)
    data = {
        "id": "gs1",
        "name": "GS1",
        "irrigation_config": {
            "irrigation_times": [{"time": "08:00", "duration": "invalid"}]
        }
    }
    sanitized = Growspace.__pre_deserialize__(data)
    assert sanitized["irrigation_config"]["irrigation_times"][0]["duration"] == 60

    # Test invalid values in irrigation_strategy (Lines 667-670)
    data = {
        "id": "gs1",
        "name": "GS1",
        "irrigation_strategy": {
            "p0_duration_minutes": "not_an_int",
            "shot_duration_seconds": "invalid"  # Added another one for coverage
        }
    }
    sanitized = Growspace.__pre_deserialize__(data)
    # The invalid field should be deleted from the dict
    assert "p0_duration_minutes" not in sanitized["irrigation_strategy"]
    assert "shot_duration_seconds" not in sanitized["irrigation_strategy"]

    # Test invalid rows/plants_per_row (Line 598)
    data = {
        "id": "gs1",
        "name": "GS1",
        "rows": "invalid"
    }
    sanitized = Growspace.__pre_deserialize__(data)
    assert sanitized["rows"] == 3
