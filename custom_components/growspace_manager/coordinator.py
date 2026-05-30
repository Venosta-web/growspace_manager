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

from .alert_monitor import AlertMonitor
from .briefing_scheduler import BriefingScheduler
from .cache import CacheManager
from .const import COORDINATOR_UPDATE_INTERVAL_MINUTES, DOMAIN, VERSION
from .conversation_store import ConversationStore
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
    IPMPreset,
    NutrientInventory,
    NutrientPreset,
    Plant,
)
from .notification_manager import NotificationManager
from .notifications import NotificationSettingsManager
from .photoperiod_flip_checker import PhotoperiodFlipChecker
from .presentation import PlantViewModelBuilder
from .service_coordinator_locator import ServiceCoordinatorLocator
from .services.environment_reporter import EnvironmentReporter
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

    @classmethod
    def build(
        cls,
        hass: HomeAssistant,
        entry: Any,
        data: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
        strain_library: Any | None = None,
        seedfinder_scraper: Any | None = None,
    ) -> GrowspaceCoordinator:
        """Build a fully wired coordinator via CoordinatorBuilder.

        Preferred over direct instantiation in tests and production code.
        """
        from .coordinator_builder import CoordinatorBuilder  # noqa: PLC0415

        return CoordinatorBuilder(hass, entry).build(
            data=data,
            options=options,
            strain_library=strain_library,
            seedfinder_scraper=seedfinder_scraper,
        )

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
        return self.ipm_service.ipm_presets

    async def save_ipm_preset(
        self,
        name: str,
        preset_type: str,
        items: list[dict[str, Any]],
        stage: str | None = None,
        min_days_in_stage: int | None = None,
        preset_id: str | None = None,
    ) -> IPMPreset:
        """Create or update an IPM preset."""
        return await self.ipm_service.async_save_ipm_preset(
            name, preset_type, items, stage, min_days_in_stage, preset_id
        )

    async def remove_ipm_preset(self, preset_id: str) -> None:
        """Remove an IPM preset by ID."""
        await self.ipm_service.async_remove_ipm_preset(preset_id)

    @ipm_presets.setter
    def ipm_presets(self, value: dict[str, IPMPreset]) -> None:
        """Set IPM presets and synchronize with nutrient manager.

        Args:
            value: New IPM presets dictionary.
        """
        self.ipm_service.ipm_presets = value
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

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry[GrowspaceCoordinator],
        *,
        data_repository: GrowspaceRepository,
        notification_state: NotificationState,
        lock: asyncio.Lock,
        cache: CacheManager,
        date_time_helper: DateTimeHelper,
        event_bus: GrowspaceEventBus,
        strain_library: StrainLibrary,
        seedfinder_scraper: SeedfinderScraper,
        plant_view_builder: PlantViewModelBuilder,
        import_export_manager: ImportExportManager,
        validator: GrowspaceValidator,
        options: dict[str, Any] | None = None,
    ) -> None:
        """Store pre-built collaborators and perform HA-level setup.

        All construction lives in CoordinatorBuilder. Call _attach_services()
        after construction to wire in the coordinator-self-dependent services.
        """
        super().__init__(
            hass,
            _LOGGER,
            name="Growspace Manager Coordinator",
            update_interval=timedelta(minutes=COORDINATOR_UPDATE_INTERVAL_MINUTES),
            config_entry=entry,
        )

        self.config_entry = entry
        self.lock = lock
        self.data_repository = data_repository
        self.notification_state = notification_state
        self.cache = cache
        self._date_time_helper = date_time_helper
        self._event_bus = event_bus
        self.strain_library = strain_library
        self.seedfinder_scraper = seedfinder_scraper
        self._plant_view_builder = plant_view_builder
        self.import_export_manager = import_export_manager
        self.validator = validator
        self.options = options or {}
        self.created_entity_ids: list[tuple[str, str, str]] = []

    def _attach_services(
        self,
        *,
        view_model_builder: ViewModelBuilder,
        nutrient_manager: NutrientManager,
        genetics_manager: GeneticsManager,
        storage_manager: StorageManager,
        growspace_manager: GrowspaceManager,
        plant_manager: PlantManager,
        watering_service: WateringService,
        training_service: TrainingService,
        ipm_service: IPMService,
        environment_analyzer: EnvironmentAnalyzer,
        environment_reporter: EnvironmentReporter,
        notification_manager: NotificationManager,
        notification_settings: NotificationSettingsManager,
        subsystem_manager: SubsystemManager,
        services: ServiceFacade,
        vision_scheduler: VisionCheckupScheduler,
        briefing_scheduler: BriefingScheduler,
        photoperiod_checker: PhotoperiodFlipChecker,
        alert_monitor: AlertMonitor,
        conversation_store: ConversationStore,
    ) -> None:
        """Wire coordinator-self-dependent services. Called by CoordinatorBuilder after __init__."""
        self.view_model_builder = view_model_builder
        self.nutrient_manager = nutrient_manager
        self.genetics_manager = genetics_manager
        self.storage_manager = storage_manager
        self._growspace_manager = growspace_manager
        self._plant_manager = plant_manager
        self.watering_service = watering_service
        self.training_service = training_service
        self.ipm_service = ipm_service
        self.environment_analyzer = environment_analyzer
        self.environment_reporter = environment_reporter
        self.notification_manager = notification_manager
        self.notification_settings = notification_settings
        self.subsystem_manager = subsystem_manager
        self.services = services
        self.vision_scheduler = vision_scheduler
        self.briefing_scheduler = briefing_scheduler
        self.photoperiod_checker = photoperiod_checker
        self.alert_monitor = alert_monitor
        self.conversation_store = conversation_store
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
        self.ipm_service.ipm_presets = self.nutrient_manager.ipm_presets

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

    def _to_date(self, date_value: DateInput) -> date | None:
        """Convert a date input to a date object (delegates to DateTimeHelper)."""
        return DateTimeHelper.to_date(date_value)

    def calculate_days(self, start_date: DateInput, end_date: DateInput = None) -> int:
        """Calculate the number of days that have passed since a given date (delegates to DateTimeHelper)."""
        return DateTimeHelper.calculate_days(start_date, end_date)

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
        """Persist current state and notify listeners."""
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
        await self.services.growspaces.async_unsubscribe_all_trackers()

        if hasattr(self, "environment_reporter"):
            self.environment_reporter.unload()
        self.notification_manager.shutdown()
        self.vision_scheduler.async_stop()
        self.briefing_scheduler.async_stop()
        self.photoperiod_checker.async_stop()
        self.alert_monitor.async_stop()
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
        # storage_manager.load_data() replaces nutrient_manager.ipm_presets with a new
        # dict loaded from storage. Sync ipm_service to point at that same dict so saves
        # go to the right place and the WebSocket handler returns up-to-date presets.
        self.ipm_service.ipm_presets = self.nutrient_manager.ipm_presets

        # Ensure calculated sensors are configured
        self.growspace_manager.ensure_calculated_sensors()

        # Ensure default special growspaces exist
        await self.growspace_manager.ensure_default_growspaces()
        await self.async_commit()

        # Schedule vision checkups for all loaded growspaces
        self.vision_scheduler.schedule_all_growspaces()
        self.briefing_scheduler.start()
        self.photoperiod_checker.schedule_all_growspaces()
        await self.alert_monitor.async_start()
        await self.conversation_store.async_load()

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
