"""Storage manager for Growspace Manager."""

from __future__ import annotations

import logging
from dataclasses import asdict

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION
from .models import Growspace, GrowspaceEvent, Plant

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
                "events": {
                    gid: [evt.to_dict() for evt in events]
                    for gid, events in self.coordinator.events.items()
                },
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

        self._load_plants(data)
        self._load_growspaces(data)
        self._load_events(data)

        # Load notification tracking
        self.coordinator._notifications_sent = data.get("notifications_sent", {})

        # Load notification switch states
        self.coordinator._notifications_enabled = data.get("notifications_enabled", {})

        # Ensure all growspaces have a notification enabled state (default True)
        for growspace_id in self.coordinator.growspaces:
            if growspace_id not in self.coordinator._notifications_enabled:
                self.coordinator._notifications_enabled[growspace_id] = True

        # Migrate legacy growspace aliases
        if hasattr(self.coordinator, "migration_manager"):
            self.coordinator.migration_manager.migrate_legacy_growspaces()
        else:
            _LOGGER.warning("MigrationManager not found on coordinator during load")

        # Save migrated data back to storage
        await self.async_save()
        _LOGGER.info("Saved migrated data to storage")

    def _load_plants(self, data: dict) -> None:
        """Load plants from storage data."""
        try:
            self.coordinator.plants = {
                pid: Plant.from_dict(p) for pid, p in data.get("plants", {}).items()
            }
            _LOGGER.info("Loaded %d plants", len(self.coordinator.plants))
        except Exception as e:
            _LOGGER.exception("Error loading plants: %s", e)
            self.coordinator.plants = {}

    def _load_growspaces(self, data: dict) -> None:
        """Load growspaces from storage data."""
        try:
            self.coordinator.growspaces = {
                gid: Growspace.from_dict(g)
                for gid, g in data.get("growspaces", {}).items()
            }
            _LOGGER.info("Loaded %d growspaces", len(self.coordinator.growspaces))

            self._apply_options_to_growspaces()
        except Exception as e:
            _LOGGER.exception("Error loading growspaces: %s", e)
            self.coordinator.growspaces = {}

    def _apply_options_to_growspaces(self) -> None:
        """Apply configuration options to loaded growspaces."""
        if not self.coordinator.options:
            _LOGGER.debug("--- COORDINATOR HAS NO OPTIONS TO APPLY ---")
            return

        _LOGGER.debug(
            "--- APPLYING OPTIONS TO GROWSPACES: %s ---",
            self.coordinator.options,
        )
        for growspace_id, growspace in self.coordinator.growspaces.items():
            if growspace_id in self.coordinator.options:
                growspace.environment_config = self.coordinator.options[growspace_id]
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

    def _load_events(self, data: dict) -> None:
        """Load events from storage data."""
        try:
            raw_events = data.get("events", {})
            self.coordinator.events = {
                gid: [GrowspaceEvent.from_dict(evt) for evt in evts]
                for gid, evts in raw_events.items()
            }
            _LOGGER.info(
                "Loaded events for %d growspaces", len(self.coordinator.events)
            )
        except Exception as e:
            _LOGGER.exception("Error loading events: %s", e)
            self.coordinator.events = {}
