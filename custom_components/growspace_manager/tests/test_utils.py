"""Tests for growspace_manager utils."""

from datetime import date, datetime, timezone
from typing import Any

import pytest

from custom_components.growspace_manager.models import Growspace, Plant
from custom_components.growspace_manager.utils import (
    calculate_days_since,
    find_first_free_position,
    format_date,
    generate_growspace_grid,
    parse_date_field,
)


# ----------------------------
# parse_date_field tests
# ----------------------------
@pytest.mark.parametrize(
    ("input_value", "expected"),
    [
        (None, None),
        (date(2025, 11, 3), date(2025, 11, 3)),
        (datetime(2025, 11, 3, 15, 30, tzinfo=timezone.utc), date(2025, 11, 3)),
        ("2025-11-03", date(2025, 11, 3)),
        ("invalid-date", None),
        (12345, None),
    ],
)
def test_parse_date_field(input_value: Any, expected: date | None) -> None:
    """Test parse_date_field function."""
    assert parse_date_field(input_value) == expected


# ----------------------------
# format_date tests
# ----------------------------
@pytest.mark.parametrize(
    ("input_value", "expected"),
    [
        (None, None),
        (date(2025, 11, 3), "2025-11-03"),
        (datetime(2025, 11, 3, 15, 30, tzinfo=timezone.utc), "2025-11-03"),
        ("2025-11-03", "2025-11-03"),
        ("invalid-date", None),
        (12345, None),
    ],
)
def test_format_date(input_value: Any, expected: str | None) -> None:
    """Test format_date function."""
    assert format_date(input_value) == expected


# ----------------------------
# calculate_days_since tests
# ----------------------------
def test_calculate_days_since() -> None:
    """Test calculate_days_since function."""
    start = date(2025, 11, 1)
    end = date(2025, 11, 3)
    assert calculate_days_since(start, end) == 2  # 2 days difference

    # default end_date = today (we can't mock here, just check type)
    result = calculate_days_since(date(2025, 11, 1))
    assert isinstance(result, int)


# ----------------------------
# find_first_free_position tests
# ----------------------------
def test_find_first_free_position() -> None:
    """Test find_first_free_position function."""
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
def test_generate_growspace_grid_basic() -> None:
    """Test generate_growspace_grid with basic plant placement."""
    plants = [
        Plant(plant_id="p1", row=1, col=1, strain="A", growspace_id="g1"),
        Plant(plant_id="p2", row=2, col=2, strain="B", growspace_id="g1"),
    ]
    grid = generate_growspace_grid(2, 2, plants)
    assert grid == [
        ["p1", None],
        [None, "p2"],
    ]


def test_generate_growspace_grid_empty() -> None:
    """Test generate_growspace_grid with no plants."""
    grid = generate_growspace_grid(2, 2, [])
    assert grid == [
        [None, None],
        [None, None],
    ]
