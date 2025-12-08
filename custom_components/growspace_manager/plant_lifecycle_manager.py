"""Plant Lifecycle Manager for Growspace Manager."""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING, Any

from .const import PlantStage
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
        if target_growspace_id and target_growspace_id in self.coordinator.growspaces:
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
                plant_id, stage=PlantStage.MOTHER, clone_start=transition_date
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
            if "dry" in target_growspace_name.lower():
                return await self.move_to_dry_growspace(
                    plant_id, plant, transition_date
                )
            if "cure" in target_growspace_name.lower():
                return await self.move_to_cure_growspace(
                    plant_id, plant, transition_date
                )
            if "clone" in target_growspace_name.lower():
                return await self.move_to_clone_growspace(
                    plant_id, plant, transition_date
                )
            if "mother" in target_growspace_name.lower():
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
        veg_days = self.coordinator.calculate_days_in_stage(plant, PlantStage.VEG)
        flower_days = self.coordinator.calculate_days_in_stage(plant, PlantStage.FLOWER)

        if veg_days > 0 or flower_days > 0:
            await self.coordinator.strain_library.record_harvest(
                plant.strain, plant.phenotype, veg_days, flower_days
            )

        # Now, proceed with moving the plant
        dry_id = self.coordinator.ensure_special_growspace(PlantStage.DRY, "dry")
        plant.growspace_id = dry_id

        growspace = self.coordinator.growspaces.get(dry_id)
        if growspace and growspace.device_id:
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
        plant_id: str,
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
            plant_id: The new clone's ID.
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
        now = date.today()

        clone_data = {
            "plant_id": plant_id,
            "growspace_id": growspace_id,
            "strain": str(strain).strip(),
            "row": int(row),
            "col": int(col),
            "stage": PlantStage.CLONE,
            "type": PlantStage.CLONE,
            "clone_start": now,
            "created_at": now.isoformat(),
        }

        if mother_plant:
            clone_data["phenotype"] = mother_plant.phenotype

        if source_mother_id:
            clone_data["source_mother"] = source_mother_id

        # Override with any explicitly provided kwargs
        clone_data.update(
            {k: v for k, v in kwargs.items() if k not in ["stage", "clone_start"]}
        )

        # Parse dates
        self.coordinator._parse_date_fields(clone_data)

        # Save the clone
        self.coordinator.plants[plant_id] = Plant(**clone_data)
        self.coordinator.update_data_property()
        await self.coordinator.async_save()
        self.coordinator.async_set_updated_data(self.coordinator.data)

        _LOGGER.info(
            "Created clone %s: %s at (%d,%d) from mother %s",
            plant_id,
            strain,
            row,
            col,
            source_mother_id or "unknown",
        )

        return plant_id
