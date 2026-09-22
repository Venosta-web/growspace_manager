"""Base date and stage logic for Growspace Manager."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from dateutil import parser

from homeassistant.util.dt import as_local, now

if TYPE_CHECKING:
    from custom_components.growspace_manager.models import Plant

type DateInput = date | datetime | str | None


def parse_date_field(date_value: DateInput) -> datetime | None:
    """Parse various date inputs into a timezone-aware datetime object."""
    if date_value is None:
        return None

    dt: datetime | None = None

    match date_value:
        case datetime():
            dt = date_value
        case date():
            dt = datetime.combine(date_value, datetime.min.time())
        case str():
            try:
                # Optimization: Try standard library parsing first
                dt = datetime.fromisoformat(date_value)
            except ValueError:
                try:
                    # Fallback to slower, more robust parser
                    dt = parser.isoparse(date_value)
                except ValueError, TypeError:
                    return None

    if dt is None:
        return None

    if dt.tzinfo is None:
        return as_local(dt)
    return dt


def to_lifecycle_timestamp(supplied: DateInput = None) -> str:
    """Return the ISO datetime string to store for a Lifecycle Timestamp.

    The single owner of how a plant stage-start (`seedling_start … cure_start`)
    is represented on write (see CONTEXT.md "Lifecycle Timestamp", ADR-0013).
    A supplied value preserves its moment; ``None`` defaults to the current
    time. Always returns a full timezone-aware ISO 8601 datetime string — never
    a date-only value — so no write site truncates with ``.date()``. A bare
    `date` (or a date-only string) is promoted to midnight-local.
    """
    parsed = parse_date_field(supplied) if supplied is not None else now()
    if parsed is None:
        parsed = now()
    return parsed.isoformat()


def plant_updated_date() -> str:
    """Return the date-only stamp for a Plant's most recent mutation.

    This is the single owner of the ``Plant.updated_at`` representation (see
    CONTEXT.md "Plant Updated Date"). Unlike a Lifecycle Timestamp, this field
    records a calendar day and is always written as ``YYYY-MM-DD``.
    """
    return now().date().isoformat()


def calculate_days_since(start_date: DateInput, end_date: DateInput = None) -> int:
    """Calculate the number of days since a start date."""
    if not start_date:
        return 0

    start = parse_date_field(start_date)
    if not start:
        return 0

    end = parse_date_field(end_date) if end_date else now()
    if not end:
        return 0

    delta = end - start
    return max(0, delta.days)


def format_date(date_value: DateInput) -> str | None:
    """Format a date for display."""
    if not date_value:
        return None

    dt = parse_date_field(date_value)
    if not dt:
        return None

    return as_local(dt).strftime("%Y-%m-%d")


def get_days_since_watering(plant: Plant) -> int:
    """Calculate days since plant was last watered."""
    return calculate_days_since(getattr(plant, "last_watered", None))


def get_days_since_training(plant: Plant) -> int:
    """Calculate days since plant was last trained."""
    return calculate_days_since(getattr(plant, "last_trained", None))


def get_days_since_ipm(plant: Plant) -> int:
    """Calculate days since plant received IPM treatment."""
    return calculate_days_since(getattr(plant, "last_ipm", None))
