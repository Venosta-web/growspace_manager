"""Plant Lifecycle Manager for Growspace Manager."""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING, Any

from .const import PLANT_STAGES, SPECIAL_GROWSPACES, PlantStage
from .models import Plant
from .utils import calculate_plant_stage

if TYPE_CHECKING:
    from .coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


class PlantLifecycleManager:
    """Manages plant lifecycle transitions and complex logic."""

    def __init__(self, coordinator: GrowspaceCoordinator) -> None:
        """Initialize the manager.

        Args:
            coordinator: The GrowspaceCoordinator instance.
        """
        self.coordinator = coordinator

    async def handle_harvest_logic(
        self,
        plant_id: str,
        plant: Plant,
        target_growspace_id: str | None,
        target_growspace_name: str | None,
        transition_date: str,
    ) -> bool:
        """Determine the harvest workflow and execute it.

        Prioritizes an explicit target, otherwise uses an automatic flow.

        Args:
            plant_id: The ID of the plant being harvested.
            plant: The Plant object.
            target_growspace_id: An explicit target growspace ID.
            target_growspace_name: A hint for the auto-flow logic.
            transition_date: The date of the harvest.

        Returns:
            True if the plant was moved, False otherwise.
        """
        # Explicit target provided
        if target_growspace_id:
            if target_growspace_id not in self.coordinator.growspaces:
                raise ValueError(f"Target growspace {target_growspace_id} not found")
            return await self._harvest_to_explicit_target(
                plant_id,
                plant,
                target_growspace_id,
                target_growspace_name,
                transition_date,
            )

        # Auto-flow based on hints or current stage
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
        """Move a harvested plant to an explicitly defined target growspace.

        Args:
            plant_id: The ID of the plant.
            plant: The Plant object.
            target_growspace_id: The ID of the destination growspace.
            target_growspace_name: The name of the destination growspace.
            transition_date: The date of the move.

        Returns:
            True, as the plant is always moved in this path.
        """
        plant.growspace_id = target_growspace_id

        try:
            pos = self.coordinator.validator.find_first_available_position(
                target_growspace_id
            )
            plant.row, plant.col = pos
        except ValueError as e:
            _LOGGER.warning(
                "Failed to find position in target growspace %s: %s",
                target_growspace_id,
                e,
            )

        # Set stage based on target
        if target_growspace_id == PlantStage.DRY or (
            target_growspace_name and "dry" in target_growspace_name.lower()
        ):
            await self.coordinator.async_update_plant(
                plant_id, stage=PlantStage.DRY, dry_start=transition_date
            )
        elif target_growspace_id == PlantStage.CURE or (
            target_growspace_name and "cure" in target_growspace_name.lower()
        ):
            await self.coordinator.async_update_plant(
                plant_id, stage=PlantStage.CURE, cure_start=transition_date
            )
        elif target_growspace_id == PlantStage.CLONE or (
            target_growspace_name and "clone" in target_growspace_name.lower()
        ):
            await self.coordinator.async_update_plant(
                plant_id, stage=PlantStage.CLONE, clone_start=transition_date
            )
        elif target_growspace_id == PlantStage.MOTHER or (
            target_growspace_name and "mother" in target_growspace_name.lower()
        ):
            await self.coordinator.async_update_plant(
                plant_id, stage=PlantStage.MOTHER, mother_start=transition_date
            )

        _LOGGER.info("Moved plant %s to growspace %s", plant_id, target_growspace_id)
        return True

    async def _harvest_auto_flow(
        self,
        plant_id: str,
        plant: Plant,
        target_growspace_name: str | None,
        transition_date: str,
    ) -> bool:
        """Automatically determine the next growspace for a harvested plant.

        The logic is based on hints in the target name or the plant's current stage.

        Args:
            plant_id: The ID of the plant.
            plant: The Plant object.
            target_growspace_name: A name hint (e.g., "Drying Tent").
            transition_date: The date of the move.

        Returns:
            True if the plant was moved, False otherwise.
        """
        current_stage = calculate_plant_stage(plant)

        # Handle name hints
        if target_growspace_name:
            name_lower = target_growspace_name.lower()

            # Strict matching against special growspace aliases
            if (
                name_lower == "dry"
                or name_lower in SPECIAL_GROWSPACES["dry"]["aliases"]
            ):
                return await self.move_to_dry_growspace(
                    plant_id, plant, transition_date
                )
            if (
                name_lower == "cure"
                or name_lower in SPECIAL_GROWSPACES["cure"]["aliases"]
            ):
                return await self.move_to_cure_growspace(
                    plant_id, plant, transition_date
                )
            if (
                name_lower == "clone"
                or name_lower in SPECIAL_GROWSPACES["clone"]["aliases"]
            ):
                return await self.move_to_clone_growspace(
                    plant_id, plant, transition_date
                )
            if (
                name_lower == "mother"
                or name_lower in SPECIAL_GROWSPACES["mother"]["aliases"]
            ):
                # Mother logic might reuse move_to_clone_growspace or similar, ensuring it ends up in mother growspace
                # For now, sticking to original logic of moving to clone growspace if mother match found?
                # Original logic: return await self.move_to_clone_growspace(...)
                return await self.move_to_clone_growspace(
                    plant_id, plant, transition_date
                )

        # Handle stage transitions
        if current_stage == PlantStage.FLOWER:
            return await self.move_to_dry_growspace(plant_id, plant, transition_date)
        if current_stage == PlantStage.DRY:
            return await self.move_to_cure_growspace(plant_id, plant, transition_date)
        if current_stage == PlantStage.MOTHER:
            return await self.move_to_clone_growspace(plant_id, plant, transition_date)
        # Fallback: move to dry
        return await self.move_to_dry_growspace(plant_id, plant, transition_date)

    async def move_to_clone_growspace(
        self, plant_id: str, plant: Plant, transition_date: str
    ) -> bool:
        """Move a plant to the dedicated 'clone' growspace.

        Args:
            plant_id: The ID of the plant to move.
            plant: The Plant object.
            transition_date: The date of the move.

        Returns:
            True, as the plant is always moved.
        """
        clone_id = self.coordinator.ensure_special_growspace(
            PlantStage.CLONE, "clone", 5, 5
        )
        plant.growspace_id = clone_id

        growspace = self.coordinator.growspaces.get(clone_id)
        if growspace:
            plant.device_id = growspace.device_id

        try:
            new_row, new_col = self.coordinator.validator.find_first_available_position(
                clone_id
            )
            plant.row, plant.col = new_row, new_col
            await self.coordinator.async_update_plant(
                plant_id,
                growspace_id=clone_id,
                row=new_row,
                col=new_col,
                stage=PlantStage.CLONE,
                clone_start=transition_date,
            )
        except ValueError as e:
            _LOGGER.warning("Failed to assign position in clone growspace: %s", e)

        plant.clone_start = transition_date
        plant.stage = PlantStage.CLONE
        _LOGGER.info("Moved plant %s → clone (ID: %s)", plant_id, clone_id)
        return True

    async def move_to_dry_growspace(
        self, plant_id: str, plant: Plant, transition_date: str
    ) -> bool:
        """Move a plant to the dedicated 'dry' growspace and record harvest analytics.

        Args:
            plant_id: The ID of the plant to move.
            plant: The Plant object.
            transition_date: The date of the move.

        Returns:
            True, as the plant is always moved.
        """
        # Record analytics before moving
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

        # Now, proceed with moving the plant
        dry_id = self.coordinator.ensure_special_growspace(PlantStage.DRY, "dry")
        plant.growspace_id = dry_id

        growspace = self.coordinator.growspaces.get(dry_id)
        if growspace:
            plant.device_id = growspace.device_id

        try:
            new_row, new_col = self.coordinator.validator.find_first_available_position(
                dry_id
            )
            plant.row, plant.col = new_row, new_col
            await self.coordinator.async_update_plant(
                plant_id,
                growspace_id=dry_id,
                row=new_row,
                col=new_col,
                stage=PlantStage.DRY,
                dry_start=transition_date,
            )
        except ValueError as e:
            _LOGGER.warning("Failed to assign position in dry growspace: %s", e)

        plant.dry_start = transition_date
        plant.stage = PlantStage.DRY
        _LOGGER.info("Moved plant %s → dry (ID: %s)", plant_id, dry_id)
        return True

    async def move_to_cure_growspace(
        self, plant_id: str, plant: Plant, transition_date: str
    ) -> bool:
        """Move a plant to the dedicated 'cure' growspace.

        Args:
            plant_id: The ID of the plant to move.
            plant: The Plant object.
            transition_date: The date of the move.

        Returns:
            True, as the plant is always moved.
        """
        cure_id = self.coordinator.ensure_special_growspace(PlantStage.CURE, "cure")
        plant.growspace_id = cure_id

        growspace = self.coordinator.growspaces.get(cure_id)
        if growspace:
            plant.device_id = growspace.device_id

        try:
            new_row, new_col = self.coordinator.validator.find_first_available_position(
                cure_id
            )
            plant.row, plant.col = new_row, new_col
            await self.coordinator.async_update_plant(
                plant_id,
                growspace_id=cure_id,
                row=new_row,
                col=new_col,
                stage=PlantStage.CURE,
                cure_start=transition_date,
            )
        except ValueError as e:
            _LOGGER.warning("Failed to assign position in cure growspace: %s", e)

        plant.cure_start = transition_date
        plant.stage = PlantStage.CURE
        _LOGGER.info("Moved plant %s → cure (ID: %s)", plant_id, cure_id)
        return True

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
        """Handle the creation of a clone plant, associating with mother if needed.

        Args:
            growspace_id: The target growspace ID.
            strain: Strain name.
            row: Row position.
            col: Col position.
            source_mother_id: ID of mother plant.
            mother_plant: Mother plant object.
            **kwargs: Extra data.

        Returns:
            The created plant ID.
        """
        phenotype = kwargs.get("phenotype", "")
        if mother_plant:
            phenotype = mother_plant.phenotype or ""  # Handle None phenotype

        # Use updated coordinator method which handles saving and ID generation
        plant = await self.coordinator.async_add_plant(
            growspace_id=growspace_id,
            strain=str(strain).strip(),
            plant_id=kwargs.get("plant_id"),
            phenotype=phenotype,
            row=int(row),
            col=int(col),
            stage=PlantStage.CLONE,
            type=PlantStage.CLONE,
            clone_start=date.today(),
            source_mother=source_mother_id,
            **{
                k: v
                for k, v in kwargs.items()
                if k not in ["stage", "clone_start", "plant_id", "phenotype"]
            },
        )

        _LOGGER.info(
            "Created clone %s: %s at (%d,%d) from mother %s",
            plant.plant_id,
            strain,
            row,
            col,
            source_mother_id or "unknown",
        )

        return plant.plant_id

    async def transition_plant_stage(
        self,
        plant_id: str,
        new_stage: str | PlantStage,
        transition_date: date | None = None,
    ) -> None:
        """Execute a plant stage transition with all associated logic.

        Args:
            plant_id: The ID of the plant.
            new_stage: The target stage.
            transition_date: The date of transition (defaults to today).
        """
        plant = self.coordinator.plants.get(plant_id)
        if not plant:
            raise ValueError(f"Plant {plant_id} not found")

        if new_stage not in PLANT_STAGES and new_stage not in [
            s.value for s in PlantStage
        ]:
            raise ValueError(f"Invalid stage: {new_stage}")

        if not transition_date:
            transition_date = date.today()

        if isinstance(transition_date, str):
            trans_date_str = transition_date
        else:
            trans_date_str = transition_date.isoformat()

        # Update plant object
        updates = {"stage": new_stage}

        stage_start_map = {
            PlantStage.VEG: "veg_start",
            PlantStage.FLOWER: "flower_start",
            PlantStage.DRY: "dry_start",
            PlantStage.CURE: "cure_start",
            PlantStage.CLONE: "clone_start",
        }

        if new_stage in stage_start_map:
            updates[stage_start_map[new_stage]] = trans_date_str

        # Update the plant
        await self.coordinator.async_update_plant(plant_id, **updates)

        # Handle physical moves for certain stages
        move_handlers = {
            PlantStage.DRY: self.move_to_dry_growspace,
            PlantStage.CURE: self.move_to_cure_growspace,
            PlantStage.CLONE: self.move_to_clone_growspace,
        }

        if new_stage in move_handlers:
            await move_handlers[new_stage](plant_id, plant, trans_date_str)
