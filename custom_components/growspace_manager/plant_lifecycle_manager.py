"""Plant Lifecycle Manager for Growspace Manager."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import date, datetime
import logging
from typing import Any
import uuid

from .const import DATE_FIELDS, PLANT_STAGES, SPECIAL_GROWSPACES, PlantStage
from .data_access.growspace_repository import GrowspaceRepository
from .domain import calculate_days_in_stage
from .exceptions import (
    GrowspaceNotFoundError,
    PlantNotFoundError,
    ValidationChangeError,
)
from .growspace_validator import GrowspaceValidator
from .models import Plant, PlantGenetics
from .services.growspace_service import GrowspaceService
from .strain_library import StrainLibrary
from .utils import calculate_plant_stage, format_date

_LOGGER = logging.getLogger(__name__)


class PlantLifecycleManager:
    """Manages plant lifecycle transitions, CRUD operations, and complex logic."""

    def __init__(
        self,
        repository: GrowspaceRepository,
        validator: GrowspaceValidator,
        growspace_service: GrowspaceService,
        strain_library: StrainLibrary,
        save_callback: Callable[[], Awaitable[None]],
        lock: asyncio.Lock,
    ) -> None:
        """Initialize the manager."""
        self.repository = repository
        self.validator = validator
        self.growspace_service = growspace_service
        self.strain_library = strain_library
        self.save_callback = save_callback
        self.lock = lock

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
        async with self.lock:
            try:
                self.validator.validate_position_not_occupied(growspace_id, row, col)
                final_row, final_col = row, col
            except ValidationChangeError:
                _LOGGER.info(
                    "Position (%d, %d) in growspace %s is occupied. Finding first available",
                    row,
                    col,
                    growspace_id,
                )
                found_row, found_col = self.validator.find_first_available_position(
                    growspace_id
                )

                if found_row is None or found_col is None:
                    _LOGGER.warning(
                        "No free space in growspace %s, cannot resolve conflict",
                        growspace_id,
                    )
                    raise ValidationChangeError(
                        f"Growspace {growspace_id} is full, cannot add/move plant"
                    ) from None

                final_row, final_col = found_row, found_col

            date_fields = {}
            for field in DATE_FIELDS:
                if field in kwargs:
                    date_fields[field] = format_date(kwargs[field])

            final_plant_id = plant_id or str(uuid.uuid4())

            genetics = PlantGenetics(
                strain_name=strain,
                phenotype_name=phenotype or "",
            )

            plant = Plant(
                plant_id=final_plant_id,
                growspace_id=growspace_id,
                genetics=genetics,
                row=final_row,
                col=final_col,
                stage=stage or "",
                type=plant_type,
                device_id=device_id,
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
                **date_fields,  # type: ignore[arg-type]
                source_mother=kwargs.get("source_mother", ""),
            )

            if not plant.stage:
                plant.stage = calculate_plant_stage(plant)

            self.repository.plants[plant.plant_id] = plant
            await self.save_callback()

            return plant

    async def async_update_plant(self, plant_id: str, **updates: Any) -> Plant:
        """Update attributes of an existing plant."""
        async with self.lock:
            plant = self.repository.plants.get(plant_id)
            if not plant:
                raise PlantNotFoundError(f"Plant {plant_id} does not exist")

            for key in DATE_FIELDS:
                if key in updates:
                    updates[key] = format_date(updates[key])

            # Handle genetics updates: strain and phenotype are read-only properties
            # that delegate to genetics.strain_name and genetics.phenotype_name
            if "strain" in updates:
                plant.genetics.strain_name = updates.pop("strain")
            if "phenotype" in updates:
                plant.genetics.phenotype_name = updates.pop("phenotype")

            for key, value in updates.items():
                if hasattr(plant, key):
                    setattr(plant, key, value)

            plant.updated_at = date.today().isoformat()
            await self.save_callback()
            return plant

    async def async_remove_plant(self, plant_id: str) -> bool:
        """Remove a plant and its associated entities."""
        async with self.lock:
            if plant_id in self.repository.plants:
                del self.repository.plants[plant_id]
                if plant_id in self.repository.notifications_sent:
                    del self.repository.notifications_sent[plant_id]
                await self.save_callback()
                return True
            return False

    async def async_move_plant(self, plant_id: str, new_row: int, new_col: int) -> None:
        """Move a plant to a new position."""
        await self.async_update_plant(plant_id, row=new_row, col=new_col)

    async def async_switch_plants(self, plant1_id: str, plant2_id: str) -> None:
        """Switch the positions of two plants."""
        async with self.lock:
            self.validator.validate_plant_exists(plant1_id)
            self.validator.validate_plant_exists(plant2_id)

            plant1 = self.repository.plants[plant1_id]
            plant2 = self.repository.plants[plant2_id]

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

            await self.save_callback()

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
            if target_growspace_id not in self.repository.growspaces:
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
            pos = self.validator.find_first_available_position(target_growspace_id)
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

        gs_id = self.growspace_service.ensure_special_growspace(
            target_stage.value, target_stage.value
        )
        target_gs = self.repository.growspaces.get(gs_id)

        try:
            new_row, new_col = self.validator.find_first_available_position(gs_id)
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
        updates["device_id"] = target_gs.device_id if target_gs else None
        if target_stage in date_map:
            updates[date_map[target_stage]] = transition_date

        await self.async_update_plant(plant_id, **updates)
        return True

    async def _record_analytics(self, plant: Plant) -> None:
        """Helper to record harvest analytics."""
        veg_days = calculate_days_in_stage(plant, PlantStage.VEG)
        flower_days = calculate_days_in_stage(plant, PlantStage.FLOWER)
        if self.strain_library and (veg_days > 0 or flower_days > 0):
            try:
                await self.strain_library.record_harvest(
                    plant.strain, plant.phenotype, veg_days, flower_days
                )
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning("Failed to record harvest analytics: %s", e)

    async def move_to_dry_growspace(
        self, plant_id: str, plant: Plant, transition_date: str
    ) -> bool:
        """Move a plant to the dry growspace."""
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
        """Move a plant to the cure growspace."""
        return await self._move_to_special_growspace(
            plant_id, plant, PlantStage.CURE, transition_date
        )

    async def move_to_clone_growspace(
        self, plant_id: str, plant: Plant, transition_date: str
    ) -> bool:
        """Move a plant back to the clone growspace."""
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

        updates: dict[str, Any] = {"stage": new_stage}
        stage_map = {
            PlantStage.VEG.value: "veg_start",
            PlantStage.FLOWER.value: "flower_start",
            PlantStage.DRY.value: "dry_start",
            PlantStage.CURE.value: "cure_start",
            PlantStage.CLONE.value: "clone_start",
        }
        if new_stage in stage_map:
            updates[stage_map[new_stage]] = trans_date_str

        plant = self.repository.plants.get(plant_id)
        if plant:
            # Prepare the NEW history list for update
            new_history = [dict(item) for item in plant.stage_history]

            # Close last open item
            for item in reversed(new_history):
                if item.get("end") is None:
                    item["end"] = trans_date_str
                    break

            # Add new stage entry
            new_history.append(
                {"stage": new_stage, "start": trans_date_str, "end": None}
            )
            updates["stage_history"] = new_history

        await self.async_update_plant(plant_id, **updates)

        plant = self.repository.plants.get(plant_id)
        if plant:
            if new_stage == PlantStage.DRY:
                await self.move_to_dry_growspace(plant_id, plant, trans_date_str)
            elif new_stage == PlantStage.CURE:
                await self.move_to_cure_growspace(plant_id, plant, trans_date_str)
            elif new_stage == PlantStage.CLONE:
                await self.move_to_clone_growspace(plant_id, plant, trans_date_str)
