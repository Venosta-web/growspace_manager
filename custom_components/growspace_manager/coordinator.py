"""Data update coordinator for the Growspace Manager integration."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

if TYPE_CHECKING:
    from .dehumidifier_coordinator import DehumidifierCoordinator
    from .irrigation_coordinator import IrrigationCoordinator
    from .vwc_irrigation_coordinator import VWCIrrigationCoordinator


from .bayesian_data import VPD_STRESS_THRESHOLDS
from .const import (
    DATE_FIELDS,
    DEFAULT_FLOWER_EARLY_DAYS,
    DEFAULT_VEG_EARLY_DAYS,
    DOMAIN,
    PlantStage,
)
from .environment_analyzer import EnvironmentAnalyzer
from .growspace_validator import GrowspaceValidator
from .import_export_manager import ImportExportManager
from .migration_manager import MigrationManager
from .models import Growspace, GrowspaceCoordinatorData, GrowspaceEvent, Plant
from .notification_manager import NotificationManager
from .plant_lifecycle_manager import PlantLifecycleManager
from .storage_manager import StorageManager
from .strain_library import StrainLibrary
from .utils import (
    calculate_days_since,
    calculate_plant_stage,
    days_to_week,
    format_date,
    generate_growspace_grid,
    parse_date_field,
)

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

    growspaces: dict[str, Growspace] = {}
    plants: dict[str, Plant] = {}
    strain_library: StrainLibrary | None = None

    def __init__(
        self,
        hass: HomeAssistant,
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
            update_interval=timedelta(minutes=15),
        )

        self.hass = hass
        self.growspaces: dict[str, Growspace] = {}
        self.plants: dict[str, Plant] = {}
        self.events: dict[str, list[GrowspaceEvent]] = {}

        self.options = options or {}
        _LOGGER.info("--- COORDINATOR INITIALIZED WITH OPTIONS: %s ---", self.options)

        # Initialize strain library
        if strain_library is None:
            # Fallback for testing or legacy init
            self.strain_library = StrainLibrary(hass)
        else:
            self.strain_library = strain_library

        self.migration_manager = MigrationManager(self)
        self.validator = GrowspaceValidator(self)
        self.storage_manager = StorageManager(self, hass)
        self.environment_analyzer = EnvironmentAnalyzer(hass, self)
        self.notification_manager = NotificationManager(hass, self)
        self.import_export_manager = ImportExportManager(hass)
        self.lifecycle_manager = PlantLifecycleManager(self)

        self._notifications_sent: dict[str, dict[str, dict[str, bool]]] = {}
        self._notifications_enabled: dict[
            str, bool
        ] = {}  # ✅ Notification switch states

        # Initialize runtime coordination
        self.irrigation_coordinators: dict[
            str, IrrigationCoordinator | VWCIrrigationCoordinator
        ] = {}
        self.dehumidifier_coordinators: dict[str, DehumidifierCoordinator] = {}
        self.created_entities: list[str] = []

        # Load data
        if data is None:
            data = {}
        self._load_plants(data.get("plants", {}))
        self._load_growspaces(data.get("growspaces", {}))

        _LOGGER.debug(
            "Loaded %d plants and %d growspaces", len(self.plants), len(self.growspaces)
        )

    def _load_plants(self, raw_plants: dict) -> None:
        """Load plants from raw data."""
        for pid, pdata in raw_plants.items():
            try:
                if isinstance(pdata, dict):
                    self.plants[pid] = Plant.from_dict(pdata)
                elif isinstance(pdata, Plant):
                    self.plants[pid] = pdata
                else:
                    self._raise_invalid_plant_data_type(pid, pdata)
            except Exception:
                _LOGGER.exception("Failed to load plant %s", pid)

    def _load_growspaces(self, raw_growspaces: dict) -> None:
        """Load growspaces from raw data."""
        for gid, gdata in raw_growspaces.items():
            try:
                if isinstance(gdata, dict):
                    self.growspaces[gid] = Growspace.from_dict(gdata)
                elif isinstance(gdata, Growspace):
                    self.growspaces[gid] = gdata
                else:
                    self._raise_invalid_growspace_data_type(gid, gdata)
            except Exception:
                _LOGGER.exception("Failed to load growspace %s", gid)

    # -----------------------------
    # Methods for editor dropdown
    def _raise_invalid_plant_data_type(self, pid: str, pdata: Any) -> None:
        """Raise TypeError for invalid plant data."""
        raise TypeError(f"Invalid data type for plant {pid}: {type(pdata)}")

    def _raise_invalid_growspace_data_type(self, gid: str, gdata: Any) -> None:
        """Raise TypeError for invalid growspace data."""
        raise TypeError(f"Invalid data type for growspace {gid}: {type(gdata)}")

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

    # =============================================================================
    # EVENT LOGBOOK MANAGEMENT
    # =============================================================================

    def add_event(self, growspace_id: str, event: GrowspaceEvent) -> None:
        """Add a Growspace event to the logbook.

        Args:
            growspace_id: The ID of the growspace where the event occurred.
            event: The GrowspaceEvent object.
        """
        if growspace_id not in self.events:
            self.events[growspace_id] = []

        self.events[growspace_id].append(event)

        # Enforce rolling buffer limit (max 50 events per growspace)
        if len(self.events[growspace_id]) > 50:
            self.events[growspace_id].pop(0)

        # Persist changes
        self.hass.async_create_task(self.async_commit())

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
            if isinstance(date_value, date):
                return date_value
            if isinstance(date_value, str):
                return parse_date_field(date_value).date()
        except Exception:
            _LOGGER.exception("Failed to parse date %s", date_value)
        return None

    def calculate_days(self, start_date: DateInput, end_date: DateInput = None) -> int:
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

    def ensure_special_growspace(
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
        self.migration_manager.cleanup_legacy_aliases(canonical_id)

        # Create or update the canonical growspace
        if canonical_id not in self.growspaces:
            self._create_special_growspace(canonical_id, name, rows, plants_per_row)
            # ✅ Enable notifications by default for new special growspace
            self._notifications_enabled[canonical_id] = True
        else:
            self._update_special_growspace_name(canonical_id, name)

        # self.update_data_property() - Handled by async_commit via async_add_growspace or manual call if needed
        # NOTE: ensure_special_growspace effectively just prepares the structure.
        # The actual save happens if it creates a NEW one via _create_special_growspace which calls nothing,
        # or updates via _update_special_growspace_name.
        # BUT wait, the original code called update_data_property() but didn't save?
        # Let's check line 374: self.update_data_property()
        # It updates local memory but doesn't persist to disk?
        # The method returns canonical_id.
        # Let's keep it safe and just update data property as before to avoiding changing behavior too much here unless we want to commit.
        self.update_data_property()
        return canonical_id

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
        return self.ensure_special_growspace(
            PlantStage.MOTHER, "mother", rows=3, plants_per_row=3
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
        await self.notification_manager.async_check_timed_notifications()
        await self.environment_analyzer.async_update_air_exchange_recommendations()

        return self.data

    async def async_commit(self) -> None:
        """Commit changes to storage and notify listeners."""
        self.update_data_property()
        await self.async_save()
        self.async_fire_growspace_updated()
        for gs_id in self.growspaces:
            if gs_id in self.irrigation_coordinators:
                self.irrigation_coordinators[gs_id].async_request_refresh()

    def async_fire_growspace_updated(self) -> None:
        """Fire event to notify frontend that growspace data has changed."""
        self.hass.bus.async_fire(f"{DOMAIN}_updated", {})

    async def async_save(self) -> None:
        """Save data to storage."""
        await self.storage_manager.async_save()
        self.async_set_updated_data(self.data)
        self.async_fire_growspace_updated()

    async def async_load(self) -> None:
        """Load data from persistent storage and handle migrations."""
        await self.storage_manager.async_load()

    def update_data_property(self) -> None:
        """Update the central `self.data` property to reflect the current coordinator state."""
        # Preserve existing recommendations if valid
        recs = {}
        if self.data and isinstance(self.data, dict):
            recs = self.data.get("air_exchange_recommendations", {})

        self.data: GrowspaceCoordinatorData = {
            "growspaces": self.growspaces,
            "plants": self.plants,
            "notifications_sent": self._notifications_sent,
            "notifications_enabled": self._notifications_enabled,
            "_version": datetime.now().isoformat(),
            "air_exchange_recommendations": recs,
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

        await self.async_commit()

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

        await self.async_commit()

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

            # Save to storage and notify
            await self.async_commit()

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

        invalid_plants = [
            plant
            for plant in plants_to_check
            if int(plant.row) > new_rows or int(plant.col) > new_plants_per_row
        ]

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

        await self.async_commit()

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
        plant_id: str | None = None,
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
            plant_id: Optional specific ID for the plant.
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
                "Position (%d, %d) in growspace %s is occupied. Finding first available spot",
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
                raise

        # Create plant object
        # Ensure dates are stored as strings to match Plant model
        plant = Plant(
            plant_id=plant_id or str(uuid.uuid4()),
            growspace_id=growspace_id,
            strain=strain,
            phenotype=phenotype,
            row=final_row,
            col=final_col,
            stage=stage or "",
            type=type,
            device_id=device_id,
            seedling_start=format_date(seedling_start),
            mother_start=format_date(mother_start),
            clone_start=format_date(clone_start),
            veg_start=format_date(veg_start),
            flower_start=format_date(flower_start),
            dry_start=format_date(dry_start),
            cure_start=format_date(cure_start),
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            source_mother=source_mother,
        )

        # Calculate stage if not explicitly provided
        if not stage:
            plant.stage = calculate_plant_stage(plant)

        self.plants[plant.plant_id] = plant

        await self.async_commit()

        return plant

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
        kwargs["type"] = PlantStage.MOTHER

        # Set mother_start to today if not provided
        if mother_start is None:
            mother_start = date.today()
        kwargs["mother_start"] = mother_start

        plant: Plant = await self.async_add_plant(
            growspace_id=mother_id,
            strain=strain,
            phenotype=phenotype,
            row=row,
            col=col,
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
        clone_gs_id = self.ensure_special_growspace(PlantStage.CLONE, "clone", 5, 5)
        new_plants: list[Plant] = []

        for _ in range(num_clones):
            row, col = self.validator.find_first_available_position(clone_gs_id)
            clone_id = await self.lifecycle_manager.handle_clone_creation(
                growspace_id=clone_gs_id,
                strain=mother.strain,
                row=row,
                col=col,
                source_mother_id=mother_plant_id,
                mother_plant=mother,
                phenotype=mother.phenotype,
            )

            if new_plant := self.plants.get(clone_id):
                new_plants.append(new_plant)
            else:
                _LOGGER.error("Failed to retrieve created clone %s", clone_id)

        return new_plants

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
        if clone.stage != PlantStage.CLONE:
            raise ValueError("Plant is not in clone stage")

        veg_gs_id = self.ensure_special_growspace(PlantStage.VEG, "veg", 5, 5)
        row, col = self.validator.find_first_available_position(veg_gs_id)

        await self.async_update_plant(
            clone_id,
            growspace_id=veg_gs_id,
            row=row,
            col=col,
            stage=PlantStage.VEG,
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

            # Enforce string format for date fields
            if key in DATE_FIELDS:
                value = format_date(value)
                updates[key] = value  # Update the value in 'updates' dict as well

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
        await self.async_commit()
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

        await self.async_commit()

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
        self,
        plant_id: str,
        new_stage: str | PlantStage,
        transition_date: date | None = None,
    ) -> None:
        """Transition a plant to a new stage."""
        await self.lifecycle_manager.transition_plant_stage(
            plant_id, new_stage, transition_date
        )

    # =============================================================================
    # DATA RETRIEVAL FOR WEBSOCKET API
    # =============================================================================

    def get_growspace_data(self, growspace_id: str | None = None) -> dict[str, Any]:
        """Get full data for a growspace (or all growspaces) for WebSocket API."""
        if growspace_id:
            if growspace_id not in self.growspaces:
                return {}
            return self._build_growspace_payload(growspace_id)

        # Return all
        return {gid: self._build_growspace_payload(gid) for gid in self.growspaces}

    def _build_growspace_payload(self, growspace_id: str) -> dict[str, Any]:
        """Build the full JSON payload for a single growspace."""
        growspace = self.growspaces[growspace_id]
        plants = self.get_growspace_plants(growspace_id)

        # Calculate max stage days
        max_veg = max(
            (calculate_days_since(p.veg_start) for p in plants if p.veg_start),
            default=0,
        )
        max_flower = max(
            (calculate_days_since(p.flower_start) for p in plants if p.flower_start),
            default=0,
        )
        max_dry = max(
            (calculate_days_since(p.dry_start) for p in plants if p.dry_start),
            default=0,
        )
        max_cure = max(
            (calculate_days_since(p.cure_start) for p in plants if p.cure_start),
            default=0,
        )

        # Calculate weeks from days
        veg_week = days_to_week(max_veg)
        flower_week = days_to_week(max_flower)

        biological_metrics = self._get_biological_metrics(
            growspace, max_veg, max_flower, max_dry, max_cure
        )

        # Get irrigation settings
        irrigation_options = growspace.irrigation_config

        # Create grid representation (Detailed rich grid)
        grid = self._generate_rich_plant_grid(growspace, plants)

        # Determine growspace type
        gs_type = "normal"
        if growspace.id in ("mother", "clone", "dry", "cure"):
            gs_type = growspace.id

        # Build complete dict
        data = {
            "growspace_id": growspace.id,
            "name": growspace.name,
            "type": gs_type,
            "rows": growspace.rows,
            "plants_per_row": growspace.plants_per_row,
            "total_plants": len(plants),
            "notification_target": growspace.notification_target,
            "max_veg_days": max_veg,
            "max_flower_days": max_flower,
            "veg_week": veg_week,
            "flower_week": flower_week,
            "max_stage_summary": f"Veg: {max_veg}d (W{veg_week}), Flower: {max_flower}d (W{flower_week})",
            "irrigation_times": list(irrigation_options.get("irrigation_times", [])),
            "drain_times": list(irrigation_options.get("drain_times", [])),
            "grid": grid,
            **biological_metrics,
        }

        # Add environment attributes
        data.update(self._get_environment_attributes(growspace))

        return data

    def _generate_rich_plant_grid(
        self, growspace: Growspace, plants: list[Plant]
    ) -> dict[str, dict[str, Any] | None]:
        """Generate the detailed plant grid representation."""
        grid: dict[str, dict[str, Any] | None] = {}
        for row in range(1, int(growspace.rows) + 1):
            for col in range(1, int(growspace.plants_per_row) + 1):
                grid[f"position_{row}_{col}"] = None

        # Fill grid with plants
        for plant in plants:
            row_i = int(plant.row)
            col_i = int(plant.col)
            position_key = f"position_{row_i}_{col_i}"
            grid[position_key] = {
                "plant_id": plant.plant_id,
                "strain": plant.strain,
                "phenotype": plant.phenotype,
                # Days in stage
                "seedling_days": self.calculate_days_in_stage(plant, "seedling"),
                "mother_days": self.calculate_days_in_stage(plant, "mother"),
                "clone_days": self.calculate_days_in_stage(plant, "clone"),
                "veg_days": self.calculate_days_in_stage(plant, "veg"),
                "flower_days": self.calculate_days_in_stage(plant, "flower"),
                "dry_days": self.calculate_days_in_stage(plant, "dry"),
                "cure_days": self.calculate_days_in_stage(plant, "cure"),
                # Start dates
                "seedling_start": format_date(plant.seedling_start),
                "mother_start": format_date(plant.mother_start),
                "clone_start": format_date(plant.clone_start),
                "veg_start": format_date(plant.veg_start),
                "flower_start": format_date(plant.flower_start),
                "dry_start": format_date(plant.dry_start),
                "cure_start": format_date(plant.cure_start),
                # Location & Stage
                "row": row_i,
                "col": col_i,
                "position": f"({row_i},{col_i})",
                "stage": calculate_plant_stage(plant),
            }
        return grid

    def _get_biological_metrics(
        self,
        growspace: Growspace,
        max_veg: int,
        max_flower: int,
        max_dry: int,
        max_cure: int,
    ) -> dict[str, Any]:
        """Calculate biological target metrics for the growspace."""
        granular_stage = self._determine_granular_stage(
            max_veg, max_flower, max_dry, max_cure
        )
        is_day = self._determine_is_day(growspace)
        day_key = "day" if is_day else "night"

        threshold_data = VPD_STRESS_THRESHOLDS.get(
            granular_stage, VPD_STRESS_THRESHOLDS["veg_early"]
        )
        cycle_data = threshold_data.get(day_key, threshold_data["day"])

        target_min, target_max = cycle_data.get("mild", (0.8, 1.2))
        danger_min, danger_max = cycle_data.get("stress", (0.6, 1.4))

        vpd_status = "unknown"
        vpd_sensor_id = growspace.environment_config.get("vpd_sensor")

        if vpd_sensor_id:
            current_vpd = self._get_sensor_value(vpd_sensor_id)
            if current_vpd is not None:
                if current_vpd < danger_min or current_vpd > danger_max:
                    vpd_status = "danger"
                elif current_vpd < target_min or current_vpd > target_max:
                    vpd_status = "warning"
                else:
                    vpd_status = "optimal"

        return {
            "granular_stage": granular_stage,
            "is_day": is_day,
            "vpd_target_min": target_min,
            "vpd_target_max": target_max,
            "vpd_danger_min": danger_min,
            "vpd_danger_max": danger_max,
            "vpd_status": vpd_status,
        }

    def _determine_granular_stage(
        self, max_veg: int, max_flower: int, max_dry: int, max_cure: int
    ) -> str:
        """Determine granular growth stage based on days."""
        if max_cure > 0:
            return "cure"
        if max_dry > 0:
            return "dry"
        if max_flower > 0:
            if max_flower <= DEFAULT_FLOWER_EARLY_DAYS:
                return "flower_early"
            if max_flower <= (DEFAULT_FLOWER_EARLY_DAYS + 21):
                return "flower_mid"
            return "flower_late"
        if max_veg > 0:
            if max_veg > 0 and max_veg <= DEFAULT_VEG_EARLY_DAYS:
                return "veg_early"
            return "veg_late"
        return "veg_early"

    def _determine_is_day(self, growspace: Growspace) -> bool:
        """Determine if it is currently day or night in the growspace."""
        light_sensor = growspace.environment_config.get("light_sensor")
        if light_sensor:
            light_state = self.hass.states.get(light_sensor)
            if light_state and light_state.state not in (
                STATE_UNKNOWN,
                STATE_UNAVAILABLE,
            ):
                if light_state.state == STATE_ON:
                    return True
                if light_state.state == "off":
                    return False
                try:
                    return float(light_state.state) > 0
                except (ValueError, TypeError):
                    pass
        return True

    def _get_sensor_value(self, sensor_id: str | None) -> float | None:
        """Safely get the numeric value from a sensor's state."""
        if not sensor_id:
            return None
        state = self.hass.states.get(sensor_id)
        if not state or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    def _get_environment_attributes(self, growspace: Growspace) -> dict[str, Any]:
        """Get environment-related attributes."""
        attributes = {}
        if growspace.environment_config:
            env_config = growspace.environment_config
            # Just copying minimal logic for now - or should we do full?
            # The sensor had full logic including dehum, fan etc.
            # Let's map the configured sensors.
            for key in [
                "temperature_sensor",
                "humidity_sensor",
                "vpd_sensor",
                "co2_sensor",
                "dehumidifier_entity",
                "circulation_fan_entity",
                "exhaust_fan_entity",
                "light_sensor",
                "irrigation_pump_entity",
                "drain_pump_entity",
            ]:
                if val := env_config.get(key):
                    attributes[key] = val
                    # Also include current state if useful?
                    # The frontend might want it to display overview.
                    # Sensor implementation included state for some.
                    if key == "dehumidifier_entity" and val:
                        attributes["dehumidifier_state"] = (
                            self.hass.states.get(val)
                            and self.hass.states.get(val).state
                        )
        return attributes

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

        plant.stage = PlantStage.FLOWER
        plant.flower_start = date.today().isoformat()
        plant.updated_at = plant.flower_start
        await self.async_commit()
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

        plant.stage = PlantStage.DRY
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

        plant.stage = PlantStage.CURE
        plant.cure_start = date.today().isoformat()
        plant.updated_at = plant.cure_start
        await self.async_commit()
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

        plant.stage = PlantStage.DRY
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
        stage_before = calculate_plant_stage(plant)
        _LOGGER.info(
            "Harvest start: plant_id=%s stage=%s current_growspace=%s target_id=%s target_name=%s date=%s",
            plant_id,
            stage_before,
            plant.growspace_id,
            target_growspace_id,
            target_growspace_name,
            transition_date,
        )

        moved = await self.lifecycle_manager.handle_harvest_logic(
            plant_id, plant, target_growspace_id, target_growspace_name, transition_date
        )

        await self.async_commit()

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

    async def async_remove_plant(self, plant_id: str) -> bool:
        """Remove a plant from the coordinator.

        Args:
            plant_id: The ID of the plant to remove.

        Returns:
            True if the plant was removed, False if it was not found.
        """
        if plant_id in self.plants:
            del self.plants[plant_id]
            await self.async_commit()
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
        return sorted(self.strain_library.get_all().keys())

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
        return await self.strain_library.clear()

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
        if stage in {PlantStage.SEEDLING, PlantStage.CLONE}:
            end_date = getattr(plant, "veg_start", None)
        elif stage == PlantStage.VEG:
            end_date = getattr(plant, "flower_start", None)
        elif stage == PlantStage.FLOWER:
            end_date = getattr(plant, "dry_start", None)
        elif stage == PlantStage.DRY:
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
        if growspace_id in (PlantStage.DRY, "dry_overview"):
            return f"sensor.{PlantStage.DRY}"
        if growspace_id in (PlantStage.CURE, "cure_overview"):
            return f"sensor.{PlantStage.CURE}"
        if growspace_id in (PlantStage.MOTHER, "mother_overview"):
            return f"sensor.{PlantStage.MOTHER}"
        if growspace_id in (PlantStage.CLONE, "clone_overview"):
            return f"sensor.{PlantStage.CLONE}"
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
        await self.async_commit()
