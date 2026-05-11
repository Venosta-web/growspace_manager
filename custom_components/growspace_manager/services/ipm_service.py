"""IPM (Integrated Pest Management) service for the Growspace Manager integration.

This service handles all IPM-related operations,
extracted from the coordinator to reduce complexity.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
import logging
from typing import TYPE_CHECKING, Any
import uuid

from ..event_builder import EventBuilder
from ..models import GrowspaceEvent, IPMPreset, Plant
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from ..data_access.growspace_repository import (
        GrowspaceRepository,
    )

_LOGGER = logging.getLogger(__name__)


class IPMService:
    """Handles all IPM operations."""

    def __init__(
        self,
        hass: HomeAssistant,
        repository: GrowspaceRepository,
        save_callback: Callable[[], Awaitable[None]],
        lock: asyncio.Lock,
        add_event_callback: Callable[[str, GrowspaceEvent], None],
        invalidate_cache_callback: Callable[[str | None], None],
    ) -> None:
        """Initialize the IPM service.

        Args:
            hass: Home Assistant instance.
            repository: Data repository.
            save_callback: Callback to save data.
            lock: Async lock for thread safety.
            add_event_callback: Callback to add events to logbook.
            invalidate_cache_callback: Callback to invalidate cache.
        """
        self.hass = hass
        self.repository = repository
        self.save_callback = save_callback
        self.lock = lock
        self.add_event = add_event_callback
        self.invalidate_cache = invalidate_cache_callback
        self.ipm_presets: dict[str, IPMPreset] = {}

    async def async_save_ipm_preset(
        self,
        name: str,
        type: str,
        items: list[dict[str, Any]],
        stage: str | None = None,
        min_days_in_stage: int | None = None,
        preset_id: str | None = None,
    ) -> IPMPreset:
        """Create or update an IPM preset.

        Args:
            name: Name of the preset.
            type: Type of application (foliar, drench, etc.).
            items: List of IPM items with 'name', 'dose_amount', 'dose_unit'.
            stage: Optional target plant stage.
            min_days_in_stage: Optional minimum days in stage.
            preset_id: Optional existing preset ID to update.

        Returns:
            The saved IPMPreset object.
        """
        if preset_id and preset_id in self.ipm_presets:
            preset = self.ipm_presets[preset_id]
            preset.name = name
            preset.type = type
            preset.items = items  # type: ignore[assignment]
            preset.stage = stage
            preset.min_days_in_stage = min_days_in_stage
        else:
            pid = preset_id or str(uuid.uuid4())
            preset = IPMPreset(
                id=pid,
                name=name,
                type=type,
                items=items,  # type: ignore[arg-type]
                stage=stage,
                min_days_in_stage=min_days_in_stage,
                created_at=dt_util.now().isoformat(),
            )
            self.ipm_presets[pid] = preset

        await self.save_callback()

        _LOGGER.info("Saved IPM preset '%s' (%s) with %d items", name, type, len(items))
        return preset

    async def async_remove_ipm_preset(self, preset_id: str) -> None:
        """Remove an IPM preset.

        Args:
            preset_id: The ID of the preset to remove.

        Raises:
            KeyError: If the preset does not exist.
        """
        if preset_id not in self.ipm_presets:
            raise KeyError(f"IPM preset '{preset_id}' not found")

        preset_name = self.ipm_presets[preset_id].name
        del self.ipm_presets[preset_id]
        await self.save_callback()
        _LOGGER.info("Removed IPM preset '%s' (id=%s)", preset_name, preset_id)

    async def async_apply_ipm(
        self,
        preset_id: str,
        growspace_id: str | None = None,
        plant_ids: list[str] | None = None,
        notes: str | None = None,
    ) -> list[str]:
        """Log an IPM application event.

        Args:
            preset_id: ID of the IPM preset applied.
            growspace_id: ID of the growspace (if applying to whole room).
            plant_ids: List of specific plant IDs (if applying to specific plants).
            notes: Optional user notes.

        Returns:
            List of affected entity IDs (plants or growspace sensors).

        Raises:
            ValueError: If neither growspace_id nor plant_ids are provided.
            KeyError: If preset_id is not found.
        """
        if preset_id not in self.ipm_presets:
            raise KeyError(f"IPM preset '{preset_id}' not found")

        preset = self.ipm_presets[preset_id]
        now = dt_util.now().isoformat()
        target_plants = self._get_target_plants(growspace_id, plant_ids)

        # Calculate max PHI from preset items
        max_phi_days = max(
            (item.get("phi_days", 0) for item in preset.items), default=0
        )

        # Update plant state
        for plant in target_plants:
            plant.last_ipm = now
            plant.last_ipm_type = preset.type

            # Update PHI clearance date if this preset has phi_days
            if max_phi_days > 0:
                clearance = (
                    dt_util.now().date() + timedelta(days=max_phi_days)
                ).isoformat()
                # Only update if new clearance is later than existing
                if (
                    not plant.phi_clearance_date
                    or clearance > plant.phi_clearance_date
                ):
                    plant.phi_clearance_date = clearance

        # Group by growspace for event logging
        affected_gids = {p.growspace_id for p in target_plants}
        if growspace_id:
            affected_gids.add(growspace_id)

        for gid in affected_gids:
            affected_in_gid = [p for p in target_plants if p.growspace_id == gid]
            all_growspace_plants = self.repository.get_growspace_plants(gid)

            event = EventBuilder.create_ipm_event(
                gid, preset, notes, plant_ids, affected_in_gid, all_growspace_plants
            )
            self.add_event(gid, event)

        # Invalidate cache for affected growspaces
        for gid in affected_gids:
            self.invalidate_cache(gid)

        await self.save_callback()

        return [p.plant_id for p in target_plants]

    def _get_target_plants(
        self, growspace_id: str | None, plant_ids: list[str] | None
    ) -> list[Plant]:
        """Resolve target plants from IDs or growspace ID."""
        if plant_ids:
            return [
                self.repository.plants[pid]
                for pid in plant_ids
                if pid in self.repository.plants
            ]
        if growspace_id:
            return self.repository.get_growspace_plants(growspace_id)
        raise ValueError("Either growspace_id or plant_ids must be provided.")
