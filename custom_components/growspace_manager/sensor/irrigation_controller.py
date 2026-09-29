"""Irrigation safety state for a growspace."""

from __future__ import annotations

from typing import Any, cast, override

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.domain.irrigation_safety import (
    ControllerSnapshot,
    ControllerState,
    controller_snapshot,
)
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity


class IrrigationControllerSensor(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):
    """Expose the active interlock and its structured reasons."""

    _attr_has_entity_name = True
    _attr_translation_key = "irrigation_controller"
    _attr_icon = "mdi:water-pump"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [state.value for state in ControllerState]

    def __init__(
        self, coordinator: GrowspaceCoordinator, growspace_id: str, growspace_name: str
    ) -> None:
        """Bind the sensor to one growspace."""
        super().__init__(coordinator)
        self._growspace_id = growspace_id
        self._attr_unique_id = f"{DOMAIN}_{growspace_id}_irrigation_controller"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, growspace_id)},
            name=growspace_name,
            model="Growspace",
            manufacturer="Growspace Manager",
        )

    def _snapshot(self) -> ControllerSnapshot:
        irrigation = self.coordinator.services.growspaces.get_irrigation_coordinator(
            self._growspace_id
        )
        if irrigation is not None:
            return cast(ControllerSnapshot, irrigation.controller_snapshot())
        return controller_snapshot(
            configured=False, automation_enabled=False, running=False
        )

    @property
    @override
    def native_value(self) -> str | None:
        """Return the controller state."""
        return self._snapshot().state.value

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return reasons and acknowledgement metadata."""
        return self._snapshot().attributes()
