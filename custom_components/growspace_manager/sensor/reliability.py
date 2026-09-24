"""Diagnostic reliability summary for a growspace."""

from __future__ import annotations

from typing import override

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import MATCH_ALL
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..const import DOMAIN
from ..coordinator import GrowspaceCoordinator
from ..reliability_store import ReliabilityCounter


class GrowspaceReliabilitySensor(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):
    """Expose lifetime verified cycles, with the key counters as attributes.

    The attributes change every observed minute, so none is recorded: the
    Recorder keeps the state, and the full history is in the export.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "reliability"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:chart-timeline-variant"
    _unrecorded_attributes = frozenset({MATCH_ALL})

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
        self._refresh()

    @callback
    def _refresh(self) -> None:
        """Read one snapshot into the state and attributes."""
        store = self.coordinator.reliability
        if store.unreadable:
            self._attr_native_value = None
            self._attr_extra_state_attributes = {}
            return
        attributes = store.sensor_attributes(self._growspace_id)
        self._attr_native_value = int(
            attributes[ReliabilityCounter.COMPLETED_VERIFIED.replace(".", "_")]
        )
        self._attr_extra_state_attributes = attributes

    @property
    @override
    def available(self) -> bool:
        """Do not present a corrupt evidence record as a valid zero total."""
        return super().available and not self.coordinator.reliability.unreadable

    @callback
    @override
    def _handle_coordinator_update(self) -> None:
        """Re-read the counters on each coordinator update."""
        self._refresh()
        super()._handle_coordinator_update()
