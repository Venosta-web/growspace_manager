"""Plant cloning service handlers: take clone and promote clone."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from custom_components.growspace_manager.const import (
    ATTR_MOTHER_PLANT_ID,
    ATTR_NUM_CLONES,
    ATTR_PLANT_ID,
    ATTR_TARGET_GROWSPACE_ID,
    ATTR_TRANSITION_DATE,
    GrowspaceService,
)
from custom_components.growspace_manager.exceptions import GrowspaceError
from custom_components.growspace_manager.schemas import (
    MOVE_CLONE_SCHEMA,
    TAKE_CLONE_SCHEMA,
)
from custom_components.growspace_manager.services._definition import ServiceDefinition
from custom_components.growspace_manager.strain_library import StrainLibrary
from custom_components.growspace_manager.utils import parse_date_field
from homeassistant.components.persistent_notification import (
    async_create as create_notification,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


async def handle_take_clone(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle taking clones from a plant."""
    mother_plant_id = call.data[ATTR_MOTHER_PLANT_ID]
    transition_date_raw = call.data.get(ATTR_TRANSITION_DATE)
    # Keep the full datetime (no .date() truncation) — ADR-0013.
    transition_date = parse_date_field(transition_date_raw) or dt_util.utcnow()

    target_growspace_id = call.data.get(ATTR_TARGET_GROWSPACE_ID)

    num_clones = call.data.get(ATTR_NUM_CLONES, 1)
    try:
        num_clones = int(num_clones)
    except (TypeError, ValueError) as err:
        raise ServiceValidationError(
            f"num_clones must be an integer, got: {num_clones!r}"
        ) from err
    if num_clones <= 0:
        raise ServiceValidationError(f"num_clones must be positive, got: {num_clones}")

    _LOGGER.debug(
        "Handling take_clone for %s, requesting %d clones to growspace %s",
        mother_plant_id,
        num_clones,
        target_growspace_id or "default (clone)",
    )

    if mother_plant_id not in coordinator.plants:
        _LOGGER.error("Mother plant %s does not exist for take_clone", mother_plant_id)
        raise ServiceValidationError(f"Mother plant {mother_plant_id} not found.")

    try:
        clones = await coordinator.services.plants.take_clones(
            mother_plant_id=mother_plant_id,
            num_clones=num_clones,
            target_growspace_id=target_growspace_id,
            transition_date=transition_date,
        )
        clones_added_count = len(clones)
    except (GrowspaceError, ValueError) as err:
        _LOGGER.error("Failed to take clones from %s: %s", mother_plant_id, err)
        raise ServiceValidationError(str(err)) from err

    _LOGGER.info(
        "Successfully took %d clones from %s to growspace %s",
        clones_added_count,
        mother_plant_id,
        target_growspace_id or "clone",
    )


async def handle_move_clone(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Move an existing clone, typically to 'veg' stage."""
    plant_id = call.data.get(ATTR_PLANT_ID)
    target_growspace_id = call.data.get(ATTR_TARGET_GROWSPACE_ID)

    transition_date_str = call.data.get(ATTR_TRANSITION_DATE)
    # Keep the full datetime (no .date() truncation) — ADR-0013.
    transition_date = parse_date_field(transition_date_str) or dt_util.utcnow()

    if not plant_id or not target_growspace_id:
        _LOGGER.error(
            "Missing plant_id or target_growspace_id for move_clone service call"
        )
        raise ServiceValidationError(
            "Missing plant_id or target_growspace_id for move_clone."
        )

    try:
        await coordinator.services.plants.promote_clone(
            clone_id=plant_id,
            target_growspace_id=target_growspace_id,
            transition_date=transition_date,
        )

        _LOGGER.info(
            "Moved clone %s to growspace %s (PROMOTED)",
            plant_id,
            target_growspace_id,
        )
    except (
        AttributeError,
        KeyError,
        ValueError,
        ServiceValidationError,
        GrowspaceError,
    ) as e:
        _LOGGER.exception("Failed to promote clone %s", plant_id)
        create_notification(
            hass,
            f"Failed to move clone {plant_id}: {e!s}",
            title="Growspace Manager Error",
        )
        raise ServiceValidationError(str(e)) from e


SERVICES: list[ServiceDefinition] = [
    ServiceDefinition(
        GrowspaceService.TAKE_CLONE,
        handle_take_clone,
        TAKE_CLONE_SCHEMA,
        needs_strain_lib=True,
    ),
    ServiceDefinition(
        GrowspaceService.MOVE_CLONE,
        handle_move_clone,
        MOVE_CLONE_SCHEMA,
        needs_strain_lib=True,
    ),
]
