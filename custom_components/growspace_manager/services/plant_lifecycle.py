"""Plant lifecycle service handlers: stage transitions and harvest."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from custom_components.growspace_manager.const import (
    ATTR_CBD_PERCENTAGE,
    ATTR_DRY_WEIGHT,
    ATTR_NEW_STAGE,
    ATTR_PLANT_ID,
    ATTR_TARGET_GROWSPACE_ID,
    ATTR_TERPENE_PROFILE,
    ATTR_THC_PERCENTAGE,
    ATTR_TRANSITION_DATE,
    ATTR_TRIM_WEIGHT,
    ATTR_WET_WEIGHT,
    GrowspaceService,
)
from custom_components.growspace_manager.exceptions import GrowspaceError
from custom_components.growspace_manager.schemas import (
    HARVEST_PLANT_SCHEMA,
    TRANSITION_PLANT_SCHEMA,
)
from custom_components.growspace_manager.services._definition import ServiceDefinition
from custom_components.growspace_manager.services.plant_utils import (
    _ensure_plant_loaded,
    _resolve_plant_id,
)
from custom_components.growspace_manager.strain_library import StrainLibrary
from custom_components.growspace_manager.utils import parse_date_field
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


async def handle_transition_plant_stage(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle transition plant stage service call."""
    plant_id = call.data[ATTR_PLANT_ID]
    if plant_id not in coordinator.plants:
        _LOGGER.error("Plant %s does not exist for transition_plant_stage", plant_id)
        raise ServiceValidationError(f"Plant {plant_id} does not exist.")

    new_stage = call.data[ATTR_NEW_STAGE]
    transition_date_str = call.data.get(ATTR_TRANSITION_DATE)
    transition_date = None
    if transition_date_str:
        transition_date = parse_date_field(transition_date_str)
        if not transition_date:
            _LOGGER.warning(
                "Could not parse transition_date string: %s", transition_date_str
            )
            raise ServiceValidationError(
                f"Invalid transition_date format: {transition_date_str}."
            )

    try:
        await coordinator.services.plants.transition_plant_stage(
            plant_id=plant_id,
            new_stage=new_stage,
            transition_date=transition_date or None,
        )
        _LOGGER.info("Plant %s transitioned to %s stage", plant_id, new_stage)

    except (
        AttributeError,
        KeyError,
        ValueError,
        ServiceValidationError,
        GrowspaceError,
    ) as err:
        _LOGGER.exception("Failed to transition plant stage for %s", plant_id)
        if isinstance(err, ServiceValidationError):
            raise
        raise ServiceValidationError(
            f"Failed to transition plant stage for {plant_id}: {err}"
        ) from err


async def handle_harvest_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> dict[str, Any] | None:
    """Handle harvest plant service call."""
    plant_id_input = call.data.get(ATTR_PLANT_ID)
    if not plant_id_input:
        raise ServiceValidationError("Missing plant_id")
    plant_id = _resolve_plant_id(hass, plant_id_input)
    await _ensure_plant_loaded(hass, coordinator, plant_id)

    target_growspace_id = call.data.get(ATTR_TARGET_GROWSPACE_ID)
    transition_date_str = call.data.get(ATTR_TRANSITION_DATE)
    transition_date = None

    if transition_date_str:
        transition_date = parse_date_field(transition_date_str)
        if not transition_date:
            _LOGGER.warning(
                "Could not parse transition_date string: %s", transition_date_str
            )
            raise ServiceValidationError(
                f"Invalid transition_date format: {transition_date_str}."
            )

    try:
        await coordinator.services.plants.transition_plant(
            plant_id=plant_id,
            target_growspace_id=target_growspace_id,
            target_growspace_name=None,
            transition_date=transition_date.date().isoformat()
            if transition_date
            else None,
            wet_weight=call.data.get(ATTR_WET_WEIGHT),
            dry_weight=call.data.get(ATTR_DRY_WEIGHT),
            trim_weight=call.data.get(ATTR_TRIM_WEIGHT),
            thc_percentage=call.data.get(ATTR_THC_PERCENTAGE),
            cbd_percentage=call.data.get(ATTR_CBD_PERCENTAGE),
            terpene_profile=call.data.get(ATTR_TERPENE_PROFILE),
        )

        return {
            ATTR_PLANT_ID: plant_id,
            ATTR_TARGET_GROWSPACE_ID: target_growspace_id,
            "harvest_date": transition_date.date().isoformat()
            if transition_date
            else None,
        }

    except (
        AttributeError,
        KeyError,
        ValueError,
        ServiceValidationError,
        GrowspaceError,
    ) as err:
        _LOGGER.exception("Failed to harvest plant %s", plant_id)
        if isinstance(err, ServiceValidationError):
            raise
        raise ServiceValidationError(
            f"Failed to harvest plant {plant_id}: {err}"
        ) from err


SERVICES: list[ServiceDefinition] = [
    ServiceDefinition(
        GrowspaceService.TRANSITION_PLANT_STAGE,
        handle_transition_plant_stage,
        TRANSITION_PLANT_SCHEMA,
        needs_strain_lib=True,
    ),
    ServiceDefinition(
        GrowspaceService.HARVEST_PLANT,
        handle_harvest_plant,
        HARVEST_PLANT_SCHEMA,
        needs_strain_lib=True,
    ),
]
