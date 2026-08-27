"""Service handlers for manual watering functionality."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from custom_components.growspace_manager.const import GrowspaceService
from custom_components.growspace_manager.schemas import (
    RESET_PLANT_LAST_WATERED_SCHEMA,
    WATER_GROWSPACE_SCHEMA,
    WATER_PLANT_SCHEMA,
)
from homeassistant.core import HomeAssistant, ServiceCall

from ._definition import ServiceDefinition
from .utils import handle_service_errors

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


@handle_service_errors
async def handle_water_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the water_plant service call.

    Args:
        hass: The Home Assistant instance.
        coordinator: The GrowspaceCoordinator instance.
        call: The service call containing plant_id, amount, and optional nutrients.
    """
    try:
        plant_id: str = call.data["plant_id"]
        amount: float = call.data["amount"]
        nutrients: dict[str, float] | None = call.data.get("nutrients")
        preset_id: str | None = call.data.get("preset_id")

        await coordinator.services.plants.water_plant(
            plant_id, amount, nutrients, preset_id
        )

        _LOGGER.info(
            "Service water_plant completed for plant %s with %sL",
            plant_id,
            amount,
        )
    except Exception:
        _LOGGER.exception("Unexpected error in water_plant")
        raise


@handle_service_errors
async def handle_water_growspace(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> dict[str, Any]:
    """Handle the water_growspace service call.

    Args:
        hass: The Home Assistant instance.
        coordinator: The GrowspaceCoordinator instance.
        call: The service call containing growspace_id, amount_per_plant, and optional nutrients.

    Returns:
        A dict containing the number of plants watered.
    """
    try:
        growspace_id: str = call.data["growspace_id"]
        amount: float | None = call.data.get("amount")
        amount_per_plant: float | None = call.data.get("amount_per_plant")
        nutrients: dict[str, float] | None = call.data.get("nutrients")
        preset_id: str | None = call.data.get("preset_id")

        plants_watered = await coordinator.services.growspaces.water_growspace(
            growspace_id, amount_per_plant, nutrients, preset_id, amount=amount
        )

        _LOGGER.info(
            "Service water_growspace completed for growspace %s: %d plants watered",
            growspace_id,
            plants_watered,
        )

    except Exception:
        _LOGGER.exception("Unexpected error in water_growspace")
        raise
    else:
        return {"plants_watered": plants_watered}


@handle_service_errors
async def handle_reset_plant_last_watered(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the reset_plant_last_watered service call.

    Clears a plant's last_watered timestamp so E2E test fixtures can exercise
    watering flows from a known clean state. Not intended for user-facing use.
    """
    plant_id: str = call.data["plant_id"]
    await coordinator.services.plants.reset_last_watered(plant_id)
    _LOGGER.info("Service reset_plant_last_watered completed for plant %s", plant_id)


SERVICES = [
    ServiceDefinition(
        GrowspaceService.WATER_PLANT,
        handle_water_plant,
        WATER_PLANT_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.WATER_GROWSPACE,
        handle_water_growspace,
        WATER_GROWSPACE_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.RESET_PLANT_LAST_WATERED,
        handle_reset_plant_last_watered,
        RESET_PLANT_LAST_WATERED_SCHEMA,
    ),
]
