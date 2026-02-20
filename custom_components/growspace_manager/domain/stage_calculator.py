"""Stage calculation logic - pure domain functions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.growspace_manager.const import PlantStage
from custom_components.growspace_manager.utils import calculate_days_since

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
