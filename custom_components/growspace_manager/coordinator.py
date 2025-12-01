"""Data update coordinator for the Growspace Manager integration."""

from __future__ import annotations

from dataclasses import asdict
from .models import Plant, Growspace
from .utils import (
    format_date,
    find_first_free_position,
    generate_growspace_grid,
    VPDCalculator,
    parse_date_field as util_parse_date_field,
    calculate_plant_stage,
)
from .strain_library import StrainLibrary
from .migration_manager import MigrationManager
from .growspace_validator import GrowspaceValidator
from .storage_manager import StorageManager
from .const import (
    STORAGE_KEY,
    PLANT_STAGES,
    DATE_FIELDS,
    DOMAIN,
    STORAGE_VERSION,
    SPECIAL_GROWSPACES,
)
import logging
import uuid
from datetime import datetime, date
from typing import TYPE_CHECKING, Any, Optional

from dateutil import parser
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator


_LOGGER = logging.getLogger(__name__)


# Type aliases for better readability
PlantDict = dict[str, Any]
GrowspaceDict = dict[str, Any]
NotificationDict = dict[str, Any]
DateInput = str | datetime | date | None


class GrowspaceCoordinator(DataUpdateCoordinator):
    """Manages Growspace, Plant, and Strain data for the Growspace Manager integration.

    This class handles loading, saving, and updating all the core data entities,
    as well as providing methods for interacting with them. It uses a Home
    Assistant Store to persist data and coordinates updates to all registered
    entities.
    """

    def __init__(
        self,
        hass,
        data: dict | None = None,
        options: dict | None = None,
        strain_library: StrainLibrary | None = None,
    ) -> None:
        """Initialize the Growspace Coordinator.

        Args:
            hass: The Home Assistant instance.
            data: Initial raw data, typically from storage (optional).
            options: Configuration options from the config entry (optional).
        """
        super().__init__(
            hass,
            _LOGGER,
            name="Growspace Manager Coordinator",
        )

        self.hass = hass
        self.growspaces: dict[str, Growspace] = {}
        self.plants: dict[str, Plant] = {}

        self.options = options or {}
        _LOGGER.info("--- COORDINATOR INITIALIZED WITH OPTIONS: %s ---", self.options)

        # Initialize strain library
        if strain_library is None:
            # Fallback for testing or legacy init
            self.strains = StrainLibrary(hass)
        else:
            self.strains = strain_library

        self.migration_manager = MigrationManager(self)
        self.validator = GrowspaceValidator(self)
        self.storage_manager = StorageManager(self, hass)

        self._notifications_sent: dict[str, dict[str, bool]] = {}
        self._notifications_enabled: dict[
            str, bool
        ] = {}  # ✅ Notification switch states
        # Initialize Env options
        self.options = options or {}

        # Load plants safely, ignoring invalid keys
        if data is None:
            data = {}
        raw_plants = data.get("plants", {})
        for pid, pdata in raw_plants.items():
            try:
                if isinstance(pdata, dict):
                    self.plants[pid] = Plant.from_dict(pdata)
                elif isinstance(pdata, Plant):
                    self.plants[pid] = pdata
                else:
                    raise TypeError(f"Invalid data type for plant {pid}: {type(pdata)}")
            except Exception as e:
                _LOGGER.warning("Failed to load plant %s: %s", pid, e)

        # Optionally load growspaces if stored
        raw_growspaces = data.get("growspaces", {})
        for gid, gdata in raw_growspaces.items():
            try:
                if isinstance(gdata, dict):
                    self.growspaces[gid] = Growspace.from_dict(gdata)
                elif isinstance(gdata, Growspace):
                    self.growspaces[gid] = gdata
                else:
                    raise TypeError(
                        f"Invalid data type for growspace {gid}: {type(gdata)}"
                    )
            except Exception as e:
                _LOGGER.warning("Failed to load growspace %s: %s", gid, e)

        _LOGGER.debug(
            "Loaded %d plants and %d growspaces", len(self.plants), len(self.growspaces)
        )

    # -----------------------------
    # Methods for editor dropdown
    # -----------------------------

    def get_growspace_options(self) -> dict[str, str]:
        """Return growspaces for dropdown selection in the editor.

        Returns:
            A dictionary mapping growspace IDs to growspace names.
        """
        return {
            gs_id: getattr(gs, "name", gs_id) for gs_id, gs in self.growspaces.items()
        }

    def get_sorted_growspace_options(self) -> list[tuple[str, str]]:
        """Return a sorted list of growspaces for dropdown selection.

        The list is sorted alphabetically by growspace name.

        Returns:
            A list of tuples, where each tuple contains a growspace ID and name.
        """
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
        """Migrate legacy special growspace aliases to their canonical forms."""
        self.migration_manager.migrate_legacy_growspaces()

    def _migrate_plants_to_growspace(self, from_id: str, to_id: str) -> None:
        """Move all plants from one growspace to another."""
        self.migration_manager.migrate_plants_to_growspace(from_id, to_id)

    # =============================================================================
    # UTILITY AND HELPER METHODS
    # =============================================================================


    def get_plant(self, plant_id: str) -> Plant | None:
        """Retrieve a plant by its ID.

        Args:
            plant_id: The unique identifier of the plant.

        Returns:
            The Plant object if found, otherwise None.
        """
        return self.plants.get(plant_id)

    def _canonical_special(self, gs_id: str) -> tuple[str, str]:
        """Return the canonical ID and name for a special growspace.

        This also triggers a migration check to ensure any legacy aliases are handled.

        Args:
            gs_id: The growspace ID to look up.

        Returns:
            A tuple containing the canonical ID and canonical name.
        """
        self.migration_manager.migrate_legacy_growspaces()

        growspace = self.growspaces.get(gs_id)
        if growspace:
            return gs_id, growspace.name  # access attribute, not dict key
        return gs_id, gs_id


    def _parse_date_field(self, date_value: str | datetime | date | None) -> str | None:
        """Parse and format a date field into a standard ISO format string.

        Args:
            date_value: The date value to parse.

        Returns:
            The formatted date string, or None if the input is invalid.
        """
        return format_date(date_value)

    def _parse_date_fields(self, kwargs: dict[str, Any]) -> None:
        """Parse all standard date fields within a dictionary in-place.

        Args:
            kwargs: A dictionary of data that may contain date fields.
        """
        for field in DATE_FIELDS:
            if field in kwargs:
                kwargs[field] = self._parse_date_field(kwargs[field])

    def _to_date(self, date_value: DateInput) -> date | None:
        """Convert a date input to a date object.

        Args:
            date_value: The date value to convert.

        Returns:
            A date object or None if conversion fails.
        """
        if not date_value or str(date_value) == "None":
            return None
        try:
            if isinstance(date_value, datetime):
                return date_value.date()
            elif isinstance(date_value, date):
                return date_value
            elif isinstance(date_value, str):
                return parser.isoparse(date_value).date()
        except Exception as e:
            _LOGGER.warning("Failed to parse date %s: %s", date_value, e)
        return None

    def calculate_days(
        self, start_date: DateInput, end_date: DateInput = None
    ) -> int:
        """Calculate the number of days that have passed since a given date.

        If an end_date is provided and is valid (i.e., not in the future relative
        to today), the calculation is capped at that date. Otherwise, it
        calculates up to today.

        Args:
            start_date: The start date to calculate from.
            end_date: The optional end date to cap the duration.

        Returns:
            The total number of days passed, or 0 if the date is invalid.
        """
        start_dt = self._to_date(start_date)
        if not start_dt:
            return 0

        target_date = date.today()

        if end_date:
            end_dt = self._to_date(end_date)
            if end_dt and end_dt <= target_date:
                target_date = end_dt

        return (target_date - start_dt).days

    def _generate_unique_name(self, base_name: str) -> str:
        """Generate a unique growspace name by appending a counter if necessary.

        Args:
            base_name: The desired base name for the growspace.

        Returns:
            A unique name that does not conflict with existing growspace names.
        """
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

    def _ensure_special_growspace(
        self, growspace_id: str, name: str, rows: int = 3, plants_per_row: int = 3
    ) -> str:
        """Ensure a special growspace (e.g., 'dry', 'cure') exists.

        If the growspace does not exist, it will be created with the specified
        parameters. This method also handles migration from legacy aliases.

        Args:
            growspace_id: The canonical ID for the special growspace.
            name: The canonical name for the special growspace.
            rows: The number of rows for the grid (if created).
            plants_per_row: The number of plants per row (if created).

        Returns:
            The canonical ID of the special growspace.
        """
        # Get canonical form
        canonical_id, _ = self._canonical_special(growspace_id)

        # Clean up any legacy aliases
        self._cleanup_legacy_aliases(canonical_id)

        # Create or update the canonical growspace
        if canonical_id not in self.growspaces:
            self._create_special_growspace(
                canonical_id, name, rows, plants_per_row
            )
            # ✅ Enable notifications by default for new special growspace
            self._notifications_enabled[canonical_id] = True
        else:
            self._update_special_growspace_name(canonical_id, name)

        self.update_data_property()
        return canonical_id

        self.migration_manager.cleanup_legacy_aliases(canonical_id)

    def _create_special_growspace(
        self, canonical_id: str, canonical_name: str, rows: int, plants_per_row: int
    ) -> None:
        """Create a new special growspace with the given parameters.

        Args:
            canonical_id: The canonical ID for the new growspace.
            canonical_name: The display name for the new growspace.
            rows: The number of rows in the grid.
            plants_per_row: The number of plants per row in the grid.
        """
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
        self, canonical_id: str, canonical_name: str
    ) -> None:
        """Update the name of an existing special growspace if it has changed.

        Args:
            canonical_id: The ID of the growspace to update.
            canonical_name: The new canonical name to set.
        """
        existing = self.growspaces[canonical_id]
        if existing.name != canonical_name:
            existing.name = canonical_name
            _LOGGER.info(
                "Updated growspace name: %s -> '%s'", canonical_id, canonical_name
            )

    def _ensure_mother_growspace(self) -> str:
        """Ensure the 'mother' growspace exists, creating it if necessary.

        Returns:
            The ID of the mother growspace.
        """
        return self._ensure_special_growspace(
            "mother", "mother", rows=3, plants_per_row=3
        )

    # =============================================================================
    # DATA UPDATE COORDINATOR OVERRIDE
    # =============================================================================

    async def _async_update_data(self) -> dict[str, Any]:
        """Refresh data, called periodically by the DataUpdateCoordinator.

        This method updates the central `self.data` property and triggers checks
        for air exchange recommendations and timed notifications.

        Returns:
            The updated data dictionary.
        """
        self.update_data_property()
        await self._async_update_air_exchange_recommendations()

        return self.data

    async def async_save(self) -> None:
        """Save the current state of all data to persistent storage."""
        await self.storage_manager.async_save()

    async def async_load(self) -> None:
        """Load data from persistent storage and handle migrations."""
        await self.storage_manager.async_load()

    def update_data_property(self) -> None:
        """Update the central `self.data` property to reflect the current coordinator state."""
        self.data = {
            "growspaces": self.growspaces,
            "plants": self.plants,
            "notifications_sent": self._notifications_sent,
            "notifications_enabled": self._notifications_enabled,
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
        """Add a new growspace to the coordinator.

        Args:
            name: The display name for the new growspace.
            rows: The number of rows in the grid.
            plants_per_row: The number of plants per row.
            notification_target: The notification service to use (optional).
            device_id: The device ID to associate with the growspace (optional).

        Returns:
            The newly created Growspace object.
        """
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

        self.update_data_property()
        await self.async_save()
        self.async_set_updated_data(self.data)

        return growspace

    async def async_remove_growspace(self, growspace_id: str) -> None:
        """Remove a growspace and all plants contained within it.

        Args:
            growspace_id: The ID of the growspace to remove.
        """
        self.validator.validate_growspace_exists(growspace_id)

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
        """Update the properties of an existing growspace.

        Args:
            growspace_id: The ID of the growspace to update.
            name: The new name for the growspace (optional).
            rows: The new number of rows (optional).
            plants_per_row: The new number of plants per row (optional).
            notification_target: The new notification target (optional).

        Raises:
            ValueError: If the growspace_id is not found.
        """
        if growspace_id not in self.growspaces:
            _LOGGER.error(
                "Attempted to update non-existent growspace: %s", growspace_id
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
                    f"notification_target: {current_target or 'None'} -> {new_target or 'None'}"
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
            self.async_set_updated_data(self.data)

            _LOGGER.debug("Growspace update completed and saved")
        else:
            _LOGGER.debug("No changes detected for growspace %s", growspace_id)

    async def _validate_plants_after_growspace_resize(
        self, growspace_id: str, new_rows: int, new_plants_per_row: int
    ) -> None:
        """Log a warning if any plants are outside the new grid boundaries after a resize.

        Args:
            growspace_id: The ID of the growspace that was resized.
            new_rows: The new number of rows.
            new_plants_per_row: The new number of plants per row.
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
                "Please update these plants' positions manually or they may not display correctly"
            )

    # =============================================================================
    # NOTIFICATION SWITCH MANAGEMENT
    # =============================================================================

    def is_notifications_enabled(self, growspace_id: str) -> bool:
        """Check if notifications are currently enabled for a specific growspace.

        Args:
            growspace_id: The ID of the growspace to check.

        Returns:
            True if notifications are enabled, False otherwise. Defaults to True.
        """
        # Default to True if not found (notifications on by default)
        return self._notifications_enabled.get(growspace_id, True)

    async def set_notifications_enabled(self, growspace_id: str, enabled: bool) -> None:
        """Enable or disable notifications for a specific growspace.

        Args:
            growspace_id: The ID of the growspace to modify.
            enabled: The new state for notifications.
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
        """Add a new plant to the coordinator.

        Args:
            growspace_id: The ID of the growspace to add the plant to.
            strain: The strain name of the plant.
            phenotype: The phenotype of the strain (optional).
            row: The row position in the grid.
            col: The column position in the grid.
            stage: The initial growth stage.
            type: The type of plant (e.g., 'normal', 'clone', 'mother').
            device_id: The device ID associated with the plant (optional).
            seedling_start: The date the seedling stage started (optional).
            mother_start: The date the mother stage started (optional).
            clone_start: The date the clone stage started (optional).
            veg_start: The date the veg stage started (optional).
            flower_start: The date the flower stage started (optional).
            dry_start: The date the dry stage started (optional).
            cure_start: The date the cure stage started (optional).
            source_mother: The ID of the mother plant this clone came from (optional).

        Returns:
            The newly created Plant object.
        """
        try:
            self.validator.validate_position_not_occupied(growspace_id, row, col)
            final_row, final_col = row, col
        except ValueError:
            _LOGGER.info(
                "Position (%d, %d) in growspace %s is occupied. Finding first available spot.",
                row,
                col,
                growspace_id,
            )
            try:
                final_row, final_col = self.validator.find_first_available_position(
                    growspace_id
                )
                _LOGGER.info(
                    "Found available position at (%d, %d)", final_row, final_col
                )
            except ValueError as e:
                # This happens if the growspace is full
                _LOGGER.error("Could not add plant: %s", e)
                raise e  # Re-raise the exception to be handled by the caller

        plant_id = str(uuid.uuid4())
        today = date.today().isoformat()
        plant = Plant(
            plant_id=plant_id,
            growspace_id=growspace_id,
            strain=strain.strip(),
            phenotype=phenotype or "",
            row=final_row,
            col=final_col,
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

        self.update_data_property()
        await self.async_save()
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
        """Handle the specific logic for creating a clone plant.

        This method attempts to find a source mother plant and copies relevant
        data from it to the new clone.

        Args:
            plant_id: The ID for the new clone.
            growspace_id: The growspace ID for the clone.
            strain: The strain name.
            phenotype: The phenotype name.
            row: The row position.
            col: The column position.
            **kwargs: Additional plant attributes.

        Returns:
            The ID of the newly created clone.
        """

        # Check if source_mother is provided
        source_mother_id = kwargs.get("source_mother")

        if source_mother_id:
            # Validate mother plant exists
            self.validator.validate_plant_exists(source_mother_id)
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
                    "Found mother plant %s for strain %s", source_mother_id, strain
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
                }
            )

        # Override with any explicitly provided kwargs
        clone_data.update(
            {k: v for k, v in kwargs.items() if k not in ["stage", "clone_start"]}
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
        """Find a mother plant with the specified strain and phenotype.

        Args:
            strain: The strain name to search for.
            phenotype: The phenotype name to search for.

        Returns:
            The Plant object of the mother if found, otherwise None.
        """
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
        """Add a new mother plant to the dedicated mother growspace.

        This ensures the 'mother' special growspace exists before adding the plant.

        Args:
            phenotype: The phenotype of the mother plant.
            strain: The strain of the mother plant.
            row: The row position.
            col: The column position.
            mother_start: The date the plant became a mother (optional).
            **kwargs: Additional plant attributes.

        Returns:
            The newly created mother Plant object.
        """
        mother_id: str = self._ensure_mother_growspace()
        kwargs["type"] = "mother"

        # Set mother_start to today if not provided
        if mother_start is None:
            mother_start = date.today()
        kwargs["mother_start"] = mother_start

        plant: Plant = await self.async_add_plant(
            mother_id, strain, phenotype, row, col, **kwargs
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
        """Create multiple clones from a mother plant and place them in the clone growspace.

        Args:
            mother_plant_id: The ID of the source mother plant.
            num_clones: The number of clones to create.
            target_growspace_id: The target growspace ID (ignored, uses 'clone').
            target_growspace_name: The target growspace name (ignored).
            transition_date: The date the clones were taken (ignored, uses today).

        Returns:
            A list of the newly created clone Plant objects.
        """
        self.validator.validate_plant_exists(mother_plant_id)

        mother = self.plants[mother_plant_id]
        clone_gs_id = self._ensure_special_growspace("clone", "clone", 5, 5)
        clone_ids = []

        for _ in range(num_clones):
            row, col = self.validator.find_first_available_position(clone_gs_id)
            clone_data = {
                "strain": mother.strain,
                "phenotype": mother.phenotype,
                "type": "clone",
                "source_mother": mother_plant_id,
                "stage": "clone",
                "clone_start": date.today(),
            }
            clone_id = await self.async_add_plant(
                clone_gs_id, **clone_data, row=row, col=col
            )
            clone_ids.append(clone_id)

        return clone_ids

    async def async_transition_clone_to_veg(self, clone_id: str) -> None:
        """Transition a plant from the clone stage to the veg stage.

        The plant will be moved to the 'veg' special growspace.

        Args:
            clone_id: The ID of the clone to transition.

        Raises:
            ValueError: If the plant is not in the clone stage.
        """
        self.validator.validate_plant_exists(clone_id)

        clone = self.plants[clone_id]
        if clone.stage != "clone":
            raise ValueError("Plant is not in clone stage")

        veg_gs_id = self._ensure_special_growspace("veg", "veg", 5, 5)
        row, col = self.validator.find_first_available_position(veg_gs_id)

        await self.async_update_plant(
            clone_id,
            growspace_id=veg_gs_id,
            row=row,
            col=col,
            stage="veg",
            veg_start=datetime.today().isoformat(),
        )

    async def async_update_plant(self, plant_id: str, **updates) -> Plant:
        """Update the attributes of an existing plant.

        Args:
            plant_id: The ID of the plant to update.
            **updates: Keyword arguments for the fields to update.

        Returns:
            The updated Plant object.

        Raises:
            ValueError: If the plant does not exist.
        """
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
                    "COORDINATOR: Updated %s: %s -> %s", key, old_value, value
                )
            else:
                _LOGGER.warning("COORDINATOR: Invalid field %s", key)

        plant.updated_at = date.today().isoformat()
        await self.async_save()
        self.update_data_property()
        self.async_set_updated_data(self.data)
        return plant

    def _handle_position_update(
        self,
        plant_id: str,
        plant: Plant,
        force_position: bool,
        kwargs: dict[str, Any],
    ) -> None:
        """Validate and handle updates to a plant's position.

        Ensures the new position is within the growspace bounds and not
        occupied by another plant.

        Args:
            plant_id: The ID of the plant being moved.
            plant: The Plant object.
            force_position: If True, skips the occupation check.
            kwargs: A dictionary of updates which may contain 'row' and 'col'.
        """
        new_row = int(kwargs.get("row", plant.row))
        new_col = int(kwargs.get("col", plant.col))

        growspace_id = kwargs.get("growspace_id", plant.growspace_id)

        # Validate bounds
        self.validator.validate_position_bounds(growspace_id, new_row, new_col)

        # Check for conflicts unless force_position is True
        if not force_position and (new_row != plant.row or new_col != plant.col):
            self.validator.validate_position_not_occupied(
                growspace_id, new_row, new_col, plant_id
            )

    async def async_move_plant(self, plant_id: str, new_row: int, new_col: int) -> None:
        """Move a plant to a new position within its current growspace.

        Args:
            plant_id: The ID of the plant to move.
            new_row: The new row number.
            new_col: The new column number.
        """
        await self.async_update_plant(plant_id, row=new_row, col=new_col)

    async def async_switch_plants(self, plant1_id: str, plant2_id: str) -> None:
        """Switch the positions of two plants within the same growspace.

        Args:
            plant1_id: The ID of the first plant.
            plant2_id: The ID of the second plant.

        Raises:
            ValueError: If the plants are in different growspaces.
        """
        self.validator.validate_plant_exists(plant1_id)
        self.validator.validate_plant_exists(plant2_id)

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
        """Service call wrapper for switching the positions of two plants.

        Args:
            plant1_id: The ID of the first plant.
            plant2_id: The ID of the second plant.
        """
        await self.async_switch_plants(plant1_id, plant2_id)

    async def async_transition_plant_stage(
        self, plant_id: str, new_stage: str, transition_date: str | None
    ) -> None:
        """Transition a plant to a new growth stage.

        This sets the plant's stage and updates the corresponding start date.

        Args:
            plant_id: The ID of the plant to transition.
            new_stage: The new stage to set.
            transition_date: The date of the transition (optional, defaults to today).

        Raises:
            ValueError: If the new stage is invalid.
        """
        self.validator.validate_plant_exists(plant_id)

        if new_stage not in PLANT_STAGES:
            raise ValueError(
                f"Invalid stage {new_stage}. Must be one of: {PLANT_STAGES}"
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
        """Transition a plant to the 'flower' stage, starting today.

        Args:
            plant_id: The ID of the plant.

        Returns:
            The updated Plant object.
        """
        plant = self.plants.get(plant_id)
        if not plant:
            raise ValueError(f"Plant {plant_id} not found")

        plant.stage = "flower"
        plant.flower_start = date.today().isoformat()
        plant.updated_at = plant.flower_start
        await self.async_save()
        self.update_data_property()
        self.async_set_updated_data(self.data)
        return plant

    async def async_start_drying(self, plant_id: str) -> Plant:
        """Transition a plant to the 'drying' stage, starting today.

        Args:
            plant_id: The ID of the plant.

        Returns:
            The updated Plant object.
        """
        plant = self.plants.get(plant_id)
        if not plant:
            raise ValueError(f"Plant {plant_id} not found")

        plant.stage = "drying"
        plant.dry_start = date.today().isoformat()
        plant.updated_at = plant.dry_start
        await self.async_save()
        self.update_data_property()
        self.async_set_updated_data(self.data)
        return plant

    async def async_start_curing(self, plant_id: str) -> Plant:
        """Transition a plant to the 'curing' stage, starting today.

        Args:
            plant_id: The ID of the plant.

        Returns:
            The updated Plant object.
        """
        plant = self.plants.get(plant_id)
        if not plant:
            raise ValueError(f"Plant {plant_id} not found")

        plant.stage = "curing"
        plant.cure_start = date.today().isoformat()
        plant.updated_at = plant.cure_start
        await self.async_save()
        self.update_data_property()
        self.async_set_updated_data(self.data)
        return plant

    async def async_harvest(self, plant_id: str) -> Plant:
        """Mark a plant as harvested, transitioning it to the 'dry' stage today.

        Args:
            plant_id: The ID of the plant.

        Returns:
            The updated Plant object.
        """
        plant = self.plants.get(plant_id)
        if not plant:
            raise ValueError(f"Plant {plant_id} not found")

        plant.stage = "dry"
        plant.dry_start = date.today().isoformat()
        plant.updated_at = plant.dry_start
        await self.async_save()
        self.update_data_property()
        self.async_set_updated_data(self.data)
        return plant

    async def async_harvest_plant(
        self,
        plant_id: str,
        target_growspace_id: str | None,
        target_growspace_name: str | None,
        transition_date: str | None,
    ) -> None:
        """Harvest a plant, which may involve moving it to a 'dry' or 'cure' growspace.

        This method orchestrates the harvest process, including recording analytics
        and moving the plant based on an explicit target or an automatic flow.

        Args:
            plant_id: The ID of the plant to harvest.
            target_growspace_id: The explicit ID of the growspace to move the plant to (optional).
            target_growspace_name: The name of the target growspace (used as a hint).
            transition_date: The date of the harvest (optional, defaults to today).
        """
        self.validator.validate_plant_exists(plant_id)

        plant = self.plants[plant_id]
        transition_date = transition_date or date.today().isoformat()

        # Log harvest start
        stage_before = self._get_plant_stage(plant)
        _LOGGER.info(
            "Harvest start: plant_id=%s stage=%s current_growspace=%s target_id=%s target_name=%s date=%s",
            plant_id,
            stage_before,
            plant.growspace_id,
            target_growspace_id,
            target_growspace_name,
            transition_date,
        )

        # Handle harvest logic
        moved = await self._handle_harvest_logic(
            plant_id, plant, target_growspace_id, target_growspace_name, transition_date
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
        target_growspace_name: str | None,
        transition_date: str,
    ) -> bool:
        """Determine the harvest workflow and execute it.

        Prioritizes an explicit target, otherwise uses an automatic flow.

        Args:
            plant_id: The ID of the plant being harvested.
            plant: The Plant object.
            target_growspace_id: An explicit target growspace ID.
            target_growspace_name: A hint for the auto-flow logic.
            transition_date: The date of the harvest.

        Returns:
            True if the plant was moved, False otherwise.
        """
        # Explicit target provided
        if target_growspace_id and target_growspace_id in self.growspaces:
            return await self._harvest_to_explicit_target(
                plant_id,
                plant,
                target_growspace_id,
                target_growspace_name,
                transition_date,
            )

        # Auto-flow based on hints or current stage
        return await self._harvest_auto_flow(
            plant_id, plant, target_growspace_name, transition_date
        )

    async def _harvest_to_explicit_target(
        self,
        plant_id: str,
        plant: Plant,
        target_growspace_id: str,
        target_growspace_name: str | None,
        transition_date: str,
    ) -> bool:
        """Move a harvested plant to an explicitly defined target growspace.

        Args:
            plant_id: The ID of the plant.
            plant: The Plant object.
            target_growspace_id: The ID of the destination growspace.
            target_growspace_name: The name of the destination growspace.
            transition_date: The date of the move.

        Returns:
            True, as the plant is always moved in this path.
        """
        plant.growspace_id = target_growspace_id

        try:
            row, col = self._find_first_available_position(target_growspace_id)
            plant.row, plant.col = row, col
        except ValueError as e:
            _LOGGER.warning(
                "Failed to find position in target growspace %s: %s",
                target_growspace_id,
                e,
            )

        # Set stage based on target
        if target_growspace_id == "dry" or (
            target_growspace_name and "dry" in target_growspace_name.lower()
        ):
            await self.async_update_plant(
                plant_id, stage="dry", dry_start=transition_date
            )
        elif target_growspace_id == "cure" or (
            target_growspace_name and "cure" in target_growspace_name.lower()
        ):
            await self.async_update_plant(
                plant_id, stage="cure", cure_start=transition_date
            )
        elif target_growspace_id == "clone" or (
            target_growspace_name and "clone" in target_growspace_name.lower()
        ):
            await self.async_update_plant(
                plant_id, stage="clone", clone_start=transition_date
            )
        elif target_growspace_id == "mother" or (
            target_growspace_name and "mother" in target_growspace_name.lower()
        ):
            await self.async_update_plant(
                plant_id, stage="mother", clone_start=transition_date
            )

        _LOGGER.info("Moved plant %s to growspace %s", plant_id, target_growspace_id)
        return True

    async def _harvest_auto_flow(
        self,
        plant_id: str,
        plant: Plant,
        target_growspace_name: str | None,
        transition_date: str,
    ) -> bool:
        """Automatically determine the next growspace for a harvested plant.

        The logic is based on hints in the target name or the plant's current stage.

        Args:
            plant_id: The ID of the plant.
            plant: The Plant object.
            target_growspace_name: A name hint (e.g., "Drying Tent").
            transition_date: The date of the move.

        Returns:
            True if the plant was moved, False otherwise.
        """
        current_stage = self._get_plant_stage(plant)

        # Handle name hints
        if target_growspace_name:
            if "dry" in target_growspace_name.lower():
                return await self._move_to_dry_growspace(
                    plant_id, plant, transition_date
                )
            if "cure" in target_growspace_name.lower():
                return await self._move_to_cure_growspace(
                    plant_id, plant, transition_date
                )
            if "clone" in target_growspace_name.lower():
                return await self._move_to_clone_growspace(
                    plant_id, plant, transition_date
                )
            if "mother" in target_growspace_name.lower():
                return await self._move_to_clone_growspace(
                    plant_id, plant, transition_date
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
        self, plant_id: str, plant: Plant, transition_date: str
    ) -> bool:
        """Move a plant to the dedicated 'clone' growspace.

        Args:
            plant_id: The ID of the plant to move.
            plant: The Plant object.
            transition_date: The date of the move.

        Returns:
            True, as the plant is always moved.
        """
        clone_id = self._ensure_special_growspace("clone", "clone", 5, 5)
        plant.growspace_id = clone_id

        try:
            new_row, new_col = self._find_first_available_position(clone_id)
            plant.row, plant.col = new_row, new_col
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
        self, plant_id: str, plant: Plant, transition_date: str
    ) -> bool:
        """Move a plant to the dedicated 'dry' growspace and record harvest analytics.

        Args:
            plant_id: The ID of the plant to move.
            plant: The Plant object.
            transition_date: The date of the move.

        Returns:
            True, as the plant is always moved.
        """
        # Record analytics before moving
        veg_days = self.calculate_days_in_stage(plant, "veg")
        flower_days = self.calculate_days_in_stage(plant, "flower")

        if veg_days > 0 or flower_days > 0:
            await self.strains.record_harvest(
                plant.strain, plant.phenotype, veg_days, flower_days
            )

        # Now, proceed with moving the plant
        dry_id = self._ensure_special_growspace("dry", "dry")
        plant.growspace_id = dry_id

        growspace = self.growspaces.get(dry_id)
        if growspace and growspace.device_id:
            plant.device_id = growspace.device_id

        try:
            new_row, new_col = self._find_first_available_position(dry_id)
            plant.row, plant.col = new_row, new_col
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
        self, plant_id: str, plant: Plant, transition_date: str
    ) -> bool:
        """Move a plant to the dedicated 'cure' growspace.

        Args:
            plant_id: The ID of the plant to move.
            plant: The Plant object.
            transition_date: The date of the move.

        Returns:
            True, as the plant is always moved.
        """
        cure_id = self._ensure_special_growspace("cure", "cure")
        plant.growspace_id = cure_id

        try:
            new_row, new_col = self._find_first_available_position(cure_id)
            plant.row, plant.col = new_row, new_col
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
        """Remove a plant from the coordinator.

        Args:
            plant_id: The ID of the plant to remove.

        Returns:
            True if the plant was removed, False if it was not found.
        """
        if plant_id in self.plants:
            del self.plants[plant_id]
            await self.async_save()
            return True
        return False

    async def _remove_plant_entities(self, plant_id: str) -> None:
        """Remove all Home Assistant entities associated with a specific plant.

        Args:
            plant_id: The ID of the plant whose entities should be removed.
        """
        entity_registry = er.async_get(self.hass)

        # Find all entities belonging to this plant
        for entity_id, entry in list(entity_registry.entities.items()):
            if entry.unique_id.startswith(plant_id):
                _LOGGER.info("Removing entity %s for plant %s", entity_id, plant_id)
                entity_registry.async_remove(entity_id)

    # =============================================================================
    # STRAIN LIBRARY MANAGEMENT
    # =============================================================================

    def get_strain_options(self) -> list[str]:
        """Get a sorted list of unique strain names from the library.

        Returns:
            A sorted list of unique strain names.
        """
        # The keys are just the strain names in the new hierarchical structure
        return sorted(self.strains.get_all().keys())

    def export_strain_library(self) -> list[str]:
        """Export all strains from the library.

        Returns:
            A list of all strain names.
        """
        return self.get_strain_options()



    async def clear_strains(self) -> int:
        """Remove all strains from the library.

        Returns:
            The number of strains cleared.
        """
        return await self.strains.clear()

    # =============================================================================
    # QUERY AND CALCULATION METHODS
    # =============================================================================

    def get_growspace_plants(self, growspace_id: str) -> list[Plant]:
        """Get all plants located in a specific growspace.

        Args:
            growspace_id: The ID of the growspace.

        Returns:
            A list of Plant objects.
        """
        return [
            plant
            for plant in self.plants.values()
            if plant.growspace_id == growspace_id
        ]

    def calculate_days_in_stage(self, plant: Plant, stage: str) -> int:
        """Calculate how many days a plant has been in a specific growth stage.

        Args:
            plant: The Plant object.
            stage: The name of the stage (e.g., 'veg', 'flower').

        Returns:
            The number of days in the stage.
        """
        start_date = getattr(plant, f"{stage}_start", None)

        end_date = None
        if stage == "seedling" or stage == "clone":
            end_date = getattr(plant, "veg_start", None)
        elif stage == "veg":
            end_date = getattr(plant, "flower_start", None)
        elif stage == "flower":
            end_date = getattr(plant, "dry_start", None)
        elif stage == "dry":
            end_date = getattr(plant, "cure_start", None)

        return self.calculate_days(start_date, end_date)

    def get_growspace_grid(self, growspace_id: str) -> list[list[str | None]]:
        """Generate a 2D grid representation of a growspace's plant layout.

        Args:
            growspace_id: The ID of the growspace.

        Returns:
            A list of lists representing the grid, with plant IDs or None.
        """
        growspace = self.growspaces[growspace_id]
        plants = self.get_growspace_plants(growspace_id)
        return generate_growspace_grid(
            int(growspace.rows), int(growspace.plants_per_row), plants
        )

    def _guess_overview_entity_id(self, growspace_id: str) -> str:
        """Make a best-effort guess of the overview sensor entity ID for a growspace.

        This is used for linking entities when the exact ID is not stored.

        Args:
            growspace_id: The ID of the growspace.

        Returns:
            The guessed entity ID string.
        """
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
        """Check if a notification for a specific event has already been sent.

        Args:
            plant_id: The ID of the plant.
            stage: The growth stage of the event.
            days: The day number of the event.

        Returns:
            True if the notification should be sent, False if it has already been sent.
        """
        return (
            not self._notifications_sent.get(plant_id, {})
            .get(stage, {})
            .get(str(days), False)
        )

    async def mark_notification_sent(
        self, plant_id: str, stage: str, days: int
    ) -> None:
        """Mark a notification as sent to prevent duplicates.

        Args:
            plant_id: The ID of the plant.
            stage: The growth stage of the event.
            days: The day number of the event.
        """
        if plant_id not in self._notifications_sent:
            self._notifications_sent[plant_id] = {}
        if stage not in self._notifications_sent[plant_id]:
            self._notifications_sent[plant_id][stage] = {}

        self._notifications_sent[plant_id][stage][str(days)] = True
        await self.async_save()

    # =============================================================================
    # TIMED NOTIFICATION MANAGEMENT
    # =============================================================================
    async def _async_check_timed_notifications(self) -> None:
        """Check all configured timed notifications and send them if the conditions are met."""
        notifications = self.options.get("timed_notifications", [])
        if not notifications:
            return

        for notification in notifications:
            trigger_type = notification["trigger_type"]  # 'veg' or 'flower'
            day_to_trigger = int(notification["day"])
            message = notification["message"]
            growspace_ids = notification["growspace_ids"]
            notification_id = notification["id"]

            for gs_id in growspace_ids:
                growspace = self.growspaces.get(gs_id)
                if not growspace:
                    continue

                plants = self.get_growspace_plants(gs_id)
                for plant in plants:
                    days_in_stage = self.calculate_days_in_stage(plant, trigger_type)

                    if days_in_stage >= day_to_trigger:
                        notification_key = f"timed_{notification_id}"
                        if not self._notifications_sent.get(plant.plant_id, {}).get(
                            notification_key, False
                        ):
                            _LOGGER.info(
                                f"Triggering timed notification for plant {plant.plant_id} in {growspace.name}"
                            )
                            title = f"{growspace.name} - {trigger_type.capitalize()} Day {day_to_trigger}"

                            await self._send_notification(gs_id, title, message)

                            if plant.plant_id not in self._notifications_sent:
                                self._notifications_sent[plant.plant_id] = {}
                            self._notifications_sent[plant.plant_id][
                                notification_key
                            ] = True
                            await self.async_save()

    async def _send_notification(
        self, growspace_id: str, title: str, message: str
    ) -> None:
        """Send a notification to the target configured for a specific growspace.

        Args:
            growspace_id: The ID of the growspace.
            title: The title of the notification.
            message: The body of the notification.
        """
        growspace = self.growspaces.get(growspace_id)
        if not growspace or not growspace.notification_target:
            _LOGGER.debug(
                "Notification not sent for growspace %s: No target configured",
                growspace_id,
            )
            return

        notification_service = growspace.notification_target.replace("notify.", "")

        await self.hass.services.async_call(
            "notify",
            notification_service,
            {
                "message": message,
                "title": title,
            },
            blocking=False,
        )
        _LOGGER.info(f"Sent notification to {notification_service}: {title}")

    def _get_sensor_value(self, entity_id: str | None) -> float | None:
        """Safely get the numeric state of a sensor entity from Home Assistant.

        Args:
            entity_id: The entity ID to look up.

        Returns:
            The numeric state of the sensor, or None if unavailable or invalid.
        """
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state and state.state not in ["unknown", "unavailable"]:
            try:
                return float(state.state)
            except (ValueError, TypeError):
                return None
        return None

    async def _async_update_air_exchange_recommendations(self) -> None:
        """Calculate and store air exchange recommendations for each growspace.

        This method compares the environmental conditions of outside air and a
        'lung room' to the conditions in each growspace under stress, recommending
        the best source for air exchange to correct the environment.
        """
        await self._async_check_timed_notifications()
        recommendations = {}
        global_settings = self.options.get("global_settings", {})

        # Get outside conditions
        outside_temp = None
        outside_humidity = None
        weather_entity_id = global_settings.get("weather_entity")
        if weather_entity_id:
            weather_state = self.hass.states.get(weather_entity_id)
            if weather_state and weather_state.attributes:
                outside_temp = weather_state.attributes.get("temperature")
                outside_humidity = weather_state.attributes.get("humidity")
        outside_vpd = (
            VPDCalculator.calculate_vpd(outside_temp, outside_humidity)
            if outside_temp is not None and outside_humidity is not None
            else None
        )

        # Get lung room conditions
        lung_room_temp = self._get_sensor_value(
            global_settings.get("lung_room_temp_sensor")
        )
        lung_room_humidity = self._get_sensor_value(
            global_settings.get("lung_room_humidity_sensor")
        )
        lung_room_vpd = (
            VPDCalculator.calculate_vpd(lung_room_temp, lung_room_humidity)
            if lung_room_temp is not None and lung_room_humidity is not None
            else None
        )

        entity_registry = er.async_get(self.hass)
        for growspace_id, growspace in self.growspaces.items():
            # Find the entity ID from the unique ID
            stress_sensor_unique_id = f"{DOMAIN}_{growspace_id}_stress"
            stress_sensor_entity_id = entity_registry.async_get_entity_id(
                "binary_sensor", DOMAIN, stress_sensor_unique_id
            )

            if not stress_sensor_entity_id:
                recommendations[growspace_id] = "Idle"  # Sensor not registered yet
                continue

            stress_state = self.hass.states.get(stress_sensor_entity_id)

            if not stress_state or stress_state.state != "on":
                recommendations[growspace_id] = "Idle"
                continue

            current_vpd = self._get_sensor_value(
                growspace.environment_config.get("vpd_sensor")
            )
            target_vpd = (
                self.data.get("bayesian_sensors_reason", {})
                .get(growspace_id, {})
                .get("target_vpd")
            )

            if current_vpd is None or target_vpd is None:
                recommendations[growspace_id] = "Idle"
                continue

            min_temp = growspace.environment_config.get(
                "minimum_source_air_temperature", 18
            )
            current_diff = abs(current_vpd - target_vpd)
            best_option = "Idle"
            best_diff = current_diff

            # Evaluate outside air
            if (
                outside_vpd is not None
                and outside_temp is not None
                and outside_temp >= min_temp
            ):
                outside_diff = abs(outside_vpd - target_vpd)
                if outside_diff < best_diff:
                    best_diff = outside_diff
                    best_option = "Open Window"

            # Evaluate lung room air
            if (
                lung_room_vpd is not None
                and lung_room_temp is not None
                and lung_room_temp >= min_temp
            ):
                lung_room_diff = abs(lung_room_vpd - target_vpd)
                if lung_room_diff < best_diff:
                    best_diff = lung_room_diff
                    best_option = "Ventilate Lung Room"

            recommendations[growspace_id] = best_option

        if "air_exchange_recommendations" not in self.data:
            self.data["air_exchange_recommendations"] = {}
        self.data["air_exchange_recommendations"].update(recommendations)
