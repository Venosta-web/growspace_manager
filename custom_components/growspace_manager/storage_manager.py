"""Storage manager for Growspace Manager."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_KEY_CONFIG, STORAGE_KEY_PLANTS, STORAGE_VERSION
from .models import EnvironmentConfig, IPMPreset, NutrientInventory, NutrientPreset

if TYPE_CHECKING:
    from .coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


class StorageManager:
    """Manages data persistence for the Growspace Manager."""

    def __init__(self, coordinator: GrowspaceCoordinator, hass: HomeAssistant) -> None:
        """Initialize the StorageManager.

        Args:
            coordinator: The GrowspaceCoordinator instance.
            hass: The Home Assistant instance.
        """
        self.coordinator = coordinator
        self.hass = hass

        # Segmented stores
        self.config_store = Store(hass, STORAGE_VERSION, STORAGE_KEY_CONFIG)
        self.plants_store = Store(hass, STORAGE_VERSION, STORAGE_KEY_PLANTS)

        # Legacy store for migration
        self.legacy_store = Store(hass, STORAGE_VERSION, STORAGE_KEY)

    async def async_save(self) -> None:
        """Save the current state to persistent storage (debounced)."""
        # debounce delay of 10 seconds as requested
        self.config_store.async_delay_save(self._get_config_data, 10)
        self.plants_store.async_delay_save(self._get_plants_data, 10)

    async def async_force_save(self) -> None:
        """Force save immediately (ignoring delay) to ensure data integrity."""
        await self.config_store.async_save(self._get_config_data())
        await self.plants_store.async_save(self._get_plants_data())

    def _get_config_data(self) -> dict[str, Any]:
        """Gather configuration data for storage."""
        # Use coordinator's nutrient manager for serialization data
        nutrient_data = self.coordinator.nutrient_manager.get_serialization_data()

        config = {
            "growspaces": {
                gid: asdict(g) for gid, g in self.coordinator.growspaces.items()
            },
            "notifications_sent": self.coordinator.notifications_sent,
            "notifications_enabled": self.coordinator.notifications_enabled,
        }
        # Merge nutrient data (presets and inventory)
        config.update(nutrient_data)
        return config

    def _get_plants_data(self) -> dict[str, Any]:
        """Gather plant data for storage."""
        return {
            "plants": {pid: asdict(p) for pid, p in self.coordinator.plants.items()},
        }

    async def async_load(self) -> None:
        """Load data from persistent storage and handle migrations."""
        config_data = await self.config_store.async_load()
        plants_data = await self.plants_store.async_load()

        if config_data or plants_data:
            _LOGGER.info("Loading data from segmented storage")
            if config_data:
                self._load_config(config_data)
            if plants_data:
                self._load_plants(plants_data)
        else:
            # Fallback to legacy
            _LOGGER.info("Checking for legacy storage data")
            legacy_data = await self.legacy_store.async_load()
            if legacy_data:
                _LOGGER.info("Migrating from legacy storage found")
                self._load_legacy(legacy_data)

                # Perform immediate save to migrate to new structure
                await self.config_store.async_save(self._get_config_data())
                await self.plants_store.async_save(self._get_plants_data())
            else:
                _LOGGER.info("No stored data found, starting fresh")
                # Ensure files are created even if empty
                await self.async_save()

    def _load_config(self, data: dict[str, Any]) -> None:
        """Load configuration data."""
        self._load_growspaces(data)

        # Load nutrient data into manager
        nutrient_presets = self._load_nutrient_presets(data)
        ipm_presets = self._load_ipm_presets(data)
        inventory = self._load_nutrient_inventory(data)

        self.coordinator.nutrient_manager.load_data(
            nutrient_presets, ipm_presets, inventory
        )

        # Notify coordinator of inventory load (compatibility shim/trigger)
        self.coordinator.on_nutrient_inventory_loaded(inventory)

        # Load notification tracking
        self.coordinator.notifications_sent = data.get("notifications_sent", {})
        self.coordinator.notifications_enabled = data.get("notifications_enabled", {})

        # Ensure all growspaces have a notification enabled state
        for growspace_id in self.coordinator.growspaces:
            if growspace_id not in self.coordinator.notifications_enabled:
                self.coordinator.notifications_enabled[growspace_id] = True

    def _load_legacy(self, data: dict[str, Any]) -> None:
        """Load from legacy single-file format."""
        # Legacy format had everything in one dict
        self._load_plants(data)  # Plants were top level "plants" key
        self._load_config(data)  # Config keys were also top level

    def _backup_corrupt_data(self, key: str, data: dict[str, Any]) -> None:
        """Backup corrupt data to a file before reset."""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"growspace_manager_{key}_CORRUPT_{timestamp}.json"
            backup_path = Path(self.hass.config.path(".storage")) / backup_filename

            with backup_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)

            _LOGGER.critical(
                "Data corruption detected for %s. Raw data backed up to %s before reset",
                key,
                backup_path,
            )
        except (OSError, TypeError, ValueError):
            _LOGGER.exception("Failed to backup corrupt %s data", key)

    def _load_plants(self, data: dict[str, Any]) -> None:
        """Load plants from storage data."""
        try:
            self.coordinator.plants = self.coordinator.serializer.deserialize_plants(
                data.get("plants", {})
            )
            _LOGGER.info("Loaded %d plants", len(self.coordinator.plants))
        except Exception:
            _LOGGER.exception("Error loading plants")
            self._backup_corrupt_data("plants", data)
            self.coordinator.plants = {}

    def _load_growspaces(self, data: dict[str, Any]) -> None:
        """Load growspaces from storage data."""
        try:
            self.coordinator.growspaces = (
                self.coordinator.serializer.deserialize_growspaces(
                    data.get("growspaces", {})
                )
            )
            _LOGGER.info("Loaded %d growspaces", len(self.coordinator.growspaces))

            self._apply_options_to_growspaces()
        except Exception:
            _LOGGER.exception("Error loading growspaces")
            self._backup_corrupt_data("growspaces", data)
            self.coordinator.growspaces = {}

    def _apply_options_to_growspaces(self) -> None:
        """Apply configuration options to loaded growspaces."""
        if not self.coordinator.options:
            return

        for growspace_id, growspace in self.coordinator.growspaces.items():
            if growspace_id in self.coordinator.options:
                options = self.coordinator.options[growspace_id]
                if isinstance(options, dict):
                    growspace.environment_config = EnvironmentConfig.from_dict(options)
                else:
                    growspace.environment_config = options

    def _load_nutrient_presets(self, data: dict[str, Any]) -> dict[str, NutrientPreset]:
        """Load nutrient presets from storage data."""
        try:
            return {
                pid: NutrientPreset.from_dict(p)
                for pid, p in data.get("nutrient_presets", {}).items()
            }
        except Exception:
            _LOGGER.exception("Error loading nutrient presets")
            return {}

    def _load_ipm_presets(self, data: dict[str, Any]) -> dict[str, IPMPreset]:
        """Load IPM presets from storage data."""
        try:
            return {
                pid: IPMPreset.from_dict(p)
                for pid, p in data.get("ipm_presets", {}).items()
            }
        except Exception:
            _LOGGER.exception("Error loading IPM presets")
            return {}

    def _load_nutrient_inventory(self, data: dict[str, Any]) -> NutrientInventory:
        """Load nutrient inventory from storage data."""
        try:
            # Explicitly type the result of from_dict
            inventory: NutrientInventory = NutrientInventory.from_dict(
                data.get("nutrient_inventory", {})
            )
        except Exception:
            _LOGGER.exception("Error loading nutrient inventory")
            return NutrientInventory()
        else:
            return inventory
