"""Service facade for the Growspace Manager integration.

This module provides a unified interface for all domain services,
reducing the complexity and size of the main GrowspaceCoordinator.
"""

from __future__ import annotations

from datetime import date
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from custom_components.growspace_manager.const import (
    ATTR_DRAIN_TIMES,
    ATTR_IRRIGATION_TIMES,
    CATEGORY_NOTE,
    DOMAIN,
    EVENT_GROWSPACE_LOG_ENTRY,
    SPECIAL_GROWSPACES,
    VERSION,
    NotificationTier,
    PlantStage,
)
from custom_components.growspace_manager.models import (
    DrainReading,
    ECRampCurve,
    Growspace,
    IPMPreset,
    IrrigationConfig,
    NutrientPreset,
    Plant,
    Subarea,
    WaterUsageData,
)
from custom_components.growspace_manager.tank_water_tracker import TankWaterTracker
from custom_components.growspace_manager.utils import (
    generate_growspace_overview_unique_id,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util, slugify

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
    from custom_components.growspace_manager.managers.growspace import GrowspaceManager
    from custom_components.growspace_manager.managers.nutrient import NutrientManager
    from custom_components.growspace_manager.managers.plant import PlantManager
    from custom_components.growspace_manager.notification_manager import (
        NotificationManager,
    )
    from custom_components.growspace_manager.notifications import (
        NotificationSettingsManager,
    )
    from custom_components.growspace_manager.services.ipm_service import IPMService
    from custom_components.growspace_manager.services.training_service import (
        TrainingService,
    )
    from custom_components.growspace_manager.services.watering_service import (
        WateringService,
    )
    from custom_components.growspace_manager.strain_library import StrainLibrary

_LOGGER = logging.getLogger(__name__)


class ServiceFacade:
    """Facade for all Growspace Manager services.

    This class centralizes delegation to specialized services and managers,
    allowing the GrowspaceCoordinator to focus on core coordination tasks.
    """

    def __init__(self, coordinator: GrowspaceCoordinator) -> None:
        """Initialize the service facade."""
        self._coordinator = coordinator
        self._tank_water_trackers: dict[str, dict[str, TankWaterTracker]] = {}

    def __getattr__(self, name: str) -> Any:
        """Handle dynamic attribute access, providing async_ aliases."""
        if name.startswith("async_"):
            base_name = name[6:]
            if hasattr(self, base_name):
                return getattr(self, base_name)
        raise AttributeError(
            f"'{self.__class__.__name__}' object has no attribute '{name}'"
        )

    async def save(self) -> None:
        """Save current data to storage.

        This delegates to the coordinator's async_commit method for persistence.
        """
        await self._coordinator.async_commit()

    async def add_growspace(self, **kwargs: Any) -> Growspace:
        """Add a new growspace and register it with Home Assistant.

        Args:
            **kwargs: Growspace configuration parameters.

        Returns:
            The newly created Growspace object.
        """
        growspace = await self._coordinator.growspace_manager.add_growspace(
            **kwargs
        )

        # Register device in HA registry
        device_registry = dr.async_get(self._coordinator.hass)
        device_registry.async_get_or_create(
            config_entry_id=self._coordinator.config_entry.entry_id,
            identifiers={(DOMAIN, growspace.id)},
            name=growspace.name,
            model=growspace.growspace_type.value
            if growspace.growspace_type
            else "Growspace",
            manufacturer="Growspace Manager",
            sw_version=VERSION,
        )

        # Initialize sub-coordinators for the new growspace
        await (
            self._coordinator.subsystem_manager.async_setup_growspace_sub_coordinators(
                growspace.id, growspace
            )
        )

        _LOGGER.info("Added growspace %s (%s)", growspace.name, growspace.id)

        return growspace

    async def update_growspace(self, growspace_id: str, **kwargs: Any) -> Growspace:
        """Update an existing growspace's configuration.

        Args:
            growspace_id: The ID of the growspace to update.
            **kwargs: Configuration parameters to update.

        Returns:
            The updated Growspace object.
        """
        growspace = await self._coordinator.growspace_manager.update_growspace(
            growspace_id, **kwargs
        )

        # Update device name if changed
        if "name" in kwargs:
            device_registry = dr.async_get(self._coordinator.hass)
            if device := device_registry.async_get_device(
                identifiers={(DOMAIN, growspace_id)}
            ):
                device_registry.async_update_device(device.id, name=kwargs["name"])

        _LOGGER.info("Updated growspace %s", growspace_id)

        return growspace

    async def add_plant(self, **kwargs: Any) -> Plant:
        """Add a new plant.

        Args:
            **kwargs: Plant configuration parameters.

        Returns:
            The newly created Plant object.
        """
        plant = await self._coordinator.plant_manager.add_plant(**kwargs)

        # Register device in HA registry
        device_registry = dr.async_get(self._coordinator.hass)
        strain_name = plant.genetics.strain_name if plant.genetics else "Unknown"
        device_registry.async_get_or_create(
            config_entry_id=self._coordinator.config_entry.entry_id,
            identifiers={(DOMAIN, plant.plant_id)},
            name=strain_name,
            model=f"Plant ({strain_name})" if strain_name else "Plant",
            manufacturer="Growspace Manager",
            sw_version=VERSION,
            suggested_area=plant.growspace_id,
        )

        _LOGGER.info(
            "Added plant %s (%s) to %s", strain_name, plant.plant_id, plant.growspace_id
        )

        return plant

    async def update_plant(self, plant_id: str, **kwargs: Any) -> Plant:
        """Update an existing plant's configuration.

        Args:
            plant_id: The ID of the plant to update.
            **kwargs: Configuration parameters to update.

        Returns:
            The updated Plant object.
        """
        plant = await self._coordinator.plant_manager.update_plant(
            plant_id, **kwargs
        )

        # Update device name if changed
        if "name" in kwargs:
            device_registry = dr.async_get(self._coordinator.hass)
            if device := device_registry.async_get_device(
                identifiers={(DOMAIN, plant_id)}
            ):
                device_registry.async_update_device(device.id, name=kwargs["name"])

        _LOGGER.info("Updated plant %s", plant_id)

        return plant

    async def remove_growspace(self, growspace_id: str) -> None:
        """Remove a growspace from the manager."""
        await self._coordinator.growspace_manager.remove_growspace(growspace_id)

    async def update_options(self, options: dict[str, Any]) -> None:
        """Update integration options and save them.

        Args:
            options: A dictionary of option keys and values to update.
        """
        # Update local options cache
        if hasattr(self._coordinator, "options"):
            self._coordinator.options.update(options)

        # Update HA config entry options
        new_options = self._coordinator.config_entry.options.copy()
        new_options.update(options)
        self._coordinator.hass.config_entries.async_update_entry(
            self._coordinator.config_entry, options=new_options
        )

        await self._coordinator.async_commit()
        _LOGGER.info("Integration options updated: %s", options)

    async def add_subarea(self, growspace_id: str, name: str) -> Any:
        """Add a named subarea to a growspace."""
        subarea = await self._coordinator.growspace_manager.add_subarea(
            growspace_id, name
        )
        _LOGGER.info("Added subarea %s to growspace %s", name, growspace_id)
        return subarea

    async def update_subarea(
        self, growspace_id: str, subarea_id: str, environment_config: dict[str, Any]
    ) -> Any:
        """Update a subarea's environment config."""
        result = await self._coordinator.growspace_manager.update_subarea(
            growspace_id, subarea_id, environment_config
        )
        _LOGGER.info("Updated subarea %s in growspace %s", subarea_id, growspace_id)
        return result

    async def remove_subarea(self, growspace_id: str, subarea_id: str) -> None:
        """Remove a subarea from a growspace."""
        await self._coordinator.growspace_manager.remove_subarea(
            growspace_id, subarea_id
        )
        _LOGGER.info("Removed subarea %s from growspace %s", subarea_id, growspace_id)

    def get_subareas(self, growspace_id: str) -> list[Subarea]:
        """Return all subareas for a growspace."""
        return self._coordinator.growspace_manager.get_subareas(growspace_id)

    def get_growspace(self, growspace_id: str) -> Growspace | None:
        """Retrieve a growspace by its ID."""
        return self._coordinator.data_repository.get_growspace(growspace_id)

    def get_sorted_growspace_options(self) -> list[tuple[str, str]]:
        """Return a sorted list of (growspace_id, name) tuples."""
        return self._coordinator.growspace_manager.get_sorted_growspace_options()

    @property
    def growspaces(self) -> dict[str, Growspace]:
        """Return all growspaces."""
        return self._coordinator.growspaces

    @property
    def plants(self) -> dict[str, Plant]:
        """Return all plants."""
        return self._coordinator.plants

    @property
    def growspace_manager(self) -> GrowspaceManager:
        """Return the growspace manager."""
        return self._coordinator.growspace_manager

    @property
    def plant_manager(self) -> PlantManager:
        """Return the plant manager."""
        return self._coordinator.plant_manager

    @property
    def strain_library(self) -> StrainLibrary | None:
        """Return the strain library."""
        return self._coordinator.strain_library

    @property
    def nutrient_manager(self) -> NutrientManager:
        """Return the nutrient manager."""
        return self._coordinator.nutrient_manager

    @property
    def watering_service(self) -> WateringService:
        """Return the watering service."""
        return self._coordinator.watering_service

    @property
    def training_service(self) -> TrainingService:
        """Return the training service."""
        return self._coordinator.training_service

    @property
    def ipm_service(self) -> IPMService:
        """Return the IPM service."""
        return self._coordinator.ipm_service

    @property
    def notification_manager(self) -> NotificationManager:
        """Return the notification manager."""
        return self._coordinator.notification_manager

    @property
    def notification_settings(self) -> NotificationSettingsManager:
        """Return the notification settings manager."""
        return self._coordinator.notification_settings

    def get_growspace_grid(self, growspace_id: str) -> list[list[str | None]]:
        """Generate a 2D grid representation of a growspace's plant layout."""
        return self._coordinator.data_repository.get_growspace_grid(growspace_id)

    def get_canonical_special(self, gs_id: str) -> tuple[str, str]:
        """Return the canonical ID and name for a special growspace."""
        return self._coordinator.growspace_manager.get_canonical_special(gs_id)

    async def async_set_lighting_schedule(
        self,
        growspace_id: str,
        veg_hours: int,
        flower_hours: int,
        dli_veg: float | None = None,
    ) -> None:
        """Set the lighting schedule for a growspace.

        Args:
            growspace_id: The ID of the growspace to update.
            veg_hours: The number of day hours during vegetative stage.
            flower_hours: The number of day hours during flowering stage.
            dli_veg: Optional DLI target for vegetative stage.
        """
        if growspace_id not in self._coordinator.growspaces:
            raise ServiceValidationError(f"Growspace '{growspace_id}' not found")

        growspace = self._coordinator.growspaces[growspace_id]
        growspace.environment_config.veg_day_hours = int(veg_hours)
        growspace.environment_config.flower_day_hours = int(flower_hours)
        if dli_veg is not None:
            growspace.environment_config.dli_target_veg = float(dli_veg)

        await self._coordinator.async_commit()
        await self._coordinator.async_refresh()
        _LOGGER.info(
            "Lighting schedule updated for %s: Veg=%sh, Flower=%sh, DLI=%s",
            growspace.name,
            veg_hours,
            flower_hours,
            dli_veg,
        )

    async def set_lighting_schedule(
        self,
        growspace_id: str,
        veg_hours: int,
        flower_hours: int,
        dli_veg: float | None = None,
    ) -> None:
        """Compatibility alias for async_set_lighting_schedule."""
        await self.async_set_lighting_schedule(
            growspace_id, veg_hours, flower_hours, dli_veg
        )
        if growspace_id not in self._coordinator.growspaces:
            raise ServiceValidationError(f"Growspace '{growspace_id}' not found")

        growspace = self._coordinator.growspaces[growspace_id]
        growspace.environment_config.veg_day_hours = int(veg_hours)
        growspace.environment_config.flower_day_hours = int(flower_hours)
        if dli_veg is not None:
            growspace.environment_config.dli_target_veg = float(dli_veg)

        await self._coordinator.async_commit()
        await self._coordinator.async_refresh()
        _LOGGER.info(
            "Lighting schedule updated for %s: Veg=%sh, Flower=%sh, DLI=%s",
            growspace.name,
            veg_hours,
            flower_hours,
            dli_veg,
        )

    async def set_notifications_enabled(self, growspace_id: str, enabled: bool) -> None:
        """Enable or disable notifications for a specific growspace."""
        if growspace_id not in self._coordinator.growspaces:
            self._coordinator.notification_settings.set_notifications_state(
                growspace_id, enabled
            )
            return

        self._coordinator.data["notifications_enabled"] = (
            self._coordinator.notification_settings.set_notifications_state(
                growspace_id, enabled
            )
        )
        await self._coordinator.async_commit()

    def get_timed_notifications(self) -> list[dict[str, Any]]:
        """Get the list of configured timed notifications."""
        return self._coordinator.notification_settings.get_timed_notifications()

    async def add_timed_notification(
        self,
        message: str,
        trigger_type: str,
        day: int,
        growspace_ids: list[str] | None = None,
    ) -> None:
        """Add a new timed notification."""
        notifications = self.get_timed_notifications().copy()
        new_notification = (
            self._coordinator.notification_settings.create_timed_notification(
                message, trigger_type, day, growspace_ids
            )
        )
        notifications.append(new_notification)
        await self.update_options({"timed_notifications": notifications})

    async def update_timed_notification(
        self,
        notification_id: str,
        message: str,
        trigger_type: str,
        day: int,
        growspace_ids: list[str] | None = None,
    ) -> None:
        """Update an existing timed notification."""
        notifications = self.get_timed_notifications().copy()
        if self._coordinator.notification_settings.update_timed_notification_in_list(
            notifications, notification_id, message, trigger_type, day, growspace_ids
        ):
            await self.update_options({"timed_notifications": notifications})

    async def remove_timed_notification(self, notification_id: str) -> None:
        """Remove a timed notification."""
        notifications = (
            self._coordinator.notification_settings.remove_timed_notification_from_list(
                self.get_timed_notifications(), notification_id
            )
        )
        await self.update_options({"timed_notifications": notifications})

    def is_notifications_enabled(self, growspace_id: str) -> bool:
        """Check if notifications are enabled for a specific growspace."""
        return (
            self._coordinator.notification_settings.is_notifications_enabled(
                growspace_id
            )
        )

    async def add_mother_plant(
        self,
        phenotype: str,
        growspace_id: str,
        strain: str | None = None,
        **kwargs: Any,
    ) -> Plant:
        """Add a new mother plant."""
        plant = await self._coordinator.plant_manager.add_mother_plant(
            phenotype=phenotype,
            growspace_id=growspace_id,
            strain=strain,
            **kwargs,
        )
        await self._coordinator.async_request_refresh()
        return plant

    async def update_irrigation_config(
        self, growspace_id: str, user_input: dict[str, Any]
    ) -> None:
        """Update irrigation configuration for a growspace.

        Args:
            growspace_id: The ID of the growspace to update.
            user_input: The user input dictionary containing new settings.
        """
        growspace = self._coordinator.growspaces.get(growspace_id)
        if not growspace:
            raise ServiceValidationError(f"Growspace {growspace_id} not found")

        # Handle "clear" flag if present
        if user_input.get("clear"):
            growspace.irrigation_config = IrrigationConfig()
            growspace.irrigation_strategy.enabled = False
            _LOGGER.info("Cleared irrigation config for %s", growspace_id)
            await self._coordinator.async_commit()
            return

        # Handle special mapping for VWC steering toggle
        if "use_vwc_steering" in user_input:
            growspace.irrigation_strategy.enabled = bool(
                user_input.pop("use_vwc_steering")
            )

        # Filter out read-only fields that were passed for display purposes
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
        if not updated_settings.get("irrigation_pump_entity"):
            updated_settings["irrigation_pump_entity"] = None
        if not updated_settings.get("drain_pump_entity"):
            updated_settings["drain_pump_entity"] = None

        # Update IrrigationConfig fields
        for k, v in updated_settings.items():
            if hasattr(growspace.irrigation_config, k):
                setattr(growspace.irrigation_config, k, v)
            elif hasattr(growspace.irrigation_strategy, k):
                setattr(growspace.irrigation_strategy, k, v)

        # Invalidate cache for this growspace
        self._coordinator.cache.invalidate(growspace_id)

        # Save and refresh
        await self._coordinator.async_commit()
        await self._coordinator.async_refresh()
        _LOGGER.info("Updated irrigation config for %s", growspace_id)

    async def take_clones(
        self,
        mother_plant_id: str,
        num_clones: int,
        target_growspace_id: str | None = None,
        target_growspace_name: str | None = None,
        transition_date: date | None = None,
    ) -> list[Plant]:
        """Create multiple clones from a mother plant.

        Args:
            mother_plant_id: The ID of the mother plant.
            num_clones: The number of clones to create.
            target_growspace_id: The ID of the target growspace.
            target_growspace_name: The name of the target growspace.
            transition_date: The date of the transition.

        Returns:
            A list of newly created Plant objects.
        """
        return await self._coordinator.plant_manager.take_clones(
            mother_plant_id=mother_plant_id,
            num_clones=num_clones,
            target_growspace_id=target_growspace_id,
            target_growspace_name=target_growspace_name,
            transition_date=transition_date,
        )

    async def promote_clone(
        self,
        clone_id: str,
        target_growspace_id: str = "veg",
        transition_date: date | None = None,
    ) -> None:
        """Promote a clone to the vegetative stage.

        Args:
            clone_id: The ID of the clone to promote.
            target_growspace_id: The ID of the target growspace.
            transition_date: The date of the transition.
        """
        await self._coordinator.plant_manager.promote_clone(
            clone_id, target_growspace_id, transition_date
        )

    async def switch_plants(self, plant1_id: str, plant2_id: str) -> None:
        """Switch the positions of two plants.

        Args:
            plant1_id: The ID of the first plant.
            plant2_id: The ID of the second plant.
        """
        await self._coordinator.plant_manager.switch_plants(plant1_id, plant2_id)

    async def move_plant(self, plant_id: str, new_row: int, new_col: int) -> None:
        """Move a plant to a new position.

        Args:
            plant_id: The ID of the plant to move.
            new_row: The new row position.
            new_col: The new column position.
        """
        await self._coordinator.plant_manager.move_plant(plant_id, new_row, new_col)

    async def transition_plant_stage(
        self,
        plant_id: str,
        new_stage: str | PlantStage,
        transition_date: date | None = None,
    ) -> None:
        """Transition a plant to a new growth stage.

        Args:
            plant_id: The ID of the plant to transition.
            new_stage: The new growth stage.
            transition_date: Optional date for the transition.
        """
        await self._coordinator.plant_manager.transition_plant_stage(
            plant_id, new_stage, transition_date
        )

    async def harvest(self, plant_id: str) -> Plant:
        """Mark a plant as harvested."""
        return await self._coordinator.plant_manager.harvest(plant_id)

    async def harvest_plant(
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
        await self._coordinator.plant_manager.harvest_plant(
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

    # =========================================================================
    # WATERING AND NUTRIENTS
    # =========================================================================

    async def water_plant(
        self,
        plant_id: str,
        amount: float,
        nutrients: dict[str, float] | None = None,
        preset_id: str | None = None,
    ) -> Plant:
        """Record a watering event for a single plant."""
        return await self._coordinator.watering_service.async_water_plant(
            plant_id, amount, nutrients, preset_id
        )

    async def water_growspace(
        self,
        growspace_id: str,
        amount_per_plant: float | None = None,
        nutrients: dict[str, float] | None = None,
        preset_id: str | None = None,
        amount: float | None = None,
    ) -> int:
        """Record a watering event for all plants in a growspace."""
        return await self._coordinator.watering_service.async_water_growspace(
            growspace_id, amount_per_plant, nutrients, preset_id, amount
        )

    async def save_nutrient_preset(
        self,
        name: str,
        nutrients: list[dict[str, Any]],
        stage: str | None = None,
        min_days_in_stage: int | None = None,
        preset_id: str | None = None,
    ) -> NutrientPreset:
        """Create or update a nutrient preset."""
        return await self._coordinator.nutrient_manager.async_save_nutrient_preset(
            name, nutrients, stage, min_days_in_stage, preset_id
        )

    async def remove_nutrient_preset(self, preset_id: str) -> None:
        """Remove a nutrient preset."""
        await self._coordinator.nutrient_manager.async_remove_nutrient_preset(preset_id)

    def get_applicable_presets(self, plant_id: str) -> list[NutrientPreset]:
        """Get all presets applicable to a plant."""
        return self._coordinator.nutrient_manager.get_applicable_presets(plant_id)

    # =========================================================================
    # IPM AND TRAINING
    # =========================================================================

    async def log_training_event(
        self,
        growspace_id: str | None,
        technique: str,
        notes: str | None = None,
        plant_ids: list[str] | None = None,
    ) -> None:
        """Log a training event for specific plants or an entire growspace."""
        await self._coordinator.training_service.async_log_training_event(
            growspace_id, technique, notes, plant_ids
        )

    async def save_ipm_preset(
        self,
        name: str,
        preset_type: str | None = None,
        items: list[dict[str, Any]] | None = None,
        stage: str | None = None,
        min_days_in_stage: int | None = None,
        preset_id: str | None = None,
        **kwargs: Any,
    ) -> IPMPreset:
        """Create or update an IPM preset."""
        # Handle legacy 'type' argument
        if preset_type is None and "type" in kwargs:
            preset_type = kwargs["type"]

        # Ensure we have required values (either from args or kwargs)
        if preset_type is None:
            raise TypeError(
                "save_ipm_preset() missing 1 required positional argument: 'preset_type'"
            )
        if items is None and "items" in kwargs:
            items = kwargs["items"]
        if items is None:
            raise TypeError(
                "save_ipm_preset() missing 1 required positional argument: 'items'"
            )

        return await self._coordinator.ipm_service.async_save_ipm_preset(
            name, preset_type, items, stage, min_days_in_stage, preset_id
        )

    async def remove_ipm_preset(self, preset_id: str) -> None:
        """Remove an IPM preset."""
        await self._coordinator.ipm_service.async_remove_ipm_preset(preset_id)

    async def apply_ipm(
        self,
        preset_id: str,
        growspace_id: str | None = None,
        plant_ids: list[str] | None = None,
        notes: str | None = None,
    ) -> list[str]:
        """Log an IPM application event."""
        return await self._coordinator.ipm_service.async_apply_ipm(
            preset_id, growspace_id, plant_ids, notes
        )

    # =========================================================================
    # DRAIN AND ENVIRONMENTAL LOGGING
    # =========================================================================

    async def log_drain_reading(
        self,
        growspace_id: str,
        feed_ec: float,
        drain_ec: float,
        drain_volume_ml: float | None = None,
        feed_volume_ml: float | None = None,
    ) -> None:
        """Log a drain EC reading for a growspace."""
        growspace = self._coordinator.growspaces.get(growspace_id)
        if not growspace:
            raise ServiceValidationError(f"Growspace '{growspace_id}' not found")

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

        await self._coordinator.async_commit()

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
            await self._coordinator.notification_manager.async_send_notification(
                growspace_id,
                f"⚠️ High drain EC in {growspace.name}",
                f"Drain EC delta ({ec_delta:.2f}) exceeds threshold ({drain_config.max_ec_delta:.2f}).",
                tier="drain_ec",
            )

    async def _async_auto_harvest(self) -> None:
        """Automatically harvest plants based on their transition date."""
        today = dt_util.now().date().isoformat()
        plants_to_harvest = [
            plant
            for plant in self._coordinator.plants.values()
            if plant.transition_date
            and plant.transition_date <= today
            and plant.stage == PlantStage.FLOWER
        ]

        for plant in plants_to_harvest:
            # Check for plants whose transition date is today or in the past
            if plant.transition_date <= today:
                plant_id = plant.plant_id
                strain_name = plant.genetics.strain_name
                gs_id = plant.growspace_id

                _LOGGER.info(
                    "Auto-harvesting plant %s (%s) in %s",
                    plant_id,
                    strain_name,
                    gs_id,
                )

                # Execute harvest
                await self._coordinator.plant_manager.harvest(
                    plant_id=plant_id,
                    transition_date=today,
                )

                # Notify
                await self._coordinator.notification_manager.async_send_notification(
                    growspace_id=gs_id,
                    title="Auto-harvest complete",
                    message=f"Plant {strain_name} has been auto-harvested",
                    tier=NotificationTier.INFO,
                )

    async def remove_plant(self, plant_id: str) -> bool:
        """Remove a plant and its associated entities."""
        # Logical removal
        removed = await self._coordinator.plant_manager.remove_plant(plant_id)

        # Entity removal (cleanup)
        if removed:
            await self._remove_plant_entities(plant_id)

        return removed

    async def _remove_plant_entities(self, plant_id: str) -> None:
        """Remove all Home Assistant entities associated with a specific plant."""
        entity_registry = er.async_get(self._coordinator.hass)

        # Find all entities belonging to this plant
        for entity_id, entry in list(entity_registry.entities.items()):
            if entry.unique_id.startswith(plant_id):
                _LOGGER.info("Removing entity %s for plant %s", entity_id, plant_id)
                entity_registry.async_remove(entity_id)

    async def configure_drain_monitoring(
        self,
        growspace_id: str,
        enabled: bool | None = None,
        max_ec_delta: float | None = None,
        target_runoff_percent: float | None = None,
    ) -> None:
        """Configure drain EC monitoring settings for a growspace."""
        growspace = self._coordinator.growspaces.get(growspace_id)
        if not growspace:
            raise ServiceValidationError(f"Growspace '{growspace_id}' not found")

        drain_config = growspace.drain_config
        if enabled is not None:
            drain_config.enabled = enabled
        if max_ec_delta is not None:
            drain_config.max_ec_delta = max_ec_delta
        if target_runoff_percent is not None:
            drain_config.target_runoff_percent = target_runoff_percent

        await self._coordinator.async_commit()

    async def reset_water_tracking(self, growspace_id: str) -> None:
        """Reset water usage counters for a growspace."""
        growspace = self._coordinator.growspaces.get(growspace_id)
        if not growspace:
            raise ServiceValidationError(f"Growspace '{growspace_id}' not found")

        growspace.water_usage = WaterUsageData(
            cycle_start_date=dt_util.now().date().isoformat()
        )
        await self._coordinator.async_commit()
        _LOGGER.info("Reset water tracking for growspace %s", growspace_id)

    async def configure_tank(
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
            await self._coordinator.async_commit()

    async def save_ec_ramp_curve(
        self,
        growspace_id: str | None = None,
        name: str | None = None,
        points: list[dict[str, Any]] | None = None,
        curve_id: str | None = None,
        **kwargs: Any,
    ) -> ECRampCurve:
        """Save an EC ramp curve."""
        # Handle missing growspace_id (legacy tests)
        if growspace_id is None:
            # Try to get the first growspace
            gids = list(self._coordinator.growspaces.keys())
            if not gids:
                raise ValueError("No growspaces available to save EC ramp curve")
            growspace_id = gids[0]
            _LOGGER.warning(
                "Legacy call to save_ec_ramp_curve missing growspace_id. Using default: %s",
                growspace_id,
            )

        # Handle legacy 'stage' instead of points if needed (unlikely but being safe)
        # Or if points is missing but provided in kwargs
        if points is None and "points" in kwargs:
            points = kwargs["points"]

        if name is None and "name" in kwargs:
            name = kwargs["name"]

        if name is None or points is None:
            raise TypeError("save_ec_ramp_curve() missing required arguments")

        return await self._coordinator.nutrient_manager.async_save_ec_ramp_curve(
            growspace_id, name, points, curve_id
        )

    async def remove_ec_ramp_curve(
        self, growspace_id: str | None, curve_id: str
    ) -> None:
        """Remove an EC ramp curve from a growspace."""
        await self._coordinator.nutrient_manager.async_remove_ec_ramp_curve(curve_id)

    async def add_timeline_note(
        self,
        plant_id: str,
        notes: str,
        timestamp: str | None = None,
        images_base64: list[str] | None = None,
        tags: list[str] | None = None,
        ph: float | None = None,
        ec: float | None = None,
        amount_ml: float | None = None,
        external_metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add a timeline note to a plant."""
        if images_base64 is None:
            images_base64 = []
        if tags is None:
            tags = []
        if external_metadata is None:
            external_metadata = {}

        plant = self._coordinator.plants.get(plant_id)
        if not plant:
            raise ServiceValidationError(f"Plant {plant_id} not found")

        growspace_id = plant.growspace_id

        # 1. Fetch current sensor snapshot
        metadata = {}
        if growspace := self._coordinator.growspaces.get(growspace_id):
            env_config = growspace.environment_config

            def _get_state(entity_id: str | None) -> float | None:
                if not entity_id:
                    return None
                state = self._coordinator.hass.states.get(entity_id)
                try:
                    if state and state.state not in ("unknown", "unavailable"):
                        return float(state.state)
                except ValueError:
                    pass
                return None

            metadata.update(
                {
                    "temperature": _get_state(env_config.temperature_sensor),
                    "humidity": _get_state(env_config.humidity_sensor),
                    "vpd": _get_state(env_config.vpd_sensor),
                    "soil_moisture": _get_state(env_config.soil_moisture_sensor),
                    "light_intensity": _get_state(env_config.light_sensor),
                }
            )

        # Add optional action data to metadata
        if ph is not None:
            metadata["ph"] = ph
        if ec is not None:
            metadata["ec"] = ec
        if amount_ml is not None:
            metadata["amount_ml"] = amount_ml

        # Merge with external metadata (if any)
        metadata.update(external_metadata)

        # 2. Process images
        image_paths = []
        if images_base64 and self._coordinator.strain_library:
            image_manager = self._coordinator.strain_library.image_manager
            if image_manager:
                for img_b64 in images_base64:
                    try:
                        abs_path = await image_manager.save_timeline_image(
                            plant_id=plant_id,
                            image_base64=img_b64,
                            timestamp=timestamp,
                        )
                        image_paths.append(f"timeline/{Path(abs_path).name}")
                    except Exception as e:
                        _LOGGER.error("Failed to save timeline image: %s", e)

        # 3. Fire event for persistence
        event_data = {
            "plant_id": plant_id,
            "growspace_id": growspace_id,
            "notes": notes,
            "tags": tags,
            "metadata": metadata,
            "images": image_paths,
            "category": CATEGORY_NOTE,
            "timestamp": timestamp or dt_util.now().isoformat(),
        }

        self._coordinator.hass.bus.async_fire(EVENT_GROWSPACE_LOG_ENTRY, event_data)
        _LOGGER.info("Added timeline note for plant %s", plant_id)

    async def score_plant(
        self,
        plant_id: str,
        vigor: int | None = None,
        structure: int | None = None,
        aroma: int | None = None,
        resin: int | None = None,
        pest_resistance: int | None = None,
    ) -> None:
        """Score a plant's phenotype performance."""
        plant = self._coordinator.plants.get(plant_id)
        if not plant:
            raise ServiceValidationError(f"Plant {plant_id} not found")

        ps = plant.phenotype_score
        if vigor is not None:
            ps.vigor = vigor
        if structure is not None:
            ps.internodal_spacing = structure
        if aroma is not None:
            ps.terpene_intensity = aroma
        if resin is not None:
            ps.resin = resin
        if pest_resistance is not None:
            ps.mold_resistance = pest_resistance

        await self._coordinator.plant_manager.update_plant(plant_id, phenotype_score=ps)
        _LOGGER.info("Plant %s phenotype scored", plant_id)

    async def update_harvest_metrics(
        self,
        plant_id: str,
        wet_weight: float | None = None,
        dry_weight: float | None = None,
        trim_weight: float | None = None,
        thc_percentage: float | None = None,
        cbd_percentage: float | None = None,
        terpene_profile: str | None = None,
    ) -> None:
        """Update harvest metrics for a plant."""
        plant = self._coordinator.plants.get(plant_id)
        if not plant:
            raise ServiceValidationError(f"Plant {plant_id} not found")

        metrics = plant.harvest_metrics
        updated = False

        if wet_weight is not None:
            metrics.wet_weight = wet_weight
            updated = True
        if dry_weight is not None:
            metrics.dry_weight = dry_weight
            updated = True
        if trim_weight is not None:
            metrics.trim_weight = trim_weight
            updated = True
        if thc_percentage is not None:
            metrics.thc_percentage = thc_percentage
            updated = True
        if cbd_percentage is not None:
            metrics.cbd_percentage = cbd_percentage
            updated = True
        if terpene_profile is not None:
            metrics.terpene_profile = terpene_profile
            updated = True

        if updated:
            await self._coordinator.plant_manager.update_plant(
                plant_id, harvest_metrics=metrics
            )
            _LOGGER.info("Plant %s harvest metrics updated", plant_id)

    # =========================================================================
    # STRAIN LIBRARY METHODS
    # =========================================================================

    def get_strain_options(self) -> list[str]:
        """Get a sorted list of unique strain names from the library."""
        if not self._coordinator.strain_library:
            return []
        return sorted(self._coordinator.strain_library.get_all().keys())

    def export_strain_library(self) -> list[str]:
        """Export all strains from the library."""
        return self.get_strain_options()

    async def clear_strains(self) -> int:
        """Remove all strains from the library."""
        if not self._coordinator.strain_library:
            return 0
        return await self._coordinator.strain_library.clear()

    # =========================================================================
    # PLANT QUERY METHODS
    # =========================================================================

    def get_growspace_plants(self, growspace_id: str) -> list[Plant]:
        """Get all plants located in a specific growspace."""
        return self._coordinator.data_repository.get_growspace_plants(growspace_id)

    def get_plant(self, plant_id: str) -> Plant | None:
        """Retrieve a plant by its ID."""
        return self._coordinator.data_repository.get_plant(plant_id)

    def get_tank_tracker(
        self, growspace_id: str, tank_entity: str
    ) -> TankWaterTracker | None:
        """Return the TankWaterTracker for a tank, or None if not configured."""
        growspace = self.get_growspace(growspace_id)
        if growspace is None:
            _LOGGER.debug("No growspace found for %s", growspace_id)
            return None
        tank = next(
            (
                t
                for t in growspace.environment_config.irrigation_tanks
                if t.sensor_entity == tank_entity
            ),
            None,
        )
        if tank is None:
            _LOGGER.debug(
                "No tank found for entity %s in growspace %s", tank_entity, growspace_id
            )
            return None
        if tank.volume_liters is None:
            _LOGGER.debug(
                "Tank %s in growspace %s has no volume defined",
                tank_entity,
                growspace_id,
            )
            return None

        gs_trackers = self._tank_water_trackers.setdefault(growspace_id, {})
        if tank_entity not in gs_trackers:
            _LOGGER.debug(
                "Creating new TankWaterTracker for %s in %s", tank_entity, growspace_id
            )
            gs_trackers[tank_entity] = TankWaterTracker(tank)
        return gs_trackers[tank_entity]

    async def async_unsubscribe_all_trackers(self) -> None:
        """Unsubscribe all tank water trackers on shutdown."""
        for gs_trackers in self._tank_water_trackers.values():
            for tracker in gs_trackers.values():
                await tracker.async_unsubscribe()
        self._tank_water_trackers.clear()

    def get_growspace_data(self, growspace_id: str | None = None) -> dict[str, Any]:
        """Get full data for a growspace (or all growspaces) for WebSocket API."""
        if growspace_id:
            if growspace_id not in self._coordinator.growspaces:
                return {}
            return self.build_growspace_payload(growspace_id)

        # Return all
        return {
            gid: self.build_growspace_payload(gid)
            for gid in self._coordinator.growspaces
        }

    def build_growspace_payload(self, growspace_id: str) -> dict[str, Any]:
        """Build the full JSON payload for a single growspace."""
        return self._coordinator.view_model_builder.build_serialized_growspace(
            growspace_id
        )

    def guess_overview_entity_id(self, growspace_id: str) -> str:
        """Make a best-effort guess of the overview sensor entity ID for a growspace."""
        # Try to look up via Entity Registry using consistent unique_id
        unique_id = generate_growspace_overview_unique_id(growspace_id)
        registry: er.EntityRegistry = er.async_get(self._coordinator.hass)
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
        if entity_id:
            return entity_id  # type: ignore[no-any-return]

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
        growspace = self.get_growspace(growspace_id)
        name = getattr(growspace, "name", growspace_id) if growspace else growspace_id
        slug = slugify(str(name).replace(" ", "_"))
        return f"sensor.{slug}"

    def should_send_notification(self, plant_id: str, stage: str, days: int) -> bool:
        """Check if a notification for a specific event has already been sent."""
        return (
            not self._coordinator.notifications_sent.get(plant_id, {})
            .get(stage, {})
            .get(str(days), False)
        )

    async def mark_notification_sent(
        self, plant_id: str, stage: str, days: int
    ) -> None:
        """Mark a notification as sent to prevent duplicates."""
        if plant_id not in self._coordinator.notifications_sent:
            self._coordinator.notifications_sent[plant_id] = {}

        if stage not in self._coordinator.notifications_sent[plant_id]:
            self._coordinator.notifications_sent[plant_id][stage] = {}

        self._coordinator.notifications_sent[plant_id][stage][str(days)] = True
        await self._coordinator.async_commit()

    def fire_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Fire a growspace manager event."""
        payload = {"event_type": event_type, "data": data}
        self._coordinator.hass.bus.async_fire("growspace_manager_updated", payload)

    def handle_position_update(
        self,
        plant_id: str,
        plant: Plant,
        force_position: bool,
        kwargs: dict[str, Any],
    ) -> None:
        """Validate and handle updates to a plant's position.

        Args:
            plant_id: The ID of the plant.
            plant: The Plant object.
            force_position: Whether to bypass occupied position check.
            kwargs: Parameters that may contain row and col.
        """
        new_row = kwargs.get("row")
        new_col = kwargs.get("col")

        if new_row is not None or new_col is not None:
            growspace_id = plant.growspace_id
            if new_row is None:
                new_row = plant.row
            if new_col is None:
                new_col = plant.col

            # 1. Bounds check
            self._coordinator.validator.validate_position_bounds(
                growspace_id, new_row, new_col
            )

            # 2. Occupancy check
            if not force_position:
                self._coordinator.validator.validate_position_not_occupied(
                    growspace_id, new_row, new_col, plant_id
                )

    def validate_plants_after_growspace_resize(
        self, growspace_id: str, new_rows: int, new_plants_per_row: int
    ) -> None:
        """Trigger background validation of plants after resizing a growspace."""
        self._coordinator.config_entry.async_create_background_task(
            self._coordinator.hass,
            self._coordinator.growspace_manager._validate_plants_after_growspace_resize(  # noqa: SLF001
                growspace_id, new_rows, new_plants_per_row
            ),
            f"validate_plants_{growspace_id}",
        )
