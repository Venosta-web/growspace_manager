"""Watering service for the Growspace Manager integration.

This service handles all watering-related operations,
extracted from the coordinator to reduce complexity.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING
from uuid import uuid4

from custom_components.growspace_manager.domain.water_aggregation import (
    record_hand_watering,
)
from custom_components.growspace_manager.event_builder import EventBuilder
from custom_components.growspace_manager.exceptions import GrowspaceError
from custom_components.growspace_manager.models import Plant
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .context import BaseService, ServiceContext

if TYPE_CHECKING:
    from custom_components.growspace_manager.data_access.growspace_repository import (
        GrowspaceRepository,
    )
    from custom_components.growspace_manager.growspace_validator import (
        GrowspaceValidator,
    )
    from custom_components.growspace_manager.managers.nutrient import NutrientManager

_LOGGER = logging.getLogger(__name__)


def _resolve_watered_at(watered_at: str | None) -> tuple[datetime, bool]:
    """Validate a report time and say whether it describes a past watering."""
    now = dt_util.now()
    if watered_at is None:
        return now, False
    parsed = dt_util.parse_datetime(watered_at)
    if parsed is None or parsed.tzinfo is None:
        raise GrowspaceError("watered_at must be an ISO timestamp with a timezone")
    if parsed > now:
        raise GrowspaceError("watered_at cannot be in the future")
    if now - parsed > timedelta(days=7):
        raise GrowspaceError("watered_at cannot be more than 7 days ago")
    return parsed, now - parsed > timedelta(minutes=1)


class WateringService(BaseService):
    """Handles all watering operations."""

    def __init__(
        self,
        ctx: ServiceContext,
        hass: HomeAssistant,
        repository: GrowspaceRepository,
        validator: GrowspaceValidator,
        nutrient_manager: NutrientManager,
    ) -> None:
        """Initialise the watering service with its dependencies."""
        super().__init__(ctx)
        self.hass = hass
        self.repository = repository
        self.validator = validator
        self.nutrient_manager = nutrient_manager

    async def async_water_plant(
        self,
        plant_id: str,
        amount: float,
        nutrients: dict[str, float] | None = None,
        preset_id: str | None = None,
        *,
        watered_at: str | None = None,
        from_monitored_tank: bool = False,
        user_id: str | None = None,
    ) -> Plant:
        """Record a watering event for a single plant.

        Args:
            plant_id: The ID of the plant to water.
            amount: The amount of water in liters.
            nutrients: Optional dict of nutrient name to concentration (ml/L).
            preset_id: Optional ID of a nutrient preset to apply.

        Returns:
            The updated Plant object.
        """
        when, late = _resolve_watered_at(watered_at)
        plant = await self._water_plant_internal(
            plant_id,
            amount,
            nutrients,
            preset_id,
            invalidate_cache=True,
            when=when,
            from_monitored_tank=from_monitored_tank,
            user_id=user_id,
        )
        if not late and self._ctx.hand_watering_callback is not None:
            self._ctx.hand_watering_callback(plant.growspace_id)
        await self._save()
        return plant

    async def _water_plant_internal(
        self,
        plant_id: str,
        amount: float,
        nutrients: dict[str, float] | None = None,
        preset_id: str | None = None,
        invalidate_cache: bool = True,
        *,
        when: datetime | None = None,
        from_monitored_tank: bool = False,
        user_id: str | None = None,
    ) -> Plant:
        """Internal watering logic with optional cache invalidation."""
        self.validator.validate_plant_exists(plant_id)
        plant = self.repository.require_plant(plant_id)

        final_nutrients, preset_name = self.nutrient_manager.resolve_nutrient_mix(
            nutrients, preset_id
        )

        # Deduct nutrients from inventory using manager
        self.nutrient_manager.deduct_from_inventory(final_nutrients, amount)

        # Update plant's last_watered timestamp
        if when is None:
            when = dt_util.now()
        watered_iso = when.isoformat()
        if plant.last_watered and len(plant.last_watered) == 10:
            previous_date = dt_util.parse_date(plant.last_watered)
            should_update = (
                previous_date is None or previous_date <= dt_util.as_local(when).date()
            )
        else:
            previous = (
                dt_util.parse_datetime(plant.last_watered)
                if plant.last_watered
                else None
            )
            should_update = previous is None or dt_util.as_utc(
                previous
            ) <= dt_util.as_utc(when)
        if should_update:
            plant.last_watered = watered_iso
        watering_id = uuid4().hex

        # Track water usage on the growspace (manual source — see ADR-0017)
        growspace = self.repository.get_growspace(plant.growspace_id)
        if growspace is not None:
            record_hand_watering(
                growspace,
                amount,
                watering_id=watering_id,
                user_id=user_id,
                plant_id=plant_id,
                watered_at=watered_iso,
                from_monitored_tank=from_monitored_tank,
                reference_date=dt_util.as_local(when).date().isoformat(),
            )

        # Invalidate cache for the growspace if requested
        if invalidate_cache:
            self._invalidate(plant.growspace_id)

        # Create and log the watering event
        event = EventBuilder.create_watering_event(
            plant,
            amount,
            preset_name,
            final_nutrients,
            watering_id=watering_id,
            user_id=user_id,
            watered_at=watered_iso,
            from_monitored_tank=from_monitored_tank,
        )
        self._emit(plant.growspace_id, event)

        _LOGGER.info(
            "Watered plant %s (%s) with %sL%s%s",
            plant_id,
            plant.strain,
            amount,
            f" using preset '{preset_name}'" if preset_name else "",
            f" + manual nutrients: {nutrients}" if nutrients else "",
        )

        return plant

    async def async_water_growspace(
        self,
        growspace_id: str,
        amount_per_plant: float | None = None,
        nutrients: dict[str, float] | None = None,
        preset_id: str | None = None,
        amount: float | None = None,
        *,
        watered_at: str | None = None,
        from_monitored_tank: bool = False,
        user_id: str | None = None,
    ) -> int:
        """Record a watering event for all plants in a growspace."""
        self.validator.validate_growspace_exists(growspace_id)
        when, late = _resolve_watered_at(watered_at)
        plants = self.repository.get_growspace_plants(growspace_id)

        if not plants:
            return 0

        # Determine amount per plant if total amount is provided
        if amount is not None:
            amount_per_plant = amount / len(plants)
        elif amount_per_plant is None:
            raise GrowspaceError(
                "Either 'amount' (total) or 'amount_per_plant' is required"
            )

        for plant in plants:
            await self._water_plant_internal(
                plant.plant_id,
                amount_per_plant,
                nutrients,
                preset_id,
                invalidate_cache=False,
                when=when,
                from_monitored_tank=from_monitored_tank,
                user_id=user_id,
            )

        if not late and self._ctx.hand_watering_callback is not None:
            self._ctx.hand_watering_callback(growspace_id)

        # Bulk invalidation
        self._invalidate(growspace_id)

        _LOGGER.info(
            "Watered %d plants in growspace %s with %sL each%s",
            len(plants),
            growspace_id,
            amount_per_plant,
            f" using preset '{preset_id}'" if preset_id else "",
        )

        await self._save()

        return len(plants)
