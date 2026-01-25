"""Tests for the DateTimeHelper utility class."""

from datetime import date, datetime
from unittest import mock

import pytest

from custom_components.growspace_manager.date_time_helper import DateTimeHelper


@pytest.mark.parametrize(
    ("input_value", "expected"),
    [
        (None, None),
        ("None", None),
        (date(2025, 1, 1), date(2025, 1, 1)),
        (datetime(2025, 1, 1, 12, 0, 0), date(2025, 1, 1)),
        ("2025-01-01", date(2025, 1, 1)),
        ("invalid", None),
    ],
)
def test_to_date(input_value, expected):
    """Test the to_date method with various inputs."""
    assert DateTimeHelper.to_date(input_value) == expected


def test_to_date_exception():
    """Test to_date handles exceptions from parse_date_field."""
    with mock.patch(
        "custom_components.growspace_manager.date_time_helper.parse_date_field",
        side_effect=Exception("Test error"),
    ):
        assert DateTimeHelper.to_date("2025-01-01") is None


def test_calculate_days():
    """Test the calculate_days method."""
    today = date.today()
    start_date = (
        today.replace(year=today.year - 1)
        if today.month > 1 or today.day > 1
        else date(today.year - 1, 12, 31)
    )

    # Simple calculation with start date only
    days = DateTimeHelper.calculate_days(start_date)
    assert days >= 365

    # Calculation with end date
    end_date = (
        start_date.replace(year=start_date.year, month=start_date.month + 1)
        if start_date.month < 12
        else date(start_date.year + 1, 1, start_date.day)
    )
    days = DateTimeHelper.calculate_days(start_date, end_date)
    assert days >= 28

    # Invalid start date
    assert DateTimeHelper.calculate_days(None) == 0

    # End date in the future (relative to today)
    future_date = today.replace(year=today.year + 1)
    # The current implementation caps at today if end_dt > target_date
    days_to_today = (today - start_date).days
    assert DateTimeHelper.calculate_days(start_date, future_date) == days_to_today

    # Invalid end date (fallback to today)
    assert DateTimeHelper.calculate_days(start_date, "invalid") == days_to_today
