"""Service handlers for drying and curing tracking."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, ServiceCall

from ..const import (
    ATTR_DATE,
    ATTR_MOISTURE_PERCENT,
    ATTR_PLANT_ID,
    ATTR_VISUAL_TAG,
    ATTR_WEIGHT_GRAMS,
    GrowspaceService,
)
from ..schemas import (
    LOG_DRYING_WEIGHT_SCHEMA,
    LOG_MOISTURE_READING_SCHEMA,
    SET_VISUAL_TAG_SCHEMA,
)
from ._definition import ServiceDefinition
from .utils import handle_service_errors

if TYPE_CHECKING:
    from ..coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


@handle_service_errors
async def handle_log_drying_weight(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle logging a daily weight reading during drying."""
    plant_id: str = call.data[ATTR_PLANT_ID]
    weight_grams: float = call.data[ATTR_WEIGHT_GRAMS]
    date: str | None = call.data.get(ATTR_DATE)

    await coordinator.services.plants.log_drying_weight(
        plant_id=plant_id,
        weight_grams=weight_grams,
        date=date,
    )
    _LOGGER.debug("Logged drying weight for plant %s: %.1f g", plant_id, weight_grams)


@handle_service_errors
async def handle_log_moisture_reading(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle logging a daily moisture meter reading."""
    plant_id: str = call.data[ATTR_PLANT_ID]
    moisture_percent: float = call.data[ATTR_MOISTURE_PERCENT]
    date: str | None = call.data.get(ATTR_DATE)

    await coordinator.services.plants.log_moisture_reading(
        plant_id=plant_id,
        moisture_percent=moisture_percent,
        date=date,
    )
    _LOGGER.debug(
        "Logged moisture reading for plant %s: %.1f%%", plant_id, moisture_percent
    )


@handle_service_errors
async def handle_set_visual_tag(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle setting or clearing the visual tag on a plant."""
    plant_id: str = call.data[ATTR_PLANT_ID]
    visual_tag: str | None = call.data.get(ATTR_VISUAL_TAG)

    await coordinator.services.plants.set_visual_tag(
        plant_id=plant_id,
        visual_tag=visual_tag,
    )
    _LOGGER.debug("Set visual tag for plant %s: %s", plant_id, visual_tag)


SERVICES = [
    ServiceDefinition(
        GrowspaceService.LOG_DRYING_WEIGHT,
        handle_log_drying_weight,
        LOG_DRYING_WEIGHT_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.LOG_MOISTURE_READING,
        handle_log_moisture_reading,
        LOG_MOISTURE_READING_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.SET_VISUAL_TAG,
        handle_set_visual_tag,
        SET_VISUAL_TAG_SCHEMA,
    ),
]
