"""Service handlers for the global Irrigation Recipe library."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from custom_components.growspace_manager.const import (
    ATTR_GROWSPACE_ID,
    ATTR_NAME,
    ATTR_RECIPE_CROP_STEERING,
    ATTR_RECIPE_ID,
    ATTR_RECIPE_KIND,
    ATTR_RECIPE_SCHEDULE,
    GrowspaceService,
    IrrigationRecipeKind,
)
from custom_components.growspace_manager.schemas import (
    APPLY_IRRIGATION_RECIPE_SCHEMA,
    REMOVE_IRRIGATION_RECIPE_SCHEMA,
    SAVE_IRRIGATION_RECIPE_SCHEMA,
    UPDATE_IRRIGATION_RECIPE_SCHEMA,
)
from homeassistant.core import HomeAssistant, ServiceCall

from ._definition import ServiceDefinition
from .utils import handle_service_errors

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


@handle_service_errors
async def handle_save_irrigation_recipe(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, call: ServiceCall
) -> None:
    """Save a growspace's current irrigation settings as a named recipe."""
    await coordinator.services.config.save_irrigation_recipe(
        growspace_id=call.data[ATTR_GROWSPACE_ID],
        name=call.data[ATTR_NAME],
        kind=IrrigationRecipeKind(call.data[ATTR_RECIPE_KIND]),
        recipe_id=call.data.get(ATTR_RECIPE_ID),
    )


@handle_service_errors
async def handle_update_irrigation_recipe(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, call: ServiceCall
) -> None:
    """Rename a recipe and/or correct the values it stores.

    Sparse: a field the call does not name keeps what the recipe stores, and
    the recipe's id, kind, creation time and provenance are not reachable from
    here at all. No growspace is touched — applying is a by-value stamp, so a
    growspace that carries this recipe simply reads as drifted afterwards.
    """
    await coordinator.services.config.update_irrigation_recipe(
        call.data[ATTR_RECIPE_ID],
        name=call.data.get(ATTR_NAME),
        crop_steering=call.data.get(ATTR_RECIPE_CROP_STEERING),
        schedule=call.data.get(ATTR_RECIPE_SCHEDULE),
    )


@handle_service_errors
async def handle_remove_irrigation_recipe(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, call: ServiceCall
) -> None:
    """Remove a recipe from the global Irrigation Recipe library."""
    await coordinator.services.config.remove_irrigation_recipe(
        call.data[ATTR_RECIPE_ID]
    )


@handle_service_errors
async def handle_apply_irrigation_recipe(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, call: ServiceCall
) -> None:
    """Stamp a saved Irrigation Recipe into a growspace (ADR-0045).

    Applying always writes, so re-applying the recipe a growspace already
    carries resets its fields to the recipe and discards hand tweaks. A recipe
    authored in a different medium is applied unscaled and the mismatch is
    logged; the WebSocket command returns that warning to the caller.
    """
    await coordinator.services.growspaces.apply_irrigation_recipe(
        call.data[ATTR_GROWSPACE_ID], call.data[ATTR_RECIPE_ID]
    )


SERVICES = [
    ServiceDefinition(
        GrowspaceService.SAVE_IRRIGATION_RECIPE,
        handle_save_irrigation_recipe,
        SAVE_IRRIGATION_RECIPE_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.UPDATE_IRRIGATION_RECIPE,
        handle_update_irrigation_recipe,
        UPDATE_IRRIGATION_RECIPE_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.REMOVE_IRRIGATION_RECIPE,
        handle_remove_irrigation_recipe,
        REMOVE_IRRIGATION_RECIPE_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.APPLY_IRRIGATION_RECIPE,
        handle_apply_irrigation_recipe,
        APPLY_IRRIGATION_RECIPE_SCHEMA,
    ),
]
