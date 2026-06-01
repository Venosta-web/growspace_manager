"""Service handlers for genetics tracking (seed batches, pollination, scoring)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from custom_components.growspace_manager.const import (
    ATTR_ACQUISITION_DATE,
    ATTR_BATCH_ID,
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
    ATTR_SEX,
    ATTR_STRAIN_NAME,
    ATTR_TERPENE_INTENSITY,
    ATTR_VIGOR,
    ATTR_YIELD_POTENTIAL,
    GrowspaceService,
)
from custom_components.growspace_manager.schemas import (
    ADD_SEED_BATCH_SCHEMA,
    DELETE_POLLINATION_SCHEMA,
    HARVEST_SEEDS_SCHEMA,
    LOG_POLLINATION_SCHEMA,
    SCORE_PHENOTYPE_SCHEMA,
    SET_PLANT_SEX_SCHEMA,
    SOW_SEED_SCHEMA,
    UNLINK_SEED_BATCH_SCHEMA,
    UPDATE_POLLINATION_SCHEMA,
    UPDATE_SEED_BATCH_SCHEMA,
)
from homeassistant.core import HomeAssistant, ServiceCall

from ._definition import ServiceDefinition
from .utils import handle_service_errors

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


@handle_service_errors
async def handle_add_seed_batch(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the add_seed_batch service call."""
    data = call.data
    await coordinator.services.genetics.async_add_seed_batch(
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
async def handle_update_seed_batch(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the update_seed_batch service call."""
    data = call.data
    acq_date = data.get(ATTR_ACQUISITION_DATE)
    await coordinator.services.genetics.async_update_seed_batch(
        batch_id=data[ATTR_BATCH_ID],
        strain_name=data.get(ATTR_STRAIN_NAME),
        breeder=data.get(ATTR_BREEDER),
        quantity=data.get(ATTR_QUANTITY),
        acquisition_date=acq_date.isoformat() if acq_date is not None else None,
        generation=data.get(ATTR_GENERATION),
        lineage=data.get(ATTR_LINEAGE),
        parent_1_strain=data.get(ATTR_PARENT_1_STRAIN),
        parent_1_phenotype=data.get(ATTR_PARENT_1_PHENOTYPE),
        parent_2_strain=data.get(ATTR_PARENT_2_STRAIN),
        parent_2_phenotype=data.get(ATTR_PARENT_2_PHENOTYPE),
        notes=data.get(ATTR_NOTES),
    )


@handle_service_errors
async def handle_log_pollination(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the log_pollination service call."""
    await coordinator.services.genetics.async_log_pollination(
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
    await coordinator.services.genetics.async_score_phenotype(
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
    await coordinator.services.genetics.async_harvest_seeds(
        event_id=call.data[ATTR_EVENT_ID],
        quantity=call.data[ATTR_QUANTITY],
        notes=call.data.get(ATTR_NOTES, ""),
    )


@handle_service_errors
async def handle_update_pollination(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the update_pollination service call."""
    data = call.data
    date_val = data.get(ATTR_DATE)
    await coordinator.services.genetics.async_update_pollination(
        event_id=data[ATTR_EVENT_ID],
        date=date_val.isoformat() if date_val is not None else None,
        donor_plant_id=data.get(ATTR_DONOR_PLANT_ID),
        receiver_plant_id=data.get(ATTR_RECEIVER_PLANT_ID),
        notes=data.get(ATTR_NOTES),
    )


@handle_service_errors
async def handle_delete_pollination(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the delete_pollination service call."""
    await coordinator.services.genetics.async_delete_pollination(
        event_id=call.data[ATTR_EVENT_ID],
    )


@handle_service_errors
async def handle_sow_seed(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the sow_seed service call."""
    await coordinator.services.genetics.async_sow_seed(
        batch_id=call.data[ATTR_BATCH_ID],
        plant_id=call.data[ATTR_PLANT_ID],
    )


@handle_service_errors
async def handle_set_plant_sex(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the set_plant_sex service call."""
    await coordinator.services.genetics.async_set_plant_sex(
        plant_id=call.data[ATTR_PLANT_ID],
        sex=call.data[ATTR_SEX],
    )


@handle_service_errors
async def handle_unlink_seed_batch(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the unlink_seed_batch service call."""
    await coordinator.services.genetics.async_unlink_seed_batch(
        plant_id=call.data[ATTR_PLANT_ID],
    )


SERVICES = [
    ServiceDefinition(
        GrowspaceService.ADD_SEED_BATCH,
        handle_add_seed_batch,
        ADD_SEED_BATCH_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.UPDATE_SEED_BATCH,
        handle_update_seed_batch,
        UPDATE_SEED_BATCH_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.LOG_POLLINATION,
        handle_log_pollination,
        LOG_POLLINATION_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.SCORE_PHENOTYPE,
        handle_score_phenotype,
        SCORE_PHENOTYPE_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.HARVEST_SEEDS,
        handle_harvest_seeds,
        HARVEST_SEEDS_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.UPDATE_POLLINATION,
        handle_update_pollination,
        UPDATE_POLLINATION_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.DELETE_POLLINATION,
        handle_delete_pollination,
        DELETE_POLLINATION_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.SOW_SEED,
        handle_sow_seed,
        SOW_SEED_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.SET_PLANT_SEX,
        handle_set_plant_sex,
        SET_PLANT_SEX_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.UNLINK_SEED_BATCH,
        handle_unlink_seed_batch,
        UNLINK_SEED_BATCH_SCHEMA,
    ),
]
