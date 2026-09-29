"""The Active Run Sensor: one Growspace's current Grow Run (#668, ADR-0035).

One lightweight entity per Growspace for dashboards and automations. Its state
is the Active Run's Sequence Number, or ``none``; its attributes are a fixed,
compact set whose keys never change with the state. Everything else about a
Run stays behind the integration's API, so completed history never becomes
entity-registry clutter.
"""

from __future__ import annotations

from typing import override

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
import homeassistant.util.dt as dt_util

from ..const import DOMAIN
from ..coordinator import GrowspaceCoordinator
from ..domain.grow_run import sensor_state
from ..services.grow_runs import ACTIVE_RUN_KEY, active_run_unique_id


class ActiveRunSensor(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):
    """Expose the Active Run's Sequence Number, or ``none``."""

    _attr_has_entity_name = True
    _attr_translation_key = ACTIVE_RUN_KEY
    _attr_icon = "mdi:sprout-outline"
    # Only the Run Revision is worth a Recorder row: it changes on every
    # lifecycle command. The rest restates the state or ticks daily.
    _unrecorded_attributes = frozenset(
        {"run_id", "label", "started_at", "duration_days", "participant_count"}
    )

    def __init__(
        self, coordinator: GrowspaceCoordinator, growspace_id: str, growspace_name: str
    ) -> None:
        """Bind the sensor to one Growspace's device."""
        super().__init__(coordinator)
        self._growspace_id = growspace_id
        self._attr_unique_id = active_run_unique_id(growspace_id)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, growspace_id)},
            name=growspace_name,
            model="Growspace",
            manufacturer="Growspace Manager",
        )
        self._refresh()

    @callback
    def _refresh(self) -> None:
        store = self.coordinator.grow_runs
        if store.unreadable:
            self._attr_native_value = None
            self._attr_extra_state_attributes = {}
            return
        state, attributes = sensor_state(
            store.ledger(self._growspace_id), dt_util.utcnow()
        )
        self._attr_native_value = state
        self._attr_extra_state_attributes = attributes

    @property
    @override
    def available(self) -> bool:
        """An unreadable history is unknown, not "no Active Run"."""
        return super().available and not self.coordinator.grow_runs.unreadable

    @callback
    @override
    def _handle_coordinator_update(self) -> None:
        """Re-read the ledger on each coordinator update."""
        self._refresh()
        super()._handle_coordinator_update()
