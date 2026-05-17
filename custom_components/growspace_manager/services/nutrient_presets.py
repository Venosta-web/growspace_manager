"""Service handlers for nutrient presets."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..const import (
    ATTR_MIN_DAYS_IN_STAGE,
    ATTR_NAME,
    ATTR_PRESET_ID,
    ATTR_STAGE,
    GrowspaceService,
)
from ..schemas import (
    REMOVE_NUTRIENT_PRESET_SCHEMA,
    SAVE_NUTRIENT_PRESET_SCHEMA,
)
from ._definition import ServiceDefinition
from .utils import handle_service_errors

from homeassistant.core import HomeAssistant, ServiceCall

if TYPE_CHECKING:
    from ..coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


@handle_service_errors
async def handle_save_nutrient_preset(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, call: ServiceCall
) -> None:
    """Handle saving a nutrient preset."""
    name = call.data[ATTR_NAME]
    nutrients = call.data["nutrients"]
    preset_id = call.data.get(ATTR_PRESET_ID)
    stage = call.data.get(ATTR_STAGE)
    min_days_in_stage = call.data.get(ATTR_MIN_DAYS_IN_STAGE)

    await coordinator.services.config.save_nutrient_preset(
        name=name,
        nutrients=nutrients,
        stage=stage,
        min_days_in_stage=min_days_in_stage,
        preset_id=preset_id,
    )


@handle_service_errors
async def handle_remove_nutrient_preset(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, call: ServiceCall
) -> None:
    """Handle removing a nutrient preset."""
    preset_id = call.data[ATTR_PRESET_ID]
    await coordinator.services.config.remove_nutrient_preset(preset_id)


SERVICES = [
    ServiceDefinition(
        GrowspaceService.SAVE_NUTRIENT_PRESET,
        handle_save_nutrient_preset,
        SAVE_NUTRIENT_PRESET_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.REMOVE_NUTRIENT_PRESET,
        handle_remove_nutrient_preset,
        REMOVE_NUTRIENT_PRESET_SCHEMA,
    ),
]
