"""Stage calculation logic - pure domain functions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .cultivation_band import band_plant_stage, growspace_cultivation_band
from .stage import PlantStage

if TYPE_CHECKING:
    from custom_components.growspace_manager.models import Plant


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
