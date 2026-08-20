"""Plant scoring and harvest metrics service handlers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from custom_components.growspace_manager.const import (
    ATTR_CBD_PERCENTAGE,
    ATTR_DRY_WEIGHT,
    ATTR_INTERNODAL_SPACING,
    ATTR_MOLD_RESISTANCE,
    ATTR_PLANT_ID,
    ATTR_RESIN,
    ATTR_TERPENE_INTENSITY,
    ATTR_TERPENE_PROFILE,
    ATTR_THC_PERCENTAGE,
    ATTR_TRIM_WEIGHT,
    ATTR_VIGOR,
    ATTR_WET_WEIGHT,
    GrowspaceService,
)
from custom_components.growspace_manager.schemas import (
    SCORE_PLANT_SCHEMA,
    UPDATE_HARVEST_METRICS_SCHEMA,
)
from custom_components.growspace_manager.services._definition import ServiceDefinition
from custom_components.growspace_manager.services.plant_utils import (
    _ensure_plant_loaded,
    _resolve_plant_id,
)
from custom_components.growspace_manager.strain_library import StrainLibrary
from homeassistant.core import HomeAssistant, ServiceCall

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


async def handle_score_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle the score_plant service call."""
    plant_id = _resolve_plant_id(hass, call.data[ATTR_PLANT_ID])
    await _ensure_plant_loaded(hass, coordinator, plant_id)

    await coordinator.services.plants.score_plant(
        plant_id=plant_id,
        vigor=call.data.get(ATTR_VIGOR),
        internodal_spacing=call.data.get(ATTR_INTERNODAL_SPACING),
        terpene_intensity=call.data.get(ATTR_TERPENE_INTENSITY),
        resin=call.data.get(ATTR_RESIN),
        mold_resistance=call.data.get(ATTR_MOLD_RESISTANCE),
    )


async def handle_update_harvest_metrics(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle the update_harvest_metrics service call."""
    plant_id = _resolve_plant_id(hass, call.data[ATTR_PLANT_ID])
    await _ensure_plant_loaded(hass, coordinator, plant_id)

    await coordinator.services.plants.update_harvest_metrics(
        plant_id=plant_id,
        wet_weight=call.data.get(ATTR_WET_WEIGHT),
        dry_weight=call.data.get(ATTR_DRY_WEIGHT),
        trim_weight=call.data.get(ATTR_TRIM_WEIGHT),
        thc_percentage=call.data.get(ATTR_THC_PERCENTAGE),
        cbd_percentage=call.data.get(ATTR_CBD_PERCENTAGE),
        terpene_profile=call.data.get(ATTR_TERPENE_PROFILE),
    )


SERVICES: list[ServiceDefinition] = [
    ServiceDefinition(
        GrowspaceService.SCORE_PLANT,
        handle_score_plant,
        SCORE_PLANT_SCHEMA,
        needs_strain_lib=True,
    ),
    ServiceDefinition(
        GrowspaceService.UPDATE_HARVEST_METRICS,
        handle_update_harvest_metrics,
        UPDATE_HARVEST_METRICS_SCHEMA,
        needs_strain_lib=True,
    ),
]
