"""Service handlers for water consumption analytics."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from custom_components.growspace_manager.const import (
    ATTR_GROWSPACE_ID,
    GrowspaceService,
)
from custom_components.growspace_manager.schemas import RESET_WATER_TRACKING_SCHEMA
from homeassistant.core import HomeAssistant, ServiceCall

from ._definition import ServiceDefinition
from .utils import handle_service_errors

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


@handle_service_errors
async def handle_reset_water_tracking(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle resetting water tracking counters for a growspace.

    Args:
        hass: The Home Assistant instance.
        coordinator: The GrowspaceCoordinator instance.
        call: The service call with growspace_id.
    """
    growspace_id: str = call.data[ATTR_GROWSPACE_ID]

    await coordinator.services.growspaces.reset_water_tracking(growspace_id=growspace_id)

    _LOGGER.info("Reset water tracking for growspace %s", growspace_id)


SERVICES = [
    ServiceDefinition(
        GrowspaceService.RESET_WATER_TRACKING,
        handle_reset_water_tracking,
        RESET_WATER_TRACKING_SCHEMA,
    ),
]
