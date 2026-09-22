"""Plant metrics calculations - pure domain functions."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from custom_components.growspace_manager.const import PlantStage
from custom_components.growspace_manager.utils import calculate_days_since, format_date

if TYPE_CHECKING:
    from custom_components.growspace_manager.models import Plant


def get_days_since_watering(plant: Plant) -> int:
    """Calculate days since plant was last watered.

    Args:
        plant: The plant to check.

    Returns:
        Number of days since last watering. Returns 0 if never watered.
    """
    return calculate_days_since(plant.last_watered)


def get_days_since_training(plant: Plant) -> int:
    """Calculate days since plant was last trained.

    Args:
        plant: The plant to check.

    Returns:
        Number of days since last training. Returns 0 if never trained.
    """
    return calculate_days_since(plant.last_trained)


def get_days_since_ipm(plant: Plant) -> int:
    """Calculate days since plant received IPM treatment.

    Args:
        plant: The plant to check.

    Returns:
        Number of days since last IPM. Returns 0 if never treated.
    """
    return calculate_days_since(plant.last_ipm)


def format_plant_position(plant: Plant) -> str:
    """Format plant position as (row, col) string.

    Args:
        plant: The plant to format position for.

    Returns:
        Position string like "(2,3)".
    """
    return f"({int(plant.row)},{int(plant.col)})"


def get_formatted_dates(plant: Plant) -> dict[str, str | None]:
    """Get all plant dates formatted as strings.

    Args:
        plant: The plant to get dates for.

    Returns:
        Dictionary of formatted date strings.
    """
    return {
        "seedling_start": format_date(plant.seedling_start),
        "mother_start": format_date(plant.mother_start),
        "clone_start": format_date(plant.clone_start),
        "veg_start": format_date(plant.veg_start),
        "flower_start": format_date(plant.flower_start),
        "dry_start": format_date(plant.dry_start),
        "cure_start": format_date(plant.cure_start),
        "last_watered": format_date(plant.last_watered),
        "last_trained": format_date(plant.last_trained),
        "last_ipm": format_date(plant.last_ipm),
    }


# Plant stages whose plants no longer sit on the irrigation line; excluded from
# the live plant count that backs per-plant Volume Mode dosing (see ADR-0011).
NON_LIVE_STAGES: frozenset[str] = frozenset(
    {PlantStage.DRY.value, PlantStage.CURE.value}
)


def count_live_plants(plants: Iterable[Plant]) -> int:
    """Return how many of ``plants`` still draw irrigation.

    The per-plant dosing basis for Volume Mode: a percent-of-substrate shot is
    dosed per pot, so the tent's total volume — and the pump seconds that
    deliver it — scale with this count (ADR-0011). Shared by the live shot
    composer and by [[Irrigation Recipe]] capture, which divides the very same
    count back out to recover a per-pot percent.
    """
    return sum(1 for p in plants if str(getattr(p, "stage", "")) not in NON_LIVE_STAGES)
