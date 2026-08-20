"""Plant spatial service handlers: move and switch plant positions."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from custom_components.growspace_manager.const import (
    ATTR_NEW_COL,
    ATTR_NEW_ROW,
    ATTR_PLANT1_ID,
    ATTR_PLANT2_ID,
    ATTR_PLANT_ID,
    GrowspaceService,
)
from custom_components.growspace_manager.exceptions import GrowspaceError
from custom_components.growspace_manager.schemas import (
    MOVE_PLANT_SCHEMA,
    SWITCH_PLANT_SCHEMA,
)
from custom_components.growspace_manager.services._definition import ServiceDefinition
from custom_components.growspace_manager.strain_library import StrainLibrary
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


async def handle_switch_plants(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle switch plants service call."""
    plant_id_1 = call.data[ATTR_PLANT1_ID]
    plant_id_2 = call.data[ATTR_PLANT2_ID]

    if plant_id_1 not in coordinator.plants:
        _LOGGER.error("Plant %s does not exist for switch_plants", plant_id_1)
        raise ServiceValidationError(f"Plant {plant_id_1} does not exist.")
    if plant_id_2 not in coordinator.plants:
        _LOGGER.error("Plant %s does not exist for switch_plants", plant_id_2)
        raise ServiceValidationError(f"Plant {plant_id_2} does not exist.")

    try:
        await coordinator.services.plants.switch_plants(plant_id_1, plant_id_2)
        _LOGGER.info("Plants %s and %s switched successfully", plant_id_1, plant_id_2)

    except (
        AttributeError,
        KeyError,
        ValueError,
        ServiceValidationError,
        GrowspaceError,
    ) as err:
        _LOGGER.exception("Failed to switch plants %s and %s", plant_id_1, plant_id_2)
        if isinstance(err, ServiceValidationError):
            raise
        raise ServiceValidationError(
            f"Failed to switch plants {plant_id_1} and {plant_id_2}: {err}"
        ) from err


async def handle_move_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle move plant service call, switching positions if target is occupied."""
    plant_id = call.data[ATTR_PLANT_ID]
    if plant_id not in coordinator.plants:
        _LOGGER.error("Plant %s does not exist for move_plant", plant_id)
        raise ServiceValidationError(f"Plant {plant_id} does not exist.")

    try:
        plant = coordinator.plants[plant_id]
        new_row, new_col = call.data[ATTR_NEW_ROW], call.data[ATTR_NEW_COL]
        old_row, old_col = plant.row, plant.col

        existing_plants = coordinator.services.growspaces.get_growspace_plants(
            plant.growspace_id
        )
        occupying_plant = None
        for other_plant in existing_plants:
            if (
                other_plant.plant_id != plant_id
                and other_plant.row == new_row
                and other_plant.col == new_col
            ):
                occupying_plant = other_plant
                break

        if occupying_plant:
            occupying_plant_id = occupying_plant.plant_id

            _LOGGER.info(
                "Switching positions: %s (%d,%d) ↔ %s (%d,%d) in growspace %s",
                plant.strain,
                old_row,
                old_col,
                occupying_plant.strain,
                new_row,
                new_col,
                plant.growspace_id,
            )

            await coordinator.services.plants.switch_plants(
                plant_id, occupying_plant_id
            )

            _LOGGER.info(
                "Successfully switched positions for %s and %s",
                plant_id,
                occupying_plant_id,
            )
        else:
            await coordinator.services.plants.move_plant(plant_id, new_row, new_col)
            _LOGGER.info(
                "Plant %s moved to (%d,%d) in growspace %s",
                plant.strain,
                new_row,
                new_col,
                plant.growspace_id,
            )

    except (
        AttributeError,
        KeyError,
        ValueError,
        ServiceValidationError,
        GrowspaceError,
    ) as err:
        _LOGGER.exception("Failed to move plant %s", plant_id)
        if isinstance(err, ServiceValidationError):
            raise
        raise ServiceValidationError(f"Failed to move plant {plant_id}: {err}") from err


SERVICES: list[ServiceDefinition] = [
    ServiceDefinition(
        GrowspaceService.SWITCH_PLANTS,
        handle_switch_plants,
        SWITCH_PLANT_SCHEMA,
        needs_strain_lib=True,
    ),
    ServiceDefinition(
        GrowspaceService.MOVE_PLANT,
        handle_move_plant,
        MOVE_PLANT_SCHEMA,
        needs_strain_lib=True,
    ),
]
