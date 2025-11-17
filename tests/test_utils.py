"""Tests for the utility functions in the Growspace Manager integration.

This file contains a suite of tests for the various helper and utility functions
defined in `custom_components/growspace_manager/utils.py`. It covers date
parsing, formatting, calculations, and grid generation logic.
"""
from datetime import date, datetime
import pytest

from custom_components.growspace_manager.utils import (
    parse_date_field,
    format_date,
    calculate_days_since,
    find_first_free_position,
    generate_growspace_grid,
)
from custom_components.growspace_manager.models import Plant, Growspace


# ----------------------------
# parse_date_field tests
# ----------------------------
@pytest.mark.parametrize(
    "input_value,expected",
    [
        (None, None),
        (date(2025, 11, 3), date(2025, 11, 3)),
        (datetime(2025, 11, 3, 15, 30), date(2025, 11, 3)),
        ("2025-11-03", date(2025, 11, 3)),
        ("invalid-date", None),
        (12345, None),
    ],
)
def test_parse_date_field(input_value, expected):
    """Test the `parse_date_field` function with various input types.

    Args:
        input_value: The value to be parsed.
        expected: The expected `date` object or None.
    """
    assert parse_date_field(input_value) == expected


# ----------------------------
# format_date tests
# ----------------------------
@pytest.mark.parametrize(
    "input_value,expected",
    [
        (None, None),
        (date(2025, 11, 3), "2025-11-03"),
        (datetime(2025, 11, 3, 15, 30), "2025-11-03"),
        ("2025-11-03", "2025-11-03"),
        ("invalid-date", None),
        (12345, None),
    ],
)
def test_format_date(input_value, expected):
    """Test the `format_date` function to ensure correct string formatting.

    Args:
        input_value: The value to be formatted.
        expected: The expected ISO-formatted date string or None.
    """
    assert format_date(input_value) == expected


# ----------------------------
# calculate_days_since tests
# ----------------------------
def test_calculate_days_since():
    """Test the `calculate_days_since` function."""
    start = date(2025, 11, 1)
    end = date(2025, 11, 3)
    assert calculate_days_since(start, end) == 2

    # default end_date = today (we can't mock here, just check type)
    result = calculate_days_since(date(2025, 11, 1))
    assert isinstance(result, int)


# ----------------------------
# find_first_free_position tests
# ----------------------------
def test_find_first_free_position():
    """Test the `find_first_free_position` function in various scenarios."""
    growspace = Growspace(
        id="test",
        name="Test Growspace",
        rows=2,
        plants_per_row=2,
    )
    occupied = {(1, 1)}
    assert find_first_free_position(growspace, occupied) == (1, 2)

    occupied = {(1, 1), (1, 2), (2, 1)}
    assert find_first_free_position(growspace, occupied) == (2, 2)

    # all positions occupied: returns bottom-right
    occupied = {(1, 1), (1, 2), (2, 1), (2, 2)}
    assert find_first_free_position(growspace, occupied) == (2, 2)


# ----------------------------
# generate_growspace_grid tests
# ----------------------------
def test_generate_growspace_grid_basic():
    """Test the basic functionality of `generate_growspace_grid`."""
    plants = [
        Plant(plant_id="p1", row=1, col=1, strain="A", growspace_id="g1"),
        Plant(plant_id="p2", row=2, col=2, strain="B", growspace_id="g1"),
    ]
    grid = generate_growspace_grid(2, 2, plants)
    assert grid == [
        ["p1", None],
        [None, "p2"],
    ]


def test_generate_growspace_grid_empty():
    """Test that `generate_growspace_grid` creates an empty grid correctly."""
    grid = generate_growspace_grid(2, 2, [])
    assert grid == [
        [None, None],
        [None, None],
    ]
