"""Coordinator for Growspace Manager integration.

This module contains the main coordinator that manages growspaces, plants,
notifications, and strain library data for the Growspace Manager integration.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict
from datetime import date, datetime
from typing import Any

from dateutil import parser

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    DATE_FIELDS,
    PLANT_STAGES,
    SPECIAL_GROWSPACES,
    STORAGE_KEY,
    STORAGE_KEY_STRAIN_LIBRARY,
    STORAGE_VERSION,
)
from .models import Growspace, Plant
from .strain_library import StrainLibrary
from .utils import (
    find_first_free_position,
    format_date,
    generate_growspace_grid,
)


_LOGGER = logging.getLogger(__name__)


# Type aliases for better readability
PlantDict = dict[str, Any]
GrowspaceDict = dict[str, Any]
NotificationDict = dict[str, Any]
DateInput = str | datetime | date | None


class GrowspaceCoordinator(DataUpdateCoordinator):
    """Coordinator for Growspace Manager."""

    def __init__(
        self, hass, data: dict | None = None, options: dict | None = None
    ) -> None:
        """Initialize the Growspace Coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Growspace Manager Coordinator",
        )

        self.hass = hass
        # Ensure data is always a dictionary
        if data is None:
            data = {}
        self.growspaces: dict[str, Growspace] = {}
        self.plants: dict[str, Plant] = {}
        self.store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)

        self.options = options or {}
        _LOGGER.debug(
            "--- COORDINATOR INITIALIZED WITH OPTIONS: %s ---",
            self.options,
        )

        # Initialize strain library immediately
        self.strains = StrainLibrary(hass, STORAGE_VERSION, STORAGE_KEY_STRAIN_LIBRARY)

        self._notifications_sent: dict[str, dict[str, bool]] = {}
        self._notifications_enabled: dict[
            str,
            bool,
        ] = {}  # ✅ Notification switch states
        # Initialize Env options
        self.options = options or {}

        # Load plants safely, ignoring invalid keys
        raw_plants = data.get("plants", {})
        for pid, pdata in raw_plants.items():
            try:
                if isinstance(pdata, dict):
                    self.plants[pid] = Plant.from_dict(pdata)
                elif isinstance(pdata, Plant):
                    self.plants[pid] = pdata
            except (ValueError, TypeError):
                _LOGGER.warning("Failed to load plant %s: %s", pid, pdata)

        # Optionally load growspaces if stored
        raw_growspaces = data.get("growspaces", {})
        for gid, gdata in raw_growspaces.items():
            try:
                self.growspaces[gid] = Growspace.from_dict(gdata)
            except (ValueError, TypeError):
                _LOGGER.warning("Failed to load growspace %s: %s", gid, gdata)

        _LOGGER.debug(
            "Loaded %d plants and %d growspaces",
            len(self.plants),
            len(self.growspaces),
        )

    # -----------------------------
    # Methods for editor dropdown
    # -----------------------------

    def get_growspace_options(self) -> dict[str, str]:
        """Return growspaces for dropdown selection in editor.

        Returns:
            dict: {growspace_id: growspace_name}

        """
        return {
            gs_id: getattr(gs, "name", gs_id) for gs_id, gs in self.growspaces.items()
        }

    def get_sorted_growspace_options(self) -> list[tuple[str, str]]:
        """Return sorted list of growspaces for dropdown, sorted by name."""
        return sorted(
            (
                (gs_id, getattr(gs, "name", gs_id))
                for gs_id, gs in self.growspaces.items()
            ),
            key=lambda x: x[1].lower(),
        )

    # =============================================================================
    # INITIALIZATION AND MIGRATION METHODS
    # =============================================================================

    def _migrate_legacy_growspaces(self) -> None:
        """Migrate legacy special growspace aliases to canonical forms."""
        try:
            for config in SPECIAL_GROWSPACES.values():
                canonical_id = config["canonical_id"]
                canonical_name = config["canonical_name"]
                aliases = config["aliases"]

                for alias in aliases:
                    self._migrate_special_alias_if_needed(
                        alias,
                        canonical_id,
                        canonical_name,
                    )
        except ValueError as e:
            _LOGGER.debug("Special growspace migration skipped: %s", e)

    def _migrate_special_alias_if_needed(
        self,
        alias_id: str,
        canonical_id: str,
        canonical_name: str,
    ) -> None:
        """Migrate alias growspace to canonical id and update plants."""
        if alias_id == canonical_id:
            return

        alias_exists = alias_id in self.growspaces
        canonical_exists = canonical_id in self.growspaces

        if alias_exists and not canonical_exists:
            self._create_canonical_from_alias(alias_id, canonical_id, canonical_name)
        elif alias_exists and canonical_exists:
            self._consolidate_alias_into_canonical(alias_id, canonical_id)

    def _create_canonical_from_alias(
        self,
        alias_id: str,
        canonical_id: str,
        canonical_name: str,
    ) -> None:
        """Create canonical growspace from alias."""
        src = self.growspaces[alias_id]
        self.growspaces[canonical_id] = Growspace(
            id=canonical_id,
            name=canonical_name,
            rows=int(
                getattr(src, "rows", 3)
                if isinstance(src, Growspace)
                else src.get("rows", 3),
            ),
            plants_per_row=int(
                getattr(src, "plants_per_row", 3)
                if isinstance(src, Growspace)
                else src.get("plants_per_row", 3),
            ),
            notification_target=getattr(src, "notification_target", None)
            if isinstance(src, Growspace)
            else src.get("notification_target"),
            device_id=getattr(src, "device_id", None)
            if isinstance(src, Growspace)
            else None,
        )

        self._migrate_plants_to_growspace(alias_id, canonical_id)
        self.growspaces.pop(alias_id, None)
        self.update_data_property()

        _LOGGER.info("Migrated growspace alias '%s' → '%s'", alias_id, canonical_id)

    def _consolidate_alias_into_canonical(
        self,
        alias_id: str,
        canonical_id: str,
    ) -> None:
        """Consolidate alias growspace into existing canonical."""
        self._migrate_plants_to_growspace(alias_id, canonical_id)
        self.growspaces.pop(alias_id, None)
        self.update_data_property()

        _LOGGER.info(
            "Consolidated growspace alias '%s' into '%s'",
            alias_id,
            canonical_id,
        )

    def _migrate_plants_to_growspace(self, from_id: str, to_id: str) -> None:
        """Migrate all plants from one growspace to another."""
        for plant in self.plants.values():
            if plant.growspace_id == from_id:
                plant.growspace_id = to_id

    # =============================================================================
    # UTILITY AND HELPER METHODS
    # =============================================================================

    def _get_plant_stage(self, plant: Plant) -> str:
        """Return the current stage of a plant based on its start dates."""
        if getattr(plant, "cure_start", None):
            return "cure"
        if getattr(plant, "dry_start", None):
            return "dry"
        if getattr(plant, "flower_start", None):
            return "flower"
        if getattr(plant, "veg_start", None):
            return "veg"
        if getattr(plant, "clone_start", None):
            return "clone"
        if getattr(plant, "mother_start", None):
            return "mother"
        return "seedling"

    def get_plant(self, plant_id: str) -> Plant | None:
        return self.plants.get(plant_id)

    def _canonical_special(self, gs_id: str) -> tuple[str, str]:
        """Return canonical (id, name) for special growspaces."""
        for config in SPECIAL_GROWSPACES.values():
            canonical_id = config["canonical_id"]
            canonical_name = config["canonical_name"]
            aliases = config["aliases"]

            for alias in aliases:
                self._migrate_special_alias_if_needed(
                    alias,
                    canonical_id,
                    canonical_name,
                )

        growspace = self.growspaces.get(gs_id)
        if growspace:
            return gs_id, growspace.name  # access attribute, not dict key
        return gs_id, gs_id

    def _validate_growspace_exists(self, growspace_id: str) -> None:
        """Validate that a growspace exists."""
        if growspace_id not in self.growspaces:
            raise ValueError(f"Growspace {growspace_id} does not exist")

    def _validate_plant_exists(self, plant_id: str) -> None:
        """Validate that a plant exists."""
        if plant_id not in self.plants:
            raise ValueError(f"Plant {plant_id} does not exist")

    def _validate_position_bounds(self, growspace_id: str, row: int, col: int) -> None:
        """Validate position is within growspace bounds."""
        growspace = self.growspaces[growspace_id]
        max_rows = int(growspace.rows)
        max_cols = int(growspace.plants_per_row)

        if row < 1 or row > max_rows:
            raise ValueError(f"Row {row} is outside growspace bounds (1-{max_rows})")
        if col < 1 or col > max_cols:
            raise ValueError(f"Column {col} is outside growspace bounds (1-{max_cols})")

    def _validate_position_not_occupied(
        self,
        growspace_id: str,
        row: int,
        col: int,
        exclude_plant_id: str | None = None,
    ) -> None:
        """Validate position is not occupied by another plant."""
        existing_plants = self.get_growspace_plants(growspace_id)
        for existing_plant in existing_plants:
            if (
                existing_plant.plant_id != exclude_plant_id
                and existing_plant.row == row
                and existing_plant.col == col
            ):
                raise ValueError(
                    f"Position ({row},{col}) is already occupied by {existing_plant.strain}",
                )

    def find_first_available_position(
        self, growspace_id: str
    ) -> tuple[int | None, int | None]:
        """Find the first available position in a growspace."""
        growspace = self.growspaces[growspace_id]
        occupied = {(p.row, p.col) for p in self.get_growspace_plants(growspace_id)}
        return find_first_free_position(growspace, occupied)

    def _parse_date_field(self, date_value: str | datetime | date | None) -> str | None:
        """Parse a date field into a string."""
        return format_date(date_value)

    def _parse_date_fields(self, kwargs: dict[str, Any]) -> None:
        """Parse all date fields in kwargs in-place."""
        for field in DATE_FIELDS:
            if field in kwargs:
                kwargs[field] = self._parse_date_field(kwargs[field])

    def _calculate_days(self, start_date: str | date | datetime | None) -> int:
        """Calculate days since a given date."""
        if not start_date or start_date == "None":  # extra guard
            return 0

        try:
            if isinstance(start_date, datetime):
                dt = start_date.date()
            elif isinstance(start_date, date):
                dt = start_date
            elif isinstance(start_date, str):
                dt = parser.isoparse(start_date).date()
            else:
                return 0

            return (date.today() - dt).days
        except (ValueError, TypeError) as e:
            _LOGGER.warning("Failed to calculate days for date %s: %s", start_date, e)
            return 0

    def _generate_unique_name(self, base_name: str) -> str:
        """Generate a unique growspace name."""
        existing_names = {gs.name.lower() for gs in self.growspaces.values()}
        name = base_name
        counter = 1

        while name.lower() in existing_names:
            name = f"{base_name} {counter}"
            counter += 1

        return name

    # =============================================================================
    # SPECIAL GROWSPACE MANAGEMENT
    # =============================================================================

    def ensure_special_growspace(
        self,
        growspace_id: str,
        name: str,
        rows: int = 3,
        plants_per_row: int = 3,
    ) -> str:
        """Ensure a special growspace exists with a stable id and return its id."""
        return self._ensure_special_growspace(growspace_id, name, rows, plants_per_row)

    def _ensure_special_growspace(
        self,
        growspace_id: str,
        name: str,
        rows: int = 3,
        plants_per_row: int = 3,
    ) -> str:
        """Ensure a special growspace exists with a stable id and return its id."""
        # Get canonical form
        canonical_id, canonical_name = self._canonical_special(growspace_id)

        # Clean up any legacy aliases
        self._cleanup_legacy_aliases(canonical_id)

        # Create or update the canonical growspace
        if canonical_id not in self.growspaces:
            self._create_special_growspace(
                canonical_id,
                canonical_name,
                rows,
                plants_per_row,
            )
            # ✅ Enable notifications by default for new special growspace
            self._notifications_enabled[canonical_id] = True
        else:
            self._update_special_growspace_name(canonical_id, canonical_name)

        self.update_data_property()
        return canonical_id

    def _cleanup_legacy_aliases(self, canonical_id: str) -> None:
        """Remove legacy aliases for a canonical growspace."""
        config = SPECIAL_GROWSPACES.get(canonical_id, {})
        aliases = config.get("aliases", [])

        if aliases:
            for legacy_id in list(self.growspaces.keys()):
                # Only remove if it's an exact alias match, not a user-created growspace
                if legacy_id in aliases and legacy_id != canonical_id:
                    self._migrate_plants_to_growspace(legacy_id, canonical_id)
                    self.growspaces.pop(legacy_id, None)
                    _LOGGER.info("Removed legacy growspace: %s", legacy_id)

    def _create_special_growspace(
        self,
        canonical_id: str,
        canonical_name: str,
        rows: int,
        plants_per_row: int,
    ) -> None:
        """Create a new special growspace."""
        self.growspaces[canonical_id] = Growspace(
            id=canonical_id,
            name=canonical_name,
            rows=rows,
            plants_per_row=plants_per_row,
        )
        _LOGGER.info(
            "Created canonical growspace: %s with name '%s'",
            canonical_id,
            canonical_name,
        )

    def _update_special_growspace_name(
        self,
        canonical_id: str,
        canonical_name: str,
    ) -> None:
        """Update the name of an existing special growspace if needed."""
        existing = self.growspaces[canonical_id]
        if existing.name != canonical_name:
            existing.name = canonical_name
            _LOGGER.info(
                "Updated growspace name: %s -> '%s'",
                canonical_id,
                canonical_name,
            )

    def _ensure_mother_growspace(self) -> str:
        """Ensure the 'mother' growspace exists."""
        return self._ensure_special_growspace(
            "mother",
            "mother",
            rows=3,
            plants_per_row=3,
        )

    # =============================================================================
    # DATA UPDATE COORDINATOR OVERRIDE
    # =============================================================================

    async def _async_update_data(self) -> dict[str, Any]:
        """Refresh data. Called by the DataUpdateCoordinator."""
        self.update_data_property()

        return self.data

    async def async_save(self) -> None:
        """Save data to storage."""
        await self.store.async_save(
            {
                "plants": {pid: asdict(p) for pid, p in self.plants.items()},
                "growspaces": {gid: asdict(g) for gid, g in self.growspaces.items()},
                "strain_library": list(self.strains.get_all()),
                "notifications_sent": self._notifications_sent,  # ✅ Save notification tracking
                "notifications_enabled": self._notifications_enabled,  # ✅ Save switch states
            },
        )

    async def async_load(self) -> None:
        """Load data from storage with migration support."""
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
            self.plants = {
                pid: Plant.from_dict(p) for pid, p in data.get("plants", {}).items()
            }
            _LOGGER.info("Loaded %d plants", len(self.plants))
        except (TypeError, ValueError) as e:
            _LOGGER.exception("Error loading plants: %s", e)
            self.plants = {}

        # Load growspaces using from_dict (handles migration)
        try:
            self.growspaces = {
                gid: Growspace.from_dict(g)
                for gid, g in data.get("growspaces", {}).items()
            }
            _LOGGER.info("Loaded %d growspaces", len(self.growspaces))
            if not self.options:
                _LOGGER.debug("--- COORDINATOR HAS NO OPTIONS TO APPLY ---")
            else:
                _LOGGER.debug(
                    "--- APPLYING OPTIONS TO GROWSPACES: %s ---",
                    self.options,
                )
                for growspace_id, growspace in self.growspaces.items():
                    if growspace_id in self.options:
                        growspace.environment_config = self.options[growspace_id]
                        _LOGGER.info(
                            "--- SUCCESS: Applied env_config to '%s': %s ---",
                            growspace.name,
                            growspace.environment_config,
                        )
                    else:
                        _LOGGER.debug(
                            "--- INFO: No options found for growspace '%s' ---",
                            growspace.name,
                        )
        except (TypeError, ValueError) as e:
            _LOGGER.exception("Error loading growspaces: %s", e)
            self.growspaces = {}

        # ✅ Load notification tracking
        self._notifications_sent = data.get("notifications_sent", {})

        # ✅ Load notification switch states
        self._notifications_enabled = data.get("notifications_enabled", {})

        # ✅ Ensure all growspaces have a notification enabled state (default True)
        for growspace_id in self.growspaces.keys():
            if growspace_id not in self._notifications_enabled:
                self._notifications_enabled[growspace_id] = True

        # ✅ Load strain library data (strains already initialized in __init__)
        strain_data = data.get("strain_library", [])
        if strain_data:
            await self.strains.import_strains(strain_data, replace=True)
            _LOGGER.info("Loaded %d strains", len(strain_data))

        # Migrate legacy growspace aliases
        self._migrate_legacy_growspaces()

        # Save migrated data back to storage
        await self.async_save()
        _LOGGER.info("Saved migrated data to storage")

    def update_data_property(self) -> None:
        """Keep self.data in sync with coordinator state."""
        self.data = {
            "growspaces": self.growspaces,
            "plants": self.plants,
            "notifications_sent": self._notifications_sent,  # ✅ Changed from self.notifications
            "notifications_enabled": self._notifications_enabled,  # ✅ Add switch states
        }

    # =============================================================================
    # GROWSPACE MANAGEMENT METHODS
    # =============================================================================

    async def async_add_growspace(
        self,
        name: str,
        rows: int = 3,
        plants_per_row: int = 3,
        notification_target: str | None = None,
        device_id: str | None = None,
    ) -> Growspace:
        """Add a new growspace and handle optional notification target."""
        # Normalize notification target
        if not notification_target or notification_target in ("None", "none", ""):
            _LOGGER.debug("No notification target provided for growspace '%s'", name)
            notification_target = None

        growspace_id = str(uuid.uuid4())
        growspace = Growspace(
            id=growspace_id,
            name=name.strip(),
            rows=rows,
            plants_per_row=plants_per_row,
            notification_target=notification_target,
            device_id=device_id,
        )
        self.growspaces[growspace_id] = growspace

        # ✅ Enable notifications by default for new growspace
        self._notifications_enabled[growspace_id] = True

        await self.async_save()

        self.update_data_property()
        self.async_set_updated_data(self.data)

        return growspace

    async def async_remove_growspace(self, growspace_id: str) -> None:
        """Remove a growspace and all its plants."""
        self._validate_growspace_exists(growspace_id)

        # Remove all plants in this growspace
        plants_to_remove = [
            plant_id
            for plant_id, plant in self.plants.items()
            if plant.growspace_id == growspace_id
        ]

        for plant_id in plants_to_remove:
            self.plants.pop(plant_id, None)
            self._notifications_sent.pop(plant_id, None)  # ✅ Use _notifications_sent

        growspace_name = self.growspaces[growspace_id].name
        self.growspaces.pop(growspace_id, None)

        # ✅ Remove notification state
        self._notifications_enabled.pop(growspace_id, None)

        self.update_data_property()
        await self.async_save()
        self.async_set_updated_data(self.data)

        _LOGGER.info(
            "Removed growspace %s (%s) and %d plants",
            growspace_id,
            growspace_name,
            len(plants_to_remove),
        )

    async def async_update_growspace(
        self,
        growspace_id: str,
        name: str = "",
        rows: int = 0,
        plants_per_row: int = 0,
        notification_target: str = "",
    ) -> None:
        """Update an existing growspace.

        Args:
            growspace_id: The ID of the growspace to update
            name: New name for the growspace (optional)
            rows: New number of rows (optional)
            plants_per_row: New number of plants per row (optional)
            notification_target: New notification target (optional)

        Raises:
            ValueError: If growspace_id not found

        """
        if growspace_id not in self.growspaces:
            _LOGGER.error(
                "Attempted to update non-existent growspace: %s",
                growspace_id,
            )
            raise ValueError(f"Growspace {growspace_id} not found")

        growspace = self.growspaces[growspace_id]
        updated = False

        # Track what changed for logging
        changes = []

        if name is not None and name != growspace.name:
            old_name = growspace.name
            growspace.name = name
            changes.append(f"name: {old_name} -> {name}")
            updated = True

        if rows is not None and rows != growspace.rows:
            old_rows = growspace.rows
            growspace.rows = rows
            changes.append(f"rows: {old_rows} -> {rows}")
            updated = True

        if plants_per_row is not None and plants_per_row != growspace.plants_per_row:
            old_ppr = growspace.plants_per_row
            growspace.plants_per_row = plants_per_row
            changes.append(f"plants_per_row: {old_ppr} -> {plants_per_row}")
            updated = True

        # Handle notification_target - convert empty string to None
        if notification_target is not None:
            # Normalize both old and new values for comparison
            current_target = growspace.notification_target or ""
            new_target = notification_target.strip() if notification_target else ""

            if current_target != new_target:
                growspace.notification_target = new_target

                changes.append(
                    f"notification_target: {current_target or 'None'} -> {new_target or 'None'}",
                )
                updated = True

        if updated:
            _LOGGER.info(
                "Updated growspace %s (%s): %s",
                growspace_id,
                growspace.name,
                ", ".join(changes),
            )

            # Check if grid size changed and validate existing plants
            if rows is not None or plants_per_row is not None:
                await self._validate_plants_after_growspace_resize(
                    growspace_id,
                    rows or growspace.rows,
                    plants_per_row or growspace.plants_per_row,
                )

            # Save to storage
            await self.async_save()

            # Notify all listeners (entities) about the update
            self.update_data_property()
            self.async_set_updated_data(self.data)  # No 'await'

            _LOGGER.debug("Growspace update completed and saved")
        else:
            _LOGGER.debug("No changes detected for growspace %s", growspace_id)

    async def _validate_plants_after_growspace_resize(
        self,
        growspace_id: str,
        new_rows: int,
        new_plants_per_row: int,
    ) -> None:
        """Validate and handle plants that are now outside the grid after resize.

        Args:
            growspace_id: The growspace that was resized
            new_rows: New number of rows
            new_plants_per_row: New number of plants per row

        """
        plants_to_check = self.get_growspace_plants(growspace_id)
        invalid_plants = []

        for plant in plants_to_check:
            if int(plant.row) > new_rows or int(plant.col) > new_plants_per_row:
                invalid_plants.append(plant)

        if invalid_plants:
            _LOGGER.warning(
                "Growspace %s resized to %dx%d. Found %d plants outside new grid boundaries:",
                growspace_id,
                new_rows,
                new_plants_per_row,
                len(invalid_plants),
            )

            for plant in invalid_plants:
                _LOGGER.warning(
                    "  - Plant %s (%s) at position (%d,%d) is outside new grid",
                    plant.plant_id,
                    plant.strain,
                    plant.row,
                    plant.col,
                )

            _LOGGER.warning(
                "Please update these plants' positions manually or they may not display correctly",
            )

    # =============================================================================
    # NOTIFICATION SWITCH MANAGEMENT
    # =============================================================================

    def is_notifications_enabled(self, growspace_id: str) -> bool:
        """Check if notifications are enabled for a growspace.

        Args:
            growspace_id: The growspace ID to check

        Returns:
            bool: True if notifications are enabled (default), False if disabled

        """
        # Default to True if not found (notifications on by default)
        return self._notifications_enabled.get(growspace_id, True)

    async def set_notifications_enabled(self, growspace_id: str, enabled: bool) -> None:
        """Enable or disable notifications for a growspace.

        Args:
            growspace_id: The growspace ID
            enabled: True to enable, False to disable

        """
        if growspace_id not in self.growspaces:
            _LOGGER.warning(
                "Attempted to set notifications for non-existent growspace: %s",
                growspace_id,
            )
            return

        old_state = self._notifications_enabled.get(growspace_id, True)
        self._notifications_enabled[growspace_id] = enabled

        # Notify listeners (updates switch state)
        # Update data dictionary
        self.data["notifications_enabled"] = self._notifications_enabled

        # Save to storage
        await self.async_save()

        # Notify listeners (updates switch state)
        self.async_set_updated_data(self.data)

        _LOGGER.info(
            "Notifications for growspace %s (%s): %s -> %s",
            growspace_id,
            self.growspaces[growspace_id].name,
            "enabled" if old_state else "disabled",
            "enabled" if enabled else "disabled",
        )

    # =============================================================================
    # PLANT MANAGEMENT METHODS
    # =============================================================================

    async def async_add_plant(
        self,
        growspace_id: str,
        strain: str,
        phenotype: str = "",
        row: int = 1,
        col: int = 1,
        stage: str = "",
        type: str = "normal",
        device_id: str | None = None,
        seedling_start: date | None = None,
        mother_start: date | None = None,
        clone_start: date | None = None,
        veg_start: date | None = None,
        flower_start: date | None = None,
        dry_start: date | None = None,
        cure_start: date | None = None,
        source_mother: str = "",
    ) -> Plant:
        plant_id = str(uuid.uuid4())
        today = date.today().isoformat()
        plant = Plant(
            plant_id=plant_id,
            growspace_id=growspace_id,
            strain=strain.strip(),
            phenotype=phenotype or "",
            row=row,
            col=col,
            stage=stage,
            created_at=today,
            type=type,
            device_id=device_id,
            seedling_start=str(seedling_start),
            mother_start=str(mother_start),
            clone_start=str(clone_start),
            veg_start=str(veg_start),
            flower_start=str(flower_start),
            dry_start=str(dry_start),
            cure_start=str(cure_start),
            source_mother=source_mother,
        )
        self.plants[plant_id] = plant

        await self.async_save()

        self.update_data_property()
        self.async_set_updated_data(self.data)

        return plant

    async def _handle_clone_creation(
        self,
        plant_id: str,
        growspace_id: str,
        strain: str,
        phenotype: str,
        row: int,
        col: int,
        **kwargs: Any,
    ) -> str:
        """Handle clone creation by copying from mother plant."""
        # Check if source_mother is provided
        source_mother_id = kwargs.get("source_mother")

        if source_mother_id:
            # Validate mother plant exists
            self._validate_plant_exists(source_mother_id)
            mother_plant = self.plants[source_mother_id]

            # Verify it's actually a mother plant
            if mother_plant.stage != "mother":
                _LOGGER.warning(
                    "Source plant %s is not in mother stage, but proceeding with clone creation",
                    source_mother_id,
                )
        else:
            # Try to find a mother plant with matching strain
            mother_plant = self._find_mother_by_strain(strain, phenotype)
            if mother_plant:
                source_mother_id = mother_plant.plant_id
                _LOGGER.info(
                    "Found mother plant %s for strain %s",
                    source_mother_id,
                    strain,
                )
            else:
                _LOGGER.warning(
                    "No mother plant found for strain %s, creating clone without source",
                    strain,
                )
                mother_plant = None

        now = date.today().isoformat()

        # Create clone data
        clone_data = {
            "plant_id": plant_id,
            "growspace_id": growspace_id,
            "strain": str(strain).strip(),
            "row": int(row),
            "col": int(col),
            "stage": "clone",
            "type": "clone",
            "clone_start": now,
            "created_at": now,
        }

        # Copy relevant data from mother plant if available
        if mother_plant:
            clone_data.update(
                {
                    "phenotype": mother_plant.phenotype,
                    "source_mother": source_mother_id,
                },
            )

        # Override with any explicitly provided kwargs
        clone_data.update(
            {k: v for k, v in kwargs.items() if k not in ["stage", "clone_start"]},
        )

        # Parse dates
        self._parse_date_fields(clone_data)

        # Save the clone
        self.plants[plant_id] = Plant(**clone_data)
        self.update_data_property()
        await self.async_save()
        self.async_set_updated_data(self.data)

        _LOGGER.info(
            "Created clone %s: %s at (%d,%d) from mother %s",
            plant_id,
            strain,
            row,
            col,
            source_mother_id or "unknown",
        )

        return plant_id

    def _find_mother_by_strain(self, strain: str, phenotype: str) -> Plant | None:
        """Find a mother plant with the specified strain."""
        for plant in self.plants.values():
            if (
                plant.stage == "mother"
                and plant.strain.lower() == strain.lower()
                and plant.phenotype.lower() == phenotype.lower()
            ):
                return plant

        return None

    async def async_add_mother_plant(
        self,
        phenotype: str,
        strain: str,
        row: int,
        col: int,
        mother_start: date | None = None,
        **kwargs: Any,
    ) -> Plant:
        """Add a plant to the permanent mother growspace."""
        mother_id: str = self._ensure_mother_growspace()
        kwargs["type"] = "mother"

        # Set mother_start to today if not provided
        if mother_start is None:
            mother_start = date.today()
        kwargs["mother_start"] = mother_start

        plant: Plant = await self.async_add_plant(
            mother_id,
            strain,
            phenotype,
            row,
            col,
            **kwargs,
        )
        return plant

    async def async_take_clones(
        self,
        mother_plant_id: str,
        num_clones: int,
        target_growspace_id: str | None,
        target_growspace_name: str | None,
        transition_date: str | None,
    ) -> list[Plant]:
        """Take clones from a mother plant into clone growspace."""
        self._validate_plant_exists(mother_plant_id)

        mother = self.plants[mother_plant_id]
        clone_gs_id = self._ensure_special_growspace("clone", "clone", 5, 5)
        clone_ids = []

        for _ in range(num_clones):
            row, col = self.find_first_available_position(clone_gs_id)
            clone_data = {
                "strain": mother.strain,
                "phenotype": mother.phenotype,
                "row": row,
                "col": col,
                "type": "clone",
                "source_mother": mother_plant_id,
                "stage": "clone",
                "clone_start": date.today(),
            }
            clone_id = await self.async_add_plant(clone_gs_id, **clone_data)
            clone_ids.append(clone_id)

        return clone_ids

    async def async_transition_clone_to_veg(self, clone_id: str) -> None:
        """Transition a clone to veg in veg growspace."""
        self._validate_plant_exists(clone_id)

        clone = self.plants[clone_id]
        if clone.stage != "clone":
            raise ValueError("Plant is not in clone stage")

        veg_gs_id = self._ensure_special_growspace("veg", "veg", 5, 5)
        row, col = self.find_first_available_position(veg_gs_id)

        await self.async_update_plant(
            clone_id,
            growspace_id=veg_gs_id,
            row=row,
            col=col,
            stage="veg",
            veg_start=datetime.today().isoformat(),
        )

    async def async_update_plant(self, plant_id: str, **updates) -> Plant:
        """Update fields of an existing plant."""
        plant = self.plants.get(plant_id)
        if not plant:
            raise ValueError(f"Plant {plant_id} does not exist")

        _LOGGER.debug("COORDINATOR: Updating plant %s", plant_id)
        for key, value in updates.items():
            _LOGGER.debug(
                "COORDINATOR: Field %s = %s (type: %s, id: %s)",
                key,
                value,
                type(value),
                id(value),
            )
        for key, value in updates.items():
            if hasattr(plant, key):
                old_value = getattr(plant, key)
                setattr(plant, key, value)
                _LOGGER.debug(
                    "COORDINATOR: Updated %s: %s -> %s",
                    key,
                    old_value,
                    value,
                )
            else:
                _LOGGER.warning("COORDINATOR: Invalid field %s", key)

        plant.updated_at = date.today().isoformat()
        await self.async_save()
        return plant

    def _handle_position_update(
        self,
        plant_id: str,
        plant: Plant,
        force_position: bool,
        kwargs: dict[str, Any],
    ) -> None:
        """Handle position updates with proper validation."""
        new_row = int(kwargs.get("row", plant.row))
        new_col = int(kwargs.get("col", plant.col))

        growspace_id = kwargs.get("growspace_id", plant.growspace_id)

        # Validate bounds
        self._validate_position_bounds(growspace_id, new_row, new_col)

        # Check for conflicts unless force_position is True
        if not force_position and (new_row != plant.row or new_col != plant.col):
            self._validate_position_not_occupied(
                growspace_id,
                new_row,
                new_col,
                plant_id,
            )

    async def async_move_plant(self, plant_id: str, new_row: int, new_col: int) -> None:
        """Move a plant to a new position."""
        await self.async_update_plant(plant_id, row=new_row, col=new_col)

    async def async_switch_plants(self, plant1_id: str, plant2_id: str) -> None:
        """Switch the positions of two plants."""
        self._validate_plant_exists(plant1_id)
        self._validate_plant_exists(plant2_id)

        plant1 = self.plants[plant1_id]
        plant2 = self.plants[plant2_id]

        # Ensure both plants are in the same growspace
        if plant1.growspace_id != plant2.growspace_id:
            raise ValueError("Cannot switch plants in different growspaces")

        # Store and swap positions
        plant1_row, plant1_col = plant1.row, plant1.col
        plant2_row, plant2_col = plant2.row, plant2.col

        plant1.row, plant1.col = plant2_row, plant2_col
        plant2.row, plant2.col = plant1_row, plant1_col

        # Update timestamps
        update_time = date.today().isoformat()
        plant1.updated_at = update_time
        plant2.updated_at = update_time

        self.update_data_property()
        await self.async_save()
        self.async_set_updated_data(self.data)

        _LOGGER.info(
            "Switched positions: %s (%s) moved from (%d,%d) to (%d,%d), %s (%s) moved from (%d,%d) to (%d,%d)",
            plant1_id,
            plant1.strain,
            plant1_col,
            plant1_row,
            plant2_col,
            plant2_row,
            plant2_id,
            plant2.strain,
            plant2_row,
            plant2_col,
            plant1_row,
            plant1_col,
        )

    async def switch_plants_service(self, plant1_id: str, plant2_id: str) -> None:
        """Service wrapper for switching plants."""
        await self.async_switch_plants(plant1_id, plant2_id)

    async def async_transition_plant_stage(
        self,
        plant_id: str,
        new_stage: str,
        transition_date: str | None,
    ) -> None:
        """Transition a plant to a new growth stage."""
        self._validate_plant_exists(plant_id)

        if new_stage not in PLANT_STAGES:
            raise ValueError(
                f"Invalid stage {new_stage}. Must be one of: {PLANT_STAGES}",
            )

        # Parse transition date
        parsed_date = (
            self._parse_date_field(transition_date) or date.today().isoformat()
        )

        await self.async_update_plant(
            plant_id,
            stage=new_stage,
            **{f"{new_stage}_start": parsed_date},
            force_position=False,
        )
        _LOGGER.info("Transitioned plant %s to %s stage", plant_id, new_stage)

    async def async_start_flowering(self, plant_id: str) -> Plant:
        """Set a plant to flowering stage."""
        plant = self.plants.get(plant_id)
        if not plant:
            raise ValueError(f"Plant {plant_id} not found")

        plant.stage = "flower"
        plant.flower_start = date.today().isoformat()
        plant.updated_at = plant.flower_start
        await self.async_save()
        return plant

    async def async_start_drying(self, plant_id: str) -> Plant:
        """Set a plant to drying stage."""
        plant = self.plants.get(plant_id)
        if not plant:
            raise ValueError(f"Plant {plant_id} not found")

        plant.stage = "drying"
        plant.dry_start = date.today().isoformat()
        plant.updated_at = plant.dry_start
        await self.async_save()
        return plant

    async def async_start_curing(self, plant_id: str) -> Plant:
        """Set a plant to curing stage."""
        plant = self.plants.get(plant_id)
        if not plant:
            raise ValueError(f"Plant {plant_id} not found")

        plant.stage = "curing"
        plant.cure_start = date.today().isoformat()
        plant.updated_at = plant.cure_start
        await self.async_save()
        return plant

    async def async_harvest(self, plant_id: str) -> Plant:
        """Mark a plant as harvested."""
        plant = self.plants.get(plant_id)
        if not plant:
            raise ValueError(f"Plant {plant_id} not found")

        plant.stage = "dry"
        plant.dry_start = date.today().isoformat()
        plant.updated_at = plant.dry_start
        await self.async_save()
        return plant

    async def async_harvest_plant(
        self,
        plant_id: str,
        target_growspace_id: str | None,
        transition_date: str | None,
    ) -> None:
        """Harvest a plant and optionally move it to another growspace."""
        self._validate_plant_exists(plant_id)

        plant = self.plants[plant_id]
        transition_date = transition_date or date.today().isoformat()

        # Log harvest start
        stage_before = self._get_plant_stage(plant)
        _LOGGER.info(
            "Harvest start: plant_id=%s stage=%s current_growspace=%s target_id=%s  date=%s",
            plant_id,
            stage_before,
            plant.growspace_id,
            target_growspace_id,
            transition_date,
        )

        # Handle harvest logic
        moved = await self._handle_harvest_logic(
            plant_id, plant, target_growspace_id, transition_date
        )

        self.update_data_property()
        await self.async_save()
        self.async_set_updated_data(self.data)

        _LOGGER.info(
            "Harvest end: plant_id=%s moved=%s target_growspace_id=%s row=%s col=%s stage=%s dry_start=%s cure_start=%s",
            plant_id,
            moved,
            target_growspace_id,
            plant.row,
            plant.col,
            plant.stage,
            plant.dry_start,
            plant.cure_start,
        )

    async def _handle_harvest_logic(
        self,
        plant_id: str,
        plant: Plant,
        target_growspace_id: str | None,
        transition_date: str,
    ) -> bool:
        """Handle the core harvest logic and return whether plant was moved."""
        # Explicit target provided
        if target_growspace_id and target_growspace_id in self.growspaces:
            return await self._harvest_to_explicit_target(
                plant_id,
                plant,
                target_growspace_id,
                transition_date,
            )

        # Auto-flow based on hints or current stage
        return await self._harvest_auto_flow(
            plant_id, plant, target_growspace_id, transition_date
        )

    async def _harvest_to_explicit_target(
        self,
        plant_id: str,
        plant: Plant,
        target_growspace_id: str,
        transition_date: str,
    ) -> bool:
        """Handle harvest to explicit target growspace."""
        plant.growspace_id = target_growspace_id

        # Set stage based on target
        if target_growspace_id == "dry":
            await self.async_update_plant(
                plant_id,
                stage="dry",
                dry_start=transition_date,
            )
        elif target_growspace_id == "cure":
            await self.async_update_plant(
                plant_id,
                stage="cure",
                cure_start=transition_date,
            )
        elif target_growspace_id == "clone":
            await self.async_update_plant(
                plant_id,
                stage="clone",
                clone_start=transition_date,
            )
        elif target_growspace_id == "mother":
            await self.async_update_plant(
                plant_id,
                stage="mother",
                clone_start=transition_date,
            )

        _LOGGER.info("Moved plant %s to growspace %s", plant_id, target_growspace_id)
        return True

    async def _harvest_auto_flow(
        self,
        plant_id: str,
        plant: Plant,
        target_growspace_id: str | None,
        transition_date: str,
    ) -> bool:
        """Handle auto-flow harvest logic."""
        current_stage = self._get_plant_stage(plant)

        # Handle name hints
        if target_growspace_id:
            if "dry" in target_growspace_id:
                return await self._move_to_dry_growspace(
                    plant_id,
                    plant,
                    transition_date,
                )
            if "cure" in target_growspace_id:
                return await self._move_to_cure_growspace(
                    plant_id,
                    plant,
                    transition_date,
                )
            if "clone" in target_growspace_id:
                return await self._move_to_clone_growspace(
                    plant_id,
                    plant,
                    transition_date,
                )
            if "mother" in target_growspace_id:
                return await self._move_to_clone_growspace(
                    plant_id,
                    plant,
                    transition_date,
                )

        # Handle stage transitions
        if current_stage == "flower":
            return await self._move_to_dry_growspace(plant_id, plant, transition_date)
        if current_stage == "dry":
            return await self._move_to_cure_growspace(plant_id, plant, transition_date)
        if current_stage == "mother":
            return await self._move_to_clone_growspace(plant_id, plant, transition_date)
        # Fallback: move to dry
        return await self._move_to_dry_growspace(plant_id, plant, transition_date)

    async def _move_to_clone_growspace(
        self,
        plant_id: str,
        plant: Plant,
        transition_date: str,
    ) -> bool:
        """Move plant to clone growspace."""
        clone_id = self._ensure_special_growspace("clone", "clone", 5, 5)
        plant.growspace_id = clone_id

        try:
            new_row, new_col = self.find_first_available_position(clone_id)
            await self.async_update_plant(
                plant_id,
                growspace_id=clone_id,
                row=new_row,
                col=new_col,
                stage="clone",
                clone_start=transition_date,
            )
        except ValueError as e:
            _LOGGER.warning("Failed to assign position in clone growspace: %s", e)

        plant.clone_start = transition_date
        plant.stage = "clone"
        _LOGGER.info("Moved plant %s → clone (ID: %s)", plant_id, clone_id)
        return True

    async def _move_to_dry_growspace(
        self,
        plant_id: str,
        plant: Plant,
        transition_date: str,
    ) -> bool:
        """Move plant to dry growspace."""
        dry_id = self._ensure_special_growspace("dry", "dry")
        plant.growspace_id = dry_id

        growspace = self.growspaces.get(dry_id)
        if growspace and growspace.device_id:
            plant.device_id = growspace.device_id

        try:
            new_row, new_col = self.find_first_available_position(dry_id)
            await self.async_update_plant(
                plant_id,
                growspace_id=dry_id,
                row=new_row,
                col=new_col,
                stage="dry",
                dry_start=transition_date,
            )
        except ValueError as e:
            _LOGGER.warning("Failed to assign position in dry growspace: %s", e)

        plant.dry_start = transition_date
        plant.stage = "dry"
        _LOGGER.info("Moved plant %s → dry (ID: %s)", plant_id, dry_id)
        return True

    async def _move_to_cure_growspace(
        self,
        plant_id: str,
        plant: Plant,
        transition_date: str,
    ) -> bool:
        """Move plant to cure growspace."""
        cure_id = self._ensure_special_growspace("cure", "cure")
        plant.growspace_id = cure_id

        try:
            new_row, new_col = self.find_first_available_position(cure_id)
            await self.async_update_plant(
                plant_id,
                growspace_id=cure_id,
                row=new_row,
                col=new_col,
                stage="cure",
                cure_start=transition_date,
            )
        except ValueError as e:
            _LOGGER.warning("Failed to assign position in cure growspace: %s", e)

        plant.cure_start = transition_date
        plant.stage = "cure"
        _LOGGER.info("Moved plant %s → cure (ID: %s)", plant_id, cure_id)
        return True

    async def async_remove_plant(self, plant_id: str) -> bool:
        """Remove a plant from the coordinator."""
        if plant_id in self.plants:
            del self.plants[plant_id]
            await self.async_save()
            return True
        return False

    async def _remove_plant_entities(self, plant_id: str) -> None:
        """Remove all entities for a given plant from Home Assistant."""
        entity_registry = er.async_get(self.hass)

        # Find all entities belonging to this plant
        for entity_id, entry in list(entity_registry.entities.items()):
            if entry.unique_id.startswith(plant_id):
                _LOGGER.info("Removing entity %s for plant %s", entity_id, plant_id)
                entity_registry.async_remove(entity_id)

    # =============================================================================
    # STRAIN LIBRARY MANAGEMENT
    # =============================================================================

    async def add_strain(self, strain: str) -> None:
        """Add a strain to the strain library."""
        await self.strains.add(strain)

    async def remove_strain(self, strain: str) -> None:
        """Remove a strain from the strain library."""
        await self.strains.remove(strain)

    def get_strain_options(self) -> list[str]:
        """Get a list of all strains in the library."""
        return self.strains.get_all()

    def export_strain_library(self) -> list[str]:
        """Export all strains from the library."""
        return self.get_strain_options()

    async def import_strains(self, strains: list[str], replace: bool = False) -> int:
        """Import a list of strains into the library."""
        return await self.strains.import_strains(strains, replace)

    async def clear_strains(self) -> int:
        """Clear all strains from the library."""
        return await self.strains.clear()

    # =============================================================================
    # QUERY AND CALCULATION METHODS
    # =============================================================================

    def get_growspace_plants(self, growspace_id: str) -> list[Plant]:
        """Get all plants in a specific growspace."""
        return [
            plant
            for plant in self.plants.values()
            if plant.growspace_id == growspace_id
        ]

    def calculate_days_in_stage(self, plant: Plant, stage: str) -> int:
        """Calculate days a plant has been in a specific stage."""
        start_date = getattr(plant, f"{stage}_start", None)
        return self._calculate_days(start_date)

    def get_growspace_grid(self, growspace_id: str) -> list[list[str | None]]:
        growspace = self.growspaces[growspace_id]
        plants = self.get_growspace_plants(growspace_id)
        return generate_growspace_grid(
            int(growspace.rows),
            int(growspace.plants_per_row),
            plants,
        )

    def _guess_overview_entity_id(self, growspace_id: str) -> str:
        """Best-effort guess of the overview sensor entity_id for a growspace."""
        # Handle special cases first
        if growspace_id in ("dry", "dry_overview"):
            return "sensor.dry"
        if growspace_id in ("cure", "cure_overview"):
            return "sensor.cure"
        if growspace_id in ("mother", "mother_overview"):
            return "sensor.mother"
        if growspace_id in ("clone", "clone_overview"):
            return "sensor.clone"
        # General case
        growspace = self.growspaces.get(growspace_id)
        name = getattr(growspace, "name", growspace_id) if growspace else growspace_id

        # Simple slugify: lowercase, spaces->underscore, keep alnum/underscore only
        slug = "".join(
            ch if ch.isalnum() or ch == "_" else "_"
            for ch in str(name).lower().replace(" ", "_")
        )

        # Collapse repeated underscores
        while "__" in slug:
            slug = slug.replace("__", "_")

        return f"sensor.{slug}"

    # =============================================================================
    # NOTIFICATION MANAGEMENT
    # =============================================================================

    def should_send_notification(self, plant_id: str, stage: str, days: int) -> bool:
        """Check if a notification should be sent for a plant."""
        return (
            not self._notifications_sent.get(plant_id, {})
            .get(stage, {})
            .get(str(days), False)
        )

    async def mark_notification_sent(
        self,
        plant_id: str,
        stage: str,
        days: int,
    ) -> None:
        """Mark a notification as sent to prevent duplicates."""
        if plant_id not in self._notifications_sent:
            self._notifications_sent[plant_id] = {}
        if stage not in self._notifications_sent[plant_id]:
            self._notifications_sent[plant_id][stage] = {}

        self._notifications_sent[plant_id][stage][str(days)] = True
        await self.async_save()
