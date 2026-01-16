"""Plant service for the Growspace Manager integration.

This service handles all plant-related CRUD operations and business logic,
extracted from the coordinator to reduce complexity.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..coordinator import GrowspaceCoordinator

from ..const import PlantStage
from ..events import (
    EVENT_PLANT_ADDED,
    EVENT_PLANT_MOVED,
    EVENT_PLANT_REMOVED,
    EVENT_PLANT_SWITCHED,
    EVENT_PLANT_TRANSITIONED,
    EVENT_PLANT_UPDATED,
    async_fire_clones_taken_event,
    async_fire_plant_event,
)
from ..models import Plant


class PlantService:
    """Handles all plant CRUD operations and business logic."""

    def __init__(self, coordinator: GrowspaceCoordinator) -> None:
        """Initialize the plant service.

        Args:
            coordinator: Reference to parent coordinator for accessing
                        shared resources (hass, plants dict, validator, etc.)
        """
        self._coord = coordinator

    async def add_plant(
        self,
        growspace_id: str,
        strain: str,
        plant_id: str | None = None,
        phenotype: str = "",
        row: int = 1,
        col: int = 1,
        stage: str = "",
        type: str = "normal",
        device_id: str | None = None,
        seedling_start: date | None = None,
        mother_start: date | None = None,
        clone_start: date | None = None,
        veg_start: date | None = None,
        flower_start: date | None = None,
        dry_start: date | None = None,
        cure_start: date | None = None,
        source_mother: str = "",
    ) -> Plant:
        """Add a new plant to the coordinator via lifecycle manager."""
        plant = await self._coord.lifecycle_manager.async_add_plant(
            growspace_id=growspace_id,
            strain=strain,
            plant_id=plant_id,
            phenotype=phenotype,
            row=row,
            col=col,
            stage=stage,
            plant_type=type,
            device_id=device_id,
            seedling_start=seedling_start,
            mother_start=mother_start,
            clone_start=clone_start,
            veg_start=veg_start,
            flower_start=flower_start,
            dry_start=dry_start,
            cure_start=cure_start,
            source_mother=source_mother,
        )

        self._coord._invalidate_cache(growspace_id)

        self._coord._fire_event(
            "plant_added", {"plant": self._coord.serializer.serialize_plant(plant)}
        )
        async_fire_plant_event(self._coord.hass, EVENT_PLANT_ADDED, plant)
        return plant

    async def add_mother_plant(
        self,
        phenotype: str,
        strain: str,
        row: int,
        col: int,
        mother_start: date | None = None,
        **kwargs: Any,
    ) -> Plant:
        """Add a new mother plant to the dedicated mother growspace.

        This ensures the 'mother' special growspace exists before adding the plant.

        Args:
            phenotype: The phenotype of the mother plant.
            strain: The strain of the mother plant.
            row: The row position.
            col: The column position.
            mother_start: The date the plant became a mother (optional).
            **kwargs: Additional plant attributes.

        Returns:
            The newly created mother Plant object.
        """
        mother_id: str = self._coord._ensure_mother_growspace()
        kwargs["type"] = PlantStage.MOTHER

        # Set mother_start to today if not provided
        if mother_start is None:
            mother_start = date.today()
        kwargs["mother_start"] = mother_start

        plant: Plant = await self.add_plant(
            growspace_id=mother_id,
            strain=strain,
            phenotype=phenotype,
            row=row,
            col=col,
            **kwargs,
        )
        return plant

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
            mother_plant_id: The ID of the source mother plant.
            num_clones: The number of clones to create.
            target_growspace_id: The target growspace ID (defaults to 'clone' if not provided).
            target_growspace_name: Ignored.
            transition_date: The date the clones were taken (defaults to today).

        Returns:
            A list of the newly created clone Plant objects.
        """
        self._coord.validator.validate_plant_exists(mother_plant_id)

        mother = self._coord.plants[mother_plant_id]

        # Determine target growspace: use provided ID or default to clone
        if target_growspace_id:
            # Validate that the target growspace exists
            if target_growspace_id not in self._coord.growspaces:
                raise ValueError(
                    f"Target growspace '{target_growspace_id}' does not exist"
                )
            clone_gs_id = target_growspace_id
        else:
            # Default to clone growspace
            clone_gs_id = self._coord.ensure_special_growspace(
                PlantStage.CLONE, "clone", 5, 5
            )

        new_plants: list[Plant] = []

        # Ensure transition_date is a date object
        if transition_date is None:
            transition_date = date.today()

        # Pre-invalidate clone growspace cache
        self._coord._invalidate_cache(clone_gs_id)

        for _ in range(num_clones):
            row, col = self._coord.validator.find_first_available_position(clone_gs_id)
            clone_id = await self._coord.lifecycle_manager.handle_clone_creation(
                growspace_id=clone_gs_id,
                strain=mother.strain,
                row=row,
                col=col,
                source_mother_id=mother_plant_id,
                mother_plant=mother,
                phenotype=mother.phenotype,
                clone_start=transition_date,
            )

            if new_plant := self._coord.plants.get(clone_id):
                new_plants.append(new_plant)
                # Fire individual plant_added event for frontend refresh
                self._coord._fire_event(
                    "plant_added",
                    {"plant": self._coord.serializer.serialize_plant(new_plant)},
                )
                async_fire_plant_event(self._coord.hass, EVENT_PLANT_ADDED, new_plant)

        # Fire clones taken event
        if new_plants:
            async_fire_clones_taken_event(
                self._coord.hass, mother, len(new_plants), clone_gs_id
            )

        return new_plants

    async def update_plant(self, plant_id: str, **updates: Any) -> Plant:
        """Update the attributes of an existing plant."""
        # Invalidate current growspace (logic for move)
        if plant := self._coord.plants.get(plant_id):
            # Invalidate cache for the current growspace to reflect updates (e.g. stage change)
            self._coord._invalidate_cache(plant.growspace_id)

            if (
                "growspace_id" in updates
                and updates["growspace_id"] != plant.growspace_id
            ):
                self._coord._invalidate_cache(updates["growspace_id"])

        plant = await self._coord.lifecycle_manager.async_update_plant(
            plant_id, **updates
        )

        self._coord._fire_event(
            "plant_updated",
            {"plant": self._coord.serializer.serialize_plant(plant)},
        )
        async_fire_plant_event(self._coord.hass, EVENT_PLANT_UPDATED, plant, updates)
        return plant

    async def move_plant(self, plant_id: str, new_row: int, new_col: int) -> None:
        """Move a plant to a new position via lifecycle manager."""
        if plant := self._coord.plants.get(plant_id):
            self._coord._invalidate_cache(plant.growspace_id)

        await self._coord.lifecycle_manager.async_move_plant(plant_id, new_row, new_col)

        # Fetch updated plant to fire event
        if plant := self._coord.plants.get(plant_id):
            async_fire_plant_event(
                self._coord.hass,
                EVENT_PLANT_MOVED,
                plant,
                {"new_row": new_row, "new_col": new_col},
            )

    async def switch_plants(self, plant1_id: str, plant2_id: str) -> None:
        """Switch the positions of two plants via lifecycle manager."""
        p1 = self._coord.plants.get(plant1_id)
        p2 = self._coord.plants.get(plant2_id)

        if p1:
            self._coord._invalidate_cache(p1.growspace_id)
        if p2:
            self._coord._invalidate_cache(p2.growspace_id)

        await self._coord.lifecycle_manager.async_switch_plants(plant1_id, plant2_id)

        # Fire events for both plants to update frontend
        if p1 := self._coord.plants.get(plant1_id):
            self._coord._fire_event(
                "plant_switched",
                {"plant": self._coord.serializer.serialize_plant(p1)},
            )
            async_fire_plant_event(self._coord.hass, EVENT_PLANT_SWITCHED, p1)

        if p2 := self._coord.plants.get(plant2_id):
            self._coord._fire_event(
                "plant_switched",
                {"plant": self._coord.serializer.serialize_plant(p2)},
            )
            async_fire_plant_event(self._coord.hass, EVENT_PLANT_SWITCHED, p2)

    async def transition_plant_stage(
        self,
        plant_id: str,
        new_stage: str | PlantStage,
        transition_date: date | None = None,
    ) -> None:
        """Transition a plant to a new stage."""
        await self._coord.lifecycle_manager.transition_plant_stage(
            plant_id, new_stage, transition_date
        )
        if plant := self._coord.plants.get(plant_id):
            async_fire_plant_event(
                self._coord.hass,
                EVENT_PLANT_TRANSITIONED,
                plant,
                {"new_stage": str(new_stage)},
            )

    async def remove_plant(self, plant_id: str) -> bool:
        """Remove a plant via lifecycle manager."""
        # Cache plant data before removal so we can fire the event
        plant = self._coord.plants.get(plant_id)
        if not plant:
            return False

        self._coord._invalidate_cache(plant.growspace_id)

        removed = await self._coord.lifecycle_manager.async_remove_plant(plant_id)
        if removed:
            self._coord._fire_event(
                "plant_removed",
                {"plant_id": plant.plant_id, "growspace_id": plant.growspace_id},
            )
            # Fire event with cached plant data
            async_fire_plant_event(self._coord.hass, EVENT_PLANT_REMOVED, plant)
        return removed

    def get_plant(self, plant_id: str) -> Plant | None:
        """Retrieve a plant by its ID.

        Args:
            plant_id: The unique identifier of the plant.

        Returns:
            The Plant object if found, otherwise None.
        """
        return self._coord.data_repository.get_plant(plant_id)
