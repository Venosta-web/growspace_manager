"""Data update coordinator for the Growspace Manager integration."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .cache import CacheManager
from .const import COORDINATOR_UPDATE_INTERVAL_MINUTES, DOMAIN, VERSION
from .data_access.growspace_repository import GrowspaceRepository
from .data_access.notification_state import NotificationState
from .date_time_helper import DateTimeHelper
from .dehumidifier_coordinator import DehumidifierCoordinator
from .environment_analyzer import EnvironmentAnalyzer
from .event_bus_pkg import GrowspaceEventBus
from .growspace_validator import GrowspaceValidator
from .humidifier_coordinator import HumidifierCoordinator
from .import_export_manager import ImportExportManager
from .integration_types import DateInput
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
from .services.context import ServiceContext
from .services.facade import ServiceFacade
from .services.ipm_service import IPMService
from .services.nutrient_inventory import NutrientInventoryService
from .services.seedfinder_scraper import SeedfinderScraper
from .services.training_service import TrainingService
from .services.watering_service import WateringService
from .storage_manager import StorageManager
from .strain_library import StrainLibrary
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
    seedfinder_scraper: SeedfinderScraper | None = None

    @property
    def growspaces(self) -> dict[str, Growspace]:
        """Return a snapshot dict of all growspaces keyed by ID."""
        return {gs.id: gs for gs in self.data_repository.get_all_growspaces()}

    @property
    def plants(self) -> dict[str, Plant]:
        """Return a snapshot dict of all plants keyed by plant_id."""
        return {p.plant_id: p for p in self.data_repository.get_all_plants()}

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
    def humidifier_coordinators(self) -> dict[str, HumidifierCoordinator]:
        """Return humidifier coordinators for all growspaces.

        Returns:
            Dictionary mapping growspace IDs to their humidifier coordinators.
        """
        return self.subsystem_manager.humidifier_coordinators

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
        """Return notification tracking data."""
        return self.notification_state.sent

    @property
    def notifications_enabled(self) -> dict[str, bool]:
        """Return notification enabled state for each growspace."""
        return self.notification_state.enabled

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
        seedfinder_scraper: SeedfinderScraper | None = None,
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
        self.data_repository = GrowspaceRepository()
        self.notification_state = NotificationState()

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

        # Initialize seedfinder scraper
        if seedfinder_scraper is None:
            self.seedfinder_scraper = SeedfinderScraper(hass)
        else:
            self.seedfinder_scraper = seedfinder_scraper

        # 3. Initialize storage (depends on repository, nutrient_manager, genetics_manager)
        self.nutrient_manager = NutrientManager(
            self.data_repository, self._save_callback
        )
        self.genetics_manager = GeneticsManager(
            self.data_repository,
            self._save_callback,
            strain_library=self.strain_library,
        )
        self.storage_manager = StorageManager(
            self.hass,
            self.data_repository,
            self.nutrient_manager,
            self.genetics_manager,
            self.notification_state,
        )

        # 4. Initialize Managers and Services
        _svc_ctx = ServiceContext(
            save_callback=self._save_callback,
            lock=self.lock,
            add_event=self.add_event,
            invalidate_cache=self.cache.invalidate,
        )

        self._growspace_manager = GrowspaceManager(
            _svc_ctx,
            self.hass,
            self.data_repository,
            self.notification_state,
            self.validator,
            self.view_model_builder,
        )

        self._plant_manager = PlantManager(
            _svc_ctx,
            self.hass,
            self.data_repository,
            self.notification_state,
            self.validator,
            self._growspace_manager,
            self.strain_library,
            self._plant_view_builder,
        )

        # Aliases for compatibility
        self._growspace_service = self._growspace_manager
        self._plant_service = self._plant_manager
        self.lifecycle_manager = self._plant_manager
        self._special_growspace_manager = self._growspace_manager

        self._watering_service = WateringService(
            _svc_ctx,
            self.hass,
            self.data_repository,
            self.validator,
            self.nutrient_manager,
        )

        self._training_service = TrainingService(
            _svc_ctx,
            self.hass,
            self.data_repository,
        )

        self._ipm_service = IPMService(
            _svc_ctx,
            self.hass,
            self.data_repository,
        )

        self.environment_analyzer = EnvironmentAnalyzer(hass, self)
        self.environment_reporter = EnvironmentReporter(hass, self)
        self.notification_manager = NotificationManager(hass, self)
        self.notification_settings = NotificationSettingsManager(self)
        self.import_export_manager = ImportExportManager(hass)

        # Initialize Subsystem Manager
        self.subsystem_manager = SubsystemManager(hass, self, entry)
        self.services = ServiceFacade(self)

        # Initialize Vision Checkup Scheduler
        self.vision_scheduler = VisionCheckupScheduler(hass, self)

        # Track created entities (platform, entity_id, unique_id) for lifecycle management
        self.created_entity_ids: list[tuple[str, str, str]] = []

        # Runtime tank water trackers keyed by growspace_id → tank_entity
        # Subsystem tracking state

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

    def _resolve_preset_nutrients(self, preset_id: str) -> dict[str, float]:
        """Resolve nutrient map from a preset ID.

        This is a compatibility helper for tests and internal logic.
        """
        if preset_id not in self.nutrient_manager.nutrient_presets:
            raise KeyError(f"Nutrient preset '{preset_id}' not found")
        return self.nutrient_manager.nutrient_presets[preset_id].get_nutrient_map()

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
        """Internal callback to handle async saving and commit logic.

        This delegates to the service facade to ensure all orchestration
        logic (including storage and cache invalidation) is executed.
        """
        await self.services.save()

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
        self.data_repository.load_growspaces(growspaces)
        self.data_repository.load_plants(plants)
        if notifications_sent := data.get("notifications_sent"):
            self.notification_state.sent = notifications_sent
        if notifications_enabled := data.get("notifications_enabled"):
            self.notification_state.enabled = notifications_enabled

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
        await self.storage_manager.async_force_save()
        self.async_set_updated_data(self.data)
        self._event_bus.fire_growspace_updated()

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

    async def async_shutdown(self) -> None:
        """Perform graceful shutdown and ensure all data is persisted.

        This method should be called during integration unload to:
        1. Unload the environment reporter
        2. Force save all data to storage to prevent data loss

        This ensures clean shutdown and data persistence.
        """
        # Cancel all sub-coordinator listeners
        self.subsystem_manager.async_cancel_all()

        # Unsubscribe all tank water trackers
        await self.services.async_unsubscribe_all_trackers()

        if hasattr(self, "environment_reporter"):
            self.environment_reporter.unload()
        self.notification_manager.shutdown()
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
        await self.async_commit()

        # Schedule vision checkups for all loaded growspaces
        self.vision_scheduler.schedule_all_growspaces()

        # Initialize environment reporter after data load
        if hasattr(self, "environment_reporter"):
            await self.environment_reporter.async_initialize()


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

    def get_growspace_grid(self, growspace_id: str) -> list[list[str | None]]:
        """Generate a 2D grid representation of a growspace's plant layout."""
        return self.services.get_growspace_grid(growspace_id)

    def _guess_overview_entity_id(self, growspace_id: str) -> str:
        """Make a best-effort guess of the overview sensor entity ID for a growspace."""
        return self.services.guess_overview_entity_id(growspace_id)

    # =============================================================================
    # NOTIFICATION MANAGEMENT
    # =============================================================================

    def should_send_notification(self, plant_id: str, stage: str, days: int) -> bool:
        """Check if a notification for a specific event has already been sent."""
        return self.services.should_send_notification(plant_id, stage, days)

    async def mark_notification_sent(
        self, plant_id: str, stage: str, days: int
    ) -> None:
        """Mark a notification as sent to prevent duplicates."""
        await self.services.mark_notification_sent(plant_id, stage, days)

    def fire_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Fire a growspace manager event."""
        self.services.fire_event(event_type, data)

    async def _async_remove_plant_entities(self, plant_id: str) -> None:
        """Remove all Home Assistant entities associated with a specific plant."""
        await self.services.remove_plant_entities(plant_id)
