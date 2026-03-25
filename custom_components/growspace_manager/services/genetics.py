"""Service handlers for genetics and seed inventory operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.growspace_manager.const import (
    ATTR_ACQUISITION_DATE,
    ATTR_BREEDER,
    ATTR_DATE,
    ATTR_DONOR_PLANT_ID,
    ATTR_EVENT_ID,
    ATTR_GENERATION,
    ATTR_LINEAGE,
    ATTR_NOTES,
    ATTR_QUANTITY,
    ATTR_RECEIVER_PLANT_ID,
    ATTR_STRAIN_NAME,
)
from custom_components.growspace_manager.services.utils import handle_service_errors
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
    from custom_components.growspace_manager.strain_library import StrainLibrary


@handle_service_errors
async def handle_add_seed_batch(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle the add_seed_batch service call."""
    await coordinator.genetics_manager.async_add_seed_batch(
        strain_name=call.data[ATTR_STRAIN_NAME],
        breeder=call.data[ATTR_BREEDER],
        quantity=call.data[ATTR_QUANTITY],
        acquisition_date=call.data[ATTR_ACQUISITION_DATE],
        generation=call.data[ATTR_GENERATION],
        lineage=call.data[ATTR_LINEAGE],
        notes=call.data.get(ATTR_NOTES, ""),
    )


@handle_service_errors
async def handle_log_pollination(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle the log_pollination service call."""
    await coordinator.genetics_manager.async_log_pollination(
        event_date=call.data[ATTR_DATE],
        donor_plant_id=call.data[ATTR_DONOR_PLANT_ID],
        receiver_plant_id=call.data[ATTR_RECEIVER_PLANT_ID],
        notes=call.data.get(ATTR_NOTES, ""),
    )


@handle_service_errors
async def handle_harvest_seeds(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle the harvest_seeds service call."""
    try:
        await coordinator.genetics_manager.async_harvest_seeds(
            event_id=call.data[ATTR_EVENT_ID],
            quantity=call.data[ATTR_QUANTITY],
            notes=call.data.get(ATTR_NOTES, ""),
        )
    except ValueError as err:
        raise ServiceValidationError(str(err)) from err
