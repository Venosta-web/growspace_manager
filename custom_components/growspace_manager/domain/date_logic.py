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
                except (ValueError, TypeError):
                    return None

    if dt is None:
        return None

    if dt.tzinfo is None:
        return as_local(dt)
    return dt


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


def calculate_days_in_stage(plant: Plant, stage: str) -> int:
    """Calculate how many days a plant has been in a specific growth stage."""
    from .stage import PlantStage, get_stage_definition  # noqa: PLC0415

    stage_def = get_stage_definition(stage)
    start_field = stage_def.start_field if stage_def else f"{stage}_start"
    start_date = getattr(plant, start_field, None)

    # Simplified lookup for common stages
    stage_map = {
        PlantStage.SEEDLING: "veg_start",
        "seedling": "veg_start",
        PlantStage.CLONE: "veg_start",
        "clone": "veg_start",
        PlantStage.VEG: "flower_start",
        "veg": "flower_start",
        PlantStage.FLOWER: "dry_start",
        "flower": "dry_start",
        PlantStage.DRY: "cure_start",
        "dry": "cure_start",
    }

    end_date = getattr(plant, stage_map.get(stage, "none"), None)
    return calculate_days_since(start_date, end_date)


def get_days_since_watering(plant: Plant) -> int:
    """Calculate days since plant was last watered."""
    return calculate_days_since(getattr(plant, "last_watered", None))


def get_days_since_training(plant: Plant) -> int:
    """Calculate days since plant was last trained."""
    return calculate_days_since(getattr(plant, "last_trained", None))


def get_days_since_ipm(plant: Plant) -> int:
    """Calculate days since plant received IPM treatment."""
    return calculate_days_since(getattr(plant, "last_ipm", None))
