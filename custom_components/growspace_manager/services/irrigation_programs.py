"""Service handlers for the global Irrigation Program library."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from custom_components.growspace_manager.const import (
    ATTR_GROWSPACE_ID,
    ATTR_NAME,
    ATTR_PROGRAM_ID,
    ATTR_PROGRAM_SLOTS,
    GrowspaceService,
)
from custom_components.growspace_manager.schemas import (
    ASSIGN_IRRIGATION_PROGRAM_SCHEMA,
    REMOVE_IRRIGATION_PROGRAM_SCHEMA,
    SAVE_IRRIGATION_PROGRAM_SCHEMA,
)
from homeassistant.core import HomeAssistant, ServiceCall

from ._definition import ServiceDefinition
from .utils import handle_service_errors

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


@handle_service_errors
async def handle_save_irrigation_program(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, call: ServiceCall
) -> None:
    """Save a plan of ``(stage, week)`` slots as a named Irrigation Program."""
    await coordinator.services.config.save_irrigation_program(
        name=call.data[ATTR_NAME],
        slots=call.data[ATTR_PROGRAM_SLOTS],
        program_id=call.data.get(ATTR_PROGRAM_ID),
    )


@handle_service_errors
async def handle_remove_irrigation_program(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, call: ServiceCall
) -> None:
    """Remove a program from the global Irrigation Program library."""
    await coordinator.services.config.remove_irrigation_program(
        call.data[ATTR_PROGRAM_ID]
    )


@handle_service_errors
async def handle_assign_irrigation_program(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, call: ServiceCall
) -> None:
    """Bind a growspace to an Irrigation Program, or unbind it (ADR-0045).

    Binding only: no setpoint is written and no pump fires. Omitting
    ``program_id`` — or passing it as null — unbinds.
    """
    await coordinator.services.growspaces.assign_irrigation_program(
        call.data[ATTR_GROWSPACE_ID], call.data.get(ATTR_PROGRAM_ID)
    )


SERVICES = [
    ServiceDefinition(
        GrowspaceService.SAVE_IRRIGATION_PROGRAM,
        handle_save_irrigation_program,
        SAVE_IRRIGATION_PROGRAM_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.REMOVE_IRRIGATION_PROGRAM,
        handle_remove_irrigation_program,
        REMOVE_IRRIGATION_PROGRAM_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.ASSIGN_IRRIGATION_PROGRAM,
        handle_assign_irrigation_program,
        ASSIGN_IRRIGATION_PROGRAM_SCHEMA,
    ),
]
