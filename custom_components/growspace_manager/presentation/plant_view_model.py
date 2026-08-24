"""Plant view model builder — the one producer of serialized Plant data.

Two projections live here so they can never drift field-by-field (ADR-0028):

- :meth:`PlantViewModelBuilder.build` — the wire payload the card reads
  (formatted dates, entity_id lookup).
- :meth:`PlantViewModelBuilder.build_attributes` — the plant sensor's HA
  attribute dict (raw stored date strings, so automations can parse them).

Sub-dataclass blocks (harvest_metrics, phenotype_score) serialize via the
model's own ``to_dict`` so a new model field can never silently drop from a
payload — the bug class behind the visual_tag/drying-fields incident.

Both projections report ``{stage}_days`` as [[Lifetime Stage Days]], including
every interval after a Reveg. ``days_since_last_watering`` keeps its historical
projection-specific semantics (never-watered → 0 on the wire, ``None`` on the
sensor).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from custom_components.growspace_manager.const import PLANT_STAGES
from custom_components.growspace_manager.domain import (
    get_days_since_watering,
    resolve_lifetime_stage_days,
)
from custom_components.growspace_manager.domain.current_stage import (
    resolve_current_stage,
)
from custom_components.growspace_manager.domain.plant_metrics import (
    format_plant_position,
    get_formatted_dates,
)
from custom_components.growspace_manager.drying_calculator import (
    compute_days_to_target,
    compute_weight_lost_pct,
    is_cure_ready,
)
from homeassistant.util import dt as dt_util

from .entity_queries import EntityQueries

if TYPE_CHECKING:
    from custom_components.growspace_manager.models import Plant
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def _drying_observations(plant: Plant) -> dict[str, Any]:
    """Drying-stage readout shared by the wire payload and the sensor."""
    weight_log = plant.drying_data.weight_log
    current_weight = weight_log[-1].weight_grams if weight_log else None
    wet_weight = plant.harvest_metrics.wet_weight
    moisture_log = plant.drying_data.moisture_log

    return {
        "drying_weight": current_weight,
        "weight_lost_pct": (
            compute_weight_lost_pct(wet_weight, current_weight)
            if current_weight is not None and wet_weight
            else None
        ),
        "days_to_target": compute_days_to_target(wet_weight, weight_log),
        "visual_tag": plant.drying_data.visual_tag,
        "drying_moisture": (
            moisture_log[-1].moisture_percent if moisture_log else None
        ),
        "drying_ready_for_cure": is_cure_ready(moisture_log),
    }


def _phi_fields(plant: Plant) -> dict[str, Any]:
    """PHI clearance readout, present only when a clearance date is set."""
    if not plant.phi_clearance_date:
        return {}
    fields: dict[str, Any] = {"phi_clearance_date": plant.phi_clearance_date}
    clearance = dt_util.parse_date(plant.phi_clearance_date)
    if clearance:
        remaining = (clearance - dt_util.now().date()).days
        fields["phi_days_remaining"] = max(0, remaining)
    else:
        fields["phi_days_remaining"] = None
    return fields


def _phenotype_score_dict(plant: Plant) -> dict[str, Any]:
    """Model-complete score dict plus the computed total_score property."""
    return {
        **plant.phenotype_score.to_dict(),
        "total_score": plant.phenotype_score.total_score,
    }


def _stage_day_fields(plant: Plant) -> dict[str, int]:
    """Return one shared Lifetime Stage Days projection for every stage key."""
    lifetime_days = resolve_lifetime_stage_days(plant, observed_on=dt_util.now().date())
    return {f"{stage}_days": lifetime_days.for_stage(stage) for stage in PLANT_STAGES}


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
        """Build the wire payload with all calculated fields.

        Args:
            plant: The plant to serialize.
            entity_id: Optional pre-resolved entity ID.

        Returns:
            Dictionary containing all plant data for frontend.
        """
        # Look up entity ID if not provided
        if not entity_id:
            entity_id = self.entity_queries.lookup_plant_entity_id(plant.plant_id)

        return {
            "plant_id": plant.plant_id,
            "growspace_id": plant.growspace_id,
            "updated_at": plant.updated_at,
            "entity_id": entity_id,
            "strain": plant.strain,
            "phenotype": plant.phenotype,
            # Days in stage
            **_stage_day_fields(plant),
            # Start dates (formatted for display)
            **get_formatted_dates(plant),
            # Location & Stage
            "row": int(plant.row),
            "col": int(plant.col),
            "position": format_plant_position(plant),
            "stage": resolve_current_stage(plant),
            # Watering & Training
            "last_training_technique": plant.last_training_technique,
            "last_ipm_type": plant.last_ipm_type,
            "days_since_last_watering": get_days_since_watering(plant),
            # Drying data — read by the plant overview dialog's drying tab
            **_drying_observations(plant),
            # PHI clearance readout
            **_phi_fields(plant),
            # Harvest & phenotype data — model-complete via to_dict
            "harvest_metrics": plant.harvest_metrics.to_dict(),
            "phenotype_score": _phenotype_score_dict(plant),
        }

    @staticmethod
    def build_attributes(plant: Plant) -> dict[str, Any]:
        """Build the plant sensor's HA attribute dict.

        Keeps raw stored date strings (not display-formatted) so user
        automations can parse them; every computed block is shared with
        :meth:`build`.
        """
        attributes: dict[str, Any] = {
            "stage": resolve_current_stage(plant),
            "growspace_id": plant.growspace_id,
            "plant_id": plant.plant_id,
            "updated_at": plant.updated_at,
            "strain": plant.strain,
            "phenotype": plant.phenotype,
            "row": plant.row,
            "col": plant.col,
            "position": format_plant_position(plant),
            "phenotype_score": _phenotype_score_dict(plant),
            "harvest_metrics": plant.harvest_metrics.to_dict(),
        }

        attributes.update(_stage_day_fields(plant))

        for stage_name in PLANT_STAGES:
            start_key = f"{stage_name}_start"
            if hasattr(plant, start_key):
                attributes[start_key] = getattr(plant, start_key)

        attributes["veg_week"] = plant.get_week_in_stage("veg")
        attributes["flower_week"] = plant.get_week_in_stage("flower")

        attributes["last_watered"] = plant.last_watered
        attributes["days_since_last_watering"] = plant.get_days_since_watering()

        attributes.update(_drying_observations(plant))
        attributes.update(_phi_fields(plant))

        return attributes
