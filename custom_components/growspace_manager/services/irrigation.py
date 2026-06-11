"""Service handlers for irrigation-related services."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from custom_components.growspace_manager.const import (
    ATTR_DRAIN_TIMES,
    ATTR_DURATION,
    ATTR_FEED_EC_MAX,
    ATTR_FEED_EC_MIN,
    ATTR_GROWSPACE_ID,
    ATTR_IRRIGATION_TIMES,
    ATTR_STAGE,
    ATTR_TIME,
    GrowspaceService,
)
from custom_components.growspace_manager.schemas import (
    ADD_DRAIN_TIME_SCHEMA,
    ADD_IRRIGATION_TIME_SCHEMA,
    REMOVE_DRAIN_TIME_SCHEMA,
    REMOVE_IRRIGATION_TIME_SCHEMA,
    RUN_IRRIGATION_CYCLE_SCHEMA,
    SET_EC_TARGET_RANGE_SCHEMA,
    SET_IRRIGATION_SETTINGS_SCHEMA,
    SET_IRRIGATION_STRATEGY_SCHEMA,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

from ._definition import ServiceDefinition
from .utils import handle_service_errors

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
    from custom_components.growspace_manager.irrigation_coordinator import (
        IrrigationCoordinator,
    )

_LOGGER = logging.getLogger(__name__)


async def _get_irrigation_coordinator(
    coordinator: GrowspaceCoordinator, growspace_id: str
) -> IrrigationCoordinator:
    """Get the irrigation coordinator for a specific growspace, raising on failure."""
    try:
        irr_coord = coordinator.services.growspaces.get_irrigation_coordinator(growspace_id)

        if irr_coord is None:
            growspace = coordinator.growspaces.get(growspace_id)
            if growspace:
                _LOGGER.info(
                    "Lazy initializing subsystems for growspace %s", growspace_id
                )
                await coordinator._subsystem_manager.async_setup_growspace_sub_coordinators(
                    growspace_id, growspace
                )
                irr_coord = coordinator.services.growspaces.get_irrigation_coordinator(growspace_id)

            if irr_coord is None:
                raise ServiceValidationError(
                    f"Growspace '{growspace_id}' not found or has no irrigation setup."
                )
        return cast("IrrigationCoordinator", irr_coord)
    except AttributeError:
        raise ServiceValidationError(
            "Irrigation coordinators not found. Setup may be incomplete."
        ) from None


@handle_service_errors
async def handle_set_irrigation_settings(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the service call to set irrigation settings for a growspace."""
    growspace_id = call.data[ATTR_GROWSPACE_ID]
    await _get_irrigation_coordinator(coordinator, growspace_id)

    settings = {
        key: value for key, value in call.data.items() if key != ATTR_GROWSPACE_ID
    }

    await coordinator.services.growspaces.set_irrigation_settings(growspace_id, settings)
    _LOGGER.info("Set irrigation settings for growspace '%s'", growspace_id)


