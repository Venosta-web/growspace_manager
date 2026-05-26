"""Overview sensor classes for Growspace Manager."""

from __future__ import annotations

from typing import Any, override

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import Event
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..const import DOMAIN
from ..coordinator import GrowspaceCoordinator
from ..models import Growspace
from ..utils import generate_growspace_overview_unique_id


class GrowspaceOverviewSensor(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):  # type: ignore[misc]
    """A sensor that provides an overview of a single growspace.

    The state of this sensor is the number of plants in the growspace. Its
    attributes contain a wealth of information, including the grid layout,
    plant details, and overall stage progression, making it the primary
    entity for the companion Lovelace card.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "overview"
    _attr_native_unit_of_measurement = None

    _unrecorded_attributes = frozenset(
        {
            "environment_config",
            "notification_config",
            "irrigation_config",
            "drain_config",
        }
    )

    TRACKABLE_ENVIRONMENT_ATTRS: tuple[str, ...] = (
        "soil_moisture_sensor",
        "temperature_sensor",
        "humidity_sensor",
        "vpd_sensor",
        "dehumidifier_entities",
        "exhaust_fan_entities",
        "humidifier_entities",
        "circulation_fan_entities",
    )

    def __init__(
        self, coordinator: GrowspaceCoordinator, growspace_id: str, growspace: Growspace
    ) -> None:
        """Initialize the growspace overview sensor."""
        super().__init__(coordinator)
        self.growspace_id = growspace_id
        self._attr_unique_id = generate_growspace_overview_unique_id(growspace_id)

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, growspace_id)},
            name=growspace.name,
            model="Growspace",
            manufacturer="Growspace Manager",
        )

    @override  # type: ignore[misc]
    async def async_added_to_hass(self) -> None:
        """Register callbacks when the entity is added to Home Assistant."""
        await super().async_added_to_hass()

        entities_to_track = self._get_trackable_sensors()
        if entities_to_track:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, entities_to_track, self._handle_sensor_update
                )
            )

    def _get_trackable_sensors(self) -> list[str]:
        """Return list of environment sensors to track for real-time updates."""
        growspace = self.coordinator.growspaces.get(self.growspace_id)
        if not growspace or not growspace.environment_config:
            return []

        env_config = growspace.environment_config
        sensors: list[str] = []

        for attr in self.TRACKABLE_ENVIRONMENT_ATTRS:
            if val := getattr(env_config, attr, None):
                if isinstance(val, list):
                    sensors.extend(val)
                elif isinstance(val, str):
                    sensors.append(val)

        return sensors

    async def _handle_sensor_update(self, event: Event) -> None:
        """Handle updates from tracked environment sensors."""
        await self.coordinator.async_refresh_growspace_data(self.growspace_id)
        self.async_write_ha_state()

    @property
    @override  # type: ignore[misc]
    def native_value(self) -> int:
        """Return the number of plants in the growspace."""
        plants = self.coordinator.services.growspaces.get_growspace_plants(self.growspace_id)
        return len(plants)

    @property
    @override  # type: ignore[misc]
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the detailed state attributes for the growspace."""
        if not self.coordinator.data:
            return {}

        serialized = self.coordinator.data.get("serialized_growspaces", {}).get(
            self.growspace_id, {}
        )
        attributes = serialized.copy()

        attributes.pop("grid", None)
        attributes.pop("plants", None)

        return attributes  # type: ignore[no-any-return]


class GrowspaceListSensor(SensorEntity):  # type: ignore[misc]
    """A sensor that exposes the list of all configured growspaces."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = None
    _attr_has_entity_name = True

    def __init__(self, coordinator: GrowspaceCoordinator) -> None:
        """Initialize the growspace list sensor."""
        self.coordinator = coordinator
        self._attr_unique_id = f"{DOMAIN}_growspaces_list"
        self._attr_translation_key = "growspaces_list"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "service")},
            name="Growspace Manager Service",
            model="Service",
            manufacturer="Growspace Manager",
        )
        self._update_growspaces()

    def _update_growspaces(self) -> None:
        """Update the internal list of growspaces from the coordinator."""
        plant_counts: dict[str, int] = {}
        for plant in self.coordinator.plants.values():
            gid = getattr(plant, "growspace_id", None)
            if gid:
                plant_counts[gid] = plant_counts.get(gid, 0) + 1
        self._growspaces = {
            gs_id: {
                "name": getattr(gs, "name", gs_id),
                "total_plants": plant_counts.get(gs_id, 0),
            }
            for gs_id, gs in self.coordinator.growspaces.items()
        }

    @property
    @override  # type: ignore[misc]
    def native_value(self) -> int:
        """Return the total number of growspaces."""
        self._update_growspaces()
        return len(self._growspaces)

    @property
    @override  # type: ignore[misc]
    def extra_state_attributes(self) -> dict[str, dict[str, Any]]:
        """Return the list of growspaces as a state attribute."""
        return {"growspaces": self._growspaces}
