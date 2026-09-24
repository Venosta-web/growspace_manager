"""Diagnostic reliability summary for a growspace."""

from __future__ import annotations

from typing import Any, override

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..const import DOMAIN
from ..coordinator import GrowspaceCoordinator


class GrowspaceReliabilitySensor(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):
    """Expose the durable cycle total and recent counters as attributes."""

    _attr_has_entity_name = True
    _attr_translation_key = "reliability"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:chart-timeline-variant"

    def __init__(
        self, coordinator: GrowspaceCoordinator, growspace_id: str, growspace_name: str
    ) -> None:
        """Bind the diagnostic entity to a growspace."""
        super().__init__(coordinator)
        self._growspace_id = growspace_id
        self._attr_unique_id = f"{DOMAIN}_{growspace_id}_reliability"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, growspace_id)},
            name=growspace_name,
            model="Growspace",
            manufacturer="Growspace Manager",
        )

    @property
    @override
    def available(self) -> bool:
        """Do not present a corrupt evidence record as a valid zero total."""
        return not self.coordinator.reliability.unreadable

    @property
    @override
    def native_value(self) -> int | None:
        """Return lifetime verified irrigation cycles."""
        if not self.available:
            return None
        return int(
            self.coordinator.reliability.snapshot(self._growspace_id)["lifetime"].get(
                "irrigation.completed_verified", 0
            )
        )

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the documented export shape as attributes."""
        return self.coordinator.reliability.snapshot(self._growspace_id)
