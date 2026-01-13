"""Storage manager for Growspace Manager."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    STORAGE_KEY,
    STORAGE_KEY_CONFIG,
    STORAGE_KEY_PLANTS,
    STORAGE_VERSION,
)
from .models import (
    EnvironmentConfig,
    IPMPreset,
    NutrientPreset,
)

_LOGGER = logging.getLogger(__name__)


class StorageManager:
    """Manages data persistence for the Growspace Manager."""

    def __init__(self, coordinator, hass: HomeAssistant) -> None:
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

    def _get_config_data(self) -> dict:
        """Gather configuration data for storage."""
        return {
            "growspaces": {
                gid: asdict(g) for gid, g in self.coordinator.growspaces.items()
            },
            "nutrient_presets": {
                pid: asdict(p) for pid, p in self.coordinator.nutrient_presets.items()
            },
            "ipm_presets": {
                pid: asdict(p) for pid, p in self.coordinator.ipm_presets.items()
            },
            "notifications_sent": self.coordinator._notifications_sent,
            "notifications_enabled": self.coordinator._notifications_enabled,
        }

    def _get_plants_data(self) -> dict:
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

    def _load_config(self, data: dict) -> None:
        """Load configuration data."""
        self._load_growspaces(data)
        self._load_nutrient_presets(data)
        self._load_ipm_presets(data)

        # Load notification tracking
        self.coordinator._notifications_sent = data.get("notifications_sent", {})
        self.coordinator._notifications_enabled = data.get("notifications_enabled", {})

        # Ensure all growspaces have a notification enabled state
        for growspace_id in self.coordinator.growspaces:
            if growspace_id not in self.coordinator._notifications_enabled:
                self.coordinator._notifications_enabled[growspace_id] = True

    def _load_legacy(self, data: dict) -> None:
        """Load from legacy single-file format."""
        # Legacy format had everything in one dict
        self._load_plants(data)  # Plants were top level "plants" key
        self._load_config(data)  # Config keys were also top level

    def _backup_corrupt_data(self, key: str, data: dict) -> None:
        """Backup corrupt data to a file before reset."""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"growspace_manager_{key}_CORRUPT_{timestamp}.json"
            backup_path = Path(self.hass.config.path(".storage")) / backup_filename

            with open(backup_path, "w") as f:
                json.dump(data, f, indent=2, default=str)

            _LOGGER.critical(
                "Data corruption detected for %s. Raw data backed up to %s before reset",
                key,
                backup_path,
            )
        except Exception as e:
            _LOGGER.error("Failed to backup corrupt %s data: %s", key, e)

    def _load_plants(self, data: dict) -> None:
        """Load plants from storage data."""
        try:
            self.coordinator.plants = self.coordinator.serializer.deserialize_plants(
                data.get("plants", {})
            )
            _LOGGER.info("Loaded %d plants", len(self.coordinator.plants))
        except Exception as e:
            _LOGGER.exception("Error loading plants: %s", e)
            self._backup_corrupt_data("plants", data)
            self.coordinator.plants = {}

    def _load_growspaces(self, data: dict) -> None:
        """Load growspaces from storage data."""
        try:
            self.coordinator.growspaces = (
                self.coordinator.serializer.deserialize_growspaces(
                    data.get("growspaces", {})
                )
            )
            _LOGGER.info("Loaded %d growspaces", len(self.coordinator.growspaces))

            self._apply_options_to_growspaces()
        except Exception as e:
            _LOGGER.exception("Error loading growspaces: %s", e)
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

    def _load_nutrient_presets(self, data: dict) -> None:
        """Load nutrient presets from storage data."""
        try:
            self.coordinator.nutrient_presets = {
                pid: NutrientPreset.from_dict(p)
                for pid, p in data.get("nutrient_presets", {}).items()
            }
        except Exception as e:
            _LOGGER.exception("Error loading nutrient presets: %s", e)
            self.coordinator.nutrient_presets = {}

    def _load_ipm_presets(self, data: dict) -> None:
        """Load IPM presets from storage data."""
        try:
            self.coordinator.ipm_presets = {
                pid: IPMPreset.from_dict(p)
                for pid, p in data.get("ipm_presets", {}).items()
            }
        except Exception as e:
            _LOGGER.exception("Error loading IPM presets: %s", e)
            self.coordinator.ipm_presets = {}
