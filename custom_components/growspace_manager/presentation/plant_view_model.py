"""Plant view model builder for frontend consumption."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from custom_components.growspace_manager.domain import (
    calculate_days_in_stage,
    get_days_since_watering,
)
from custom_components.growspace_manager.domain.plant_metrics import (
    format_plant_position,
    get_formatted_dates,
)
from custom_components.growspace_manager.utils import calculate_plant_stage

from .entity_queries import EntityQueries

if TYPE_CHECKING:
    from custom_components.growspace_manager.models import Plant
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class PlantViewModelBuilder:
    """Builds rich plant payloads for frontend consumption."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the plant view model builder.

        Args:
            hass: Home Assistant instance.
        """
        self.hass = hass
        self.entity_queries = EntityQueries(hass)

    def build(self, plant: Plant, entity_id: str | None = None) -> dict[str, Any]:
        """Build complete plant payload with all calculated fields.

        Args:
            plant: The plant to serialize.
            entity_id: Optional pre-resolved entity ID.

        Returns:
            Dictionary containing all plant data for frontend.
        """
        # Look up entity ID if not provided
        if not entity_id:
            entity_id = self.entity_queries.lookup_plant_entity_id(plant.plant_id)

        # Get formatted dates
        dates = get_formatted_dates(plant)

        # Calculate days in each stage
        stage_days = {
            "seedling_days": calculate_days_in_stage(plant, "seedling"),
            "mother_days": calculate_days_in_stage(plant, "mother"),
            "clone_days": calculate_days_in_stage(plant, "clone"),
            "veg_days": calculate_days_in_stage(plant, "veg"),
            "flower_days": calculate_days_in_stage(plant, "flower"),
            "dry_days": calculate_days_in_stage(plant, "dry"),
            "cure_days": calculate_days_in_stage(plant, "cure"),
        }

        # Build complete payload
        return {
            "plant_id": plant.plant_id,
            "growspace_id": plant.growspace_id,
            "entity_id": entity_id,
            "strain": plant.strain,
            "phenotype": plant.phenotype,
            # Days in stage
            **stage_days,
            # Start dates
            **dates,
            # Location & Stage
            "row": int(plant.row),
            "col": int(plant.col),
            "position": format_plant_position(plant),
            "stage": calculate_plant_stage(plant),
            # Watering & Training
            "last_training_technique": plant.last_training_technique,
            "last_ipm_type": plant.last_ipm_type,
            "days_since_last_watering": get_days_since_watering(plant),
            # Harvest data — included so the frontend plant overview dialog can read them
            "harvest_metrics": {
                "wet_weight": plant.harvest_metrics.wet_weight,
                "dry_weight": plant.harvest_metrics.dry_weight,
                "trim_weight": plant.harvest_metrics.trim_weight,
                "thc_percentage": plant.harvest_metrics.thc_percentage,
                "cbd_percentage": plant.harvest_metrics.cbd_percentage,
                "terpene_profile": plant.harvest_metrics.terpene_profile,
            },
            "scores": {
                "vigor": plant.scores.vigor,
                "structure": plant.scores.structure,
                "aroma": plant.scores.aroma,
                "resin": plant.scores.resin,
                "pest_resistance": plant.scores.pest_resistance,
            },
        }
