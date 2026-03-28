"""Service facade for the Growspace Manager integration.

This module provides a unified interface for all domain services,
reducing the complexity and size of the main GrowspaceCoordinator.
"""

from __future__ import annotations

from datetime import date
import logging
from typing import TYPE_CHECKING, Any

from custom_components.growspace_manager.const import (
    DOMAIN,
    VERSION,
    NotificationTier,
    PlantStage,
)
from custom_components.growspace_manager.models import (
    DrainReading,
    Growspace,
    IPMPreset,
    NutrientPreset,
    Plant,
    WaterUsageData,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


class ServiceFacade:
    """Facade for all Growspace Manager services.

    This class centralizes delegation to specialized services and managers,
    allowing the GrowspaceCoordinator to focus on core coordination tasks.
    """

    def __init__(self, coordinator: GrowspaceCoordinator) -> None:
        """Initialize the service facade.

        Args:
            coordinator: The GrowspaceCoordinator instance.
        """
        self._coordinator = coordinator

    async def add_growspace(self, **kwargs: Any) -> Growspace:
        """Add a new growspace and register it with Home Assistant.

        Args:
            **kwargs: Growspace configuration parameters.

        Returns:
            The newly created Growspace object.
        """
        growspace = await self._coordinator.growspace_manager.async_add_growspace(**kwargs)

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
        await self._coordinator.subsystem_manager.async_setup_growspace_sub_coordinators(
            growspace.id, growspace
        )

        return growspace

    async def update_growspace(self, growspace_id: str, **kwargs: Any) -> Growspace:
        """Update an existing growspace's configuration.

        Args:
            growspace_id: The ID of the growspace to update.
            **kwargs: Configuration parameters to update.

        Returns:
            The updated Growspace object.
        """
        growspace = await self._coordinator.growspace_manager.async_update_growspace(
            growspace_id, **kwargs
        )

        # Update device name if changed
        if "name" in kwargs:
            device_registry = dr.async_get(self._coordinator.hass)
            if device := device_registry.async_get_device(
                identifiers={(DOMAIN, growspace_id)}
            ):
                device_registry.async_update_device(device.id, name=kwargs["name"])

        return growspace

    async def add_plant(self, **kwargs: Any) -> Plant:
        """Add a new plant.

        Args:
            **kwargs: Plant configuration parameters.

        Returns:
            The newly created Plant object.
        """
        plant = await self._coordinator.plant_manager.async_add_plant(**kwargs)

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

        return plant

    async def update_plant(self, plant_id: str, **kwargs: Any) -> Plant:
        """Update an existing plant's configuration.

        Args:
            plant_id: The ID of the plant to update.
            **kwargs: Configuration parameters to update.

        Returns:
            The updated Plant object.
        """
        plant = await self._coordinator.plant_manager.async_update_plant(plant_id, **kwargs)

        # Update device name if changed
        if "name" in kwargs:
            device_registry = dr.async_get(self._coordinator.hass)
            if device := device_registry.async_get_device(
                identifiers={(DOMAIN, plant_id)}
            ):
                device_registry.async_update_device(device.id, name=kwargs["name"])

        return plant

    async def remove_growspace(self, growspace_id: str) -> None:
        """Remove a growspace from the manager."""
        await self._coordinator.async_remove_growspace(growspace_id)

    async def update_options(self, options: dict[str, Any]) -> None:
        """Update integration options."""
        await self._coordinator.async_update_options(options)

    async def async_set_lighting_schedule(
        self,
        growspace_id: str,
        veg_hours: int,
        flower_hours: int,
        dli_veg: float | None = None,
    ) -> None:
        """Set the lighting schedule for a growspace."""
        await self._coordinator.async_set_lighting_schedule(
            growspace_id, veg_hours, flower_hours, dli_veg
        )

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
        return await self._coordinator.plant_manager.async_take_clones(
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
        await self._coordinator.plant_manager.async_promote_clone(
            clone_id, target_growspace_id, transition_date
        )

    async def switch_plants(self, plant1_id: str, plant2_id: str) -> None:
        """Switch the positions of two plants.

        Args:
            plant1_id: The ID of the first plant.
            plant2_id: The ID of the second plant.
        """
        await self._coordinator.plant_manager.async_switch_plants(plant1_id, plant2_id)

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
        preset_type: str,
        items: list[dict[str, Any]],
        stage: str | None = None,
        min_days_in_stage: int | None = None,
        preset_id: str | None = None,
    ) -> IPMPreset:
        """Create or update an IPM preset."""
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
                tier="drain_ec", # Changed from category to tier
            )

    async def _async_auto_harvest(self) -> None:
        """Automatically harvest plants based on their transition date."""
        today = dt_util.now().date().isoformat()
        plants_to_harvest = [
            plant
            for plant in self._coordinator.plants.values()
            if plant.transition_date and plant.transition_date <= today and plant.stage == PlantStage.FLOWER
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

    async def configure_tank(
        self,
        growspace_id: str,
        tank_entity: str,
        *,
        volume_liters: float | None = None,
    ) -> None:
        """Update runtime configuration for an irrigation tank."""
        growspace = self._coordinator.get_growspace(growspace_id)
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
        growspace_id: str,
        name: str,
        stage: str,
        points: list[dict[str, Any]],
        curve_id: str | None = None,
    ) -> None:
        """Save/update an EC ramp curve for a growspace."""
        # EC ramp curves are managed by NutrientManager
        await self._coordinator.nutrient_manager.async_save_ec_ramp_curve(
            name=name,
            stage=stage,
            points=points,
            curve_id=curve_id,
        )

    async def remove_ec_ramp_curve(self, growspace_id: str | None, curve_id: str) -> None:
        """Remove an EC ramp curve from a growspace."""
        await self._coordinator.nutrient_manager.async_remove_ec_ramp_curve(curve_id)
