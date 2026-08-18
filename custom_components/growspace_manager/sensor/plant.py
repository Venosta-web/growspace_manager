"""Plant entity sensor for Growspace Manager."""

from __future__ import annotations

from typing import Any, override

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import Plant
from custom_components.growspace_manager.presentation.plant_view_model import (
    PlantViewModelBuilder,
)
from custom_components.growspace_manager.utils import calculate_plant_stage
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity


class PlantEntity(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):
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
    @override
    def native_value(self) -> str:
        """Return the current growth stage of the plant."""
        plant = self.coordinator.plants.get(self._plant.plant_id)
        if not plant:
            return "unknown"

        stage = calculate_plant_stage(plant)

        self.coordinator.growspaces.get(plant.growspace_id)

        return stage

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the detailed state attributes for the plant."""
        plant = self.coordinator.plants.get(self._plant.plant_id)
        if not plant:
            return {}

        return PlantViewModelBuilder.build_attributes(plant)

    @override
    async def async_added_to_hass(self) -> None:
        """Register callbacks when the entity is added to Home Assistant."""
        await super().async_added_to_hass()
