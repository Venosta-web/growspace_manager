"""Stage calculation logic - pure domain functions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.growspace_manager.utils import calculate_days_since

from .cultivation_band import band_plant_stage, growspace_cultivation_band
from .stage import PlantStage

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

    Delegates to the [[Plant Lifecycle]] module's [[Cultivation Band]] so the
    dehumidifier, humidifier, circulation fan, and exhaust fan classify flower
    on exactly the same boundaries the Bayesian evaluation does. The old strict
    ``> 21`` / ``> 42`` comparisons here put day 21 in Early Flower and day 42
    in Mid Flower while every other consumer had already moved on (#635).

    The band ladder is unchanged: cure > dry > late_flower > mid_flower >
    early_flower > mother > veg > seedling == clone, and an empty growspace
    still reports veg.
    """
    if not plants:
        return PlantStage.VEG
    return band_plant_stage(growspace_cultivation_band(plants))
