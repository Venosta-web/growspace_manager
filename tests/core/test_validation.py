"""Tests for validation.py functions."""

from datetime import date, datetime

import pytest
import voluptuous as vol

from custom_components.growspace_manager.validation import (
    valid_date_or_none,
    valid_growspace_id,
)


class TestValidDateOrNone:
    """Tests for valid_date_or_none function."""

    def test_none_value(self):
        """Test that None returns None."""
        assert valid_date_or_none(None) is None

    def test_empty_string(self):
        """Test that empty string returns None."""
        assert valid_date_or_none("") is None

    def test_datetime_instance(self):
        """Test that datetime instance is returned as-is."""
        dt = datetime(2024, 1, 15, 10, 30, 0)
        result = valid_date_or_none(dt)
        assert result == dt
        assert isinstance(result, datetime)

    def test_date_instance(self):
        """Test that date instance is returned as-is."""
        d = date(2024, 1, 15)
        result = valid_date_or_none(d)
        assert result == d
        assert isinstance(result, date)

    def test_iso_datetime_string(self):
        """Test parsing ISO datetime string."""
        result = valid_date_or_none("2024-01-15T10:30:00")
        assert isinstance(result, datetime)
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15
        assert result.hour == 10
        assert result.minute == 30

    def test_iso_datetime_string_with_z(self):
        """Test parsing ISO datetime string with Z suffix."""
        result = valid_date_or_none("2024-01-15T10:30:00Z")
        assert isinstance(result, datetime)
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_iso_date_string(self):
        """Test parsing ISO date string."""
        result = valid_date_or_none("2024-01-15")
        assert isinstance(result, date)
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_invalid_date_format(self):
        """Test that invalid date format raises vol.Invalid."""
        with pytest.raises(
            vol.Invalid, match="is not a valid date or ISO format string"
        ):
            valid_date_or_none("not-a-date")

    def test_invalid_date_format_numbers(self):
        """Test that invalid numeric format raises vol.Invalid."""
        with pytest.raises(
            vol.Invalid, match="is not a valid date or ISO format string"
        ):
            valid_date_or_none("99/99/9999")

    def test_integer_value(self):
        """Test that integer value raises vol.Invalid."""
        with pytest.raises(
            vol.Invalid, match="is not a valid date or ISO format string"
        ):
            valid_date_or_none(12345)


class TestValidGrowspaceId:
    """Tests for valid_growspace_id function."""

    def test_valid_string(self):
        """Test that valid string is returned."""
        result = valid_growspace_id("test_growspace")
        assert result == "test_growspace"

    def test_valid_string_with_uuid(self):
        """Test that UUID string is valid."""
        uuid_str = "550e8400-e29b-41d4-a716-446655440000"
        result = valid_growspace_id(uuid_str)
        assert result == uuid_str

    def test_empty_string(self):
        """Test that empty string raises vol.Invalid."""
        with pytest.raises(vol.Invalid, match="Growspace ID cannot be empty"):
            valid_growspace_id("")

    def test_none_value(self):
        """Test that None raises vol.Invalid."""
        with pytest.raises(vol.Invalid, match="Growspace ID cannot be empty"):
            valid_growspace_id(None)

    def test_integer_value(self):
        """Test that integer raises vol.Invalid."""
        with pytest.raises(vol.Invalid, match="Growspace ID cannot be empty"):
            valid_growspace_id(123)

    def test_list_value(self):
        """Test that list raises vol.Invalid."""
        with pytest.raises(vol.Invalid, match="Growspace ID cannot be empty"):
            valid_growspace_id(["test"])

    def test_dict_value(self):
        """Test that dict raises vol.Invalid."""
        with pytest.raises(vol.Invalid, match="Growspace ID cannot be empty"):
            valid_growspace_id({"id": "test"})
