"""Service handlers for genetics tracking (seed batches, pollination, scoring)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from custom_components.growspace_manager.const import (
    ATTR_ACQUISITION_DATE,
    ATTR_BREEDER,
    ATTR_DATE,
    ATTR_DONOR_PLANT_ID,
    ATTR_EVENT_ID,
    ATTR_GENERATION,
    ATTR_INTERNODAL_SPACING,
    ATTR_KEEPER,
    ATTR_LINEAGE,
    ATTR_MOLD_RESISTANCE,
    ATTR_NOTES,
    ATTR_PARENT_1_PHENOTYPE,
    ATTR_PARENT_1_STRAIN,
    ATTR_PARENT_2_PHENOTYPE,
    ATTR_PARENT_2_STRAIN,
    ATTR_PLANT_ID,
    ATTR_QUANTITY,
    ATTR_RECEIVER_PLANT_ID,
    ATTR_RESIN,
    ATTR_STRAIN_NAME,
    ATTR_TERPENE_INTENSITY,
    ATTR_VIGOR,
    ATTR_YIELD_POTENTIAL,
)
from custom_components.growspace_manager.services.utils import handle_service_errors
from homeassistant.core import HomeAssistant, ServiceCall

if TYPE_CHECKING:
    from growspace_manager.coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


@handle_service_errors
async def handle_add_seed_batch(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the add_seed_batch service call."""
    data = call.data
    await coordinator.genetics_manager.async_add_seed_batch(
        strain_name=data[ATTR_STRAIN_NAME],
        breeder=data[ATTR_BREEDER],
        quantity=data[ATTR_QUANTITY],
        acquisition_date=data[ATTR_ACQUISITION_DATE].isoformat(),
        generation=data[ATTR_GENERATION],
        lineage=data.get(ATTR_LINEAGE, ""),
        parent_1_strain=data.get(ATTR_PARENT_1_STRAIN),
        parent_1_phenotype=data.get(ATTR_PARENT_1_PHENOTYPE),
        parent_2_strain=data.get(ATTR_PARENT_2_STRAIN),
        parent_2_phenotype=data.get(ATTR_PARENT_2_PHENOTYPE),
        notes=data.get(ATTR_NOTES, ""),
    )


@handle_service_errors
async def handle_log_pollination(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the log_pollination service call."""
    await coordinator.genetics_manager.async_log_pollination(
        date=call.data[ATTR_DATE],
        donor_plant_id=call.data[ATTR_DONOR_PLANT_ID],
        receiver_plant_id=call.data[ATTR_RECEIVER_PLANT_ID],
        notes=call.data.get(ATTR_NOTES, ""),
    )


@handle_service_errors
async def handle_score_phenotype(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the score_phenotype service call."""
    await coordinator.genetics_manager.async_score_phenotype(
        plant_id=call.data[ATTR_PLANT_ID],
        vigor=call.data.get(ATTR_VIGOR),
        internodal_spacing=call.data.get(ATTR_INTERNODAL_SPACING),
        terpene_intensity=call.data.get(ATTR_TERPENE_INTENSITY),
        resin=call.data.get(ATTR_RESIN),
        mold_resistance=call.data.get(ATTR_MOLD_RESISTANCE),
        yield_potential=call.data.get(ATTR_YIELD_POTENTIAL),
        keeper=call.data.get(ATTR_KEEPER),
        notes=call.data.get(ATTR_NOTES),
    )


@handle_service_errors
async def handle_harvest_seeds(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the harvest_seeds service call."""
    await coordinator.genetics_manager.async_harvest_seeds(
        event_id=call.data[ATTR_EVENT_ID],
        quantity=call.data[ATTR_QUANTITY],
        notes=call.data.get(ATTR_NOTES, ""),
    )
