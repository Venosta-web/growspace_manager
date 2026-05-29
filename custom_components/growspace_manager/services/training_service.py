"""Training service for the Growspace Manager integration.

This service handles all plant training-related operations,
extracted from the coordinator to reduce complexity.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from custom_components.growspace_manager.event_builder import EventBuilder
from custom_components.growspace_manager.models import Plant
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .context import BaseService, ServiceContext

if TYPE_CHECKING:
    from custom_components.growspace_manager.data_access.growspace_repository import (
        GrowspaceRepository,
    )

_LOGGER = logging.getLogger(__name__)


class TrainingService(BaseService):
    """Handles all plant training operations."""

    def __init__(
        self,
        ctx: ServiceContext,
        hass: HomeAssistant,
        repository: GrowspaceRepository,
    ) -> None:
        super().__init__(ctx)
        self.hass = hass
        self.repository = repository

    async def async_log_training_event(
        self,
        growspace_id: str | None,
        technique: str,
        notes: str | None = None,
        plant_ids: list[str] | None = None,
    ) -> None:
        """Log a training event for specific plants or an entire growspace."""
        _LOGGER.debug(
            "async_log_training_event called with gid=%s, pids=%s, technique=%s",
            growspace_id,
            plant_ids,
            technique,
        )

        target_plants = self._get_target_plants(growspace_id, plant_ids)
        now = dt_util.now().isoformat()

        # Update plants
        for plant in target_plants:
            plant.last_training_technique = technique
            plant.last_trained = now

        # Group by growspace for event logging
        affected_gids = {p.growspace_id for p in target_plants}
        if not target_plants and growspace_id:
            affected_gids = {growspace_id}

        for gid in affected_gids:
            affected_in_gid = [p for p in target_plants if p.growspace_id == gid]
            all_growspace_plants = self.repository.get_growspace_plants(gid)

            event = EventBuilder.create_training_event(
                gid,
                technique,
                notes or "",
                plant_ids or [],
                affected_in_gid,
                all_growspace_plants,
            )
            self._emit(gid, event)

            # Invalidate cache before saving
            self._invalidate(gid)

        await self._save()

    def _get_target_plants(
        self, growspace_id: str | None, plant_ids: list[str] | None
    ) -> list[Plant]:
        """Resolve target plants from IDs or growspace ID."""
        if plant_ids:
            return [
                self.repository.require_plant(pid)
                for pid in plant_ids
                if self.repository.has_plant(pid)
            ]
        if growspace_id:
            return self.repository.get_growspace_plants(growspace_id)
        raise ValueError("Either growspace_id or plant_ids must be provided.")
