"""Drying sensor classes for Growspace Manager."""

from __future__ import annotations

from typing import Any, override

from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.drying_calculator import (
    compute_days_to_target,
    compute_weight_lost_pct,
    is_cure_ready,
)
from custom_components.growspace_manager.models import Plant
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity


class DryingWeightSensor(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):
    """Sensor tracking daily drying weight for a plant."""

    _attr_has_entity_name = True
    _attr_translation_key = "drying_weight"
    _attr_native_unit_of_measurement = "g"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:scale"

    def __init__(self, coordinator: GrowspaceCoordinator, plant: Plant) -> None:
        """Initialize the drying weight sensor."""
        from custom_components.growspace_manager.const import DOMAIN  # noqa: PLC0415

        super().__init__(coordinator)
        self._plant_id = plant.plant_id
        self._attr_unique_id = f"{DOMAIN}_{plant.plant_id}_drying_weight"
        growspace = coordinator.services.growspaces.get_growspace(plant.growspace_id)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, plant.growspace_id)},
            name=growspace.name if growspace else plant.growspace_id,
            model="Growspace",
            manufacturer="Growspace Manager",
        )

    def _get_plant(self) -> Plant | None:
        return self.coordinator.services.plants.get_plant(self._plant_id)

    @property
    @override
    def native_value(self) -> float | None:
        """Return the latest logged weight in grams."""
        plant = self._get_plant()
        if not plant or not plant.drying_data.weight_log:
            return None
        return plant.drying_data.weight_log[-1].weight_grams

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return weight_lost_pct and days_to_target."""
        plant = self._get_plant()
        if not plant:
            return {}
        wet_weight = plant.harvest_metrics.wet_weight
        log = plant.drying_data.weight_log
        current = log[-1].weight_grams if log else None
        return {
            "weight_lost_pct": compute_weight_lost_pct(wet_weight, current)
            if current is not None
            else None,
            "days_to_target": compute_days_to_target(wet_weight, log),
        }


class DryingMoistureSensor(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):
    """Sensor tracking daily moisture meter readings for a plant."""

    _attr_has_entity_name = True
    _attr_translation_key = "drying_moisture"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:water-percent"

    def __init__(self, coordinator: GrowspaceCoordinator, plant: Plant) -> None:
        """Initialize the drying moisture sensor."""
        from custom_components.growspace_manager.const import DOMAIN  # noqa: PLC0415

        super().__init__(coordinator)
        self._plant_id = plant.plant_id
        self._attr_unique_id = f"{DOMAIN}_{plant.plant_id}_drying_moisture"
        growspace = coordinator.services.growspaces.get_growspace(plant.growspace_id)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, plant.growspace_id)},
            name=growspace.name if growspace else plant.growspace_id,
            model="Growspace",
            manufacturer="Growspace Manager",
        )

    def _get_plant(self) -> Plant | None:
        return self.coordinator.services.plants.get_plant(self._plant_id)

    @property
    @override
    def native_value(self) -> float | None:
        """Return the latest logged moisture percent."""
        plant = self._get_plant()
        if not plant or not plant.drying_data.moisture_log:
            return None
        return plant.drying_data.moisture_log[-1].moisture_percent


class DryingReadyForCureSensor(
    CoordinatorEntity[GrowspaceCoordinator], BinarySensorEntity
):
    """Binary sensor that is on when a plant's moisture is at or below the cure threshold."""

    _attr_has_entity_name = True
    _attr_translation_key = "drying_ready_for_cure"
    _attr_icon = "mdi:jar-outline"

    def __init__(self, coordinator: GrowspaceCoordinator, plant: Plant) -> None:
        """Initialize the ready-for-cure binary sensor."""
        from custom_components.growspace_manager.const import DOMAIN  # noqa: PLC0415

        super().__init__(coordinator)
        self._plant_id = plant.plant_id
        self._get_plant = coordinator.services.plants.get_plant
        self._attr_unique_id = f"{DOMAIN}_{plant.plant_id}_ready_for_cure"
        growspace = coordinator.services.growspaces.get_growspace(plant.growspace_id)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, plant.growspace_id)},
            name=growspace.name if growspace else plant.growspace_id,
            model="Growspace",
            manufacturer="Growspace Manager",
        )

    @property
    @override
    def is_on(self) -> bool:
        """Return True when the latest moisture reading is at or below the cure threshold."""
        plant = self._get_plant(self._plant_id)
        if not plant:
            return False
        return is_cure_ready(plant.drying_data.moisture_log)
