"""Service handler for configuring irrigation tank settings."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

from ..const import (
    ATTR_GROWSPACE_ID,
    ATTR_TANK_ENTITY,
    ATTR_VOLUME_LITERS,
    GrowspaceService,
)
from ..schemas import CONFIGURE_TANK_SCHEMA
from ._definition import ServiceDefinition
from .utils import handle_service_errors

if TYPE_CHECKING:
    from ..coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


@handle_service_errors
async def handle_configure_tank(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle configuring an irrigation tank's settings.

    Args:
        hass: The Home Assistant instance.
        coordinator: The GrowspaceCoordinator instance.
        call: The service call with growspace_id, tank_entity, and optional volume_liters.
    """
    growspace_id: str = call.data[ATTR_GROWSPACE_ID]
    tank_entity: str = call.data[ATTR_TANK_ENTITY]
    volume_liters: float | None = call.data.get(ATTR_VOLUME_LITERS)

    growspace = coordinator.data_repository.get_growspace(growspace_id)
    tanks = (
        growspace.environment_config.irrigation_tanks
        if growspace and growspace.environment_config
        else []
    )
    matching = [t for t in tanks if t.sensor_entity == tank_entity]
    if not matching:
        raise ServiceValidationError(
            f"Tank entity '{tank_entity}' not found in growspace '{growspace_id}'"
        )

    await coordinator.growspace_manager.async_configure_tank(
        growspace_id,
        tank_entity,
        volume_liters=volume_liters,
    )

    _LOGGER.info("Updated tank config for %s in %s", tank_entity, growspace_id)


SERVICES = [
    ServiceDefinition(
        GrowspaceService.CONFIGURE_TANK,
        handle_configure_tank,
        CONFIGURE_TANK_SCHEMA,
    ),
]
