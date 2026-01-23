"""Data update coordinator for the Growspace Manager integration."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
import logging
from typing import Any
import uuid

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util, slugify

from .cache import CacheManager
from .const import (
    ATTR_DRAIN_TIMES,
    ATTR_GROWSPACE_ID,
    ATTR_IRRIGATION_TIMES,
    ATTR_MOTHER_PLANT_ID,
    ATTR_PLANT_ID,
    ATTR_TARGET_GROWSPACE_ID,
    CATEGORY_IPM,
    CATEGORY_TRAINING,
    CATEGORY_WATERING,
    DOMAIN,
    SPECIAL_GROWSPACES,
    PlantStage,
)
from .data_access.growspace_repository import GrowspaceRepository
from .date_time_helper import DateTimeHelper
from .dehumidifier_coordinator import DehumidifierCoordinator
from .environment_analyzer import EnvironmentAnalyzer
from .event_bus_pkg import GrowspaceEventBus
from .exceptions import GrowspaceError, GrowspaceNotFoundError, ValidationChangeError
from .growspace_validator import GrowspaceValidator
from .import_export_manager import ImportExportManager
from .irrigation_coordinator import IrrigationCoordinator
from .managers.nutrient import NutrientManager
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
from .plant_lifecycle_manager import PlantLifecycleManager
from .serializers import GrowspaceSerializer
from .services.environment_reporter import EnvironmentReporter
from .services.growspace_service import GrowspaceService
from .services.nutrient_inventory import NutrientInventoryService
from .services.plant_service import PlantService
from .services.special_growspace_manager import SpecialGrowspaceManager
from .storage_manager import StorageManager
from .strain_library import StrainLibrary
from .types import DateInput
from .utils import generate_growspace_overview_unique_id
from .view_model_builder import ViewModelBuilder
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
        """Return the growspaces dictionary."""
        return self.data_repository.growspaces

    @growspaces.setter
    def growspaces(self, value: dict[str, Growspace]) -> None:
        """Set the growspaces dictionary."""
        self.data_repository.growspaces = value

    @property
    def plants(self) -> dict[str, Plant]:
        """Return the plants dictionary."""
        return self.data_repository.plants

    @plants.setter
    def plants(self, value: dict[str, Plant]) -> None:
        """Set the plants dictionary."""
        self.data_repository.plants = value

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

    @property
    def nutrient_presets(self) -> dict[str, NutrientPreset]:
        """Return nutrient presets from manager."""
        return self.nutrient_manager.presets

    @nutrient_presets.setter
    def nutrient_presets(self, value: dict[str, NutrientPreset]) -> None:
        """Set nutrient presets in manager."""
        self.nutrient_manager.presets = value

    @property
    def ipm_presets(self) -> dict[str, IPMPreset]:
        """Return IPM presets from manager."""
        return self.nutrient_manager.ipm_presets

    @ipm_presets.setter
    def ipm_presets(self, value: dict[str, IPMPreset]) -> None:
        """Set IPM presets in manager."""
        self.nutrient_manager.ipm_presets = value

    @property
    def nutrient_inventory_service(self) -> NutrientInventoryService | None:
        """Return nutrient inventory service from manager."""
        return self.nutrient_manager.inventory_service

    @nutrient_inventory_service.setter
    def nutrient_inventory_service(
        self, value: NutrientInventoryService | None
    ) -> None:
        """Set nutrient inventory service in manager."""
        self.nutrient_manager.inventory_service = value

    @property
    def nutrient_inventory(self) -> NutrientInventory | None:
        """Return nutrient inventory from manager."""
        return self.nutrient_manager.inventory

    @nutrient_inventory.setter
    def nutrient_inventory(self, value: NutrientInventory | None) -> None:
        """Set nutrient inventory in manager."""
        self.nutrient_manager.inventory = value

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
        self.lock = asyncio.Lock()
        self.serializer = GrowspaceSerializer(hass)

        # Initialize Data Repository first - it owns the data dicts
        self.data_repository = GrowspaceRepository({}, {})

        # Initialize helper managers
        self._special_growspace_manager = SpecialGrowspaceManager(self)
        self._date_time_helper = DateTimeHelper()
        self._event_bus = GrowspaceEventBus(hass)
        # self.events removed - using native HA Event Bus

        # Cache management - using dedicated CacheManager
        self.cache = CacheManager()

        self.notifications_sent: dict[str, dict[str, dict[str, bool]]] = {}
        self.notifications_enabled: dict[
            str, bool
        ] = {}  # ✅ Notification switch states

        # Notification settings management
        self.notification_settings = NotificationSettingsManager(self)

        self.options = options or {}
        _LOGGER.info("--- COORDINATOR INITIALIZED WITH OPTIONS: %s ---", self.options)

        # Initialize strain library
        if strain_library is None:
            # Fallback for testing or legacy init
            self.strain_library = StrainLibrary(hass)
        else:
            self.strain_library = strain_library

        # Initialize Environment Reporter
        self.environment_reporter = EnvironmentReporter(hass, self)

        self.validator = GrowspaceValidator(self)
        self.storage_manager = StorageManager(self, hass)
        self.environment_analyzer = EnvironmentAnalyzer(hass, self)
        self.notification_manager = NotificationManager(hass, self)
        self.import_export_manager = ImportExportManager(hass)
        self.lifecycle_manager = PlantLifecycleManager(self)
        self.nutrient_manager = NutrientManager(self)

        # Update Data Repository with loaded data
        self.data_repository.load_data(self.growspaces, self.plants)

        # Initialize Subsystem Manager
        self.subsystem_manager = SubsystemManager(hass, self, entry)

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

        # Initialize domain services
        self._plant_service = PlantService(self)
        self._growspace_service = GrowspaceService(self)

        # Initialize view model builder
        self.view_model_builder = ViewModelBuilder(self)

    def on_nutrient_inventory_loaded(self, inventory: NutrientInventory) -> None:
        """Update inventory and service after load."""
        self.nutrient_manager.load_data(
            self.nutrient_manager.presets, self.nutrient_manager.ipm_presets, inventory
        )

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
                sw_version="0.3.3",
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
        """Return the canonical ID and name for a special growspace (delegates to SpecialGrowspaceManager)."""
        return self._special_growspace_manager.get_canonical_special(gs_id)

    def _to_date(self, date_value: DateInput) -> date | None:
        """Convert a date input to a date object (delegates to DateTimeHelper)."""
        return DateTimeHelper.to_date(date_value)

    def calculate_days(self, start_date: DateInput, end_date: DateInput = None) -> int:
        """Calculate the number of days that have passed since a given date (delegates to DateTimeHelper)."""
        return DateTimeHelper.calculate_days(start_date, end_date)

    # =============================================================================
    # SPECIAL GROWSPACE MANAGEMENT
    # =============================================================================

    def _create_special_growspace(
        self,
        canonical_id: str,
        canonical_name: str,
        rows: int,
        plants_per_row: int,
        growspace_type: GrowspaceType,
    ) -> None:
        """Create a new special growspace (delegates to SpecialGrowspaceManager)."""
        self._special_growspace_manager.create_special_growspace(
            canonical_id, canonical_name, rows, plants_per_row, growspace_type
        )

    def _update_special_growspace_name(
        self, canonical_id: str, canonical_name: str
    ) -> None:
        """Update the name of an existing special growspace (delegates to SpecialGrowspaceManager)."""
        self._special_growspace_manager.update_special_growspace_name(
            canonical_id, canonical_name
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
        # Periodic refresh implies environment data might have changed (VPD, etc).
        # We must invalidate ALL caches to ensure calculations are fresh.
        self.cache.invalidate(None)

        self.data = self.view_model_builder.build_data_property()
        await self.notification_manager.async_check_timed_notifications()
        await self.environment_analyzer.async_update_air_exchange_recommendations()

        return self.data

    async def async_commit(self) -> None:
        """Commit changes to storage and notify listeners."""
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
        """Save current data to storage (delegated to async_commit)."""

        await self.async_commit()

    async def async_add_growspace(self, **kwargs: Any) -> Growspace:
        """Add a growspace (delegated to GrowspaceService)."""
        growspace = await self._growspace_service.add_growspace(**kwargs)

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
            sw_version="0.3.3",
        )

        # Initialize sub-coordinators for the new growspace
        await self.subsystem_manager.async_setup_growspace_sub_coordinators(
            growspace.id, growspace
        )

        return growspace

    async def async_update_growspace(
        self, growspace_id: str, **kwargs: Any
    ) -> Growspace:
        """Update a growspace (delegated to GrowspaceService)."""
        return await self._growspace_service.update_growspace(growspace_id, **kwargs)

    async def async_add_plant(self, **kwargs: Any) -> Plant:
        """Add a plant (delegated to PlantService)."""
        return await self._plant_service.add_plant(**kwargs)

    async def async_update_plant(self, plant_id: str, **kwargs: Any) -> Plant:
        """Update a plant (delegated to PlantService)."""
        return await self._plant_service.update_plant(plant_id, **kwargs)

    def async_fire_growspace_updated(self) -> None:
        """Fire an event to notify that growspace data has been updated (delegates to EventBus)."""
        self._event_bus.fire_growspace_updated()

    async def async_shutdown(self) -> None:
        """Perform shutdown tasks, ensuring data is persisted."""
        if hasattr(self, "environment_reporter"):
            self.environment_reporter.unload()
        await self.storage_manager.async_force_save()

    async def async_load(self) -> None:
        """Load data from persistent storage and handle migrations."""
        await self.storage_manager.async_load()

        # Ensure calculated sensors are configured
        self._growspace_service.ensure_calculated_sensors()

        # Ensure default special growspaces exist
        await self._growspace_service.ensure_default_growspaces()
        await self.async_save()

        # Update Data Repository with loaded data
        self.data_repository.load_data(self.growspaces, self.plants)
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
        """Remove a growspace and all plants within it (delegates to GrowspaceService)."""
        await self._growspace_service.remove_growspace(growspace_id)

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

    async def _validate_plants_after_growspace_resize(
        self, growspace_id: str, new_rows: int, new_plants_per_row: int
    ) -> None:
        """Validate plants are within new grid boundaries after resize.

        Delegates to GrowspaceValidator.
        """
        self.validator.validate_plants_after_resize(
            growspace_id, new_rows, new_plants_per_row
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
        """Add a new mother plant (delegates to PlantService)."""
        return await self._plant_service.add_mother_plant(
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
        """Create multiple clones from a mother plant (delegates to PlantService)."""
        return await self._plant_service.take_clones(
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
        self.validator.validate_plant_exists(clone_id)
        clone = self.plants[clone_id]
        source_gs_id = clone.growspace_id

        if clone.stage != PlantStage.CLONE:
            raise ValidationChangeError(
                f"Plant {clone_id} is not in clone stage (current: {clone.stage})"
            )

        # Resolve target growspace ID (handle aliases like 'veg')
        if target_growspace_id == "veg":
            target_gs_id = self._growspace_service.ensure_special_growspace(
                PlantStage.VEG, "veg", 5, 5
            )
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
        self.cache.invalidate(source_gs_id)
        self.cache.invalidate(target_gs_id)

        # Update the existing plant
        # We explicitly set stage to VEG and update veg_start.
        await self._plant_service.update_plant(
            clone_id,
            growspace_id=target_gs_id,
            row=row,
            col=col,
            stage=PlantStage.VEG,
            veg_start=transition_date,
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
        await self._plant_service.switch_plants(plant1_id, plant2_id)

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

        final_nutrients, preset_name = self.nutrient_manager.resolve_nutrient_mix(
            nutrients, preset_id
        )

        # Deduct nutrients from inventory using manager
        self.nutrient_manager.deduct_from_inventory(final_nutrients, amount)

        # Update plant's last_watered timestamp
        now_iso = dt_util.now().isoformat()
        plant.last_watered = now_iso

        # Invalidate cache for the growspace if requested
        if invalidate_cache:
            self.cache.invalidate(plant.growspace_id)

        reasons = self._create_watering_event_reasons(
            plant, amount, preset_name, final_nutrients
        )

        # Create a GrowspaceEvent for the logbook
        event = GrowspaceEvent(
            sensor_type="irrigation",
            growspace_id=plant.growspace_id,
            start_time=now_iso,
            end_time=now_iso,
            duration_sec=0,
            severity=0.0,
            category=CATEGORY_WATERING,
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

    def _resolve_nutrient_mix(
        self, nutrients: dict[str, float] | None, preset_id: str | None
    ) -> tuple[dict[str, float], str | None]:
        """Resolve final nutrient mix from optional preset and manual overrides."""
        final_nutrients: dict[str, float] = {}
        preset_name: str | None = None

        if preset_id:
            if preset_id not in self.nutrient_presets:
                raise KeyError(f"Nutrient preset '{preset_id}' not found")
            preset = self.nutrient_presets[preset_id]
            preset_name = preset.name
            final_nutrients.update(preset.get_nutrient_map())

        if nutrients:
            final_nutrients.update(nutrients)

        return final_nutrients, preset_name

    def _create_watering_event_reasons(
        self,
        plant: Plant,
        amount: float,
        preset_name: str | None,
        final_nutrients: dict[str, float],
    ) -> list[str]:
        """Build the reasons list for a watering event."""
        reasons = []
        reasons.append(f"plant_id:{plant.plant_id}")

        plant_info = f"Plant: {plant.strain}"
        if plant.phenotype:
            plant_info += f" ({plant.phenotype})"
        reasons.append(plant_info)

        reasons.append(f"Watered with {amount}L")
        if preset_name:
            reasons.append(f"Preset: {preset_name}")

        if final_nutrients:
            nutrient_details = []
            for name, conc in final_nutrients.items():
                total_ml = round(amount * conc, 2)
                nutrient_details.append(f"{name}: {conc}ml/L (Total: {total_ml}ml)")
            reasons.append(f"Nutrients: {', '.join(nutrient_details)}")

        return reasons

    async def async_water_growspace(
        self,
        growspace_id: str,
        amount_per_plant: float | None = None,
        nutrients: dict[str, float] | None = None,
        preset_id: str | None = None,
        amount: float | None = None,
    ) -> int:
        """Record a watering event for all plants in a growspace."""
        self.validator.validate_growspace_exists(growspace_id)
        plants = self.get_growspace_plants(growspace_id)

        if not plants:
            return 0

        # Determine amount per plant if total amount is provided
        if amount is not None:
            amount_per_plant = amount / len(plants)
        elif amount_per_plant is None:
            raise GrowspaceError(
                "Either 'amount' (total) or 'amount_per_plant' is required"
            )

        for plant in plants:
            await self._water_plant_internal(
                plant.plant_id,
                amount_per_plant,
                nutrients,
                preset_id,
                invalidate_cache=False,
            )

        # Bulk invalidation
        self.cache.invalidate(growspace_id)

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
        if preset_id not in self.nutrient_manager.presets:
            raise KeyError(f"Nutrient preset '{preset_id}' not found")
        return self.nutrient_manager.presets[preset_id].get_nutrient_map()

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
                gid, technique, notes or "", plant_ids or [], affected_in_gid
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
            self.cache.invalidate(gid)

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
        self,
        gid: str,
        technique: str,
        notes: str,
        plant_ids: list[str],
        affected_in_gid: list[Plant],
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
            preset.items = items  # type: ignore[assignment]
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
            self.cache.invalidate(gid)

        await self.async_save()

        return [p.plant_id for p in target_plants]

    def _create_ipm_reasons(
        self,
        gid: str,
        preset: IPMPreset,
        notes: str | None,
        plant_ids: list[str] | None,
        affected_in_gid: list[Plant],
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
        """Mark a plant as harvested (delegates to PlantService)."""
        return await self._plant_service.harvest(plant_id)

    async def async_harvest_plant(
        self,
        plant_id: str,
        target_growspace_id: str | None = None,
        target_growspace_name: str | None = None,
        transition_date: str | None = None,
    ) -> None:
        """Harvest a plant with full orchestration (delegates to PlantService)."""
        await self._plant_service.harvest_plant(
            plant_id, target_growspace_id, target_growspace_name, transition_date
        )

    async def async_remove_plant(self, plant_id: str) -> bool:
        """Remove a plant (delegates to PlantService)."""
        return await self._plant_service.remove_plant(plant_id)

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
