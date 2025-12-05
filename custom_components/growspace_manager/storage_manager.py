"""Storage manager for Growspace Manager."""

from __future__ import annotations

import logging
from dataclasses import asdict

from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION
from .models import Growspace, Plant

_LOGGER = logging.getLogger(__name__)


class StorageManager:
    """Manages data persistence for the Growspace Manager."""

    def __init__(self, coordinator, hass) -> None:
        """Initialize the StorageManager.

        Args:
            coordinator: The GrowspaceCoordinator instance.
            hass: The Home Assistant instance.
        """
        self.coordinator = coordinator
        self.hass = hass
        self.store = Store(hass, STORAGE_VERSION, STORAGE_KEY)

    async def async_save(self) -> None:
        """Save the current state of all data to persistent storage."""
        await self.store.async_save(
            {
                "plants": {
                    pid: asdict(p) for pid, p in self.coordinator.plants.items()
                },
                "growspaces": {
                    gid: asdict(g) for gid, g in self.coordinator.growspaces.items()
                },
                "notifications_sent": self.coordinator._notifications_sent,
                "notifications_enabled": self.coordinator._notifications_enabled,
            }
        )

    async def async_load(self) -> None:
        """Load data from persistent storage and handle migrations."""
        data = await self.store.async_load()
        if not data:
            _LOGGER.info("No stored data found, starting fresh")
            return

        _LOGGER.debug("DEBUG: Raw storage data keys = %s", list(data.keys()))
        _LOGGER.debug(
            "DEBUG: Raw growspaces in storage = %s",
            list(data.get("growspaces", {}).keys()),
        )
        _LOGGER.info("Loading data from storage")

        # Load plants using from_dict (handles migration)
        try:
            self.coordinator.plants = {
                pid: Plant.from_dict(p) for pid, p in data.get("plants", {}).items()
            }
            _LOGGER.info("Loaded %d plants", len(self.coordinator.plants))
        except Exception as e:
            _LOGGER.exception("Error loading plants: %s", e)
            self.coordinator.plants = {}

        # Load growspaces using from_dict (handles migration)
        try:
            self.coordinator.growspaces = {
                gid: Growspace.from_dict(g)
                for gid, g in data.get("growspaces", {}).items()
            }
            _LOGGER.info("Loaded %d growspaces", len(self.coordinator.growspaces))

            # Apply options to growspaces
            if not self.coordinator.options:
                _LOGGER.debug("--- COORDINATOR HAS NO OPTIONS TO APPLY ---")
            else:
                _LOGGER.debug(
                    "--- APPLYING OPTIONS TO GROWSPACES: %s ---",
                    self.coordinator.options,
                )
                for growspace_id, growspace in self.coordinator.growspaces.items():
                    if growspace_id in self.coordinator.options:
                        growspace.environment_config = self.coordinator.options[
                            growspace_id
                        ]
                        _LOGGER.debug(
                            "--- SUCCESS: Applied env_config to '%s': %s ---",
                            growspace.name,
                            growspace.environment_config,
                        )
                    else:
                        _LOGGER.info(
                            "--- INFO: No options found for growspace '%s' ---",
                            growspace.name,
                        )
        except Exception as e:
            _LOGGER.exception("Error loading growspaces: %s", e)
            self.coordinator.growspaces = {}

        # Load notification tracking
        self.coordinator._notifications_sent = data.get("notifications_sent", {})

        # Load notification switch states
        self.coordinator._notifications_enabled = data.get("notifications_enabled", {})

        # Ensure all growspaces have a notification enabled state (default True)
        for growspace_id in self.coordinator.growspaces:
            if growspace_id not in self.coordinator._notifications_enabled:
                self.coordinator._notifications_enabled[growspace_id] = True

        # Migrate legacy growspace aliases
        # We delegate this back to the coordinator's migration manager
        # But since we are in StorageManager, we can access it via coordinator
        if hasattr(self.coordinator, "migration_manager"):
            self.coordinator.migration_manager.migrate_legacy_growspaces()
        else:
            # Fallback if migration manager is not yet initialized (should not happen if init order is correct)
            _LOGGER.warning("MigrationManager not found on coordinator during load")

        # Save migrated data back to storage
        await self.async_save()
        _LOGGER.info("Saved migrated data to storage")
