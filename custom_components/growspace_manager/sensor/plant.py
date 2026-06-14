"""Plant entity sensor for Growspace Manager."""

from __future__ import annotations

from typing import Any, override

from custom_components.growspace_manager.const import (
    ATTR_COL,
    ATTR_GROWSPACE_ID,
    ATTR_PHENOTYPE,
    ATTR_PLANT_ID,
    ATTR_ROW,
    ATTR_STAGE,
    ATTR_STRAIN,
    DOMAIN,
    PLANT_STAGES,
)
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.drying_calculator import (
    compute_days_to_target,
    compute_weight_lost_pct,
    is_cure_ready,
)
from custom_components.growspace_manager.models import Plant
from custom_components.growspace_manager.utils import calculate_plant_stage
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util


class PlantEntity(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):  # type: ignore[misc]
    """A sensor representing a single plant in a growspace.

    The state of this sensor is the plant's current growth stage (e.g., 'veg',
    'flower'). Its attributes contain all other details about the plant, such as
    strain, position, and the duration of each growth stage.
    """

    _attr_has_entity_name = True
    _unrecorded_attributes = frozenset({"phenotype_score", "harvest_metrics"})

    def __init__(self, coordinator: GrowspaceCoordinator, plant: Plant) -> None:
        """Initialize the plant sensor entity."""
        super().__init__(coordinator)
        self._plant = plant
        self._attr_unique_id = f"{DOMAIN}_{plant.plant_id}"
        self._attr_name = f"{plant.strain} ({plant.row},{plant.col})"
        self._attr_translation_key = "plant"
        self._attr_native_unit_of_measurement = None

        growspace_id = plant.growspace_id
        growspace: Any = coordinator.growspaces.get(growspace_id, {})
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, growspace_id)},
            name=getattr(growspace, "name", growspace_id),
            model="Growspace",
            manufacturer="Growspace Manager",
        )

    @property
    @override  # type: ignore[misc]
    def native_value(self) -> str:
        """Return the current growth stage of the plant."""
        plant = self.coordinator.plants.get(self._plant.plant_id)
        if not plant:
            return "unknown"

        stage = calculate_plant_stage(plant)

        self.coordinator.growspaces.get(plant.growspace_id)

        return stage

    @property
    @override  # type: ignore[misc]
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the detailed state attributes for the plant."""
        plant = self.coordinator.plants.get(self._plant.plant_id)
        if not plant:
            return {}

        stage = calculate_plant_stage(plant)
        attributes = {
            ATTR_STAGE: stage,
            ATTR_GROWSPACE_ID: plant.growspace_id,
            ATTR_PLANT_ID: plant.plant_id,
            ATTR_STRAIN: plant.strain,
            ATTR_PHENOTYPE: plant.phenotype,
            ATTR_ROW: plant.row,
            ATTR_COL: plant.col,
            "position": f"({int(plant.row)},{int(plant.col)})",
            "phenotype_score": plant.phenotype_score.to_dict()
            if hasattr(plant.phenotype_score, "to_dict")
            else {},
            "harvest_metrics": plant.harvest_metrics.to_dict()
            if hasattr(plant.harvest_metrics, "to_dict")
            else {},
        }

        for stage_name in PLANT_STAGES:
            start_key = f"{stage_name}_start"
            if hasattr(plant, start_key):
                attributes[start_key] = getattr(plant, start_key)

            attributes[f"{stage_name}_days"] = plant.get_days_in_stage(stage_name)

        attributes["veg_week"] = plant.get_week_in_stage("veg")
        attributes["flower_week"] = plant.get_week_in_stage("flower")

        attributes["last_watered"] = plant.last_watered
        attributes["days_since_last_watering"] = plant.get_days_since_watering()

        weight_log = plant.drying_data.weight_log
        current_weight = weight_log[-1].weight_grams if weight_log else None
        wet_weight = plant.harvest_metrics.wet_weight
        attributes["drying_weight"] = current_weight
        attributes["weight_lost_pct"] = (
            compute_weight_lost_pct(wet_weight, current_weight)
            if current_weight is not None and wet_weight
            else None
        )
        attributes["days_to_target"] = compute_days_to_target(wet_weight, weight_log)
        attributes["visual_tag"] = plant.drying_data.visual_tag

        moisture_log = plant.drying_data.moisture_log
        attributes["drying_moisture"] = moisture_log[-1].moisture_percent if moisture_log else None
        attributes["drying_ready_for_cure"] = is_cure_ready(moisture_log)

        if plant.phi_clearance_date:
            attributes["phi_clearance_date"] = plant.phi_clearance_date
            try:
                clearance = dt_util.parse_date(plant.phi_clearance_date)
                if clearance:
                    remaining = (clearance - dt_util.now().date()).days
                    attributes["phi_days_remaining"] = max(0, remaining)
            except (ValueError, TypeError):
                attributes["phi_days_remaining"] = None

        return attributes

    @override  # type: ignore[misc]
    async def async_added_to_hass(self) -> None:
        """Register callbacks when the entity is added to Home Assistant."""
        await super().async_added_to_hass()
