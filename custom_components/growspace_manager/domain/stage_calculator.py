"""Stage calculation logic - pure domain functions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.growspace_manager.utils import calculate_days_since

from .stage import DEFAULT_FLOWER_EARLY_DAYS, FLOWER_LATE_MIN_DAYS, PlantStage

if TYPE_CHECKING:
    from custom_components.growspace_manager.models import Plant


def calculate_days_in_stage(plant: Plant, stage: str) -> int:
    """Calculate how many days a plant has been in a specific growth stage.

    This is a pure function with no external dependencies.

    Args:
        plant: The plant to calculate stage duration for.
        stage: The stage to calculate (e.g., "veg", "flower", "dry").

    Returns:
        Number of days in the stage. Returns 0 if stage hasn't started.
    """
    start_date = getattr(plant, f"{stage}_start", None)

    end_date = None
    if stage in {PlantStage.SEEDLING, PlantStage.CLONE}:
        end_date = getattr(plant, "veg_start", None)
    elif stage == PlantStage.VEG:
        end_date = getattr(plant, "flower_start", None)
    elif stage == PlantStage.FLOWER:
        end_date = getattr(plant, "dry_start", None)
    elif stage == PlantStage.DRY:
        end_date = getattr(plant, "cure_start", None)

    return calculate_days_since(start_date, end_date)


def determine_coordinator_stage(plants: list[Plant]) -> PlantStage:
    """Determine the dominant growth stage for environmental control.

    Applies a priority ladder so the most demanding stage wins:
    cure > dry > late_flower > mid_flower > early_flower > mother > veg > seedling == clone.
    """
    max_seedling_days = 0
    max_clone_days = 0
    max_veg_days = 0
    max_flower_days = 0
    max_dry_days = 0
    max_cure_days = 0
    max_mother_days = 0

    for plant in plants:
        max_seedling_days = max(
            max_seedling_days, calculate_days_in_stage(plant, PlantStage.SEEDLING)
        )
        max_clone_days = max(
            max_clone_days, calculate_days_in_stage(plant, PlantStage.CLONE)
        )
        max_veg_days = max(max_veg_days, calculate_days_in_stage(plant, PlantStage.VEG))
        max_flower_days = max(
            max_flower_days, calculate_days_in_stage(plant, PlantStage.FLOWER)
        )
        max_dry_days = max(max_dry_days, calculate_days_in_stage(plant, PlantStage.DRY))
        max_cure_days = max(
            max_cure_days, calculate_days_in_stage(plant, PlantStage.CURE)
        )
        max_mother_days = max(
            max_mother_days, calculate_days_in_stage(plant, PlantStage.MOTHER)
        )

    if max_cure_days > 0:
        return PlantStage.CURE
    if max_dry_days > 0:
        return PlantStage.DRY
    if max_flower_days > FLOWER_LATE_MIN_DAYS:
        return PlantStage.FLOWER_LATE
    if max_flower_days > DEFAULT_FLOWER_EARLY_DAYS:
        return PlantStage.FLOWER_MID
    if max_flower_days > 0:
        return PlantStage.FLOWER_EARLY
    if max_mother_days > 0:
        return PlantStage.MOTHER
    if max_veg_days > 0:
        return PlantStage.VEG
    if max_seedling_days > 0:
        return PlantStage.SEEDLING
    if max_clone_days > 0:
        return PlantStage.CLONE

    return PlantStage.VEG
