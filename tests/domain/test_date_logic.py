"""Tests for date and stage logic."""

from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.domain.date_logic import (
    calculate_days_in_stage,
    calculate_days_since,
    format_date,
    get_days_since_ipm,
    get_days_since_training,
    get_days_since_watering,
    parse_date_field,
    to_lifecycle_timestamp,
)
from custom_components.growspace_manager.domain.stage import PlantStage
from homeassistant.util.dt import as_local, set_default_time_zone

# Set a consistent timezone for tests
DEFAULT_TZ = UTC


@pytest.fixture(autouse=True)
def setup_tz():
    """Set up default timezone for tests."""
    set_default_time_zone(DEFAULT_TZ)


def test_to_lifecycle_timestamp_preserves_supplied_time():
    """A supplied datetime keeps its time, returned as an ISO string."""
    result = to_lifecycle_timestamp("2026-03-01T14:30:00+00:00")
    # Round-trips through parse_date_field, so the moment is preserved.
    assert parse_date_field(result) == datetime(2026, 3, 1, 14, 30, tzinfo=UTC)
    assert isinstance(result, str)


def test_to_lifecycle_timestamp_promotes_date_only_to_datetime():
    """A date-only value becomes a midnight-local datetime string, not truncated."""
    result = to_lifecycle_timestamp("2026-01-15")
    assert isinstance(result, str)
    parsed = parse_date_field(result)
    assert parsed.date() == date(2026, 1, 15)
    assert parsed.tzinfo is not None
    # The result is a full datetime string, never a bare date.
    assert "T" in result


def test_to_lifecycle_timestamp_accepts_date_object():
    """A datetime.date object is accepted and promoted to a datetime string."""
    result = to_lifecycle_timestamp(date(2026, 1, 15))
    assert parse_date_field(result).date() == date(2026, 1, 15)
    assert "T" in result


def test_to_lifecycle_timestamp_defaults_to_now_when_none():
    """None defaults to the current moment (full datetime, not date-only)."""
    result = to_lifecycle_timestamp(None)
    assert isinstance(result, str)
    parsed = parse_date_field(result)
    assert parsed is not None
    # Carries a real time component, not midnight from a .date() truncation.
    assert "T" in result


def test_parse_date_field_none():
    """Test parse_date_field with None."""
    assert parse_date_field(None) is None


def test_parse_date_field_datetime():
    """Test parse_date_field with datetime."""
    dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    assert parse_date_field(dt) == dt


def test_parse_date_field_date():
    """Test parse_date_field with date."""
    d = date(2024, 1, 1)
    result = parse_date_field(d)
    assert result.date() == d
    assert result.time() == datetime.min.time()
    assert result.tzinfo is not None


def test_parse_date_field_str_iso():
    """Test parse_date_field with ISO string."""
    s = "2024-01-01T12:00:00+00:00"
    result = parse_date_field(s)
    assert result == datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)


def test_parse_date_field_invalid_type():
    """Test parse_date_field with an invalid type (e.g. int)."""
    assert parse_date_field(123) is None


def test_parse_date_field_str_robust():
    """Test parse_date_field with robust parsing."""
    s = "2024-01-01 12:00"
    result = parse_date_field(s)
    assert result.year == 2024
    assert result.month == 1
    assert result.day == 1
    assert result.hour == 12
    assert result.minute == 0


def test_parse_date_field_str_invalid():
    """Test parse_date_field with invalid string."""
    assert parse_date_field("not-a-date") is None


def test_parse_date_field_naive():
    """Test parse_date_field with naive datetime."""
    dt = datetime(2024, 1, 1, 12, 0, 0)
    result = parse_date_field(dt)
    assert result.tzinfo is not None
    assert result == as_local(dt)


def test_calculate_days_since_none():
    """Test calculate_days_since with None."""
    assert calculate_days_since(None) == 0
    assert calculate_days_since("") == 0


def test_calculate_days_since_invalid_start():
    """Test calculate_days_since with invalid start date."""
    assert calculate_days_since("invalid") == 0


def test_calculate_days_since_with_end_date():
    """Test calculate_days_since with end date provided."""
    start = "2024-01-01"
    end = "2024-01-11"
    assert calculate_days_since(start, end) == 10


def test_calculate_days_since_default_now(freezer):
    """Test calculate_days_since defaults to now."""
    freezer.move_to("2024-01-11 12:00:00Z")
    start = "2024-01-01 12:00:00Z"
    assert calculate_days_since(start) == 10


def test_calculate_days_since_negative_delta():
    """Test calculate_days_since with negative delta."""
    start = "2024-01-11"
    end = "2024-01-01"
    assert calculate_days_since(start, end) == 0


def test_calculate_days_since_invalid_end():
    """Test calculate_days_since with invalid end date."""
    assert calculate_days_since("2024-01-01", "not-a-date") == 0


def test_format_date_none():
    """Test format_date with None."""
    assert format_date(None) is None


def test_format_date_valid():
    """Test format_date with valid input."""
    assert format_date("2024-01-01 12:00:00") == "2024-01-01"


def test_format_date_invalid():
    """Test format_date with invalid input."""
    assert format_date("invalid") is None


def test_calculate_days_in_stage():
    """Test calculate_days_in_stage with various stages."""
    plant = MagicMock()
    # Mocking plant attributes
    # calculate_days_in_stage uses getattr(plant, f"{stage}_start", None)
    plant.seedling_start = "2024-01-01"
    plant.veg_start = "2024-01-11"
    plant.flower_start = "2024-01-21"
    plant.dry_start = "2024-01-31"
    plant.cure_start = "2024-02-10"

    # Test SEEDLING (mapped to veg_start for END date)
    assert calculate_days_in_stage(plant, PlantStage.SEEDLING) == 10
    assert calculate_days_in_stage(plant, "seedling") == 10

    # Test VEG (mapped to flower_start for END date)
    assert calculate_days_in_stage(plant, PlantStage.VEG) == 10

    # Test FLOWER (mapped to dry_start for END date)
    assert calculate_days_in_stage(plant, PlantStage.FLOWER) == 10

    # Test DRY (mapped to cure_start for END date)
    assert calculate_days_in_stage(plant, PlantStage.DRY) == 10


def test_calculate_days_in_stage_no_start():
    """Test calculate_days_in_stage when start attribute is missing."""
    plant = MagicMock()
    # Ensure attributes are missing
    plant.nonexistent_start = None
    assert calculate_days_in_stage(plant, "nonexistent") == 0


def test_get_days_since_helpers(freezer):
    """Test helper functions for days since events."""
    freezer.move_to("2024-01-11 12:00:00Z")
    plant = MagicMock()

    plant.last_watered = "2024-01-01 12:00:00Z"
    assert get_days_since_watering(plant) == 10

    plant.last_trained = "2024-01-02 12:00:00Z"
    assert get_days_since_training(plant) == 9

    plant.last_ipm = "2024-01-03 12:00:00Z"
    assert get_days_since_ipm(plant) == 8
