"""Data update coordinator for the Growspace Manager integration."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import Any, override

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .const import (
    ATTR_DRAIN_TIMES,
    ATTR_GROWSPACE_ID,
    ATTR_IRRIGATION_TIMES,
    ATTR_MOTHER_PLANT_ID,
    ATTR_PLANT_ID,
    ATTR_TARGET_GROWSPACE_ID,
    CANONICAL_ID_CLONE,
    CANONICAL_ID_CURE,
    CANONICAL_ID_DRY,
    CANONICAL_ID_MOTHER,
    CANONICAL_ID_VEG,
    CATEGORY_IPM,
    CATEGORY_TRAINING,
    CONF_HUMIDITY_SENSOR,
    CONF_TEMP_SENSOR,
    CONF_VPD_SENSOR,
    DEFAULT_PLANTS_PER_ROW,
    DEFAULT_ROWS,
    DOMAIN,
    EVENT_GROWSPACE_LOG_ENTRY,
    SPECIAL_GROWSPACES,
    PlantStage,
)
from .data_repository import DataRepository
from .dehumidifier_coordinator import DehumidifierCoordinator
from .environment_analyzer import EnvironmentAnalyzer
from .events import (
    EVENT_GROWSPACE_ADDED,
    EVENT_GROWSPACE_REMOVED,
    EVENT_GROWSPACE_UPDATED,
    EVENT_PLANT_ADDED,
    EVENT_PLANT_HARVESTED,
    EVENT_PLANT_MOVED,
    EVENT_PLANT_REMOVED,
    EVENT_PLANT_SWITCHED,
    EVENT_PLANT_TRANSITIONED,
    EVENT_PLANT_UPDATED,
    async_fire_clones_taken_event,
    async_fire_growspace_event,
    async_fire_plant_event,
)
from .exceptions import (
    GrowspaceNotFoundError,
    ValidationChangeError,
)
from .growspace_validator import GrowspaceValidator
from .import_export_manager import ImportExportManager
from .irrigation_coordinator import IrrigationCoordinator
from .managers.subsystem import SubsystemManager
from .models import (
    Growspace,
    GrowspaceEvent,
    GrowspaceType,
    IPMPreset,
    NutrientPreset,
    Plant,
)
from .notification_manager import NotificationManager
from .plant_lifecycle_manager import PlantLifecycleManager
from .serializers import GrowspaceSerializer
from .storage_manager import StorageManager
from .strain_library import StrainLibrary
from .utils import (
    calculate_days_since,
    calculate_plant_stage,
    generate_growspace_overview_unique_id,
    parse_date_field,
)
from .vwc_irrigation_coordinator import VWCIrrigationCoordinator

_LOGGER = logging.getLogger(__name__)


# Type aliases for better readability
type PlantDict = dict[str, Any]
type GrowspaceDict = dict[str, Any]
type NotificationDict = dict[str, Any]
type DateInput = str | datetime | date | None


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

    @staticmethod
    def get_for_service_call(
        hass: HomeAssistant, call: ServiceCall | dict[str, Any]
    ) -> GrowspaceCoordinator:
        """Retrieve the correct coordinator based on service call data.

        Args:
            hass: The Home Assistant instance.
            call: A ServiceCall or dict containing the service call data.

        Returns:
            The appropriate GrowspaceCoordinator for the request.

        Raises:
            ServiceValidationError: If no matching coordinator can be found.
        """

        data = call.data if isinstance(call, ServiceCall) else call

        entries: list[ConfigEntry[GrowspaceCoordinator]] = (
            hass.config_entries.async_entries(DOMAIN)
        )
        coordinators: list[GrowspaceCoordinator] = [
            entry.runtime_data
            for entry in entries
            if entry.state == ConfigEntryState.LOADED and hasattr(entry, "runtime_data")
        ]

        id_lookups = [
            (ATTR_GROWSPACE_ID, "growspaces"),
            (ATTR_TARGET_GROWSPACE_ID, "growspaces"),
            (ATTR_PLANT_ID, "plants"),
            (ATTR_MOTHER_PLANT_ID, "plants"),
        ]

        for key, attr in id_lookups:
            if val := data.get(key):
                for coordinator in coordinators:
                    target_collection = getattr(coordinator, attr)
                    if isinstance(val, list):
                        if any(item in target_collection for item in val):
                            return coordinator
                    elif val in target_collection:
                        return coordinator

        if len(coordinators) == 1:
            return coordinators[0]

        raise ServiceValidationError(
            "Could not determine which Growspace Manager instance to use. "
            "Please specify a valid growspace_id or plant_id."
        )

    @property
    def irrigation_coordinators(
        self,
    ) -> dict[str, IrrigationCoordinator | VWCIrrigationCoordinator]:
        """Return irrigation coordinators fro SubsystemManager."""
        return self.subsystem_manager.irrigation_coordinators

    @property
    def dehumidifier_coordinators(self) -> dict[str, DehumidifierCoordinator]:
        """Return dehumidifier coordinators fro SubsystemManager."""
        return self.subsystem_manager.dehumidifier_coordinators

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry[GrowspaceCoordinator],
        data: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
        strain_library: StrainLibrary | None = None,
    ) -> None:
        """Initialize the Growspace Coordinator.

        Args:
            hass: The Home Assistant instance.
            entry: The config entry.
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
        self.config_entry = entry
        self._lock = asyncio.Lock()
        self.serializer = GrowspaceSerializer(hass)
        self.growspaces: dict[str, Growspace] = {}
        self.plants: dict[str, Plant] = {}
        # self.events removed - using native HA Event Bus
        self.nutrient_presets: dict[str, NutrientPreset] = {}
        self.ipm_presets: dict[str, IPMPreset] = {}

        # Optimization: Cache for serialized growspace data
        self._serialized_cache: dict[str, dict[str, Any]] = {}

        self.options = options or {}
        _LOGGER.info("--- COORDINATOR INITIALIZED WITH OPTIONS: %s ---", self.options)

        # Initialize strain library
        if strain_library is None:
            # Fallback for testing or legacy init
            self.strain_library = StrainLibrary(hass)
        else:
            self.strain_library = strain_library

        self.validator = GrowspaceValidator(self)
        self.storage_manager = StorageManager(self, hass)
        self.environment_analyzer = EnvironmentAnalyzer(hass, self)
        self.notification_manager = NotificationManager(hass, self)
        self.import_export_manager = ImportExportManager(hass)
        self.lifecycle_manager = PlantLifecycleManager(self)

        # Initialize Data Repository
        self.data_repository = DataRepository(self.growspaces, self.plants)

        # Initialize Subsystem Manager
        self.subsystem_manager = SubsystemManager(hass, self, entry)

        self._notifications_sent: dict[str, dict[str, dict[str, bool]]] = {}
        self._notifications_enabled: dict[
            str, bool
        ] = {}  # ✅ Notification switch states

        self.created_entity_ids: list[tuple[str, str, str]] = []

        # Load data
        if data is None:
            data = {}

        self.plants = self.serializer.deserialize_plants(data.get("plants", {}))
        self.growspaces = self.serializer.deserialize_growspaces(
            data.get("growspaces", {})
        )

        # Update Data Repository with loaded data
        self.data_repository.load_data(self.growspaces, self.plants)

        _LOGGER.debug(
            "Loaded %d plants and %d growspaces", len(self.plants), len(self.growspaces)
        )

    def _extract_gs_ids_from_result(self, result: Any, gs_ids: set[str]) -> None:
        """Extract growspace IDs from function result."""
        if not result:
            return

        if hasattr(result, "growspace_id") and result.growspace_id:
            gs_ids.add(result.growspace_id)
        elif hasattr(result, "id") and hasattr(
            result, "plants_per_row"
        ):  # Growspace check
            gs_ids.add(result.id)

    def _extract_gs_ids_from_args(
        self, args: tuple, kwargs: dict[str, Any], gs_ids: set[str]
    ) -> None:
        """Extract growspace IDs from function arguments."""
        # Strategy 2: Check arguments for 'growspace_id'
        if "growspace_id" in kwargs:
            gs_ids.add(kwargs["growspace_id"])
        elif len(args) > 0 and isinstance(args[0], str):
            arg_id = args[0]
            if arg_id in self.growspaces:
                gs_ids.add(arg_id)

        # Strategy 3: Check for 'plant_id' and look up growspace
        pid = kwargs.get("plant_id")
        if (
            not pid
            and len(args) > 0
            and isinstance(args[0], str)
            and args[0] in self.plants
        ):
            pid = args[0]

        if pid and (plant := self.plants.get(pid)):
            gs_ids.add(plant.growspace_id)

    # =============================================================================
    # CACHING AND OPTIMIZATION HELPER
    # =============================================================================

    def _invalidate_cache(self, growspace_id: str | None = None) -> None:
        """Invalidate the serialization cache.

        Args:
            growspace_id: The ID of the growspace to invalidate. If None, clear all.
        """
        if growspace_id is None:
            self._serialized_cache.clear()
        else:
            self._serialized_cache.pop(growspace_id, None)

    async def async_refresh_growspace_data(self, growspace_id: str) -> None:
        """Thread-safe method to refresh data for a specific growspace.

        This method acquires the coordinator lock, invalidates the cache for the
        specified growspace, and updates the data property. External classes should
        use this method instead of directly accessing _lock and _invalidate_cache.

        Args:
            growspace_id: The ID of the growspace to refresh.
        """
        async with self._lock:
            self._invalidate_cache(growspace_id)
            self.update_data_property()

    def _get_serialized_growspace(
        self, growspace_id: str, preloaded_plants: list[Plant] | None = None
    ) -> dict[str, Any]:
        """Get serialized growspace data, using cache if available.

        Args:
            growspace_id: The ID of the growspace to serialize.
            preloaded_plants: Optional list of plants in this growspace.
                              If provided, avoids a full scan of self.plants.
        """
        if growspace_id in self._serialized_cache:
            return self._serialized_cache[growspace_id]

        growspace = self.growspaces[growspace_id]
        # Optimization: Use preloaded plants if available, else fetch them
        if preloaded_plants is not None:
            plants = preloaded_plants
        else:
            plants = self.get_growspace_plants(growspace_id)

        # Calculate aggregated stats for the growspace
        stage_attr_map = {
            "veg_start": "max_veg_days",
            "flower_start": "max_flower_days",
            "dry_start": "max_dry_days",
            "cure_start": "max_cure_days",
        }

        # Calculate max days for each stage
        max_days = {
            target_var: max(
                (
                    calculate_days_since(getattr(p, attr))
                    for p in plants
                    if getattr(p, attr)
                ),
                default=0,
            )
            for attr, target_var in stage_attr_map.items()
        }

        max_veg_days = max_days["max_veg_days"]
        max_flower_days = max_days["max_flower_days"]
        max_dry_days = max_days["max_dry_days"]
        max_cure_days = max_days["max_cure_days"]

        # Calculate biological metrics via EnvironmentAnalyzer (View Model assembly)
        biological_metrics = self.environment_analyzer.calculate_biological_metrics(
            growspace, max_veg_days, max_flower_days, max_dry_days, max_cure_days
        )

        serialized = self.serializer.serialize_growspace(
            growspace,
            plants,
            biological_metrics,
            max_veg_days=max_veg_days,
            max_flower_days=max_flower_days,
            max_dry_days=max_dry_days,
            max_cure_days=max_cure_days,
        )

        # Inject timestamp for efficient frontend equality checks (change detection)
        serialized["_ts"] = int(dt_util.utcnow().timestamp() * 1000)

        self._serialized_cache[growspace_id] = serialized
        return serialized

    async def async_initialize_sub_coordinators(
        self, entry: ConfigEntry[GrowspaceCoordinator]
    ) -> None:
        """Initialize sub-coordinators for irrigation and dehumidifier."""
        await self.async_register_devices()  # Register devices first
        await self.subsystem_manager.async_initialize_sub_coordinators(self.growspaces)

    async def async_register_devices(self) -> None:
        """Register growspaces as devices."""
        device_registry = dr.async_get(self.hass)
        for gs_id, growspace in self.growspaces.items():
            device_registry.async_get_or_create(
                config_entry_id=self.config_entry.entry_id,
                identifiers={(DOMAIN, gs_id)},
                name=growspace.name,
                model=growspace.growspace_type.value
                if growspace.growspace_type
                else "Growspace",
                manufacturer="Growspace Manager",
                sw_version="0.3.3",
            )

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

    # =============================================================================
    # EVENT LOGBOOK MANAGEMENT
    # =============================================================================

    def add_event(self, growspace_id: str, event: GrowspaceEvent) -> None:
        """Fire a Growspace event to the HA Event Bus (Native Event Sourcing)."""
        event_data = asdict(event)
        # Ensure primitive types for JSON serialization if needed, though asdict does most.
        # Enforce event structure

        self.hass.bus.async_fire(EVENT_GROWSPACE_LOG_ENTRY, event_data)

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
        return self.data_repository.get_plant(plant_id)

    def _canonical_special(self, gs_id: str) -> tuple[str, str]:
        """Return the canonical ID and name for a special growspace.

        This also triggers a migration check to ensure any legacy aliases are handled.

        Args:
            gs_id: The growspace ID to look up.

        Returns:
            A tuple containing the canonical ID and canonical name.
        """

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
        self,
        growspace_id: str,
        name: str,
        rows: int = DEFAULT_ROWS,
        plants_per_row: int = DEFAULT_PLANTS_PER_ROW,
        growspace_type: GrowspaceType = GrowspaceType.FLOWER,
        update_data: bool = True,
    ) -> str:
        """Ensure a special growspace (e.g., 'dry', 'cure') exists.

        If the growspace does not exist, it will be created with the specified
        parameters. This method also handles migration from legacy aliases.

        Args:
            growspace_id: The canonical ID for the special growspace.
            name: The canonical name for the special growspace.
            rows: The number of rows for the grid (if created).
            plants_per_row: The number of plants per row (if created).
            growspace_type: The type of growspace.

        Returns:
            The canonical ID of the special growspace.
        """
        # Get canonical form
        canonical_id, _ = self._canonical_special(growspace_id)

        # Create or update the canonical growspace
        if canonical_id not in self.growspaces:
            self._create_special_growspace(
                canonical_id, name, rows, plants_per_row, growspace_type
            )
            # ✅ Enable notifications by default for new special growspace
            self._notifications_enabled[canonical_id] = True
            # Cache invalidation for new space
            self._invalidate_cache(canonical_id)
        else:
            self._update_special_growspace_name(canonical_id, name)
            # Ensure type is correct even if existing (for migration)
            start_type = self.growspaces[canonical_id].growspace_type
            if start_type != growspace_type:
                self.growspaces[canonical_id].growspace_type = growspace_type
            # Name or Type changed -> Invalidate
            self._invalidate_cache(canonical_id)

        if update_data:
            self.update_data_property()
        return canonical_id

    def _create_special_growspace(
        self,
        canonical_id: str,
        canonical_name: str,
        rows: int,
        plants_per_row: int,
        growspace_type: GrowspaceType,
    ) -> None:
        """Create a new special growspace with the given parameters."""
        self.growspaces[canonical_id] = Growspace(
            id=canonical_id,
            name=canonical_name,
            rows=rows,
            plants_per_row=plants_per_row,
            growspace_type=growspace_type,
        )
        _LOGGER.info(
            "Created canonical growspace: %s with name '%s'",
            canonical_id,
            canonical_name,
        )

    def _update_special_growspace_name(
        self, canonical_id: str, canonical_name: str
    ) -> None:
        """Update the name of an existing special growspace if it has changed."""
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
            PlantStage.MOTHER,
            "mother",
            rows=DEFAULT_ROWS,
            plants_per_row=DEFAULT_PLANTS_PER_ROW,
            growspace_type=GrowspaceType.MOTHER,
        )

    # =============================================================================
    # DATA UPDATE COORDINATOR OVERRIDE
    # =============================================================================

    @override
    async def _async_update_data(self) -> dict[str, Any]:
        """Refresh data, called periodically by the DataUpdateCoordinator.

        This method updates the central `self.data` property and triggers checks
        for air exchange recommendations and timed notifications.

        Returns:
            The updated data dictionary.
        """
        # Periodic refresh implies environment data might have changed (VPD, etc).
        # We must invalidate ALL caches to ensure calculations are fresh.
        self._invalidate_cache(None)

        self.update_data_property()
        await self.notification_manager.async_check_timed_notifications()
        await self.environment_analyzer.async_update_air_exchange_recommendations()

        return self.data

    async def async_commit(self) -> None:
        """Commit changes to storage and notify listeners."""
        # Ensure we always have fresh data when committing
        self._invalidate_cache()
        self.update_data_property()
        await self.storage_manager.async_save()
        self.async_set_updated_data(self.data)
        self.async_fire_growspace_updated()

        for gs_id in self.growspaces:
            if gs_id in self.irrigation_coordinators:
                self.config_entry.async_create_background_task(
                    self.hass,
                    self.irrigation_coordinators[gs_id].async_request_refresh(),
                    f"irrigation_refresh_{gs_id}",
                )

    def async_fire_growspace_updated(self) -> None:
        """Fire an event when the growspace configuration is updated."""
        self.hass.bus.async_fire(EVENT_GROWSPACE_UPDATED, {})

    async def async_save(self) -> None:
        """Save data to storage (Alias for async_commit)."""
        await self.async_commit()

    async def async_shutdown(self) -> None:
        """Perform shutdown tasks, ensuring data is persisted."""
        await self.storage_manager.async_force_save()

    async def async_load(self) -> None:
        """Load data from persistent storage and handle migrations."""
        await self.storage_manager.async_load()
        self._ensure_calculated_sensors()
        await self._ensure_default_growspaces()
        # Update Data Repository with loaded data
        self.data_repository.load_data(self.growspaces, self.plants)

    def migrate_plant_image_paths(self) -> int:
        """Migrate plant image paths from .jpg to .webp.

        This should be called after WebP migration to update stored plant data.

        Returns:
            Number of plant image paths updated.
        """
        updated_count = 0

        for plant_id, plant in self.plants.items():
            # Check if plant has phenotype data with image_path
            if not plant.phenotype:
                continue

            image_path = plant.phenotype.get("image_path")
            if not image_path or not isinstance(image_path, str):
                continue

            # Update .jpg to .webp
            if image_path.endswith(".jpg") or image_path.endswith(".jpeg"):
                new_path = image_path.replace(".jpg", ".webp").replace(".jpeg", ".webp")
                plant.phenotype["image_path"] = new_path
                updated_count += 1
                _LOGGER.debug(
                    "Migrated plant %s image path: %s -> %s",
                    plant_id,
                    image_path,
                    new_path,
                )

        return updated_count

    async def _ensure_default_growspaces(self) -> None:
        """Ensure that the default special growspaces (dry, cure, etc.) exist."""
        default_growspaces = [
            (
                CANONICAL_ID_DRY,
                "dry",
                DEFAULT_ROWS,
                DEFAULT_PLANTS_PER_ROW,
                GrowspaceType.DRY,
            ),
            (
                CANONICAL_ID_CURE,
                "cure",
                DEFAULT_ROWS,
                DEFAULT_PLANTS_PER_ROW,
                GrowspaceType.CURE,
            ),
            (
                CANONICAL_ID_MOTHER,
                "mother",
                DEFAULT_ROWS,
                DEFAULT_PLANTS_PER_ROW,
                GrowspaceType.MOTHER,
            ),
            (CANONICAL_ID_CLONE, "clone", 5, 5, GrowspaceType.CLONE),
            (CANONICAL_ID_VEG, "veg", 5, 5, GrowspaceType.VEG),
        ]

        for (
            growspace_id,
            name,
            rows,
            plants_per_row,
            gs_type,
        ) in default_growspaces:
            # Use the coordinator's method to ensure special growspaces
            self.ensure_special_growspace(
                growspace_id,
                name,
                rows,
                plants_per_row,
                growspace_type=gs_type,
                update_data=False,
            )

        self.update_data_property()
        await self.async_save()

    def _ensure_calculated_sensors(self) -> None:
        """Ensure default calculated sensors are configured in growspace config."""
        for growspace in self.growspaces.values():
            env_config = growspace.environment_config
            if not env_config:
                continue

            temp_sensor = getattr(env_config, CONF_TEMP_SENSOR, None)
            humidity_sensor = getattr(env_config, CONF_HUMIDITY_SENSOR, None)
            vpd_sensor = getattr(env_config, CONF_VPD_SENSOR, None)

            if temp_sensor and humidity_sensor and not vpd_sensor:
                calc_name = f"{growspace.name} Calculated VPD"
                expected_id = f"sensor.{slugify(calc_name)}"

                # Patch config
                setattr(env_config, CONF_VPD_SENSOR, expected_id)
                _LOGGER.info("Configured default calculated VPD for %s", growspace.name)
                # Config changed
                self._invalidate_cache(growspace.id)

    def update_data_property(self) -> None:
        """Update the central `self.data` property to reflect the current coordinator state."""
        # Preserve existing recommendations if valid
        recs = {}
        if self.data and isinstance(self.data, dict):
            recs = self.data.get("air_exchange_recommendations", {})

        # Optimized: Serialize growspaces using cache
        serialized_growspaces = {}

        # 1. Pre-calculate plant distribution to avoid O(N*M) lookups
        # Only do this if we actually need to serialize (cache miss)
        # However, to know if we have a cache miss, we iterate.
        # It's cleaner to build the map once if ANY cache is missing.
        # But `_get_serialized_growspace` checks the cache internally.
        # So we can just build the map. O(Plants) is cheap compared to repeated scans.

        plants_by_growspace: dict[str, list[Plant]] = {}
        # Only build this index if we have work to do
        # Check if all caches are valid? No, too complex.
        # Just build it. It's O(N).
        for plant in self.plants.values():
            if plant.growspace_id not in plants_by_growspace:
                plants_by_growspace[plant.growspace_id] = []
            plants_by_growspace[plant.growspace_id].append(plant)

        for growspace_id in self.growspaces:
            # Pass the pre-filtered list to the serializer
            # Use empty list if no plants found for this growspace
            plants = plants_by_growspace.get(growspace_id, [])
            serialized_growspaces[growspace_id] = self._get_serialized_growspace(
                growspace_id, preloaded_plants=plants
            )

        self.data = {
            "growspaces": self.growspaces,
            "plants": self.plants,
            "notifications_sent": self._notifications_sent,
            "notifications_enabled": self._notifications_enabled,
            "_version": dt_util.now().isoformat(),
            "serialized_growspaces": serialized_growspaces,
            "air_exchange_recommendations": recs,
        }

    async def async_update_irrigation_config(
        self, growspace_id: str, user_input: dict[str, Any]
    ) -> None:
        """Update irrigation configuration for a growspace.

        Args:
            growspace_id: The ID of the growspace to update.
            user_input: The user input dictionary containing new settings.
        """
        growspace = self.growspaces.get(growspace_id)
        if not growspace:
            raise GrowspaceNotFoundError(f"Growspace {growspace_id} not found")

        # CRITICAL FIX: Only update the R/W fields (pump entities and durations)
        # Filter out the read-only fields that were passed for display purposes
        updated_settings = {
            k: v
            for k, v in user_input.items()
            if k
            not in [
                ATTR_IRRIGATION_TIMES,
                ATTR_DRAIN_TIMES,
                "growspace_id_read_only",
            ]
        }

        # Explicitly handle pump entities to allow clearing them (setting to None)
        if "irrigation_pump_entity" not in updated_settings:
            updated_settings["irrigation_pump_entity"] = None
        if "drain_pump_entity" not in updated_settings:
            updated_settings["drain_pump_entity"] = None

        # Update the config in the growspace object
        for k, v in updated_settings.items():
            if hasattr(growspace.irrigation_config, k):
                setattr(growspace.irrigation_config, k, v)

        # Invalidate cache for this growspace
        self._invalidate_cache(growspace_id)

        # Save via coordinator
        await self.async_save()

        # Notify listeners
        self.async_set_updated_data(self.data)

    # =============================================================================
    # GROWSPACE MANAGEMENT METHODS
    # =============================================================================

    async def async_add_growspace(
        self,
        name: str,
        rows: int = DEFAULT_ROWS,
        plants_per_row: int = DEFAULT_PLANTS_PER_ROW,
        notification_target: str | None = None,
        device_id: str | None = None,
        growspace_type: GrowspaceType = GrowspaceType.FLOWER,
    ) -> Growspace:
        """Add a new growspace to the coordinator.

        Args:
            name: The display name for the new growspace.
            rows: The number of rows in the grid.
            plants_per_row: The number of plants per row.
            notification_target: The notification service to use (optional).
            device_id: The device ID to associate with the growspace (optional).
            growspace_type: The type of growspace.
        """
        async with self._lock:  # Added
            # Normalize notification target
            if not notification_target or notification_target in ("None", "none", ""):
                _LOGGER.debug(
                    "No notification target provided for growspace '%s'", name
                )
                notification_target = None

            growspace_id = str(uuid.uuid4())
            growspace = Growspace(
                id=growspace_id,
                name=name.strip(),
                rows=rows,
                plants_per_row=plants_per_row,
                notification_target=notification_target,
                device_id=device_id,
                growspace_type=growspace_type,
            )
            self.growspaces[growspace_id] = growspace

            # ✅ Enable notifications by default for new growspace
            self._notifications_enabled[growspace_id] = True

            # Cache: no need to invalidate other caches, just add this one implicitly next time

            await self.async_commit()

            async_fire_growspace_event(self.hass, EVENT_GROWSPACE_ADDED, growspace)
            return growspace

    async def async_remove_growspace(self, growspace_id: str) -> None:
        """Remove a growspace and all plants contained within it.

        Args:
            growspace_id: The ID of the growspace to remove.
        """
        async with self._lock:  # Added
            self.validator.validate_growspace_exists(growspace_id)

            # Remove all plants in this growspace
            plants_to_remove = [
                plant_id
                for plant_id, plant in self.plants.items()
                if plant.growspace_id == growspace_id
            ]

            for plant_id in plants_to_remove:
                self.plants.pop(plant_id, None)
                self._notifications_sent.pop(
                    plant_id, None
                )  # ✅ Use _notifications_sent

            growspace = self.growspaces[growspace_id]
            growspace_name = growspace.name
            self.growspaces.pop(growspace_id, None)

            # ✅ Remove notification state
            self._notifications_enabled.pop(growspace_id, None)

            # Cache: Remove from cache
            # Handled by decorator

            # ✅ Remove device from registry
            try:
                dev_reg = dr.async_get(self.hass)
                device = dev_reg.async_get_device(identifiers={(DOMAIN, growspace_id)})
                if device:
                    dev_reg.async_remove_device(device.id)
                    _LOGGER.debug("Removed device for growspace %s", growspace_id)
            except Exception:
                _LOGGER.exception(
                    "Error removing device for growspace %s", growspace_id
                )

            await self.async_commit()

            _LOGGER.info(
                "Removed growspace %s (%s) and %d plants",
                growspace_id,
                growspace_name,
                len(plants_to_remove),
            )
            async_fire_growspace_event(self.hass, EVENT_GROWSPACE_REMOVED, growspace)

    def _update_growspace_structure(
        self, growspace: Growspace, kwargs: dict[str, Any], changes: list[str]
    ) -> bool:
        """Update growspace structure (dimensions)."""
        updated = False
        if "rows" in kwargs:
            rows = int(kwargs["rows"])
            if rows != growspace.rows:
                changes.append(f"rows: {growspace.rows} -> {rows}")
                growspace.rows = rows
                updated = True

        if "plants_per_row" in kwargs:
            ppr = int(kwargs["plants_per_row"])
            if ppr != growspace.plants_per_row:
                changes.append(f"plants_per_row: {growspace.plants_per_row} -> {ppr}")
                growspace.plants_per_row = ppr
                updated = True
        return updated

    def _update_growspace_config(
        self, growspace: Growspace, kwargs: dict[str, Any], changes: list[str]
    ) -> bool:
        """Update growspace configuration."""
        updated = False
        if "name" in kwargs:
            name = kwargs["name"]
            if name != growspace.name:
                changes.append(f"name: {growspace.name} -> {name}")
                growspace.name = name
                updated = True

        if "notification_target" in kwargs:
            nt = kwargs["notification_target"]
            nt = nt.strip() if nt else None
            current = growspace.notification_target
            if nt != current:
                changes.append(f"notification_target: {current} -> {nt}")
                growspace.notification_target = nt
                updated = True

        if "environment_config" in kwargs:
            growspace.environment_config = kwargs["environment_config"]
            changes.append("environment_config updated")
            updated = True

        if "irrigation_config" in kwargs:
            growspace.irrigation_config = kwargs["irrigation_config"]
            changes.append("irrigation_config updated")
            updated = True

        return updated

    async def async_update_growspace(
        self, growspace_id: str, **kwargs: dict[str, Any]
    ) -> None:
        """Update a growspace."""
        async with self._lock:
            if growspace_id not in self.growspaces:
                raise GrowspaceNotFoundError(f"Growspace {growspace_id} not found")

            growspace = self.growspaces[growspace_id]
            changes: list[str] = []

            # Update structure
            struct_updated = self._update_growspace_structure(
                growspace, kwargs, changes
            )
            # Update config
            config_updated = self._update_growspace_config(growspace, kwargs, changes)

            updated = struct_updated or config_updated

            if updated:
                _LOGGER.info(
                    "Updated growspace %s (%s): %s",
                    growspace_id,
                    growspace.name,
                    ", ".join(changes),
                )

                # Cache invalidation handled by decorator

                # Validate plants if grid changed
                if "rows" in kwargs or "plants_per_row" in kwargs:
                    await self._validate_plants_after_growspace_resize(
                        growspace_id,
                        growspace.rows,
                        growspace.plants_per_row,
                    )

                await self.async_commit()
                async_fire_growspace_event(
                    self.hass, EVENT_GROWSPACE_UPDATED, growspace
                )
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

        # Notification settings generally don't change visual grid serialization, but we can invalidate if needed
        # self._invalidate_cache(growspace_id)

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
        """Add a new plant to the coordinator via lifecycle manager."""

        plant = await self.lifecycle_manager.async_add_plant(
            growspace_id=growspace_id,
            strain=strain,
            plant_id=plant_id,
            phenotype=phenotype,
            row=row,
            col=col,
            stage=stage,
            plant_type=type,
            device_id=device_id,
            seedling_start=seedling_start,
            mother_start=mother_start,
            clone_start=clone_start,
            veg_start=veg_start,
            flower_start=flower_start,
            dry_start=dry_start,
            cure_start=cure_start,
            source_mother=source_mother,
        )

        self._invalidate_cache(growspace_id)

        self._fire_event(
            "plant_added", {"plant": self.serializer.serialize_plant(plant)}
        )
        async_fire_plant_event(self.hass, EVENT_PLANT_ADDED, plant)
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
        target_growspace_id: str | None = None,
        target_growspace_name: str | None = None,
        transition_date: date | None = None,
    ) -> list[Plant]:
        """Create multiple clones from a mother plant and place them in the clone growspace.

        Args:
            mother_plant_id: The ID of the source mother plant.
            num_clones: The number of clones to create.
            target_growspace_id: Ignored, defaults to 'clone'.
            target_growspace_name: Ignored.
            transition_date: The date the clones were taken (defaults to today).

        Returns:
            A list of the newly created clone Plant objects.
        """
        self.validator.validate_plant_exists(mother_plant_id)

        mother = self.plants[mother_plant_id]
        clone_gs_id = self.ensure_special_growspace(PlantStage.CLONE, "clone", 5, 5)
        new_plants: list[Plant] = []

        # Ensure transition_date is a date object
        if transition_date is None:
            transition_date = date.today()

        # Pre-invalidate clone growspace cache
        self._invalidate_cache(clone_gs_id)

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
                clone_start=transition_date,
            )

            if new_plant := self.plants.get(clone_id):
                new_plants.append(new_plant)
            else:
                _LOGGER.error("Failed to retrieve created clone %s", clone_id)

        # Fire clones taken event
        if new_plants:
            async_fire_clones_taken_event(
                self.hass, mother, len(new_plants), clone_gs_id
            )

        return new_plants

    async def async_promote_clone(
        self,
        clone_id: str,
        target_growspace_id: str = "veg",
        transition_date: date | None = None,
    ) -> None:
        """Promote a clone to the vegetative stage, moving it to a new growspace.

        This updates the EXISTING plant record, preserving its ID and history.

        Args:
            clone_id: The ID of the clone to promote.
            target_growspace_id: The ID of the target growspace (defaults to 'veg').
            transition_date: The date of the transition (defaults to today).
        """
        self.validator.validate_plant_exists(clone_id)
        clone = self.plants[clone_id]
        source_gs_id = clone.growspace_id

        if clone.stage != PlantStage.CLONE:
            raise ValidationChangeError(
                f"Plant {clone_id} is not in clone stage (current: {clone.stage})"
            )

        # Resolve target growspace ID (handle aliases like 'veg')
        if target_growspace_id == "veg":
            target_gs_id = self.ensure_special_growspace(PlantStage.VEG, "veg", 5, 5)
        else:
            # Ensure custom growspace exists
            if target_growspace_id not in self.growspaces:
                raise GrowspaceNotFoundError(
                    f"Target growspace {target_growspace_id} does not exist"
                )
            target_gs_id = target_growspace_id

        # Find position
        row, col = self.validator.find_first_available_position(target_gs_id)

        # Default transition date
        if transition_date is None:
            transition_date = date.today()

        # Invalidate both caches
        self._invalidate_cache(source_gs_id)
        self._invalidate_cache(target_gs_id)

        # Update the existing plant
        # We explicitly set stage to VEG and update veg_start.
        await self.async_update_plant(
            clone_id,
            growspace_id=target_gs_id,
            row=row,
            col=col,
            stage=PlantStage.VEG,
            veg_start=transition_date,
        )

    async def async_update_plant(self, plant_id: str, **updates) -> Plant:
        """Update the attributes of an existing plant."""
        # Invalidate current growspace (logic for move)
        if plant := self.plants.get(plant_id):
            # Invalidate cache for the current growspace to reflect updates (e.g. stage change)
            self._invalidate_cache(plant.growspace_id)

            if (
                "growspace_id" in updates
                and updates["growspace_id"] != plant.growspace_id
            ):
                self._invalidate_cache(updates["growspace_id"])

        plant = await self.lifecycle_manager.async_update_plant(plant_id, **updates)

        self._fire_event(
            "plant_updated",
            {"plant": self.serializer.serialize_plant(plant)},
        )
        async_fire_plant_event(self.hass, EVENT_PLANT_UPDATED, plant, updates)
        return plant

    def _handle_position_update(
        self,
        plant_id: str,
        plant: Plant,
        force_position: bool,
        kwargs: dict[str, Any],
    ) -> None:
        """Validate and handle updates to a plant's position.

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
        """Move a plant to a new position via lifecycle manager."""
        if plant := self.plants.get(plant_id):
            self._invalidate_cache(plant.growspace_id)

        await self.lifecycle_manager.async_move_plant(plant_id, new_row, new_col)

        # Fetch updated plant to fire event
        if plant := self.plants.get(plant_id):
            async_fire_plant_event(
                self.hass,
                EVENT_PLANT_MOVED,
                plant,
                {"new_row": new_row, "new_col": new_col},
            )

    async def async_switch_plants(self, plant1_id: str, plant2_id: str) -> None:
        """Switch the positions of two plants via lifecycle manager."""
        p1 = self.plants.get(plant1_id)
        p2 = self.plants.get(plant2_id)

        if p1:
            self._invalidate_cache(p1.growspace_id)
        if p2:
            self._invalidate_cache(p2.growspace_id)

        await self.lifecycle_manager.async_switch_plants(plant1_id, plant2_id)

        # Fire events for both plants to update frontend
        if p1 := self.plants.get(plant1_id):
            self._fire_event(
                "plant_updated",
                {"plant": self.serializer.serialize_plant(p1)},
            )
            async_fire_plant_event(self.hass, EVENT_PLANT_SWITCHED, p1)

        if p2 := self.plants.get(plant2_id):
            self._fire_event(
                "plant_updated",
                {"plant": self.serializer.serialize_plant(p2)},
            )
            async_fire_plant_event(self.hass, EVENT_PLANT_SWITCHED, p2)

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
        # Cache invalidation handled by decorator via plant_id lookup

        await self.lifecycle_manager.transition_plant_stage(
            plant_id, new_stage, transition_date
        )
        if plant := self.plants.get(plant_id):
            async_fire_plant_event(
                self.hass,
                EVENT_PLANT_TRANSITIONED,
                plant,
                {"new_stage": str(new_stage)},
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
        # Use cache via helper
        return self._get_serialized_growspace(growspace_id)

    async def async_start_flowering(self, plant_id: str) -> Plant:
        """Transition a plant to the 'flower' stage, starting today."""
        await self.async_transition_plant_stage(
            plant_id, PlantStage.FLOWER, date.today()
        )
        return self.plants[plant_id]

    async def async_start_drying(self, plant_id: str) -> Plant:
        """Transition a plant to the 'drying' stage, starting today."""
        await self.async_transition_plant_stage(plant_id, PlantStage.DRY, date.today())
        return self.plants[plant_id]

    async def async_start_curing(self, plant_id: str) -> Plant:
        """Transition a plant to the 'curing' stage, starting today."""
        await self.async_transition_plant_stage(plant_id, PlantStage.CURE, date.today())
        return self.plants[plant_id]

    # =============================================================================
    # MANUAL WATERING METHODS
    # =============================================================================

    async def async_water_plant(
        self,
        plant_id: str,
        amount: float,
        nutrients: dict[str, float] | None = None,
        preset_id: str | None = None,
    ) -> Plant:
        """Record a watering event for a single plant.

        Args:
            plant_id: The ID of the plant to water.
            amount: The amount of water in liters.
            nutrients: Optional dict of nutrient name to concentration (ml/L).
            preset_id: Optional ID of a nutrient preset to apply.

        Returns:
            The updated Plant object.
        """
        plant = await self._water_plant_internal(
            plant_id, amount, nutrients, preset_id, invalidate_cache=True
        )
        await self.async_save()
        return plant

    async def _water_plant_internal(
        self,
        plant_id: str,
        amount: float,
        nutrients: dict[str, float] | None = None,
        preset_id: str | None = None,
        invalidate_cache: bool = True,
    ) -> Plant:
        """Internal watering logic with optional cache invalidation."""
        self.validator.validate_plant_exists(plant_id)
        plant = self.plants[plant_id]

        final_nutrients: dict[str, float] = {}
        preset_name: str | None = None

        # 1. Apply preset nutrients if provided
        if preset_id:
            if preset_id not in self.nutrient_presets:
                raise KeyError(f"Nutrient preset '{preset_id}' not found")
            preset = self.nutrient_presets[preset_id]
            preset_name = preset.name
            final_nutrients.update(preset.get_nutrient_map())

        # 2. Merge with manual nutrients (manual overrides preset)
        if nutrients:
            final_nutrients.update(nutrients)

        # Update plant's last_watered timestamp
        now_iso = dt_util.now().isoformat()
        plant.last_watered = now_iso

        # Invalidate cache for the growspace if requested
        if invalidate_cache:
            self._invalidate_cache(plant.growspace_id)

        # Build reasons for the event
        reasons = []

        # Add Plant ID for filtering (prefixed for easy parsing)
        reasons.append(f"plant_id:{plant_id}")

        # Add Plant display info
        plant_info = f"Plant: {plant.strain}"
        if plant.phenotype:
            plant_info += f" ({plant.phenotype})"
        reasons.append(plant_info)

        reasons.append(f"Watered with {amount}L")
        if preset_name:
            reasons.append(f"Preset: {preset_name}")

        if final_nutrients:
            # Calculate total ml for each nutrient and format strings
            nutrient_details = []
            for name, conc in final_nutrients.items():
                total_ml = round(amount * conc, 2)
                nutrient_details.append(f"{name}: {conc}ml/L (Total: {total_ml}ml)")

            reasons.append(f"Nutrients: {', '.join(nutrient_details)}")

        # Create a GrowspaceEvent for the logbook
        event = GrowspaceEvent(
            sensor_type="irrigation",
            growspace_id=plant.growspace_id,
            start_time=now_iso,
            end_time=now_iso,
            duration_sec=0,
            severity=0.0,
            category="environmental",
            reasons=reasons,
        )
        self.add_event(plant.growspace_id, event)

        _LOGGER.info(
            "Watered plant %s (%s) with %sL%s%s",
            plant_id,
            plant.strain,
            amount,
            f" using preset '{preset_name}'" if preset_name else "",
            f" + manual nutrients: {nutrients}" if nutrients else "",
        )

        return plant

    async def async_water_growspace(
        self,
        growspace_id: str,
        amount_per_plant: float,
        nutrients: dict[str, float] | None = None,
        preset_id: str | None = None,
    ) -> int:
        """Record a watering event for all plants in a growspace.

        Args:
            growspace_id: The ID of the growspace to water.
            amount_per_plant: The amount of water per plant in liters.
            nutrients: Optional dict of nutrient name to concentration (ml/L).
            preset_id: Optional ID of a nutrient preset to apply.

        Returns:
            The number of plants watered.
        """
        self.validator.validate_growspace_exists(growspace_id)
        plants = self.get_growspace_plants(growspace_id)

        for plant in plants:
            await self._water_plant_internal(
                plant.plant_id,
                amount_per_plant,
                nutrients,
                preset_id,
                invalidate_cache=False,
            )

        # Bulk invalidation
        self._invalidate_cache(growspace_id)

        _LOGGER.info(
            "Watered %d plants in growspace %s with %sL each%s",
            len(plants),
            growspace_id,
            amount_per_plant,
            f" using preset '{preset_id}'" if preset_id else "",
        )

        await self.async_save()

        return len(plants)

    # =============================================================================
    # NUTRIENT PRESET METHODS
    # =============================================================================

    async def async_save_nutrient_preset(
        self,
        name: str,
        nutrients: list[dict[str, Any]],
        stage: str | None = None,
        min_days_in_stage: int | None = None,
        preset_id: str | None = None,
    ) -> NutrientPreset:
        """Create or update a nutrient preset.

        Args:
            name: Human-readable name for the preset.
            nutrients: List of nutrient items with 'name' and 'dose_ml_l'.
            stage: Optional plant stage this preset applies to.
            min_days_in_stage: Optional minimum days in stage for this preset.
            preset_id: Optional ID of the preset to update. If not provided, a new one will be created.

        Returns:
            The saved NutrientPreset object.
        """
        if preset_id and preset_id in self.nutrient_presets:
            preset = self.nutrient_presets[preset_id]
            preset.name = name
            preset.nutrients = nutrients  # type: ignore[arg-type]
            preset.stage = stage
            preset.min_days_in_stage = min_days_in_stage
            # ID and created_at remain unchanged
        else:
            # Create new
            pid = preset_id or str(uuid.uuid4())
            preset = NutrientPreset(
                id=pid,
                name=name,
                items=nutrients,  # type: ignore[arg-type]
                stage=stage,
                min_days_in_stage=min_days_in_stage,
                created_at=dt_util.now().isoformat(),
            )
            self.nutrient_presets[pid] = preset
        await self.async_save()

        _LOGGER.info(
            "Saved nutrient preset '%s' with %d nutrients (id=%s)",
            name,
            len(nutrients),
            preset_id,
        )

        # Invalidate cache for all growspaces as presets are global
        self._serialized_cache.clear()

        return preset

    async def async_remove_nutrient_preset(self, preset_id: str) -> None:
        """Remove a nutrient preset.

        Args:
            preset_id: The ID of the preset to remove.

        Raises:
            KeyError: If the preset does not exist.
        """
        if preset_id not in self.nutrient_presets:
            raise KeyError(f"Nutrient preset '{preset_id}' not found")

        preset_name = self.nutrient_presets[preset_id].name
        del self.nutrient_presets[preset_id]
        await self.async_save()

        # Invalidate cache for all growspaces as presets are global
        self._serialized_cache.clear()

        _LOGGER.info("Removed nutrient preset '%s' (id=%s)", preset_name, preset_id)

    def get_applicable_presets(self, plant_id: str) -> list[NutrientPreset]:
        """Get all presets applicable to a plant based on its current stage and days.

        Args:
            plant_id: The ID of the plant to check.

        Returns:
            List of applicable NutrientPreset objects.
        """
        self.validator.validate_plant_exists(plant_id)
        plant = self.plants[plant_id]

        applicable: list[NutrientPreset] = []

        for preset in self.nutrient_presets.values():
            # If preset has no stage filter, it applies to all stages
            if preset.stage is not None:
                # Check if plant's current stage matches preset stage
                if str(plant.stage).lower() != str(preset.stage).lower():
                    continue

            # If preset has min_days_in_stage, check if plant meets it
            if preset.min_days_in_stage is not None:
                current_stage = str(plant.stage).lower()
                days_in_stage = plant.get_days_in_stage(current_stage)
                if days_in_stage < preset.min_days_in_stage:
                    continue

            applicable.append(preset)

        return applicable

    def _resolve_preset_nutrients(self, preset_id: str) -> dict[str, float]:
        """Resolve a preset ID to its nutrient map.

        Args:
            preset_id: The ID of the preset to resolve.

        Returns:
            Dict mapping nutrient name to concentration (ml/L).

        Raises:
            KeyError: If the preset does not exist.
        """
        if preset_id not in self.nutrient_presets:
            raise KeyError(f"Nutrient preset '{preset_id}' not found")

        return self.nutrient_presets[preset_id].get_nutrient_map()

    # =============================================================================
    # IPM METHODS
    # =============================================================================

    async def async_log_training_event(
        self,
        growspace_id: str | None,
        technique: str,
        notes: str | None = None,
        plant_ids: list[str] | None = None,
    ) -> None:
        """Log a training event for specific plants or an entire growspace."""
        _LOGGER.debug(
            "async_log_training_event called with gid=%s, pids=%s, technique=%s",
            growspace_id,
            plant_ids,
            technique,
        )

        target_plants = self._get_target_plants(growspace_id, plant_ids)
        now = dt_util.now().isoformat()

        # Update plants
        for plant in target_plants:
            plant.last_training_technique = technique
            plant.last_trained = now

        # Group by growspace for event logging
        affected_gids = {p.growspace_id for p in target_plants}
        if not target_plants and growspace_id:
            affected_gids = {growspace_id}

        for gid in affected_gids:
            affected_in_gid = [p for p in target_plants if p.growspace_id == gid]
            reasons = self._create_training_reasons(
                gid, technique, notes, plant_ids, affected_in_gid
            )

            event = GrowspaceEvent(
                sensor_type=technique,
                growspace_id=gid,
                start_time=now,
                end_time=now,
                duration_sec=0,
                severity=0.5,
                category=CATEGORY_TRAINING,
                reasons=reasons,
            )
            self.add_event(gid, event)

            # Invalidate cache before saving
            self._invalidate_cache(gid)

        await self.async_save()

    def _get_target_plants(
        self, growspace_id: str | None, plant_ids: list[str] | None
    ) -> list[Plant]:
        """Resolve target plants from IDs or growspace ID."""
        if plant_ids:
            return [self.plants[pid] for pid in plant_ids if pid in self.plants]
        if growspace_id:
            return self.get_growspace_plants(growspace_id)
        raise ValueError("Either growspace_id or plant_ids must be provided.")

    def _create_training_reasons(
        self, gid, technique, notes, plant_ids, affected_in_gid
    ) -> list[str]:
        """Generate reason strings for training events."""
        reasons = [f"plant_id:{p.plant_id}" for p in affected_in_gid]
        reasons.append(f"Technique: {technique.replace('_', ' ').title()}")

        if notes:
            reasons.append(f"Notes: {notes}")

        if plant_ids and len(plant_ids) < len(self.get_growspace_plants(gid)):
            affected_names = [p.strain for p in affected_in_gid]
            if affected_names:
                reasons.append(f"Plants: {', '.join(affected_names)}")
        return reasons

    async def async_save_ipm_preset(
        self,
        name: str,
        type: str,
        items: list[dict[str, Any]],
        stage: str | None = None,
        min_days_in_stage: int | None = None,
        preset_id: str | None = None,
    ) -> IPMPreset:
        """Create or update an IPM preset.

        Args:
            name: Name of the preset.
            type: Type of application (foliar, drench, etc.).
            items: List of IPM items with 'name', 'dose_amount', 'dose_unit'.
            stage: Optional target plant stage.
            min_days_in_stage: Optional minimum days in stage.
            preset_id: Optional existing preset ID to update.

        Returns:
            The saved IPMPreset object.
        """
        if preset_id and preset_id in self.ipm_presets:
            preset = self.ipm_presets[preset_id]
            preset.name = name
            preset.type = type
            preset.items = items  # type: ignore[arg-type]
            preset.stage = stage
            preset.min_days_in_stage = min_days_in_stage
        else:
            pid = preset_id or str(uuid.uuid4())
            preset = IPMPreset(
                id=pid,
                name=name,
                type=type,
                items=items,  # type: ignore[arg-type]
                stage=stage,
                min_days_in_stage=min_days_in_stage,
                created_at=dt_util.now().isoformat(),
            )
            self.ipm_presets[pid] = preset

        await self.async_save()
        self._serialized_cache.clear()

        _LOGGER.info("Saved IPM preset '%s' (%s) with %d items", name, type, len(items))
        return preset

    async def async_remove_ipm_preset(self, preset_id: str) -> None:
        """Remove an IPM preset.

        Args:
            preset_id: The ID of the preset to remove.

        Raises:
            KeyError: If the preset does not exist.
        """
        if preset_id not in self.ipm_presets:
            raise KeyError(f"IPM preset '{preset_id}' not found")

        preset_name = self.ipm_presets[preset_id].name
        del self.ipm_presets[preset_id]
        await self.async_save()
        self._serialized_cache.clear()
        _LOGGER.info("Removed IPM preset '%s' (id=%s)", preset_name, preset_id)

    async def async_apply_ipm(
        self,
        preset_id: str,
        growspace_id: str | None = None,
        plant_ids: list[str] | None = None,
        notes: str | None = None,
    ) -> list[str]:
        """Log an IPM application event.

        Args:
            preset_id: ID of the IPM preset applied.
            growspace_id: ID of the growspace (if applying to whole room).
            plant_ids: List of specific plant IDs (if applying to specific plants).
            notes: Optional user notes.

        Returns:
            List of affected entity IDs (plants or growspace sensors).

        Raises:
            ValueError: If neither growspace_id nor plant_ids are provided.
            KeyError: If preset_id is not found.
        """
        if preset_id not in self.ipm_presets:
            raise KeyError(f"IPM preset '{preset_id}' not found")

        preset = self.ipm_presets[preset_id]
        now = dt_util.now().isoformat()
        target_plants = self._get_target_plants(growspace_id, plant_ids)

        # Update plant state
        for plant in target_plants:
            plant.last_ipm = now
            plant.last_ipm_type = preset.type
            # Also update updated_at?
            # plant.updated_at = now # Optional but good practice if tracked.
            # However, looking at Plant model, updated_at is present.
            # I will just set IPM fields for now to match specific requirements.

            # Re-save plant to storage happens via async_save called later.

        # Group by growspace for event logging
        affected_gids = {p.growspace_id for p in target_plants}
        if growspace_id:
            affected_gids.add(growspace_id)

        for gid in affected_gids:
            affected_in_gid = [p for p in target_plants if p.growspace_id == gid]
            reasons = self._create_ipm_reasons(
                gid, preset, notes, plant_ids, affected_in_gid
            )

            event = GrowspaceEvent(
                sensor_type=f"ipm_{preset.type}",
                growspace_id=gid,
                start_time=now,
                end_time=now,
                duration_sec=0,
                severity=0.5,
                category=CATEGORY_IPM,
                reasons=reasons,
            )
            self.add_event(gid, event)

        # Invalidate cache for affected growspaces
        for gid in affected_gids:
            self._invalidate_cache(gid)

        await self.async_save()

        return [p.plant_id for p in target_plants]

    def _create_ipm_reasons(
        self, gid, preset, notes, plant_ids, affected_in_gid
    ) -> list[str]:
        """Generate reason strings for IPM events."""
        recipe_str = ", ".join(
            [f"{i['name']} ({i['dose_amount']}{i['dose_unit']})" for i in preset.items]
        )
        reasons = [
            f"IPM Treatment: {preset.name}",
            f"Type: {preset.type}",
            f"Recipe: {recipe_str}",
        ]
        reasons.extend([f"plant_id:{p.plant_id}" for p in affected_in_gid])

        if plant_ids and len(plant_ids) < len(self.get_growspace_plants(gid)):
            affected_names = [p.strain for p in affected_in_gid]
            if affected_names:
                reasons.append(f"Plants: {', '.join(affected_names)}")

        if notes:
            reasons.append(f"Notes: {notes}")
        return reasons

    async def async_harvest(self, plant_id: str) -> Plant:
        """Mark a plant as harvested, transitioning it to the 'dry' stage today."""
        return await self.async_start_drying(plant_id)

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

        # Invalidate source
        self._invalidate_cache(plant.growspace_id)
        # Invalidate target if known (and different)
        if target_growspace_id:
            self._invalidate_cache(target_growspace_id)

        moved = await self.lifecycle_manager.handle_harvest_logic(
            plant_id, plant, target_growspace_id, target_growspace_name, transition_date
        )

        # If moved and target was dynamic, we rely on full refresh or cache might be stale if logic picked a new growspace
        # But handle_harvest_logic returns boolean 'moved'.
        # Safest is to rely on periodic refresh or specific invalidation if we knew logic.
        # But logic is in lifecycle manager.
        # Since harvest is infrequent, we can optionally clear all caches to be safe, or just stick to source/target known.
        if moved:
            # Invalidate common harvest targets just in case
            self._invalidate_cache("dry")
            self._invalidate_cache("cure")

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
        async_fire_plant_event(self.hass, EVENT_PLANT_HARVESTED, plant)

    async def async_remove_plant(self, plant_id: str) -> bool:
        """Remove a plant via lifecycle manager."""
        # Cache plant data before removal so we can fire the event
        plant = self.plants.get(plant_id)
        if not plant:
            return False

        self._invalidate_cache(plant.growspace_id)

        removed = await self.lifecycle_manager.async_remove_plant(plant_id)
        if removed:
            self._fire_event(
                "plant_removed",
                {"plant_id": plant.plant_id, "growspace_id": plant.growspace_id},
            )
            # Fire event with cached plant data
            async_fire_plant_event(self.hass, EVENT_PLANT_REMOVED, plant)
        return removed

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
        return self.data_repository.get_growspace_plants(growspace_id)

    def get_growspace_grid(self, growspace_id: str) -> list[list[str | None]]:
        """Generate a 2D grid representation of a growspace's plant layout.

        Args:
            growspace_id: The ID of the growspace.

        Returns:
            A list of lists representing the grid, with plant IDs or None.
        """
        return self.data_repository.get_growspace_grid(growspace_id)

    def _guess_overview_entity_id(self, growspace_id: str) -> str:
        """Make a best-effort guess of the overview sensor entity ID for a growspace.

        This is used for linking entities when the exact ID is not stored.

        Args:
            growspace_id: The ID of the growspace.

        Returns:
            The guessed entity ID string.
        """
        # Try to look up via Entity Registry using consistent unique_id
        unique_id = generate_growspace_overview_unique_id(growspace_id)
        registry = er.async_get(self.hass)
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
        if entity_id:
            return entity_id

        # Fallback: Handle special cases logic data-driven
        for special_def in SPECIAL_GROWSPACES.values():
            canonical_id = special_def["canonical_id"]
            if growspace_id == canonical_id or growspace_id in special_def.get(
                "aliases", []
            ):
                canonical_uid = generate_growspace_overview_unique_id(canonical_id)
                eid = registry.async_get_entity_id("sensor", DOMAIN, canonical_uid)
                if eid:
                    return eid
                return f"sensor.{canonical_id}"

        # Standard Fallback
        # Try to guess based on name if available
        growspace = self.growspaces.get(growspace_id)
        name = getattr(growspace, "name", growspace_id) if growspace else growspace_id

        slug = slugify(str(name).replace(" ", "_"))
        # If it wasn't a special case, the old logic returned sensor.{slug}
        # But wait, looking at the test expectation: "sensor.my_growspace"
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

    def _fire_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Fire a growspace manager event."""
        payload = {"event_type": event_type, "data": data}
        self.hass.bus.async_fire("growspace_manager_updated", payload)
