"""Watering service for the Growspace Manager integration.

This service handles all watering-related operations,
extracted from the coordinator to reduce complexity.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..event_builder import EventBuilder
from ..exceptions import GrowspaceError
from ..models import Plant
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .context import BaseService, ServiceContext

if TYPE_CHECKING:
    from ..data_access.growspace_repository import (
        GrowspaceRepository,
    )
    from ..growspace_validator import (
        GrowspaceValidator,
    )
    from ..managers.nutrient import NutrientManager

_LOGGER = logging.getLogger(__name__)


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
        plant = await self._water_plant_internal(
            plant_id, amount, nutrients, preset_id, invalidate_cache=True
        )
        await self._save()
        return plant

    async def _water_plant_internal(
        self,
        plant_id: str,
        amount: float,
        nutrients: dict[str, float] | None = None,
        preset_id: str | None = None,
        invalidate_cache: bool = True,
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
        now_iso = dt_util.now().isoformat()
        plant.last_watered = now_iso

        # Track water usage on the growspace
        growspace = self.repository.get_growspace(plant.growspace_id)
        if growspace is not None:
            today = dt_util.now().date().isoformat()
            water_usage = growspace.water_usage
            water_usage.total_liters += amount
            # Append or update today's daily reading
            daily = water_usage.daily_readings
            if daily and daily[-1].get("date") == today:
                daily[-1]["liters"] = daily[-1].get("liters", 0.0) + amount
                daily[-1]["plant_count"] = len(
                    self.repository.get_growspace_plants(plant.growspace_id)
                )
            else:
                daily.append(
                    {
                        "date": today,
                        "liters": amount,
                        "plant_count": len(
                            self.repository.get_growspace_plants(plant.growspace_id)
                        ),
                    }
                )
            # Enforce rolling window
            max_readings = water_usage.max_daily_readings
            if len(daily) > max_readings:
                water_usage.daily_readings = daily[-max_readings:]

        # Invalidate cache for the growspace if requested
        if invalidate_cache:
            self._invalidate(plant.growspace_id)

        # Create and log the watering event
        event = EventBuilder.create_watering_event(
            plant, amount, preset_name, final_nutrients
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
    ) -> int:
        """Record a watering event for all plants in a growspace."""
        self.validator.validate_growspace_exists(growspace_id)
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
            )

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
