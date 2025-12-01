"""Migration manager for Growspace Manager."""

from __future__ import annotations

import logging
from typing import Any

from .const import SPECIAL_GROWSPACES
from .models import Growspace, Plant

_LOGGER = logging.getLogger(__name__)


class MigrationManager:
    """Manages data migrations for the Growspace Manager."""

    def __init__(self, coordinator) -> None:
        """Initialize the MigrationManager.

        Args:
            coordinator: The GrowspaceCoordinator instance.
        """
        self.coordinator = coordinator

    def migrate_legacy_growspaces(self) -> None:
        """Migrate legacy special growspace aliases to their canonical forms."""
        try:
            for config in SPECIAL_GROWSPACES.values():
                canonical_id = config["canonical_id"]
                canonical_name = config["canonical_name"]
                aliases = config["aliases"]

                for alias in aliases:
                    self._migrate_special_alias_if_needed(
                        alias, canonical_id, canonical_name
                    )
        except ValueError as e:
            _LOGGER.debug("Special growspace migration skipped: %s", e)

    def _migrate_special_alias_if_needed(
        self, alias_id: str, canonical_id: str, canonical_name: str
    ) -> None:
        """Migrate a single growspace alias to its canonical ID if it exists."""
        if alias_id == canonical_id:
            return

        growspaces = self.coordinator.growspaces
        alias_exists = alias_id in growspaces
        canonical_exists = canonical_id in growspaces

        if alias_exists and not canonical_exists:
            self._create_canonical_from_alias(alias_id, canonical_id, canonical_name)
        elif alias_exists and canonical_exists:
            self._consolidate_alias_into_canonical(alias_id, canonical_id)

    def _create_canonical_from_alias(
        self, alias_id: str, canonical_id: str, canonical_name: str
    ) -> None:
        """Create a new canonical growspace from a legacy alias."""
        growspaces = self.coordinator.growspaces
        src = growspaces[alias_id]
        
        # Handle both dict and object access for src (just in case)
        # Though in coordinator it seems they are objects after load.
        # But during load they might be dicts? 
        # The coordinator load converts them to objects first.
        # So we can assume objects.
        
        rows = getattr(src, "rows", 3)
        plants_per_row = getattr(src, "plants_per_row", 3)
        notification_target = getattr(src, "notification_target", None)
        device_id = getattr(src, "device_id", None)

        growspaces[canonical_id] = Growspace(
            id=canonical_id,
            name=canonical_name,
            rows=int(rows),
            plants_per_row=int(plants_per_row),
            notification_target=notification_target,
            device_id=device_id,
        )

        self.migrate_plants_to_growspace(alias_id, canonical_id)
        growspaces.pop(alias_id, None)
        self.coordinator.update_data_property()

        _LOGGER.info("Migrated growspace alias '%s' → '%s'", alias_id, canonical_id)

    def _consolidate_alias_into_canonical(
        self, alias_id: str, canonical_id: str
    ) -> None:
        """Consolidate plants from a legacy alias into an existing canonical growspace."""
        self.migrate_plants_to_growspace(alias_id, canonical_id)
        self.coordinator.growspaces.pop(alias_id, None)
        self.coordinator.update_data_property()

        _LOGGER.info(
            "Consolidated growspace alias '%s' into '%s'", alias_id, canonical_id
        )

    def migrate_plants_to_growspace(self, from_id: str, to_id: str) -> None:
        """Move all plants from one growspace to another."""
        for plant in self.coordinator.plants.values():
            if plant.growspace_id == from_id:
                plant.growspace_id = to_id

    def cleanup_legacy_aliases(self, canonical_id: str) -> None:
        """Remove any legacy alias growspaces that have been migrated."""
        config = SPECIAL_GROWSPACES.get(canonical_id, {})
        aliases = config.get("aliases", [])

        if aliases:
            growspaces = self.coordinator.growspaces
            for legacy_id in list(growspaces.keys()):
                # Only remove if it's an exact alias match, not a user-created growspace
                if legacy_id in aliases and legacy_id != canonical_id:
                    self.migrate_plants_to_growspace(legacy_id, canonical_id)
                    growspaces.pop(legacy_id, None)
                    _LOGGER.info("Removed legacy growspace: %s", legacy_id)
