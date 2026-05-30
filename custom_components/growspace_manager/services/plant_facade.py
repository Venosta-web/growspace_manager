"""Plant sub-facade for the Growspace Manager integration."""

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
    MoistureEntry,
    NutrientPreset,
    Plant,
    WeightEntry,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


class PlantFacade:
    """Facade for all plant lifecycle and mutation operations."""

    def __init__(self, coordinator: GrowspaceCoordinator) -> None:
        """Initialise the facade with the coordinator."""
        self._coordinator = coordinator

    # -------------------------------------------------------------------------
    # CRUD
    # -------------------------------------------------------------------------

    @property
    def plants(self) -> dict[str, Plant]:
        """Return all plants keyed by plant_id."""
        return self._coordinator.plants

    def get_plant(self, plant_id: str) -> Plant | None:
        """Return a plant by ID."""
        return self._coordinator.data_repository.get_plant(plant_id)

    def get_applicable_presets(self, plant_id: str) -> list[NutrientPreset]:
        """Return all nutrient presets applicable to a plant."""
        return self._coordinator.nutrient_manager.get_applicable_presets(plant_id)

    async def add_plant(self, **kwargs: Any) -> Plant:
        """Add a new plant and register its HA device."""
        plant = await self._coordinator.plant_manager.add_plant(**kwargs)
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
            "Added plant %s (%s) to %s",
            strain_name,
            plant.plant_id,
            plant.growspace_id,
        )
        return plant

    async def update_plant(self, plant_id: str, **kwargs: Any) -> Plant:
        """Update an existing plant and sync its HA device name if changed."""
        plant = await self._coordinator.plant_manager.update_plant(plant_id, **kwargs)
        if "name" in kwargs:
            device_registry = dr.async_get(self._coordinator.hass)
            if device := device_registry.async_get_device(
                identifiers={(DOMAIN, plant_id)}
            ):
                device_registry.async_update_device(device.id, name=kwargs["name"])
        _LOGGER.info("Updated plant %s", plant_id)
        return plant

    async def remove_plant(self, plant_id: str) -> bool:
        """Remove a plant and its associated HA entities."""
        removed = await self._coordinator.plant_manager.remove_plant(plant_id)
        if removed:
            await self.remove_plant_entities(plant_id)
        return removed

    async def async_remove_plant(self, plant_id: str, **kwargs: Any) -> bool:
        """Alias for remove_plant."""
        return await self.remove_plant(plant_id)

    async def remove_plant_entities(self, plant_id: str) -> None:
        """Remove all HA entities associated with a plant."""
        entity_registry = er.async_get(self._coordinator.hass)
        for entity_id, entry in list(entity_registry.entities.items()):
            if entry.unique_id.startswith(plant_id):
                _LOGGER.info("Removing entity %s for plant %s", entity_id, plant_id)
                entity_registry.async_remove(entity_id)

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    async def add_mother_plant(
        self,
        phenotype: str,
        strain: str,
        row: int,
        col: int,
        mother_start: date | None = None,
        **kwargs: Any,
    ) -> Plant:
        """Add a new mother plant."""
        plant = await self._coordinator.plant_manager.add_mother_plant(
            phenotype=phenotype,
            strain=strain,
            row=row,
            col=col,
            mother_start=mother_start,
            **kwargs,
        )
        await self._coordinator.async_request_refresh()
        return plant

    async def take_clones(
        self,
        mother_plant_id: str,
        num_clones: int,
        target_growspace_id: str | None = None,
        target_growspace_name: str | None = None,
        transition_date: date | None = None,
    ) -> list[Plant]:
        """Create clones from a mother plant."""
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
        """Promote a clone to the vegetative stage."""
        await self._coordinator.plant_manager.promote_clone(
            clone_id=clone_id,
            target_growspace_id=target_growspace_id,
            transition_date=transition_date,
        )

    async def switch_plants(self, plant1_id: str, plant2_id: str) -> None:
        """Switch the positions of two plants."""
        await self._coordinator.plant_manager.switch_plants(plant1_id, plant2_id)

    async def move_plant(self, plant_id: str, new_row: int, new_col: int) -> None:
        """Move a plant to a new grid position."""
        await self._coordinator.plant_manager.move_plant(plant_id, new_row, new_col)

    async def transition_plant_stage(
        self,
        plant_id: str,
        new_stage: str | PlantStage,
        transition_date: date | None = None,
    ) -> None:
        """Transition a plant to a new growth stage."""
        await self._coordinator.plant_manager.transition_plant_stage(
            plant_id, new_stage, transition_date
        )

    async def harvest(self, plant_id: str) -> Plant:
        """Mark a plant as harvested."""
        return await self._coordinator.plant_manager.harvest(plant_id)

    async def transition_plant(
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
        """Transition a plant out of its current growspace (harvest or move)."""
        await self._coordinator.plant_manager.transition_plant(
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

    async def async_transition_plant(
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
        """Alias for transition_plant."""
        await self.transition_plant(
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

    async def _async_auto_harvest(self) -> None:
        """Automatically harvest plants whose transition date has passed."""
        today = dt_util.now().date().isoformat()
        plants_to_harvest = [
            plant
            for plant in self._coordinator.plants.values()
            if plant.transition_date
            and plant.transition_date <= today
            and plant.stage == PlantStage.FLOWER
        ]
        for plant in plants_to_harvest:
            plant_id = plant.plant_id
            strain_name = plant.genetics.strain_name
            gs_id = plant.growspace_id
            _LOGGER.info(
                "Auto-harvesting plant %s (%s) in %s", plant_id, strain_name, gs_id
            )
            await self._coordinator.plant_manager.harvest(
                plant_id=plant_id,
                transition_date=today,
            )
            await self._coordinator.notification_manager.async_send_notification(
                growspace_id=gs_id,
                title="Auto-harvest complete",
                message=f"Plant {strain_name} has been auto-harvested",
                tier=NotificationTier.INFO,
            )

    # -------------------------------------------------------------------------
    # Watering and IPM
    # -------------------------------------------------------------------------

    async def water_plant(
        self,
        plant_id: str,
        amount: float,
        nutrients: dict[str, float] | None = None,
        preset_id: str | None = None,
    ) -> Plant:
        """Record a watering event for a plant."""
        return await self._coordinator.watering_service.async_water_plant(
            plant_id, amount, nutrients, preset_id
        )

    async def reset_last_watered(self, plant_id: str) -> None:
        """Clear the last_watered timestamp for a plant.

        Intended for use by E2E test fixtures only — not exposed in the UI.
        """
        plant = self._coordinator.plants.get(plant_id)
        if not plant:
            raise ServiceValidationError(f"Plant '{plant_id}' not found")
        plant.last_watered = None
        await self._coordinator.async_commit()

    async def apply_ipm(
        self,
        preset_id: str | None = None,
        growspace_id: str | None = None,
        plant_ids: list[str] | None = None,
        notes: str | None = None,
    ) -> list[str]:
        """Log an IPM application event."""
        return await self._coordinator.ipm_service.async_apply_ipm(
            preset_id, growspace_id, plant_ids, notes
        )

    async def log_training_event(
        self,
        growspace_id: str | None,
        technique: str,
        notes: str | None = None,
        plant_ids: list[str] | None = None,
    ) -> None:
        """Log a training event."""
        await self._coordinator.training_service.async_log_training_event(
            growspace_id, technique, notes, plant_ids
        )

    # -------------------------------------------------------------------------
    # Drying
    # -------------------------------------------------------------------------

    async def log_drying_weight(
        self,
        plant_id: str,
        weight_grams: float,
        date: str | None = None,
    ) -> None:
        """Append a weight entry to a plant's drying log."""
        plant = self._coordinator.plants.get(plant_id)
        if not plant:
            raise ServiceValidationError(f"Plant '{plant_id}' not found")
        entry_date = date or dt_util.now().date().isoformat()
        plant.drying_data.weight_log.append(
            WeightEntry(date=entry_date, weight_grams=weight_grams)
        )
        await self._coordinator.async_commit()

    async def log_moisture_reading(
        self,
        plant_id: str,
        moisture_percent: float,
        date: str | None = None,
    ) -> None:
        """Append a moisture entry to a plant's drying log."""
        plant = self._coordinator.plants.get(plant_id)
        if not plant:
            raise ServiceValidationError(f"Plant '{plant_id}' not found")
        entry_date = date or dt_util.now().date().isoformat()
        plant.drying_data.moisture_log.append(
            MoistureEntry(date=entry_date, moisture_percent=moisture_percent)
        )
        await self._coordinator.async_commit()

    async def set_visual_tag(self, plant_id: str, visual_tag: str | None) -> None:
        """Set or clear the visual tag on a plant."""
        plant = self._coordinator.plants.get(plant_id)
        if not plant:
            raise ServiceValidationError(f"Plant '{plant_id}' not found")
        plant.drying_data.visual_tag = visual_tag
        await self._coordinator.async_commit()

    # -------------------------------------------------------------------------
    # Scoring and metrics
    # -------------------------------------------------------------------------

    async def score_plant(
        self,
        plant_id: str,
        vigor: int | None = None,
        structure: int | None = None,
        aroma: int | None = None,
        resin: int | None = None,
        pest_resistance: int | None = None,
        internodal_spacing: int | None = None,
        terpene_intensity: int | None = None,
        mold_resistance: int | None = None,
        yield_potential: int | None = None,
        keeper: bool | None = None,
        notes: str | None = None,
    ) -> None:
        """Score a plant's phenotype performance."""
        plant = self._coordinator.plants.get(plant_id)
        if not plant:
            raise ServiceValidationError(f"Plant {plant_id} not found")
        ps = plant.phenotype_score
        if vigor is not None:
            ps.vigor = vigor
        if internodal_spacing is not None:
            ps.internodal_spacing = internodal_spacing
        elif structure is not None:
            ps.internodal_spacing = structure
        if terpene_intensity is not None:
            ps.terpene_intensity = terpene_intensity
        elif aroma is not None:
            ps.terpene_intensity = aroma
        if resin is not None:
            ps.resin = resin
        if mold_resistance is not None:
            ps.mold_resistance = mold_resistance
        elif pest_resistance is not None:
            ps.mold_resistance = pest_resistance
        if yield_potential is not None:
            ps.yield_potential = yield_potential
        if keeper is not None:
            ps.keeper = keeper
        if notes is not None:
            ps.notes = notes
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
