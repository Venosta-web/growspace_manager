"""Data update coordinator for the Growspace Manager integration."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import slugify

from .cache import CacheManager
from .const import (
    ATTR_DRAIN_TIMES,
    ATTR_IRRIGATION_TIMES,
    COORDINATOR_UPDATE_INTERVAL_MINUTES,
    DOMAIN,
    SPECIAL_GROWSPACES,
    VERSION,
)
from .data_access.growspace_repository import GrowspaceRepository
from .date_time_helper import DateTimeHelper
from .dehumidifier_coordinator import DehumidifierCoordinator
from .environment_analyzer import EnvironmentAnalyzer
from .event_bus_pkg import GrowspaceEventBus
from .exceptions import GrowspaceNotFoundError
from .growspace_validator import GrowspaceValidator
from .import_export_manager import ImportExportManager
from .irrigation_coordinator import IrrigationCoordinator
from .managers.genetics import GeneticsManager
from .managers.growspace import GrowspaceManager
from .managers.nutrient import NutrientManager
from .managers.plant import PlantManager
from .managers.subsystem import SubsystemManager
from .models import (
    Growspace,
    GrowspaceEvent,
    GrowspaceType,
    IPMPreset,
    NutrientInventory,
    NutrientPreset,
    Plant,
)
from .notification_manager import NotificationManager
from .notifications import NotificationSettingsManager
from .presentation import PlantViewModelBuilder
from .service_coordinator_locator import ServiceCoordinatorLocator
from .services.environment_reporter import EnvironmentReporter
from .services.ipm_service import IPMService
from .services.nutrient_inventory import NutrientInventoryService
from .services.training_service import TrainingService
from .services.watering_service import WateringService
from .storage_manager import StorageManager
from .strain_library import StrainLibrary
from .tank_water_tracker import TankWaterTracker
from .types import DateInput
from .utils import generate_growspace_overview_unique_id
from .view_model_builder import ViewModelBuilder
from .vision_checkup_scheduler import VisionCheckupScheduler
from .vwc_irrigation_coordinator import VWCIrrigationCoordinator

_LOGGER = logging.getLogger(__name__)


class GrowspaceCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Manages Growspace, Plant, and Strain data for the Growspace Manager integration.

    This class handles loading, saving, and updating all the core data entities,
    as well as providing methods for interacting with them. It uses a Home
    Assistant Store to persist data and coordinates updates to all registered
    entities.
    """

    config_entry: ConfigEntry[GrowspaceCoordinator]
    strain_library: StrainLibrary | None = None

    @property
    def growspaces(self) -> dict[str, Growspace]:
        """Return all growspaces managed by this coordinator.

        Returns:
            Dictionary mapping growspace IDs to Growspace objects.
        """
        return self.data_repository.growspaces

    @growspaces.setter
    def growspaces(self, value: dict[str, Growspace]) -> None:
        """Set the growspaces dictionary.

        Args:
            value: New growspaces dictionary to set.
        """
        self.data_repository.growspaces = value

    @property
    def plants(self) -> dict[str, Plant]:
        """Return all plants managed by this coordinator.

        Returns:
            Dictionary mapping plant IDs to Plant objects.
        """
        return self.data_repository.plants

    @plants.setter
    def plants(self, value: dict[str, Plant]) -> None:
        """Set the plants dictionary.

        Args:
            value: New plants dictionary to set.
        """
        self.data_repository.plants = value

    @staticmethod
    def get_for_service_call(
        hass: HomeAssistant, call: ServiceCall | dict[str, Any]
    ) -> GrowspaceCoordinator:
        """Retrieve the correct coordinator based on service call data.

        Delegates to ServiceCoordinatorLocator for implementation.

        Args:
            hass: The Home Assistant instance.
            call: A ServiceCall or dict containing the service call data.

        Returns:
            The appropriate GrowspaceCoordinator for the request.

        Raises:
            ServiceValidationError: If no matching coordinator can be found.
        """
        return ServiceCoordinatorLocator.get_for_service_call(hass, call)

    @staticmethod
    def get_any(hass: HomeAssistant) -> GrowspaceCoordinator:
        """Get any loaded coordinator, for commands that don't target a specific entity.

        Args:
            hass: The Home Assistant instance.

        Returns:
            Any loaded GrowspaceCoordinator instance.

        Raises:
            ServiceValidationError: If no coordinator is loaded.
        """
        return ServiceCoordinatorLocator.get_any(hass)

    @property
    def irrigation_coordinators(
        self,
    ) -> dict[str, IrrigationCoordinator | VWCIrrigationCoordinator]:
        """Return irrigation coordinators for all growspaces.

        Returns:
            Dictionary mapping growspace IDs to their irrigation coordinators.
        """
        return self.subsystem_manager.irrigation_coordinators

    @property
    def dehumidifier_coordinators(self) -> dict[str, DehumidifierCoordinator]:
        """Return dehumidifier coordinators for all growspaces.

        Returns:
            Dictionary mapping growspace IDs to their dehumidifier coordinators.
        """
        return self.subsystem_manager.dehumidifier_coordinators

    @property
    def ec_ramp_curves(self) -> dict[str, Any]:
        """Return all EC ramp curves.

        Returns:
            Dictionary mapping curve IDs to ECRampCurve objects.
        """
        return self.nutrient_manager.ec_ramp_curves

    @property
    def nutrient_presets(self) -> dict[str, NutrientPreset]:
        """Return all configured nutrient presets.

        Returns:
            Dictionary mapping preset IDs to NutrientPreset objects.
        """
        return self.nutrient_manager.nutrient_presets

    @nutrient_presets.setter
    def nutrient_presets(self, value: dict[str, NutrientPreset]) -> None:
        """Set nutrient presets.

        Args:
            value: New nutrient presets dictionary.
        """
        self.nutrient_manager.nutrient_presets = value

    @property
    def ipm_presets(self) -> dict[str, IPMPreset]:
        """Return all configured IPM (Integrated Pest Management) presets.

        Returns:
            Dictionary mapping preset IDs to IPMPreset objects.
        """
        return self._ipm_service.ipm_presets

    @ipm_presets.setter
    def ipm_presets(self, value: dict[str, IPMPreset]) -> None:
        """Set IPM presets and synchronize with nutrient manager.

        Args:
            value: New IPM presets dictionary.
        """
        self._ipm_service.ipm_presets = value
        self.nutrient_manager.ipm_presets = (
            value  # Keep in sync for backward compatibility
        )

    @property
    def nutrient_inventory_service(self) -> NutrientInventoryService | None:
        """Return the nutrient inventory service if configured.

        Returns:
            NutrientInventoryService instance or None if not configured.
        """
        return self.nutrient_manager.inventory_service

    @nutrient_inventory_service.setter
    def nutrient_inventory_service(
        self, value: NutrientInventoryService | None
    ) -> None:
        """Set the nutrient inventory service.

        Args:
            value: NutrientInventoryService instance or None to clear.
        """
        self.nutrient_manager.inventory_service = value

    @property
    def nutrient_inventory(self) -> NutrientInventory | None:
        """Return the current nutrient inventory.

        Returns:
            NutrientInventory instance or None if not configured.
        """
        return self.nutrient_manager.inventory

    @nutrient_inventory.setter
    def nutrient_inventory(self, value: NutrientInventory | None) -> None:
        """Set the nutrient inventory.

        Args:
            value: NutrientInventory instance or None to clear.
        """
        self.nutrient_manager.inventory = value

    @property
    def notifications_sent(self) -> dict[str, dict[str, dict[str, bool]]]:
        """Return notification tracking data.

        Structure: {plant_id: {stage: {day: sent_bool}}}

        Returns:
            Nested dictionary tracking which notifications have been sent.
        """
        return self.data_repository.notifications_sent

    @notifications_sent.setter
    def notifications_sent(self, value: dict[str, dict[str, dict[str, bool]]]) -> None:
        """Set notification tracking data.

        Args:
            value: New notification tracking dictionary.
        """
        self.data_repository.notifications_sent = value

    @property
    def notifications_enabled(self) -> dict[str, bool]:
        """Return notification enabled state for each growspace.

        Returns:
            Dictionary mapping growspace IDs to enabled state (bool).
        """
        return self.data_repository.notifications_enabled

    @notifications_enabled.setter
    def notifications_enabled(self, value: dict[str, bool]) -> None:
        """Set notification enabled state.

        Args:
            value: Dictionary mapping growspace IDs to enabled state.
        """
        self.data_repository.notifications_enabled = value

    @property
    def growspace_manager(self) -> GrowspaceManager:
        """Return the growspace manager."""
        return self._growspace_manager

    @property
    def plant_manager(self) -> PlantManager:
        """Return the plant manager."""
        return self._plant_manager

    @property
    def growspace_service(self) -> GrowspaceManager:
        """Legacy alias for growspace service."""
        return self._growspace_manager

    @property
    def plant_service(self) -> PlantManager:
        """Legacy alias for plant service."""
        return self._plant_manager

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry[GrowspaceCoordinator],
        data: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
        strain_library: StrainLibrary | None = None,
    ) -> None:
        """Initialize the Growspace Coordinator.

        The coordinator manages all growspace and plant data, coordinates between
        specialized services, and handles persistence and updates.

        Args:
            hass: The Home Assistant instance.
            entry: The config entry for this integration.
            data: Initial raw data from storage to restore state. If None, starts fresh.
            options: Configuration options from the config entry.
            strain_library: Optional pre-initialized strain library. If None, creates new.
        """
        super().__init__(
            hass,
            _LOGGER,
            name="Growspace Manager Coordinator",
            update_interval=timedelta(minutes=COORDINATOR_UPDATE_INTERVAL_MINUTES),
            config_entry=entry,
        )

        self.config_entry = entry
        self.lock = asyncio.Lock()

        # Initialize Data Repository first - it owns the data dicts
        self.data_repository = GrowspaceRepository({}, {})

        # 1. Initialize logic components with minimal dependencies
        self.validator = GrowspaceValidator(self.data_repository)
        self.view_model_builder = ViewModelBuilder(self)

        # Initialize presentation layer builders
        self._plant_view_builder = PlantViewModelBuilder(hass)

        # 2. Load initial data if provided (uses mashumaro and validator)
        if data:
            self._load_initial_data(data)

        # Initialize helper managers
        self._date_time_helper = DateTimeHelper()
        self._event_bus = GrowspaceEventBus(hass)

        # Cache management - using dedicated CacheManager
        self.cache = CacheManager()

        # Initialize strain library
        if strain_library is None:
            self.strain_library = StrainLibrary(hass)
        else:
            self.strain_library = strain_library

        # 3. Initialize storage (depends on repository, nutrient_manager, genetics_manager)
        self.nutrient_manager = NutrientManager(
            self.data_repository, self._save_callback
        )
        self.genetics_manager = GeneticsManager(
            self.data_repository, self._save_callback
        )
        self.storage_manager = StorageManager(
            self.hass,
            self.data_repository,
            self.nutrient_manager,
            self.genetics_manager,
        )

        # 4. Initialize Managers (replacing services)
        self._growspace_manager = GrowspaceManager(
            self.hass,
            self.data_repository,
            self.validator,
            self.view_model_builder,
            self._save_callback,
            self.lock,
        )

        self._plant_manager = PlantManager(
            self.hass,
            self.data_repository,
            self.validator,
            self._growspace_manager,
            self.strain_library,
            self._plant_view_builder,
            self._save_callback,
            self.lock,
        )

        # Aliases for compatibility
        self._growspace_service = self._growspace_manager
        self._plant_service = self._plant_manager
        self.lifecycle_manager = self._plant_manager
        self._special_growspace_manager = self._growspace_manager

        # Initialize specialized services
        self._watering_service = WateringService(
            self.hass,
            self.data_repository,
            self.validator,
            self.nutrient_manager,
            self._save_callback,
            self.lock,
            self.add_event,
            self.cache.invalidate,
        )

        self._training_service = TrainingService(
            self.hass,
            self.data_repository,
            self._save_callback,
            self.lock,
            self.add_event,
            self.cache.invalidate,
        )

        self._ipm_service = IPMService(
            self.hass,
            self.data_repository,
            self._save_callback,
            self.lock,
            self.add_event,
            self.cache.invalidate,
        )

        # 4. Initialize analysis and notification (still depend on coordinator for now)
        self.environment_analyzer = EnvironmentAnalyzer(hass, self)
        self.environment_reporter = EnvironmentReporter(hass, self)
        self.notification_manager = NotificationManager(hass, self)
        self.notification_settings = NotificationSettingsManager(self)
        self.import_export_manager = ImportExportManager(hass)

        # Initialize Subsystem Manager
        self.subsystem_manager = SubsystemManager(hass, self, entry)

        # Initialize Vision Checkup Scheduler
        self.vision_scheduler = VisionCheckupScheduler(hass, self)

        # Track created entities (platform, entity_id, unique_id) for lifecycle management
        self.created_entity_ids: list[tuple[str, str, str]] = []

        # Runtime tank water trackers keyed by growspace_id → tank_entity
        self._tank_water_trackers: dict[str, dict[str, TankWaterTracker]] = {}

        # Options and state initialization

        self.options = options or {}
        _LOGGER.info("--- COORDINATOR INITIALIZED WITH OPTIONS: %s ---", self.options)

    def on_nutrient_inventory_loaded(self, inventory: NutrientInventory) -> None:
        """Update inventory and synchronize services after loading from storage.

        This method is called after the nutrient inventory is loaded from storage
        to ensure all services have the correct data and are synchronized.

        Args:
            inventory: The loaded nutrient inventory.
        """
        self.nutrient_manager.load_data(
            self.nutrient_manager.nutrient_presets,
            self.nutrient_manager.ipm_presets,
            inventory,
        )
        # Sync IPM presets with IPM service
        self._ipm_service.ipm_presets = self.nutrient_manager.ipm_presets

    # =============================================================================
    # CACHING AND OPTIMIZATION HELPER
    # =============================================================================

    async def async_refresh_growspace_data(self, growspace_id: str) -> None:
        """Thread-safe method to refresh data for a specific growspace.

        This method acquires the coordinator lock, invalidates the cache for the
        specified growspace, and updates the data property. External classes should
        use this method instead of directly accessing _lock and _invalidate_cache.

        Args:
            growspace_id: The ID of the growspace to refresh.
        """
        async with self.lock:
            self.cache.invalidate(growspace_id)
            self.data = self.view_model_builder.build_data_property()

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
                sw_version=VERSION,
            )

    # =============================================================================
    # INITIALIZATION AND MIGRATION METHODS
    # =============================================================================

    # =============================================================================
    # EVENT LOGBOOK MANAGEMENT
    # =============================================================================

    def add_event(self, growspace_id: str, event: GrowspaceEvent) -> None:
        """Fire a Growspace event to the HA Event Bus (delegates to EventBus)."""
        self._event_bus.fire_log_entry(event)

    # =============================================================================
    # UTILITY AND HELPER METHODS
    # =============================================================================

    def canonical_special(self, gs_id: str) -> tuple[str, str]:
        """Return the canonical ID and name for a special growspace."""
        return self.growspace_manager.get_canonical_special(gs_id)

    def _to_date(self, date_value: DateInput) -> date | None:
        """Convert a date input to a date object (delegates to DateTimeHelper)."""
        return DateTimeHelper.to_date(date_value)

    def calculate_days(self, start_date: DateInput, end_date: DateInput = None) -> int:
        """Calculate the number of days that have passed since a given date (delegates to DateTimeHelper)."""
        return DateTimeHelper.calculate_days(start_date, end_date)

    # =============================================================================
    # SPECIAL GROWSPACE MANAGEMENT (Delegated to GrowspaceManager)
    # =============================================================================

    def _create_special_growspace(
        self,
        canonical_id: str,
        canonical_name: str,
        rows: int,
        plants_per_row: int,
        growspace_type: GrowspaceType,
    ) -> None:
        """Compatibility alias for GrowspaceManager legacy method."""
        self.growspace_manager._create_special_growspace(  # noqa: SLF001
            canonical_id, canonical_name, rows, plants_per_row, growspace_type
        )

    def _update_special_growspace_name(
        self, canonical_id: str, canonical_name: str
    ) -> None:
        """Compatibility alias for GrowspaceManager legacy method."""
        # Use public method if available (to capture test mocks better)
        if hasattr(self.growspace_manager, "update_special_growspace_name"):
            self.growspace_manager.update_special_growspace_name(
                canonical_id, canonical_name
            )
        else:
            self.growspace_manager._update_special_growspace_name(  # noqa: SLF001
                canonical_id, canonical_name
            )

    def _update_growspace_structure(self, growspace_id: str, **kwargs: Any) -> Any:
        """Compatibility alias for GrowspaceManager legacy method."""
        growspace = self.growspaces.get(growspace_id)
        if not growspace:
            return False
        changes = kwargs.pop("changes", [])
        return self.growspace_manager._update_growspace_structure(  # noqa: SLF001
            growspace, kwargs, changes
        )

    def _update_growspace_config(self, growspace_id: str, **kwargs: Any) -> Any:
        """Compatibility alias for GrowspaceManager legacy method."""
        growspace = self.growspaces.get(growspace_id)
        if not growspace:
            return False
        changes = kwargs.pop("changes", [])
        return self.growspace_manager._update_growspace_config(  # noqa: SLF001
            growspace, kwargs, changes
        )

    # =============================================================================
    # DATA UPDATE COORDINATOR OVERRIDE
    # =============================================================================
    async def _async_update_data(self) -> dict[str, Any]:
        """Refresh data periodically, called by DataUpdateCoordinator.

        This method is called automatically based on the update_interval (15 minutes).
        It performs the following operations:
        1. Invalidates all caches to ensure fresh calculations
        2. Rebuilds the data property for all entities
        3. Checks for timed notifications that need to be sent
        4. Updates air exchange recommendations based on current conditions

        Returns:
            The updated data dictionary containing all growspace and plant data.
        """
        # Periodic refresh implies environment data might have changed (VPD, etc).
        # We must invalidate ALL caches to ensure calculations are fresh.
        self.cache.invalidate(None)

        self.data = self.view_model_builder.build_data_property()
        await self.notification_manager.async_check_timed_notifications()
        await self.notification_manager.async_check_tank_levels()
        await self.notification_manager.async_check_pending_alerts()
        await self.environment_analyzer.async_update_air_exchange_recommendations()

        return self.data

    async def _save_callback(self) -> None:
        """Helper to call current async_commit for late-binding in tests."""
        await self.async_commit()

    def _load_initial_data(self, data: dict[str, Any]) -> None:
        """Load and validate initial data from a dictionary.

        Uses mashumaro for deserialization. Model __pre_deserialize__ hooks
        handle all migrations automatically.
        """
        # Deserialize growspaces using mashumaro
        raw_growspaces = data.get("growspaces", {})
        growspaces = {}
        for gid, gdata in raw_growspaces.items():
            if isinstance(gdata, Growspace):
                growspaces[gid] = gdata
            elif isinstance(gdata, dict):
                try:
                    growspaces[gid] = Growspace.from_dict(gdata)
                except (ValueError, KeyError, TypeError, Exception):
                    # Catch mashumaro or other deserialization errors as "structure mismatch"
                    # We use Exception here to be safe but log specifically
                    _LOGGER.exception(
                        "Failed to load growspace %s due to data structure mismatch",
                        gid,
                    )
            else:
                _LOGGER.error(
                    "Failed to load growspace %s (invalid type: %s)", gid, type(gdata)
                )

        # Deserialize plants using mashumaro
        raw_plants = data.get("plants", {})
        plants = {}
        for pid, pdata in raw_plants.items():
            if isinstance(pdata, Plant):
                plants[pid] = pdata
            elif isinstance(pdata, dict):
                try:
                    plants[pid] = Plant.from_dict(pdata)
                except (ValueError, KeyError, TypeError, Exception):
                    _LOGGER.exception(
                        "Failed to load plant %s due to data structure mismatch",
                        pid,
                    )
            else:
                _LOGGER.error(
                    "Failed to load plant %s (invalid type: %s)", pid, type(pdata)
                )

        # Update the repository with deserialized objects
        self.data_repository.load_data(
            growspaces,
            plants,
            data.get("notifications_sent"),
            data.get("notifications_enabled"),
        )

    async def async_commit(self) -> None:
        """Commit all changes to storage and notify listeners.

        This method performs the following operations:
        1. Invalidates all caches to ensure fresh data
        2. Rebuilds the data property for entities
        3. Persists changes to storage
        4. Notifies all listeners of the update
        5. Triggers irrigation coordinator refreshes

        This is the primary method for persisting state changes.
        """
        # Ensure we always have fresh data when committing
        self.cache.invalidate()
        self.data = self.view_model_builder.build_data_property()
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

    async def async_save(self) -> None:
        """Save current data to storage.

        This is an alias for async_commit() for backward compatibility.
        Prefer using async_commit() directly in new code.
        """
        await self.async_commit()

    async def async_add_growspace(self, **kwargs: Any) -> Growspace:
        """Add a new growspace and register it with Home Assistant.

        Creates a new growspace using the GrowspaceService, registers it as a device
        in Home Assistant's device registry, and initializes any associated
        sub-coordinators (irrigation, dehumidifier).

        Args:
            **kwargs: Growspace configuration parameters (name, rows, plants_per_row, etc.).

        Returns:
            The newly created Growspace object.
        """
        growspace = await self.growspace_manager.add_growspace(**kwargs)

        # Register device in HA registry
        device_registry = dr.async_get(self.hass)
        device_registry.async_get_or_create(
            config_entry_id=self.config_entry.entry_id,
            identifiers={(DOMAIN, growspace.id)},
            name=growspace.name,
            model=growspace.growspace_type.value
            if growspace.growspace_type
            else "Growspace",
            manufacturer="Growspace Manager",
            sw_version=VERSION,
        )

        # Initialize sub-coordinators for the new growspace
        await self.subsystem_manager.async_setup_growspace_sub_coordinators(
            growspace.id, growspace
        )

        return growspace

    async def async_update_growspace(
        self, growspace_id: str, **kwargs: Any
    ) -> Growspace:
        """Update an existing growspace's configuration.

        Args:
            growspace_id: The ID of the growspace to update.
            **kwargs: Configuration parameters to update.

        Returns:
            The updated Growspace object.
        """
        await self.growspace_manager.update_growspace(growspace_id, **kwargs)
        # Return the growspace from repo
        gs = self.growspaces.get(growspace_id)
        if gs:
            return gs

        raise GrowspaceNotFoundError(f"Growspace {growspace_id} not found after update")

    async def async_add_plant(self, **kwargs: Any) -> Plant:
        """Add a new plant to a growspace.

        Args:
            **kwargs: Plant configuration parameters (growspace_id, strain, row, col, etc.).

        Returns:
            The newly created Plant object.
        """
        return await self.plant_manager.add_plant(**kwargs)

    async def async_update_plant(self, plant_id: str, **kwargs: Any) -> Plant:
        """Update an existing plant's data.

        Args:
            plant_id: The ID of the plant to update.
            **kwargs: Plant parameters to update.

        Returns:
            The updated Plant object.
        """
        return await self.plant_manager.update_plant(plant_id, **kwargs)

    def async_fire_growspace_updated(self) -> None:
        """Fire an event to notify that growspace data has been updated (delegates to EventBus)."""
        self._event_bus.fire_growspace_updated()

    async def async_shutdown(self) -> None:
        """Perform graceful shutdown and ensure all data is persisted.

        This method should be called during integration unload to:
        1. Unload the environment reporter
        2. Force save all data to storage to prevent data loss

        This ensures clean shutdown and data persistence.
        """
        if hasattr(self, "environment_reporter"):
            self.environment_reporter.unload()
        self.vision_scheduler.async_stop()
        await self.storage_manager.async_force_save()

    async def async_load(self) -> None:
        """Load data from persistent storage and initialize the integration.

        This method performs the following initialization steps:
        1. Loads all data from persistent storage
        2. Configures calculated sensors
        3. Ensures default special growspaces exist (clone, veg, flower, etc.)
        4. Saves any initialization changes
        5. Initializes the environment reporter

        This should be called once during integration setup.
        """
        await self.storage_manager.async_load(self.options)

        # Ensure calculated sensors are configured
        self.growspace_manager.ensure_calculated_sensors()

        # Ensure default special growspaces exist
        await self.growspace_manager.ensure_default_growspaces()
        await self.async_save()

        # Schedule vision checkups for all loaded growspaces
        self.vision_scheduler.schedule_all_growspaces()

        # Initialize environment reporter after data load
        if hasattr(self, "environment_reporter"):
            await self.environment_reporter.async_initialize()

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
        # Change logic to also treat falsy values (like empty strings) as None.
        if not updated_settings.get("irrigation_pump_entity"):
            updated_settings["irrigation_pump_entity"] = None
        if not updated_settings.get("drain_pump_entity"):
            updated_settings["drain_pump_entity"] = None

        # Update the config in the growspace object
        for k, v in updated_settings.items():
            if hasattr(growspace.irrigation_config, k):
                setattr(growspace.irrigation_config, k, v)

        # Invalidate cache for this growspace
        self.cache.invalidate(growspace_id)

        # Save via coordinator
        await self.async_save()

        # Notify listeners
        self.async_set_updated_data(self.data)

    # =============================================================================
    # GROWSPACE MANAGEMENT METHODS
    # =============================================================================

    async def async_remove_growspace(self, growspace_id: str) -> None:
        """Remove a growspace and all plants within it."""
        await self.growspace_manager.remove_growspace(growspace_id)

    def _validate_plants_after_growspace_resize(
        self, growspace_id: str, new_rows: int, new_plants_per_row: int
    ) -> None:
        """Compatibility alias for GrowspaceManager legacy method."""

        self.hass.async_create_task(
            self.growspace_manager._validate_plants_after_growspace_resize(  # noqa: SLF001
                growspace_id, new_rows, new_plants_per_row
            )
        )

    # =============================================================================
    # NOTIFICATION SWITCH MANAGEMENT
    # =============================================================================

    def is_notifications_enabled(self, growspace_id: str) -> bool:
        """Check if notifications are enabled for a specific growspace.

        Delegates to NotificationManager.
        """
        return self.notification_settings.is_notifications_enabled(growspace_id)

    async def set_notifications_enabled(self, growspace_id: str, enabled: bool) -> None:
        """Enable or disable notifications for a specific growspace.

        Delegates to NotificationManager.
        """
        if growspace_id not in self.growspaces:
            # The manager will log a warning, just return early to avoid data update errors
            self.notification_settings.set_notifications_state(growspace_id, enabled)
            return

        # Update state via notification manager
        self.data["notifications_enabled"] = (
            self.notification_settings.set_notifications_state(growspace_id, enabled)
        )
        await self.async_commit()

    # =============================================================================
    # TIMED NOTIFICATION MANAGEMENT
    # =============================================================================

    def get_timed_notifications(self) -> list[dict[str, Any]]:
        """Get the list of configured timed notifications.

        Delegates to NotificationManager.
        """
        return self.notification_settings.get_timed_notifications()

    async def async_add_timed_notification(
        self,
        message: str,
        trigger_type: str,
        day: int,
        growspace_ids: list[str] | None = None,
    ) -> None:
        """Add a new timed notification.

        Delegates to NotificationManager.
        """
        notifications = self.get_timed_notifications().copy()
        new_notification = self.notification_settings.create_timed_notification(
            message, trigger_type, day, growspace_ids
        )
        notifications.append(new_notification)
        await self.async_update_options({"timed_notifications": notifications})

    async def async_update_timed_notification(
        self,
        notification_id: str,
        message: str,
        trigger_type: str,
        day: int,
        growspace_ids: list[str] | None = None,
    ) -> None:
        """Update an existing timed notification.

        Delegates to NotificationManager.
        """
        notifications = self.get_timed_notifications().copy()
        self.notification_settings.update_timed_notification_in_list(
            notifications, notification_id, message, trigger_type, day, growspace_ids
        )
        await self.async_update_options({"timed_notifications": notifications})

    async def async_remove_timed_notification(self, notification_id: str) -> None:
        """Remove a timed notification.

        Delegates to NotificationManager.
        """
        notifications = self.notification_settings.remove_timed_notification_from_list(
            self.get_timed_notifications(), notification_id
        )
        await self.async_update_options({"timed_notifications": notifications})

    async def async_update_options(self, options: dict[str, Any]) -> None:
        """Update config entry options and trigger reload."""
        new_options = self.config_entry.options.copy()
        new_options.update(options)
        self.hass.config_entries.async_update_entry(
            self.config_entry, options=new_options
        )

    # =============================================================================
    # PLANT MANAGEMENT METHODS
    # =============================================================================

    async def async_add_mother_plant(
        self,
        phenotype: str,
        strain: str,
        row: int,
        col: int,
        mother_start: date | None = None,
        **kwargs: Any,
    ) -> Plant:
        """Add a new mother plant."""
        return await self.plant_manager.add_mother_plant(
            phenotype=phenotype,
            strain=strain,
            row=row,
            col=col,
            mother_start=mother_start,
            **kwargs,
        )

    async def async_take_clones(
        self,
        mother_plant_id: str,
        num_clones: int,
        target_growspace_id: str | None = None,
        target_growspace_name: str | None = None,
        transition_date: date | None = None,
    ) -> list[Plant]:
        """Create multiple clones from a mother plant."""
        return await self.plant_manager.take_clones(
            mother_plant_id=mother_plant_id,
            num_clones=num_clones,
            target_growspace_id=target_growspace_id,
            target_growspace_name=target_growspace_name,
            transition_date=transition_date,
        )

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
        await self.plant_manager.promote_clone(
            clone_id, target_growspace_id, transition_date
        )

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

    async def switch_plants_service(self, plant1_id: str, plant2_id: str) -> None:
        """Service call wrapper for switching the positions of two plants.

        Args:
            plant1_id: The ID of the first plant.
            plant2_id: The ID of the second plant.
        """
        await self.plant_manager.switch_plants(plant1_id, plant2_id)

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
        return self.view_model_builder.build_serialized_growspace(growspace_id)

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
        """Record a watering event for a single plant (delegated to WateringService)."""
        return await self._watering_service.async_water_plant(
            plant_id, amount, nutrients, preset_id
        )

    async def async_water_growspace(
        self,
        growspace_id: str,
        amount_per_plant: float | None = None,
        nutrients: dict[str, float] | None = None,
        preset_id: str | None = None,
        amount: float | None = None,
    ) -> int:
        """Record a watering event for all plants in a growspace (delegated to WateringService)."""
        return await self._watering_service.async_water_growspace(
            growspace_id, amount_per_plant, nutrients, preset_id, amount
        )

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
        """Create or update a nutrient preset (delegated)."""
        return await self.nutrient_manager.async_save_nutrient_preset(
            name, nutrients, stage, min_days_in_stage, preset_id
        )

    async def async_remove_nutrient_preset(self, preset_id: str) -> None:
        """Remove a nutrient preset (delegated)."""
        await self.nutrient_manager.async_remove_nutrient_preset(preset_id)

    def get_applicable_presets(self, plant_id: str) -> list[NutrientPreset]:
        """Get all presets applicable to a plant (delegated)."""
        return self.nutrient_manager.get_applicable_presets(plant_id)

    def _resolve_preset_nutrients(self, preset_id: str) -> dict[str, float]:
        """Resolve a preset ID to its nutrient map (delegated)."""
        # This helper might not be needed if internal usage is gone,
        # but kept for potential external compatibility or service usage
        if preset_id not in self.nutrient_manager.nutrient_presets:
            raise KeyError(f"Nutrient preset '{preset_id}' not found")
        return self.nutrient_manager.nutrient_presets[preset_id].get_nutrient_map()

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
        """Log a training event for specific plants or an entire growspace (delegated to TrainingService)."""
        await self._training_service.async_log_training_event(
            growspace_id, technique, notes, plant_ids
        )

    async def async_save_ipm_preset(
        self,
        name: str,
        type: str,
        items: list[dict[str, Any]],
        stage: str | None = None,
        min_days_in_stage: int | None = None,
        preset_id: str | None = None,
    ) -> IPMPreset:
        """Create or update an IPM preset (delegated to IPMService)."""
        return await self._ipm_service.async_save_ipm_preset(
            name, type, items, stage, min_days_in_stage, preset_id
        )

    async def async_remove_ipm_preset(self, preset_id: str) -> None:
        """Remove an IPM preset (delegated to IPMService)."""
        await self._ipm_service.async_remove_ipm_preset(preset_id)

    async def async_apply_ipm(
        self,
        preset_id: str,
        growspace_id: str | None = None,
        plant_ids: list[str] | None = None,
        notes: str | None = None,
    ) -> list[str]:
        """Log an IPM application event (delegated to IPMService)."""
        return await self._ipm_service.async_apply_ipm(
            preset_id, growspace_id, plant_ids, notes
        )

    async def async_log_drain_reading(
        self,
        growspace_id: str,
        feed_ec: float,
        drain_ec: float,
        drain_volume_ml: float | None = None,
        feed_volume_ml: float | None = None,
    ) -> None:
        """Log a drain EC reading for a growspace and alert if delta exceeds threshold."""
        from .models import DrainReading  # noqa: PLC0415

        growspace = self.growspaces.get(growspace_id)
        if not growspace:
            from homeassistant.exceptions import ServiceValidationError  # noqa: PLC0415

            raise ServiceValidationError(f"Growspace '{growspace_id}' not found")

        from homeassistant.util import dt as dt_util  # noqa: PLC0415

        reading = DrainReading(
            timestamp=dt_util.now().isoformat(),
            feed_ec=feed_ec,
            drain_ec=drain_ec,
            drain_volume_ml=drain_volume_ml,
            feed_volume_ml=feed_volume_ml,
        )

        drain_config = growspace.drain_config
        drain_config.readings.append(reading)
        # Enforce rolling window
        if len(drain_config.readings) > drain_config.max_readings:
            drain_config.readings = drain_config.readings[-drain_config.max_readings :]

        await self.async_commit()

        # Fire alert if drain EC delta exceeds threshold
        ec_delta = drain_ec - feed_ec
        if drain_config.enabled and ec_delta > drain_config.max_ec_delta:
            _LOGGER.warning(
                "Drain EC alert for %s: drain=%.2f, feed=%.2f, delta=%.2f exceeds threshold %.2f",
                growspace_id,
                drain_ec,
                feed_ec,
                ec_delta,
                drain_config.max_ec_delta,
            )
            await self.notification_manager.async_send_notification(
                growspace_id,
                f"\u26a0\ufe0f High drain EC in {growspace.name}",
                (
                    f"Drain EC ({drain_ec:.2f}) exceeds feed EC ({feed_ec:.2f}) "
                    f"by {ec_delta:.2f} (threshold: {drain_config.max_ec_delta:.2f}). "
                    "Consider flushing to prevent salt buildup."
                ),
            )

    async def async_configure_drain_monitoring(
        self,
        growspace_id: str,
        enabled: bool | None = None,
        max_ec_delta: float | None = None,
        target_runoff_percent: float | None = None,
    ) -> None:
        """Configure drain EC monitoring settings for a growspace."""
        growspace = self.growspaces.get(growspace_id)
        if not growspace:
            from homeassistant.exceptions import ServiceValidationError  # noqa: PLC0415

            raise ServiceValidationError(f"Growspace '{growspace_id}' not found")

        drain_config = growspace.drain_config
        if enabled is not None:
            drain_config.enabled = enabled
        if max_ec_delta is not None:
            drain_config.max_ec_delta = max_ec_delta
        if target_runoff_percent is not None:
            drain_config.target_runoff_percent = target_runoff_percent

        await self.async_commit()

    async def async_reset_water_tracking(self, growspace_id: str) -> None:
        """Reset water usage counters for a growspace."""
        from homeassistant.util import dt as dt_util  # noqa: PLC0415

        from .models import WaterUsageData  # noqa: PLC0415

        growspace = self.growspaces.get(growspace_id)
        if not growspace:
            from homeassistant.exceptions import ServiceValidationError  # noqa: PLC0415

            raise ServiceValidationError(f"Growspace '{growspace_id}' not found")

        growspace.water_usage = WaterUsageData(
            cycle_start_date=dt_util.now().date().isoformat()
        )
        await self.async_commit()
        _LOGGER.info("Reset water tracking for growspace %s", growspace_id)

    async def async_save_ec_ramp_curve(
        self,
        name: str,
        stage: str,
        points: list[dict[str, Any]],
        curve_id: str | None = None,
    ) -> None:
        """Create or update an EC ramp curve (delegated to NutrientManager)."""
        await self.nutrient_manager.async_save_ec_ramp_curve(
            name=name, stage=stage, points=points, curve_id=curve_id
        )

    async def async_remove_ec_ramp_curve(self, curve_id: str) -> None:
        """Remove an EC ramp curve (delegated to NutrientManager)."""
        await self.nutrient_manager.async_remove_ec_ramp_curve(curve_id)

    async def async_configure_tank(
        self,
        growspace_id: str,
        tank_entity: str,
        *,
        volume_liters: float | None = None,
    ) -> None:
        """Update runtime configuration for an irrigation tank."""
        growspace = self.get_growspace(growspace_id)
        if growspace is None:
            return
        tank = next(
            (
                t
                for t in growspace.environment_config.irrigation_tanks
                if t.sensor_entity == tank_entity
            ),
            None,
        )
        if tank is None:
            return
        if volume_liters is not None:
            tank.volume_liters = volume_liters
            await self.storage_manager.async_save()

    def get_tank_tracker(
        self, growspace_id: str, tank_entity: str
    ) -> TankWaterTracker | None:
        """Return the TankWaterTracker for a tank, or None if not configured."""
        growspace = self.get_growspace(growspace_id)
        if growspace is None:
            return None
        tank = next(
            (
                t
                for t in growspace.environment_config.irrigation_tanks
                if t.sensor_entity == tank_entity
            ),
            None,
        )
        if tank is None or tank.volume_liters is None:
            return None
        gs_trackers = self._tank_water_trackers.setdefault(growspace_id, {})
        if tank_entity not in gs_trackers:
            gs_trackers[tank_entity] = TankWaterTracker(tank)
        return gs_trackers[tank_entity]

    async def async_harvest(self, plant_id: str) -> Plant:
        """Mark a plant as harvested."""
        return await self.plant_manager.harvest(plant_id)

    async def async_harvest_plant(
        self,
        plant_id: str,
        target_growspace_id: str | None = None,
        target_growspace_name: str | None = None,
        transition_date: str | None = None,
        wet_weight: float | None = None,
        dry_weight: float | None = None,
        trim_weight: float | None = None,
        thc_percentage: float | None = None,
        cbd_percentage: float | None = None,
        terpene_profile: str | None = None,
    ) -> None:
        """Harvest a plant with full orchestration."""
        await self.plant_manager.harvest_plant(
            plant_id=plant_id,
            target_growspace_id=target_growspace_id,
            target_growspace_name=target_growspace_name,
            transition_date=transition_date,
            wet_weight=wet_weight,
            dry_weight=dry_weight,
            trim_weight=trim_weight,
            thc_percentage=thc_percentage,
            cbd_percentage=cbd_percentage,
            terpene_profile=terpene_profile,
        )

    async def async_remove_plant(self, plant_id: str) -> bool:
        """Remove a plant."""
        return await self.plant_manager.remove_plant(plant_id)

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
        if not self.strain_library:
            return []
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
        if not self.strain_library:
            return 0
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

    def get_plant(self, plant_id: str) -> Plant | None:
        """Retrieve a plant by its ID."""
        return self.data_repository.get_plant(plant_id)

    def get_growspace(self, growspace_id: str) -> Growspace | None:
        """Retrieve a growspace by its ID."""
        return self.data_repository.get_growspace(growspace_id)

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
        registry: er.EntityRegistry = er.async_get(self.hass)
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
        if entity_id:
            return entity_id  # type: ignore[no-any-return]  # Entity Registry returns Any

        # Fallback: Handle special cases logic data-driven
        for special_def in SPECIAL_GROWSPACES.values():
            canonical_id = special_def["canonical_id"]
            if growspace_id == canonical_id or growspace_id in special_def.get(
                "aliases", []
            ):
                canonical_uid = generate_growspace_overview_unique_id(str(canonical_id))
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
            not self.notifications_sent.get(plant_id, {})
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
        if plant_id not in self.notifications_sent:
            self.notifications_sent[plant_id] = {}

        if stage not in self.notifications_sent[plant_id]:
            self.notifications_sent[plant_id][stage] = {}

        self.notifications_sent[plant_id][stage][str(days)] = True
        await self.async_commit()

    def fire_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Fire a growspace manager event."""
        payload = {"event_type": event_type, "data": data}
        self.hass.bus.async_fire("growspace_manager_updated", payload)
