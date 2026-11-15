"""Compact, flat Growspace Mapping sensors for external consumers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, override

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import MATCH_ALL, MAX_LENGTH_STATE_ENTITY_ID
from homeassistant.core import Event, EventStateChangedData, callback, valid_entity_id
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..const import DOMAIN
from ..coordinator import GrowspaceCoordinator
from ..models import ACInfinityDevice, Growspace
from ..utils import (
    default_calculated_vpd_entity_id,
    generate_growspace_overview_unique_id,
    generate_vpd_sensor_unique_id,
)

_METRICS = (
    "granular_stage",
    "is_day",
    "veg_week",
    "flower_week",
    "vpd_target_min",
    "vpd_target_max",
    "vpd_danger_min",
    "vpd_danger_max",
)
# Leave room for the entity references and for JSON encoding multibyte names.
_MAX_DISPLAY_NAME_LENGTH = 255
_MAX_GROWSPACE_ID_LENGTH = 255


def _primary_actuator(
    entity_id: str | None, ports: list[ACInfinityDevice]
) -> str | None:
    """Use the first AC Infinity port's mode entity when no plain actuator is set."""
    return entity_id or (ports[0].mode_entity if ports else None)


def _entity_reference(value: str | None) -> str | None:
    """Omit malformed and oversized references from imported configurations."""
    if value and len(value) <= MAX_LENGTH_STATE_ENTITY_ID and valid_entity_id(value):
        return value
    return None


class GrowspaceMappingSensor(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):
    """Expose one growspace's primary entity IDs and current display metrics."""

    _attr_has_entity_name = True
    _attr_translation_key = "growspace_mapping"
    _unrecorded_attributes = frozenset({MATCH_ALL})

    def __init__(self, coordinator: GrowspaceCoordinator, growspace: Growspace) -> None:
        """Bind this mapping to the growspace and its overview registry entry."""
        super().__init__(coordinator)
        self._growspace_id = growspace.id
        self._growspace_name_at_setup = growspace.name
        self._overview_unique_id = generate_growspace_overview_unique_id(growspace.id)
        self._attr_unique_id = f"{DOMAIN}_{growspace.id}_mapping"
        # A standalone entity keeps the uncapped device name out of friendly_name.
        self._attr_translation_placeholders = {
            "growspace": str(growspace.name)[:_MAX_DISPLAY_NAME_LENGTH]
        }
        self._tracked_overview: str | None = None
        self._untrack_overview: Callable[[], None] | None = None

    @override
    async def async_added_to_hass(self) -> None:
        """Follow the overview and relevant entity registry changes."""
        await super().async_added_to_hass()
        self._async_track_overview()
        self.async_on_remove(self._async_untrack_overview)
        self.async_on_remove(
            self.hass.bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED, self._async_registry_update
            )
        )

    @callback
    def _async_track_overview(self) -> None:
        overview_id = self._overview_entity_id
        if overview_id == self._tracked_overview:
            return
        self._async_untrack_overview()
        self._tracked_overview = overview_id
        if overview_id is not None:
            self._untrack_overview = async_track_state_change_event(
                self.hass, overview_id, self._async_overview_changed
            )

    @callback
    def _async_untrack_overview(self) -> None:
        if self._untrack_overview is not None:
            self._untrack_overview()
            self._untrack_overview = None

    @callback
    def _async_overview_changed(self, event: Event[EventStateChangedData]) -> None:
        """Follow direct overview refreshes as well as coordinator updates."""
        self.async_write_ha_state()

    @callback
    def _async_registry_update(
        self, event: Event[er.EventEntityRegistryUpdatedData]
    ) -> None:
        """Publish changed references without waiting for a coordinator refresh."""
        entity_id = event.data["entity_id"]
        if entity_id in (self._tracked_overview, self._overview_entity_id):
            self._async_track_overview()
            self.async_write_ha_state()
        elif (
            growspace := self.coordinator.services.growspaces.get_growspace(
                self._growspace_id
            )
        ) is not None and entity_id == self._vpd_entity_id(growspace):
            self.async_write_ha_state()

    def _vpd_entity_id(self, growspace: Growspace) -> str | None:
        environment = growspace.environment_config
        configured = environment.vpd_sensor
        pair_count = min(
            len(environment.temperature_sensors)
            or bool(environment.temperature_sensor),
            len(environment.humidity_sensors) or bool(environment.humidity_sensor),
        )
        if not pair_count:
            return configured

        index = 0 if pair_count > 1 else None
        registry = er.async_get(self.hass)
        unique_id = generate_vpd_sensor_unique_id(self._growspace_id, index)
        if configured:
            # A growspace rename leaves its original calculated VPD default in
            # the configuration until the next integration setup.
            if configured not in (
                default_calculated_vpd_entity_id(growspace.name, index),
                default_calculated_vpd_entity_id(self._growspace_name_at_setup, index),
            ):
                return configured
            if (entry := registry.async_get(configured)) and (
                entry.platform,
                entry.unique_id,
            ) != (DOMAIN, unique_id):
                return configured

        return registry.async_get_entity_id("sensor", DOMAIN, unique_id) or configured

    @property
    def _overview_entity_id(self) -> str | None:
        return er.async_get(self.hass).async_get_entity_id(
            "sensor", DOMAIN, self._overview_unique_id
        )

    @property
    def _metrics(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        serialized = data.get("serialized_growspaces", {}).get(self._growspace_id, {})
        return serialized.get("metrics", {})  # type: ignore[no-any-return]

    @property
    @override
    def native_value(self) -> str | None:
        """Return the current granular stage."""
        return self._metrics.get("granular_stage")

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return a fixed set of scalar attributes."""
        growspace = self.coordinator.services.growspaces.get_growspace(
            self._growspace_id
        )
        if growspace is None:
            return {}

        environment = growspace.environment_config
        entity_ids = {
            "overview_entity_id": self._overview_entity_id,
            "temperature_entity_id": environment.temperature_sensor,
            "humidity_entity_id": environment.humidity_sensor,
            "vpd_entity_id": self._vpd_entity_id(growspace),
            "exhaust_entity_id": _primary_actuator(
                environment.exhaust_fan_entity,
                environment.exhaust_fan_ac_infinity_devices,
            ),
            "circulation_entity_id": _primary_actuator(
                environment.circulation_fan_entity,
                environment.circulation_fan_ac_infinity_devices,
            ),
            "humidifier_entity_id": _primary_actuator(
                environment.humidifier_entity,
                environment.humidifier_ac_infinity_devices,
            ),
            "dehumidifier_entity_id": _primary_actuator(
                environment.dehumidifier_entity,
                environment.dehumidifier_ac_infinity_devices,
            ),
        }
        metrics = self._metrics
        return {
            "growspace_mapping": True,
            "growspace_id": (
                growspace.id if len(growspace.id) <= _MAX_GROWSPACE_ID_LENGTH else None
            ),
            "name": growspace.name[:_MAX_DISPLAY_NAME_LENGTH],
            "type": growspace.growspace_type.value,
            **{
                key: _entity_reference(entity_id)
                for key, entity_id in entity_ids.items()
            },
            **{key: metrics.get(key) for key in _METRICS},
        }
