"""Plant service for the Growspace Manager integration.

This service handles all plant-related CRUD operations and business logic,
extracted from the coordinator to reduce complexity.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import date
import logging
from typing import Any

from custom_components.growspace_manager.const import PlantStage
from custom_components.growspace_manager.data_access.growspace_repository import (
    GrowspaceRepository,
)
from custom_components.growspace_manager.events import (
    EVENT_PLANT_ADDED,
    EVENT_PLANT_HARVESTED,
    EVENT_PLANT_MOVED,
    EVENT_PLANT_REMOVED,
    EVENT_PLANT_SWITCHED,
    EVENT_PLANT_TRANSITIONED,
    EVENT_PLANT_UPDATED,
    async_fire_clones_taken_event,
    async_fire_plant_event,
)
from custom_components.growspace_manager.growspace_validator import GrowspaceValidator
from custom_components.growspace_manager.models import Plant
from custom_components.growspace_manager.plant_lifecycle_manager import (
    PlantLifecycleManager,
)
from custom_components.growspace_manager.serializers import GrowspaceSerializer
from custom_components.growspace_manager.services.growspace_service import (
    GrowspaceService,
)
from custom_components.growspace_manager.utils import calculate_plant_stage
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class PlantService:
    """Handles all plant CRUD operations and business logic."""

    def __init__(
        self,
        hass: HomeAssistant,
        repository: GrowspaceRepository,
        validator: GrowspaceValidator,
        lifecycle_manager: PlantLifecycleManager,
        growspace_service: GrowspaceService,
        serializer: GrowspaceSerializer,
        save_callback: Callable[[], Awaitable[None]],
        lock: asyncio.Lock,
    ) -> None:
        """Initialize the plant service.

        Args:
            hass: Home Assistant instance.
            repository: Data repository.
            validator: Growspace validator.
            lifecycle_manager: Plant lifecycle manager.
            growspace_service: Growspace service.
            serializer: Growspace serializer.
            save_callback: Callback to save data.
            lock: Async lock for thread safety.
        """
        self.hass = hass
        self.repository = repository
        self.validator = validator
        self.lifecycle_manager = lifecycle_manager
        self.growspace_service = growspace_service
        self.serializer = serializer
        self.save_callback = save_callback
        self.lock = lock

    def _fire_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Fire a growspace manager event."""
        payload = {"event_type": event_type, "data": data}
        self.hass.bus.async_fire("growspace_manager_updated", payload)

    async def add_plant(
        self,
        growspace_id: str,
        strain: str,
        plant_id: str | None = None,
        phenotype: str = "",
        row: int = 1,
        col: int = 1,
        stage: str = "",
        type_str: str = "normal",
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
        """Add a new plant to the system via lifecycle manager."""
        plant = await self.lifecycle_manager.async_add_plant(
            growspace_id=growspace_id,
            strain=strain,
            plant_id=plant_id,
            phenotype=phenotype,
            row=row,
            col=col,
            stage=stage,
            plant_type=type_str,
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

        # Invalidate cache if available
        # self.cache.invalidate(growspace_id)

        self._fire_event(
            "plant_added", {"plant": self.serializer.serialize_plant(plant)}
        )
        async_fire_plant_event(self.hass, EVENT_PLANT_ADDED, plant)
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
        mother_id: str = self.growspace_service.ensure_mother_growspace()
        kwargs["type_str"] = PlantStage.MOTHER

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
        self.validator.validate_plant_exists(mother_plant_id)

        mother = self.repository.plants[mother_plant_id]

        # Determine target growspace: use provided ID or default to clone
        if target_growspace_id:
            # Validate that the target growspace exists
            if target_growspace_id not in self.repository.growspaces:
                raise ValueError(
                    f"Target growspace '{target_growspace_id}' does not exist"
                )
            clone_gs_id = target_growspace_id
        else:
            # Default to clone growspace
            clone_gs_id = self.growspace_service.ensure_special_growspace(
                PlantStage.CLONE, "clone", 5, 5
            )

        new_plants: list[Plant] = []

        # Ensure transition_date is a date object
        if transition_date is None:
            transition_date = date.today()

        # Pre-invalidate clone growspace cache
        # if self.cache:
        #     self.cache.invalidate(clone_gs_id)

        for _ in range(num_clones):
            row, col = self.validator.find_first_available_position(clone_gs_id)
            if row is None or col is None:
                _LOGGER.warning("Clone growspace %s is full", clone_gs_id)
                raise ValueError(f"Growspace '{clone_gs_id}' is full")

            clone_id = await self.lifecycle_manager.handle_clone_creation(
                growspace_id=clone_gs_id,
                strain=mother.strain,
                row=row,
                col=col,
                source_mother_id=mother_plant_id,
                mother_plant=mother,
                phenotype=mother.phenotype,
                clone_start=transition_date,
            )

            if new_plant := self.repository.plants.get(clone_id):
                new_plants.append(new_plant)
                # Fire individual plant_added event for frontend refresh
                self._fire_event(
                    "plant_added",
                    {"plant": self.serializer.serialize_plant(new_plant)},
                )
                async_fire_plant_event(self.hass, EVENT_PLANT_ADDED, new_plant)

        # Fire clones taken event
        if new_plants:
            async_fire_clones_taken_event(
                self.hass, mother, len(new_plants), clone_gs_id
            )

        return new_plants

    async def update_plant(self, plant_id: str, **updates: Any) -> Plant:
        """Update the attributes of an existing plant."""
        # Invalidate current growspace (logic for move)
        # if plant := self.repository.plants.get(plant_id):
        #     # Invalidate cache for the current growspace to reflect updates (e.g. stage change)
        #     # self.cache.invalidate(plant.growspace_id)

        #     if (
        #         "growspace_id" in updates
        #         and updates["growspace_id"] != plant.growspace_id
        #     ):
        #         # self.cache.invalidate(updates["growspace_id"])
        #         pass

        plant = await self.lifecycle_manager.async_update_plant(plant_id, **updates)

        self._fire_event(
            "plant_updated",
            {"plant": self.serializer.serialize_plant(plant)},
        )
        async_fire_plant_event(self.hass, EVENT_PLANT_UPDATED, plant, updates)
        return plant

    async def move_plant(self, plant_id: str, new_row: int, new_col: int) -> None:
        """Move a plant to a new position via lifecycle manager."""
        # if plant := self.repository.plants.get(plant_id):
        #     # self.cache.invalidate(plant.growspace_id)
        #     pass

        await self.lifecycle_manager.async_move_plant(plant_id, new_row, new_col)

        # Fetch updated plant to fire event
        if plant := self.repository.plants.get(plant_id):
            async_fire_plant_event(
                self.hass,
                EVENT_PLANT_MOVED,
                plant,
                {"new_row": new_row, "new_col": new_col},
            )

    async def switch_plants(self, plant1_id: str, plant2_id: str) -> None:
        """Switch the positions of two plants via lifecycle manager."""
        # p1 = self.repository.plants.get(plant1_id)
        # p2 = self.repository.plants.get(plant2_id)

        # if p1:
        #     # self.cache.invalidate(p1.growspace_id)
        #     pass
        # if p2:
        #     # self.cache.invalidate(p2.growspace_id)
        #     pass

        await self.lifecycle_manager.async_switch_plants(plant1_id, plant2_id)

        # Fire events for both plants to update frontend
        if p1 := self.repository.plants.get(plant1_id):
            self._fire_event(
                "plant_switched",
                {"plant": self.serializer.serialize_plant(p1)},
            )
            async_fire_plant_event(self.hass, EVENT_PLANT_SWITCHED, p1)

        if p2 := self.repository.plants.get(plant2_id):
            self._fire_event(
                "plant_switched",
                {"plant": self.serializer.serialize_plant(p2)},
            )
            async_fire_plant_event(self.hass, EVENT_PLANT_SWITCHED, p2)

    async def transition_plant_stage(
        self,
        plant_id: str,
        new_stage: str | PlantStage,
        transition_date: date | None = None,
    ) -> None:
        """Transition a plant to a new stage."""
        await self.lifecycle_manager.transition_plant_stage(
            plant_id, new_stage, transition_date
        )
        if plant := self.repository.plants.get(plant_id):
            async_fire_plant_event(
                self.hass,
                EVENT_PLANT_TRANSITIONED,
                plant,
                {"new_stage": str(new_stage)},
            )

    async def remove_plant(self, plant_id: str) -> bool:
        """Remove a plant via lifecycle manager."""
        # Cache plant data before removal so we can fire the event
        plant = self.repository.plants.get(plant_id)
        if not plant:
            return False

        # if self.cache:
        #     self.cache.invalidate(plant.growspace_id)

        removed = await self.lifecycle_manager.async_remove_plant(plant_id)
        if removed:
            self._fire_event(
                "plant_removed",
                {"plant_id": plant.plant_id, "growspace_id": plant.growspace_id},
            )
            # Fire event with cached plant data
            async_fire_plant_event(self.hass, EVENT_PLANT_REMOVED, plant)
        return removed

    def get_plant(self, plant_id: str) -> Plant | None:
        """Retrieve a plant by its ID.

        Args:
            plant_id: The unique identifier of the plant.

        Returns:
            The Plant object if found, otherwise None.
        """
        return self.repository.get_plant(plant_id)

    # =========================================================================
    # STAGE TRANSITION CONVENIENCE METHODS
    # =========================================================================

    async def start_flowering(self, plant_id: str) -> Plant:
        """Transition a plant to the 'flower' stage, starting today.

        Args:
            plant_id: The ID of the plant to start flowering.

        Returns:
            The updated Plant object.
        """
        await self.transition_plant_stage(plant_id, PlantStage.FLOWER, date.today())
        return self.repository.plants[plant_id]

    async def start_drying(self, plant_id: str) -> Plant:
        """Transition a plant to the 'drying' stage, starting today.

        Args:
            plant_id: The ID of the plant to start drying.

        Returns:
            The updated Plant object.
        """
        await self.transition_plant_stage(plant_id, PlantStage.DRY, date.today())
        return self.repository.plants[plant_id]

    async def start_curing(self, plant_id: str) -> Plant:
        """Transition a plant to the 'curing' stage, starting today.

        Args:
            plant_id: The ID of the plant to start curing.

        Returns:
            The updated Plant object.
        """
        await self.transition_plant_stage(plant_id, PlantStage.CURE, date.today())
        return self.repository.plants[plant_id]

    async def harvest(self, plant_id: str) -> Plant:
        """Quick harvest - mark plant as harvested and transition to drying stage.

        This is a convenience method that transitions the plant to the dry stage
        starting today.

        Args:
            plant_id: The ID of the plant to harvest.

        Returns:
            The updated Plant object.
        """
        return await self.start_drying(plant_id)

    # =========================================================================
    # HARVEST ORCHESTRATION
    # =========================================================================

    async def harvest_plant(
        self,
        plant_id: str,
        target_growspace_id: str | None = None,
        target_growspace_name: str | None = None,
        transition_date: str | None = None,
    ) -> None:
        """Harvest a plant, which may involve moving it to a 'dry' or 'cure' growspace.

        This method orchestrates the harvest process, including recording analytics
        and moving the plant based on an explicit target or an automatic flow.

        Args:
            plant_id: The ID of the plant to harvest.
            target_growspace_id: The explicit ID of the growspace to move the plant to (optional).
            target_growspace_name: The name of the target growspace (used as a hint).
            transition_date: The date of the harvest (optional, defaults to today).
        """
        self.validator.validate_plant_exists(plant_id)

        plant = self.repository.plants[plant_id]
        transition_date_str = transition_date or date.today().isoformat()

        # Log harvest start
        stage_before = calculate_plant_stage(plant)
        _LOGGER.info(
            "Harvest start: plant_id=%s stage=%s current_growspace=%s target_id=%s target_name=%s date=%s",
            plant_id,
            stage_before,
            plant.growspace_id,
            target_growspace_id,
            target_growspace_name,
            transition_date_str,
        )

        # Invalidate source
        # if self.cache:
        #     self.cache.invalidate(plant.growspace_id)
        # # Invalidate target if known (and different)
        # if target_growspace_id and self.cache:
        #     self.cache.invalidate(target_growspace_id)

        moved = await self.lifecycle_manager.handle_harvest_logic(
            plant_id,
            plant,
            target_growspace_id,
            target_growspace_name,
            transition_date_str,
        )

        # Invalidate common harvest targets just in case
        # if moved and self.cache:
        #     self.cache.invalidate("dry")
        #     self.cache.invalidate("cure")

        await self.save_callback()

        _LOGGER.info(
            "Harvest end: plant_id=%s moved=%s target_growspace_id=%s row=%s col=%s stage=%s dry_start=%s cure_start=%s",
            plant_id,
            moved,
            target_growspace_id,
            plant.row,
            plant.col,
            plant.stage,
            plant.dry_start,
            plant.cure_start,
        )
        async_fire_plant_event(self.hass, EVENT_PLANT_HARVESTED, plant)
