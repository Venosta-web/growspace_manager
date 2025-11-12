"""Utility functions for date parsing, formatting, and calculations in growspace_manager."""

from __future__ import annotations
from datetime import date, datetime
from dateutil import parser
from .models import Plant, Growspace

DateInput = str | datetime | date | None


def parse_date_field(date_value: DateInput) -> date | None:
    """Parse various date inputs into a date object."""
    if date_value is None:
        return None
    if isinstance(date_value, datetime):
        return date_value.date()  # <-- convert datetime to date
    if isinstance(date_value, date):
        return date_value
    if isinstance(date_value, str):
        try:
            return parser.isoparse(date_value).date()  # <-- always return date
        except (ValueError, TypeError):
            return None
    return None


def format_date(date_value: DateInput) -> str | None:
    """Format a date input into a 'YYYY-MM-DD' string."""
    dt = parse_date_field(date_value)
    if dt is None:
        return None
    return dt.isoformat()  # will now always be "YYYY-MM-DD"


def calculate_days_since(
    start_date: DateInput, end_date: DateInput | None = None
) -> int:
    """Returns the number of days from start_date to end_date.

    If end_date is None, uses today's date.
    """
    start = parse_date_field(start_date)
    end = parse_date_field(end_date) if end_date else date.today()
    if start is None or end is None:
        return 0
    return (end - start).days


def find_first_free_position(
    growspace: Growspace, occupied_positions: set[tuple[int, int]]
) -> tuple[int, int]:
    """_Returns the first col/row thats free in growspace.

    Args:
        growspace (dict): _description_
        occupied_positions (set[tuple[int, int]]): _description_

    Returns:
        tuple[int, int]: _description_
    """

    total_rows = int(growspace.rows)
    total_cols = int(growspace.plants_per_row)
    for r in range(1, total_rows + 1):
        for c in range(1, total_cols + 1):
            if (r, c) not in occupied_positions:
                return r, c
    return total_rows, total_cols


def generate_growspace_grid(
    rows: int, cols: int, plant_positions: list[Plant]
) -> list[list[str | None]]:
    """Generate a grid representing the growspace with plant IDs."""
    grid: list[list[str | None]] = [[None for _ in range(cols)] for _ in range(rows)]
    for plant in plant_positions:
        r, c = plant.row - 1, plant.col - 1
        grid[r][c] = plant.plant_id
    return grid