@handle_service_errors
async def handle_set_irrigation_strategy(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the service call to set irrigation strategy for a growspace."""
    growspace_id = call.data[ATTR_GROWSPACE_ID]
    await _get_irrigation_coordinator(coordinator, growspace_id)

    strategy = {
        key: value for key, value in call.data.items() if key != ATTR_GROWSPACE_ID
    }

    await coordinator.services.growspaces.set_irrigation_strategy(growspace_id, strategy)
    _LOGGER.info("Set irrigation strategy for growspace '%s'", growspace_id)



@handle_service_errors
async def handle_add_irrigation_time(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the service call to add an irrigation time to a schedule."""
    growspace_id = call.data[ATTR_GROWSPACE_ID]
    irrigation_coord = await _get_irrigation_coordinator(coordinator, growspace_id)

    duration = call.data.get(ATTR_DURATION)
    if duration is None:
        duration = irrigation_coord.get_default_duration("irrigation")

    await coordinator.services.growspaces.add_irrigation_schedule_item(
        growspace_id, ATTR_IRRIGATION_TIMES, call.data[ATTR_TIME], duration
    )


@handle_service_errors
async def handle_remove_irrigation_time(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the service call to remove an irrigation time from a schedule."""
    growspace_id = call.data[ATTR_GROWSPACE_ID]
    await _get_irrigation_coordinator(coordinator, growspace_id)
    await coordinator.services.growspaces.remove_irrigation_schedule_item(
        growspace_id, ATTR_IRRIGATION_TIMES, call.data[ATTR_TIME]
    )


@handle_service_errors
async def handle_add_drain_time(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the service call to add a drain time to a schedule."""
    growspace_id = call.data[ATTR_GROWSPACE_ID]
    irrigation_coord = await _get_irrigation_coordinator(coordinator, growspace_id)

    duration = call.data.get(ATTR_DURATION)
    if duration is None:
        duration = irrigation_coord.get_default_duration("drain")

    await coordinator.services.growspaces.add_irrigation_schedule_item(
        growspace_id, ATTR_DRAIN_TIMES, call.data[ATTR_TIME], duration
    )


@handle_service_errors
async def handle_remove_drain_time(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the service call to remove a drain time from a schedule."""
    growspace_id = call.data[ATTR_GROWSPACE_ID]
    await _get_irrigation_coordinator(coordinator, growspace_id)
    await coordinator.services.growspaces.remove_irrigation_schedule_item(
        growspace_id, ATTR_DRAIN_TIMES, call.data[ATTR_TIME]
    )


@handle_service_errors
async def handle_run_irrigation_cycle(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the service call to manually trigger an irrigation cycle."""
    growspace_id = call.data[ATTR_GROWSPACE_ID]
    duration = call.data.get(ATTR_DURATION)
    irrigation_coord = await _get_irrigation_coordinator(coordinator, growspace_id)
    await irrigation_coord.async_manual_run(duration=duration)
    _LOGGER.info(
        "Manual irrigation cycle started for growspace '%s' (duration=%s)",
        growspace_id,
        duration,
    )


@handle_service_errors
async def handle_set_ec_target_range(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the service call to set (upsert) a feed EC target range for a stage."""
    growspace_id: str = call.data[ATTR_GROWSPACE_ID]
    stage: str = call.data[ATTR_STAGE]
    feed_ec_min: float = call.data[ATTR_FEED_EC_MIN]
    feed_ec_max: float = call.data[ATTR_FEED_EC_MAX]

    await coordinator.services.growspaces.set_ec_target_range(
        growspace_id=growspace_id,
        stage=stage,
        feed_ec_min=feed_ec_min,
        feed_ec_max=feed_ec_max,
    )
    _LOGGER.info(
        "Set EC target range for growspace '%s' stage '%s': %.1f–%.1f",
        growspace_id,
        stage,
        feed_ec_min,
        feed_ec_max,
    )


SERVICES = [
    ServiceDefinition(
        GrowspaceService.RUN_IRRIGATION_CYCLE,
        handle_run_irrigation_cycle,
        RUN_IRRIGATION_CYCLE_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.SET_IRRIGATION_SETTINGS,
        handle_set_irrigation_settings,
        SET_IRRIGATION_SETTINGS_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.SET_IRRIGATION_STRATEGY,
        handle_set_irrigation_strategy,
        SET_IRRIGATION_STRATEGY_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.ADD_IRRIGATION_TIME,
        handle_add_irrigation_time,
        ADD_IRRIGATION_TIME_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.REMOVE_IRRIGATION_TIME,
        handle_remove_irrigation_time,
        REMOVE_IRRIGATION_TIME_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.ADD_DRAIN_TIME,
        handle_add_drain_time,
        ADD_DRAIN_TIME_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.REMOVE_DRAIN_TIME,
        handle_remove_drain_time,
        REMOVE_DRAIN_TIME_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.SET_EC_TARGET_RANGE,
        handle_set_ec_target_range,
        SET_EC_TARGET_RANGE_SCHEMA,
    ),
]
