"""Plant Lifecycle Manager for Growspace Manager."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from .const import DATE_FIELDS, PLANT_STAGES, SPECIAL_GROWSPACES, PlantStage
from .exceptions import (
    GrowspaceNotFoundError,
    PlantNotFoundError,
    ValidationChangeError,
)
from .models import Plant
from .utils import calculate_plant_stage, format_date

if TYPE_CHECKING:
    from .coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


class PlantLifecycleManager:
    """Manages plant lifecycle transitions, CRUD operations, and complex logic."""

    def __init__(self, coordinator: GrowspaceCoordinator) -> None:
        """Initialize the manager."""
        self.coordinator = coordinator

    # =========================================================================
    # PLANT CRUD OPERATIONS
    # =========================================================================

    async def async_add_plant(
        self,
        growspace_id: str,
        strain: str,
        plant_id: str | None = None,
        phenotype: str = "",
        row: int = 1,
        col: int = 1,
        stage: str = "",
        plant_type: str = "normal",
        device_id: str | None = None,
        **kwargs: Any,
    ) -> Plant:
        """Add a new plant to the system."""
        async with self.coordinator._lock:  # Accessing generic lock from coordinator
            try:
                self.coordinator.validator.validate_position_not_occupied(
                    growspace_id, row, col
                )
                final_row, final_col = row, col
            except ValidationChangeError:
                _LOGGER.info(
                    "Position (%d, %d) in growspace %s is occupied. Finding first available",
                    row,
                    col,
                    growspace_id,
                )
                final_row, final_col = (
                    self.coordinator.validator.find_first_available_position(
                        growspace_id
                    )
                )

            date_fields = {}
            for field in DATE_FIELDS:
                if field in kwargs:
                    date_fields[field] = format_date(kwargs[field])

            plant = Plant(
                plant_id=plant_id or str(uuid.uuid4()),
                growspace_id=growspace_id,
                strain=strain,
                phenotype=phenotype,
                row=final_row,
                col=final_col,
                stage=stage or "",
                type=plant_type,
                device_id=device_id,
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
                **date_fields,
                source_mother=kwargs.get("source_mother", ""),
            )

            if not plant.stage:
                plant.stage = calculate_plant_stage(plant)

            self.coordinator.plants[plant.plant_id] = plant
            await self.coordinator.async_commit()

            return plant

    async def async_update_plant(self, plant_id: str, **updates: Any) -> Plant:
        """Update attributes of an existing plant."""
        async with self.coordinator._lock:
            plant = self.coordinator.plants.get(plant_id)
            if not plant:
                raise PlantNotFoundError(f"Plant {plant_id} does not exist")

            for key in DATE_FIELDS:
                if key in updates:
                    updates[key] = format_date(updates[key])

            for key, value in updates.items():
                if hasattr(plant, key):
                    setattr(plant, key, value)

            plant.updated_at = date.today().isoformat()
            await self.coordinator.async_commit()
            return plant

    async def async_remove_plant(self, plant_id: str) -> bool:
        """Remove a plant and its associated entities."""
        async with self.coordinator._lock:
            if plant_id in self.coordinator.plants:
                del self.coordinator.plants[plant_id]
                if plant_id in self.coordinator._notifications_sent:
                    del self.coordinator._notifications_sent[plant_id]
                await self.coordinator.async_commit()
                return True
            return False

    async def async_move_plant(self, plant_id: str, new_row: int, new_col: int) -> None:
        """Move a plant to a new position."""
        await self.async_update_plant(plant_id, row=new_row, col=new_col)

    async def async_switch_plants(self, plant1_id: str, plant2_id: str) -> None:
        """Switch the positions of two plants."""
        async with self.coordinator._lock:
            self.coordinator.validator.validate_plant_exists(plant1_id)
            self.coordinator.validator.validate_plant_exists(plant2_id)

            plant1 = self.coordinator.plants[plant1_id]
            plant2 = self.coordinator.plants[plant2_id]

            if plant1.growspace_id != plant2.growspace_id:
                raise ValidationChangeError(
                    "Cannot switch plants in different growspaces"
                )

            p1_row, p1_col = plant1.row, plant1.col
            p2_row, p2_col = plant2.row, plant2.col

            plant1.row, plant1.col = p2_row, p2_col
            plant2.row, plant2.col = p1_row, p1_col

            now = date.today().isoformat()
            plant1.updated_at = now
            plant2.updated_at = now

            await self.coordinator.async_commit()

    # =========================================================================
    # HARVEST & TRANSITION LOGIC
    # =========================================================================

    async def handle_harvest_logic(
        self,
        plant_id: str,
        plant: Plant,
        target_growspace_id: str | None,
        target_growspace_name: str | None,
        transition_date: str,
    ) -> bool:
        """Determine harvest workflow and execute it."""
        if target_growspace_id:
            if target_growspace_id not in self.coordinator.growspaces:
                raise GrowspaceNotFoundError(
                    f"Target growspace {target_growspace_id} not found"
                )
            return await self._harvest_to_explicit_target(
                plant_id,
                plant,
                target_growspace_id,
                target_growspace_name,
                transition_date,
            )

        return await self._harvest_auto_flow(
            plant_id, plant, target_growspace_name, transition_date
        )

    async def _harvest_to_explicit_target(
        self,
        plant_id: str,
        plant: Plant,
        target_growspace_id: str,
        target_growspace_name: str | None,
        transition_date: str,
    ) -> bool:
        """Move harvested plant to explicit target."""
        try:
            pos = self.coordinator.validator.find_first_available_position(
                target_growspace_id
            )
            new_row, new_col = pos
        except ValueError as e:
            _LOGGER.warning(
                "Failed to find position in %s growspace: %s",
                target_growspace_id,
                e,
            )
            new_row, new_col = 1, 1

        stage_updates = {}
        target_lower = (target_growspace_name or "").lower()

        if target_growspace_id == PlantStage.DRY or "dry" in target_lower:
            stage_updates = {"stage": PlantStage.DRY, "dry_start": transition_date}
        elif target_growspace_id == PlantStage.CURE or "cure" in target_lower:
            stage_updates = {"stage": PlantStage.CURE, "cure_start": transition_date}
        elif target_growspace_id == PlantStage.CLONE or "clone" in target_lower:
            stage_updates = {"stage": PlantStage.CLONE, "clone_start": transition_date}
        elif target_growspace_id == PlantStage.MOTHER or "mother" in target_lower:
            stage_updates = {
                "stage": PlantStage.MOTHER,
                "mother_start": transition_date,
            }

        await self.async_update_plant(
            plant_id,
            growspace_id=target_growspace_id,
            row=new_row,
            col=new_col,
            **stage_updates,
        )
        return True

    async def _harvest_auto_flow(
        self,
        plant_id: str,
        plant: Plant,
        target_growspace_name: str | None,
        transition_date: str,
    ) -> bool:
        """Automatically determine harvest flow."""
        if target_growspace_name:
            name_lower = target_growspace_name.lower()
            for stage in [
                PlantStage.DRY,
                PlantStage.CURE,
                PlantStage.CLONE,
                PlantStage.MOTHER,
            ]:
                info = SPECIAL_GROWSPACES.get(stage.value, {})
                aliases = info.get("aliases", [])
                if name_lower == stage.value or name_lower in aliases:
                    return await self._move_to_special_growspace(
                        plant_id, plant, stage, transition_date
                    )

        current_stage = calculate_plant_stage(plant)
        if current_stage == PlantStage.FLOWER:
            return await self.move_to_dry_growspace(plant_id, plant, transition_date)
        if current_stage == PlantStage.DRY:
            return await self.move_to_cure_growspace(plant_id, plant, transition_date)
        if current_stage == PlantStage.MOTHER:
            return await self.move_to_clone_growspace(plant_id, plant, transition_date)

        return await self.move_to_dry_growspace(plant_id, plant, transition_date)

    async def _move_to_special_growspace(
        self,
        plant_id: str,
        plant: Plant,
        target_stage: PlantStage,
        transition_date: str,
        record_harvest_analytics: bool = False,
    ) -> bool:
        """Generic method to move a plant to a special growspace."""
        if record_harvest_analytics:
            await self._record_analytics(plant)

        gs_id = self.coordinator.ensure_special_growspace(
            target_stage, target_stage.value
        )
        target_gs = self.coordinator.growspaces.get(gs_id)

        try:
            new_row, new_col = self.coordinator.validator.find_first_available_position(
                gs_id
            )
        except ValueError as e:
            _LOGGER.warning(
                "Failed to find position in %s growspace: %s",
                gs_id,
                e,
            )
            new_row, new_col = 1, 1

        updates = {
            "growspace_id": gs_id,
            "row": new_row,
            "col": new_col,
            "stage": target_stage,
        }

        date_map = {
            PlantStage.DRY: "dry_start",
            PlantStage.CURE: "cure_start",
            PlantStage.CLONE: "clone_start",
            PlantStage.MOTHER: "mother_start",
            PlantStage.VEG: "veg_start",
        }
        if target_gs:
            updates["device_id"] = target_gs.device_id
        if target_stage in date_map:
            updates[date_map[target_stage]] = transition_date

        await self.async_update_plant(plant_id, **updates)
        return True

    async def _record_analytics(self, plant: Plant) -> None:
        """Helper to record harvest analytics."""
        veg_days = self.coordinator.serializer.calculate_days_in_stage(
            plant, PlantStage.VEG
        )
        flower_days = self.coordinator.serializer.calculate_days_in_stage(
            plant, PlantStage.FLOWER
        )
        if veg_days > 0 or flower_days > 0:
            try:
                await self.coordinator.strain_library.record_harvest(
                    plant.strain, plant.phenotype, veg_days, flower_days
                )
            except Exception as e:
                _LOGGER.warning("Failed to record harvest analytics: %s", e)

    async def move_to_dry_growspace(
        self, plant_id: str, plant: Plant, transition_date: str
    ) -> bool:
        return await self._move_to_special_growspace(
            plant_id,
            plant,
            PlantStage.DRY,
            transition_date,
            record_harvest_analytics=True,
        )

    async def move_to_cure_growspace(
        self, plant_id: str, plant: Plant, transition_date: str
    ) -> bool:
        return await self._move_to_special_growspace(
            plant_id, plant, PlantStage.CURE, transition_date
        )

    async def move_to_clone_growspace(
        self, plant_id: str, plant: Plant, transition_date: str
    ) -> bool:
        return await self._move_to_special_growspace(
            plant_id, plant, PlantStage.CLONE, transition_date
        )

    async def handle_clone_creation(
        self,
        growspace_id: str,
        strain: str,
        row: int,
        col: int,
        source_mother_id: str | None = None,
        mother_plant: Plant | None = None,
        **kwargs: Any,
    ) -> str:
        """Handle clone creation."""
        phenotype = kwargs.pop("phenotype", "")
        if mother_plant:
            phenotype = mother_plant.phenotype or ""

        plant = await self.async_add_plant(
            growspace_id=growspace_id,
            strain=str(strain).strip(),
            phenotype=phenotype,
            row=int(row),
            col=int(col),
            stage=PlantStage.CLONE,
            plant_type=PlantStage.CLONE,
            clone_start=kwargs.pop("clone_start", date.today()),
            source_mother=source_mother_id,
            **kwargs,
        )
        return plant.plant_id

    async def transition_plant_stage(
        self,
        plant_id: str,
        new_stage: str | PlantStage,
        transition_date: date | None = None,
    ) -> None:
        """Execute a plant stage transition."""
        if isinstance(new_stage, PlantStage):
            new_stage = new_stage.value

        if new_stage not in PLANT_STAGES:
            raise ValidationChangeError(f"Invalid stage: {new_stage}")

        transition_date = transition_date or date.today()
        trans_date_str = (
            transition_date.isoformat()
            if hasattr(transition_date, "isoformat")
            else str(transition_date)
        )

        updates = {"stage": new_stage}
        stage_map = {
            PlantStage.VEG: "veg_start",
            PlantStage.FLOWER: "flower_start",
            PlantStage.DRY: "dry_start",
            PlantStage.CURE: "cure_start",
            PlantStage.CLONE: "clone_start",
        }
        if new_stage in stage_map:
            updates[stage_map[new_stage]] = trans_date_str

        await self.async_update_plant(plant_id, **updates)

        plant = self.coordinator.plants.get(plant_id)
        if plant:
            if new_stage == PlantStage.DRY:
                await self.move_to_dry_growspace(plant_id, plant, trans_date_str)
            elif new_stage == PlantStage.CURE:
                await self.move_to_cure_growspace(plant_id, plant, trans_date_str)
            elif new_stage == PlantStage.CLONE:
                await self.move_to_clone_growspace(plant_id, plant, trans_date_str)
