"""Strain-related sensor classes for Growspace Manager."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, override

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

STRAIN_LIBRARY_DEVICE_INFO = DeviceInfo(
    identifiers={(DOMAIN, "strain_library")},
    name="Strain Library",
    model="Strain Library",
    manufacturer="Growspace Manager",
)


class StrainLibrarySensor(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):  # type: ignore[misc]
    """A sensor that provides analytics from the user's strain library."""

    _attr_has_entity_name = True
    _attr_translation_key = "strain_library"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = None
    _unrecorded_attributes = frozenset()

    def __init__(self, coordinator: GrowspaceCoordinator) -> None:
        """Initialize the Strain Library sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_strain_library"
        self._attr_translation_key = "strain_library"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_info = STRAIN_LIBRARY_DEVICE_INFO

    @staticmethod
    def _strain_counts(strains: dict[str, dict[str, Any]]) -> tuple[int, int, int]:
        """Return catalogued, ancestor, and total strain counts."""
        ancestor_count = sum(
            bool(data.get("meta", {}).get("is_stub", False))
            for data in strains.values()
        )
        total_count = len(strains)
        return total_count - ancestor_count, ancestor_count, total_count

    @property
    @override  # type: ignore[misc]
    def native_value(self) -> int:
        """Return the number of catalogued strains in the library."""
        strains = self.coordinator.services.config.strain_library.get_all()
        catalogued_count, _, _ = self._strain_counts(strains)
        return catalogued_count

    @property
    @override  # type: ignore[misc]
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return strain analytics as state attributes."""
        analytics = self.coordinator.services.config.strain_library.get_analytics()
        strains = self.coordinator.services.config.strain_library.get_all()
        catalogued_count, ancestor_count, total_count = self._strain_counts(strains)
        catalogued_strains = {
            name
            for name, data in strains.items()
            if not data.get("meta", {}).get("is_stub", False)
        }

        return {
            "strain_count": catalogued_count,
            "ancestor_strain_count": ancestor_count,
            "total_strain_count": total_count,
            "strain_list": [
                name
                for name in analytics.get("strain_list", [])
                if name in catalogued_strains
            ],
            "last_updated": dt_util.utcnow().isoformat(),
            "note": "Full analytics available via WebSocket API: growspace_manager/get_strain_library",
        }


class SeedInventorySensor(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):  # type: ignore[misc]
    """Sensor exposing the total seed count across all batches."""

    _attr_has_entity_name = True
    _attr_translation_key = "seed_inventory"
    _attr_icon = "mdi:seed"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: GrowspaceCoordinator) -> None:
        """Initialize the seed inventory sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_seed_inventory"
        self._attr_device_info = STRAIN_LIBRARY_DEVICE_INFO

    @property
    @override  # type: ignore[misc]
    def native_value(self) -> int:
        """Return total number of seeds across all batches."""
        return self.coordinator.services.genetics.get_total_seed_count()

    @property
    @override  # type: ignore[misc]
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return each seed batch as a list of dicts."""
        return {
            "seed_batches": [
                asdict(batch)
                for batch in self.coordinator.services.genetics.seed_batches.values()
            ],
        }
