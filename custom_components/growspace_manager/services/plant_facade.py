"""Plant sub-facade for the Growspace Manager integration."""

from __future__ import annotations

from datetime import date
import logging
from typing import TYPE_CHECKING, Any

from custom_components.growspace_manager.const import (
    ATTR_AMOUNT,
    ATTR_AMOUNT_ML,
    ATTR_COL,
    ATTR_EC,
    ATTR_GROWSPACE_ID,
    ATTR_IMAGES,
    ATTR_METADATA,
    ATTR_NOTES,
    ATTR_PH,
    ATTR_PHENOTYPE,
    ATTR_PLANT_ID,
    ATTR_ROW,
    ATTR_SEED_BATCH_ID,
    ATTR_START_NUMBER,
    ATTR_STRAIN,
    ATTR_TAGS,
    ATTR_TECHNIQUE,
    ATTR_TRANSITION_DATE,
    CANONICAL_ID_MOTHER,
    DATE_FIELDS,
    GrowspaceService,
    NotificationTier,
    PlantStage,
)
from custom_components.growspace_manager.exceptions import GrowspaceError
from custom_components.growspace_manager.models import (
    MoistureEntry,
    NutrientPreset,
    Plant,
    WeightEntry,
)
from custom_components.growspace_manager.schemas import (
    ADD_PLANT_SCHEMA,
    ADD_PLANTS_SCHEMA,
    ADD_TIMELINE_NOTE_SCHEMA,
    LOG_TRAINING_EVENT_SCHEMA,
    REMOVE_PLANT_SCHEMA,
    UPDATE_PLANT_SCHEMA,
)
from custom_components.growspace_manager.services.plant_utils import (
    _ensure_plant_loaded,
    _resolve_plant_id,
)
from custom_components.growspace_manager.strain_library import StrainLibrary
from custom_components.growspace_manager.utils import parse_date_field
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from ._definition import ServiceDefinition
from .utils import handle_service_errors

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
        return self._coordinator._data_repository.get_plant(plant_id)

    def get_applicable_presets(self, plant_id: str) -> list[NutrientPreset]:
        """Return all nutrient presets applicable to a plant."""
        return self._coordinator._nutrient_manager.get_applicable_presets(plant_id)

    async def add_plant(self, **kwargs: Any) -> Plant:
        """Add a new plant."""
        plant = await self._coordinator._plant_manager.add_plant(**kwargs)
        strain_name = plant.genetics.strain_name if plant.genetics else "Unknown"
        _LOGGER.info(
            "Added plant %s (%s) to %s",
            strain_name,
            plant.plant_id,
            plant.growspace_id,
        )
        return plant

    async def update_plant(self, plant_id: str, **kwargs: Any) -> Plant:
        """Update an existing plant."""
        plant = await self._coordinator._plant_manager.update_plant(plant_id, **kwargs)
        _LOGGER.info("Updated plant %s", plant_id)
        return plant

    async def remove_plant(self, plant_id: str) -> bool:
        """Remove a plant and its associated HA entities."""
        removed = await self._coordinator._plant_manager.remove_plant(plant_id)
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
        plant = await self._coordinator._plant_manager.add_mother_plant(
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
        return await self._coordinator._plant_manager.take_clones(
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
        await self._coordinator._plant_manager.promote_clone(
            clone_id=clone_id,
            target_growspace_id=target_growspace_id,
            transition_date=transition_date,
        )

    async def switch_plants(self, plant1_id: str, plant2_id: str) -> None:
        """Switch the positions of two plants."""
        await self._coordinator._plant_manager.switch_plants(plant1_id, plant2_id)

    async def move_plant(self, plant_id: str, new_row: int, new_col: int) -> None:
        """Move a plant to a new grid position."""
        await self._coordinator._plant_manager.move_plant(plant_id, new_row, new_col)

    async def set_plant_layout(
        self,
        growspace_id: str,
        expected_layout_revision: int,
        placements: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Commit a complete revision-guarded Plant Layout."""
        return await self._coordinator._plant_manager.set_plant_layout(
            growspace_id, expected_layout_revision, placements
        )

    async def relocate_to_growspace(
        self, target_growspace_id: str, plant_ids: list[str]
    ) -> list[str]:
        """Relocate plants into a growspace as one layout mutation."""
        return await self._coordinator._plant_manager.relocate_plants_to_growspace(
            target_growspace_id, plant_ids
        )

    async def transition_plant_stage(
        self,
        plant_id: str,
        new_stage: str | PlantStage,
        transition_date: date | None = None,
    ) -> None:
        """Transition a plant to a new growth stage."""
        await self._coordinator._plant_manager.transition_plant_stage(
            plant_id, new_stage, transition_date
        )

    async def harvest(self, plant_id: str) -> Plant:
        """Mark a plant as harvested."""
        return await self._coordinator._plant_manager.harvest(plant_id)

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
        await self._coordinator._plant_manager.transition_plant(
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
            await self._coordinator._plant_manager.harvest(
                plant_id=plant_id,
                transition_date=today,
            )
            await self._coordinator._notification_manager.async_send_notification(
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
        await self._coordinator._plant_manager.update_plant(
            plant_id, phenotype_score=ps
        )
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
            await self._coordinator._plant_manager.update_plant(
                plant_id, harvest_metrics=metrics
            )
            _LOGGER.info("Plant %s harvest metrics updated", plant_id)

    # -------------------------------------------------------------------------
    # Service call adapters
    # -------------------------------------------------------------------------

    def _resolve_position_conflict(
        self,
        growspace_id: str,
        plant_id: str,
        service_data: dict[str, Any],
    ) -> None:
        """Check for position conflicts and resolve if necessary."""
        if ATTR_ROW not in service_data or ATTR_COL not in service_data:
            return

        new_row, new_col = service_data[ATTR_ROW], service_data[ATTR_COL]
        existing_plants = self._coordinator.services.growspaces.get_growspace_plants(
            growspace_id
        )
        is_occupied = any(
            p.plant_id != plant_id and p.row == new_row and p.col == new_col
            for p in existing_plants
        )

        if is_occupied:
            _LOGGER.warning(
                "Position (%d,%d) in growspace %s is occupied. Finding first free space",
                new_row,
                new_col,
                growspace_id,
            )
            free_row, free_col = (
                self._coordinator.validator.find_first_available_position(growspace_id)
            )
            if free_row is not None and free_col is not None:
                _LOGGER.info(
                    "Moving plant %s to first free space: (%d,%d)",
                    plant_id,
                    free_row,
                    free_col,
                )
                service_data[ATTR_ROW] = free_row
                service_data[ATTR_COL] = free_col
            else:
                _LOGGER.error(
                    "No free space found in growspace %s for plant %s. Position will not be updated",
                    growspace_id,
                    plant_id,
                )
                service_data.pop(ATTR_ROW, None)
                service_data.pop(ATTR_COL, None)

    @staticmethod
    def _prepare_update_data(service_data: dict[str, Any]) -> dict[str, Any]:
        """Prepare the dictionary for updating plant data."""
        update_data = {}
        for k, v in service_data.items():
            if k == ATTR_PLANT_ID:
                continue

            if v is None and k not in DATE_FIELDS:
                continue

            if k in DATE_FIELDS:
                parsed_value = parse_date_field(v)
                update_data[k] = parsed_value
                _LOGGER.debug(
                    "UPDATE_PLANT: Parsed date field %s: '%s' -> %s", k, v, parsed_value
                )
            else:
                update_data[k] = v
                _LOGGER.debug("UPDATE_PLANT: Non-date field %s: '%s'", k, v)
        return update_data

    async def add_plant_from_call(
        self,
        hass: HomeAssistant,
        strain_library: StrainLibrary,
        call: ServiceCall,
    ) -> None:
        """Unpack an add_plant ServiceCall and delegate to add_plant."""
        _LOGGER.debug("Service call: add_plant with data: %s", call.data)

        growspace_id = call.data[ATTR_GROWSPACE_ID]
        if growspace_id not in self._coordinator.growspaces:
            _LOGGER.error("Growspace %s does not exist for add_plant", growspace_id)
            raise ServiceValidationError(f"Growspace '{growspace_id}' not found.")

        try:
            row = call.data[ATTR_ROW]
            col = call.data[ATTR_COL]

            add_date_fields = [f for f in DATE_FIELDS if f != "transition_date"]
            parsed_dates = {
                f: parse_date_field(call.data.get(f)) for f in add_date_fields
            }

            if growspace_id == CANONICAL_ID_MOTHER and not parsed_dates.get(
                "mother_start"
            ):
                parsed_dates["mother_start"] = dt_util.utcnow()
                _LOGGER.debug(
                    "Auto-setting mother_start to now for '%s' growspace",
                    CANONICAL_ID_MOTHER,
                )

            seed_batch_id = call.data.get(ATTR_SEED_BATCH_ID)
            batch = (
                self._coordinator.services.genetics.seed_batch_by_id(seed_batch_id)
                if seed_batch_id
                else None
            )

            try:
                plant = await self.add_plant(
                    growspace_id=growspace_id,
                    strain=call.data[ATTR_STRAIN],
                    row=row,
                    col=col,
                    phenotype=call.data.get(ATTR_PHENOTYPE, ""),
                    seed_batch_id=seed_batch_id,
                    generation=batch.generation if batch else "",
                    **parsed_dates,  # type: ignore[arg-type]
                )
                plant_id = plant.plant_id
            except GrowspaceError as err:
                raise ServiceValidationError(str(err)) from err

            _LOGGER.info(
                "Plant %s added successfully to growspace %s at (%d,%d)",
                plant_id,
                growspace_id,
                row,
                col,
            )

        except (
            AttributeError,
            KeyError,
            ValueError,
            ServiceValidationError,
            GrowspaceError,
            Exception,
        ) as err:
            _LOGGER.exception("Failed to add plant")
            raise ServiceValidationError(f"Failed to add plant: {err}") from err

    async def add_plants_from_call(
        self,
        hass: HomeAssistant,
        strain_library: StrainLibrary,
        call: ServiceCall,
    ) -> None:
        """Unpack a batch add_plants ServiceCall and delegate to add_plant."""

        def validate_batch_add() -> tuple[str, str, int, int]:
            gs_id = call.data[ATTR_GROWSPACE_ID]
            if gs_id not in self._coordinator.growspaces:
                _LOGGER.error("Growspace %s does not exist for add_plants", gs_id)
                raise ServiceValidationError(f"Growspace {gs_id} does not exist")

            row, col = self._coordinator.validator.find_first_available_position(gs_id)
            if row is None or col is None:
                _LOGGER.error("Growspace %s is full for add_plants", gs_id)
                raise ServiceValidationError(f"Growspace {gs_id} is full")

            strn = call.data[ATTR_STRAIN]
            amt = call.data[ATTR_AMOUNT]
            return gs_id, strn, amt, row

        try:
            _LOGGER.debug("Service call: add_plants with data: %s", call.data)

            growspace_id, strain, amount, _ = validate_batch_add()
            start_number = call.data.get(ATTR_START_NUMBER, 1)
            base_phenotype = call.data.get(ATTR_PHENOTYPE)
            seed_batch_id = call.data.get(ATTR_SEED_BATCH_ID)
            batch = (
                self._coordinator.services.genetics.seed_batch_by_id(seed_batch_id)
                if seed_batch_id
                else None
            )
            batch_generation = batch.generation if batch else ""

            add_date_fields = [f for f in DATE_FIELDS if f != "transition_date"]
            parsed_dates = {
                f: parse_date_field(call.data.get(f)) for f in add_date_fields
            }

            if growspace_id == CANONICAL_ID_MOTHER and not parsed_dates.get(
                "mother_start"
            ):
                parsed_dates["mother_start"] = dt_util.utcnow()
                _LOGGER.debug(
                    "Auto-setting mother_start to now for '%s' growspace (batch)",
                    CANONICAL_ID_MOTHER,
                )

            plants_added_count = 0

            for i in range(amount):
                current_number = start_number + i
                if base_phenotype:
                    phenotype = f"{base_phenotype} #{current_number}"
                else:
                    phenotype = f"{strain} #{current_number}"

                free_row, free_col = (
                    self._coordinator.validator.find_first_available_position(
                        growspace_id
                    )
                )

                if free_row is None or free_col is None:
                    _LOGGER.warning(
                        "Growspace %s is full. Stopped batch add after %d plants",
                        growspace_id,
                        plants_added_count,
                    )
                    break

                try:
                    await self.add_plant(
                        growspace_id=growspace_id,
                        strain=strain,
                        row=free_row,
                        col=free_col,
                        phenotype=phenotype,
                        seed_batch_id=seed_batch_id,
                        generation=batch_generation,
                        **parsed_dates,  # type: ignore[arg-type]
                    )
                    plants_added_count += 1
                except GrowspaceError as err:
                    _LOGGER.error("Failed to add plant %d of batch: %s", i + 1, err)
                    break

            _LOGGER.info(
                "Batch add complete. Added %d/%d plants to growspace %s",
                plants_added_count,
                amount,
                growspace_id,
            )

        except (
            AttributeError,
            KeyError,
            ValueError,
            ServiceValidationError,
            GrowspaceError,
            Exception,
        ) as err:
            _LOGGER.exception("Unexpected error during batch add plants")
            raise ServiceValidationError(f"Failed to batch add plants: {err}") from err

    async def update_plant_from_call(
        self,
        hass: HomeAssistant,
        strain_library: StrainLibrary,
        call: ServiceCall,
    ) -> None:
        """Unpack an update_plant ServiceCall and delegate to update_plant."""
        try:
            plant_id = call.data[ATTR_PLANT_ID]
            self._coordinator.validator.validate_plant_exists(plant_id)

            _LOGGER.debug("UPDATE_PLANT: Incoming call.data: %s", call.data)

            plant = self._coordinator.plants[plant_id]
            growspace_id = plant.growspace_id

            service_data = dict(call.data)

            self._resolve_position_conflict(growspace_id, plant_id, service_data)

            update_data = self._prepare_update_data(service_data)

            if not update_data:
                _LOGGER.warning(
                    "No update fields provided for plant %s. Service call ignored",
                    plant_id,
                )
                return

            if ATTR_STRAIN in update_data and ATTR_PHENOTYPE in update_data:
                strain = update_data[ATTR_STRAIN]
                phenotype = update_data[ATTR_PHENOTYPE]

                strain_key = strain.strip()
                pheno_key = phenotype.strip() if phenotype else "default"

                await strain_library.add_strain(strain=strain_key, phenotype=pheno_key)

            await self.update_plant(plant_id, **update_data)
            _LOGGER.info("Updated plant %s with data: %s", plant_id, update_data)

        except (
            AttributeError,
            KeyError,
            ValueError,
            ServiceValidationError,
            GrowspaceError,
        ) as err:
            _LOGGER.exception("Failed to update plant")
            if isinstance(err, ServiceValidationError):
                raise
            raise ServiceValidationError(f"Failed to update plant: {err}") from err

    async def remove_plant_from_call(
        self,
        hass: HomeAssistant,
        strain_library: StrainLibrary,
        call: ServiceCall,
    ) -> None:
        """Unpack a remove_plant ServiceCall and delegate to remove_plant."""
        plant_id = call.data[ATTR_PLANT_ID]

        if plant_id not in self._coordinator.plants:
            _LOGGER.error("Plant %s not found for removal", plant_id)
            raise ServiceValidationError(f"Plant {plant_id} not found for removal.")

        try:
            plant_info = self._coordinator.plants[plant_id]
            await self.remove_plant(plant_id)
            _LOGGER.info(
                "Plant %s removed successfully from growspace %s",
                plant_id,
                plant_info.growspace_id,
            )

        except (
            AttributeError,
            KeyError,
            ValueError,
            ServiceValidationError,
            GrowspaceError,
        ) as err:
            _LOGGER.exception("Failed to remove plant %s", plant_id)
            if isinstance(err, ServiceValidationError):
                raise
            raise ServiceValidationError(
                f"Failed to remove plant {plant_id}: {err}"
            ) from err

    async def add_timeline_note_from_call(
        self,
        hass: HomeAssistant,
        strain_library: StrainLibrary,
        call: ServiceCall,
    ) -> None:
        """Unpack an add_timeline_note ServiceCall and delegate to add_timeline_note."""
        plant_id = _resolve_plant_id(hass, call.data[ATTR_PLANT_ID])
        await _ensure_plant_loaded(hass, self._coordinator, plant_id)

        await self._coordinator.services.add_timeline_note(
            plant_id=plant_id,
            notes=call.data[ATTR_NOTES],
            timestamp=call.data.get(ATTR_TRANSITION_DATE),
            images_base64=call.data.get(ATTR_IMAGES, []),
            tags=call.data.get(ATTR_TAGS, []),
            ph=call.data.get(ATTR_PH),
            ec=call.data.get(ATTR_EC),
            amount_ml=call.data.get(ATTR_AMOUNT_ML),
            external_metadata=call.data.get(ATTR_METADATA, {}),
        )

    @handle_service_errors
    async def log_training_event_from_call(
        self,
        hass: HomeAssistant,
        call: ServiceCall,
    ) -> None:
        """Unpack a log_training_event ServiceCall and delegate to log_training_event."""
        growspace_id: str | None = call.data.get(ATTR_GROWSPACE_ID)
        technique: str = call.data[ATTR_TECHNIQUE]
        notes: str | None = call.data.get(ATTR_NOTES)
        plant_ids: list[str] | None = call.data.get(ATTR_PLANT_ID)

        await self.log_training_event(
            growspace_id=growspace_id,
            technique=technique,
            notes=notes,
            plant_ids=plant_ids,
        )


async def _handle_add_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    await coordinator.services.plants.add_plant_from_call(hass, strain_library, call)


async def _handle_add_plants(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    await coordinator.services.plants.add_plants_from_call(hass, strain_library, call)


async def _handle_update_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    await coordinator.services.plants.update_plant_from_call(hass, strain_library, call)


async def _handle_remove_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    await coordinator.services.plants.remove_plant_from_call(hass, strain_library, call)


async def _handle_add_timeline_note(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    await coordinator.services.plants.add_timeline_note_from_call(
        hass, strain_library, call
    )


async def _handle_log_training_event(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    await coordinator.services.plants.log_training_event_from_call(hass, call)


SERVICES: list[ServiceDefinition] = [
    ServiceDefinition(
        GrowspaceService.ADD_PLANT,
        _handle_add_plant,
        ADD_PLANT_SCHEMA,
        needs_strain_lib=True,
    ),
    ServiceDefinition(
        GrowspaceService.ADD_PLANTS,
        _handle_add_plants,
        ADD_PLANTS_SCHEMA,
        needs_strain_lib=True,
    ),
    ServiceDefinition(
        GrowspaceService.REMOVE_PLANT,
        _handle_remove_plant,
        REMOVE_PLANT_SCHEMA,
        needs_strain_lib=True,
    ),
    ServiceDefinition(
        GrowspaceService.UPDATE_PLANT,
        _handle_update_plant,
        UPDATE_PLANT_SCHEMA,
        needs_strain_lib=True,
    ),
    ServiceDefinition(
        GrowspaceService.ADD_TIMELINE_NOTE,
        _handle_add_timeline_note,
        ADD_TIMELINE_NOTE_SCHEMA,
        needs_strain_lib=True,
    ),
    ServiceDefinition(
        GrowspaceService.LOG_TRAINING_EVENT,
        _handle_log_training_event,
        LOG_TRAINING_EVENT_SCHEMA,
    ),
]
