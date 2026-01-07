"""Service handlers for nutrient presets."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, ServiceCall

from ..const import (
    ATTR_MIN_DAYS_IN_STAGE,
    ATTR_PRESET_ID,
    ATTR_PRESET_NAME,
    ATTR_STAGE,
)

if TYPE_CHECKING:
    from ..coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


async def handle_save_nutrient_preset(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, call: ServiceCall
) -> None:
    """Handle saving a nutrient preset."""
    name = call.data[ATTR_PRESET_NAME]
    nutrients = call.data["nutrients"]
    stage = call.data.get(ATTR_STAGE)
    min_days_in_stage = call.data.get(ATTR_MIN_DAYS_IN_STAGE)

    await coordinator.async_save_nutrient_preset(
        name=name,
        nutrients=nutrients,
        stage=stage,
        min_days_in_stage=min_days_in_stage,
    )


async def handle_remove_nutrient_preset(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, call: ServiceCall
) -> None:
    """Handle removing a nutrient preset."""
    preset_id = call.data[ATTR_PRESET_ID]
    await coordinator.async_remove_nutrient_preset(preset_id)
