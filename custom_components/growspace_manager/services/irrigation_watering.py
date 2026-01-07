"""Service handlers for manual watering functionality."""

import logging
from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall

from ..coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


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
    plant_id: str = call.data["plant_id"]
    amount: float = call.data["amount"]
    nutrients: dict[str, float] | None = call.data.get("nutrients")
    preset_id: str | None = call.data.get("preset_id")

    await coordinator.async_water_plant(plant_id, amount, nutrients, preset_id)

    _LOGGER.info(
        "Service water_plant completed for plant %s with %sL",
        plant_id,
        amount,
    )


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
    growspace_id: str = call.data["growspace_id"]
    amount_per_plant: float = call.data["amount_per_plant"]
    nutrients: dict[str, float] | None = call.data.get("nutrients")
    preset_id: str | None = call.data.get("preset_id")

    plants_watered = await coordinator.async_water_growspace(
        growspace_id, amount_per_plant, nutrients, preset_id
    )

    _LOGGER.info(
        "Service water_growspace completed for growspace %s: %d plants watered",
        growspace_id,
        plants_watered,
    )

    return {"plants_watered": plants_watered}
