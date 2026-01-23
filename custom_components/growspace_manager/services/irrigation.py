"""Service handlers for irrigation-related services."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from custom_components.growspace_manager.const import (
    ATTR_DRAIN_TIMES,
    ATTR_DURATION,
    ATTR_GROWSPACE_ID,
    ATTR_IRRIGATION_TIMES,
    ATTR_TIME,
)
from custom_components.growspace_manager.exceptions import GrowspaceError
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

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
        irrigation_coordinators = coordinator.irrigation_coordinators

        if growspace_id not in irrigation_coordinators:
            # Fallback: Check if growspace exists and try to lazy init
            growspace = coordinator.growspaces.get(growspace_id)
            if growspace:
                _LOGGER.info(
                    "Lazy initializing subsystems for growspace %s", growspace_id
                )
                await coordinator.subsystem_manager.async_setup_growspace_sub_coordinators(
                    growspace_id, growspace
                )
                # Re-fetch
                irrigation_coordinators = coordinator.irrigation_coordinators

            if growspace_id not in irrigation_coordinators:
                raise ServiceValidationError(
                    f"Growspace '{growspace_id}' not found or has no irrigation setup."
                )
        return cast("IrrigationCoordinator", irrigation_coordinators[growspace_id])
    except AttributeError:
        raise ServiceValidationError(
            "Irrigation coordinators not found. Setup may be incomplete."
        ) from None


async def handle_set_irrigation_settings(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the service call to set irrigation settings for a growspace."""
    try:
        growspace_id = call.data[ATTR_GROWSPACE_ID]
        irrigation_coord = await _get_irrigation_coordinator(coordinator, growspace_id)

        settings = {
            key: value for key, value in call.data.items() if key != ATTR_GROWSPACE_ID
        }

        await irrigation_coord.async_set_settings(settings)
        _LOGGER.info("Set irrigation settings for growspace '%s'", growspace_id)
    except GrowspaceError as err:
        raise ServiceValidationError(str(err)) from err
    except Exception as err:
        _LOGGER.exception("Unexpected error in set_irrigation_settings")
        raise ServiceValidationError(
            f"Failed to set irrigation settings: {err}"
        ) from err


async def handle_add_irrigation_time(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the service call to add an irrigation time to a schedule."""
    try:
        growspace_id = call.data[ATTR_GROWSPACE_ID]
        irrigation_coord = await _get_irrigation_coordinator(coordinator, growspace_id)

        duration = call.data.get(ATTR_DURATION)
        if duration is None:
            duration = irrigation_coord.get_default_duration("irrigation")

        await irrigation_coord.async_add_schedule_item(
            ATTR_IRRIGATION_TIMES, call.data[ATTR_TIME], duration
        )
    except GrowspaceError as err:
        raise ServiceValidationError(str(err)) from err
    except Exception as err:
        _LOGGER.exception("Unexpected error in add_irrigation_time")
        raise ServiceValidationError(f"Failed to add irrigation time: {err}") from err


async def handle_remove_irrigation_time(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the service call to remove an irrigation time from a schedule."""
    try:
        growspace_id = call.data[ATTR_GROWSPACE_ID]
        irrigation_coord = await _get_irrigation_coordinator(coordinator, growspace_id)
        await irrigation_coord.async_remove_schedule_item(
            ATTR_IRRIGATION_TIMES, call.data[ATTR_TIME]
        )
    except GrowspaceError as err:
        raise ServiceValidationError(str(err)) from err
    except Exception as err:
        _LOGGER.exception("Unexpected error in remove_irrigation_time")
        raise ServiceValidationError(
            f"Failed to remove irrigation time: {err}"
        ) from err


async def handle_add_drain_time(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the service call to add a drain time to a schedule."""
    try:
        growspace_id = call.data[ATTR_GROWSPACE_ID]
        irrigation_coord = await _get_irrigation_coordinator(coordinator, growspace_id)

        duration = call.data.get(ATTR_DURATION)
        if duration is None:
            duration = irrigation_coord.get_default_duration("drain")

        await irrigation_coord.async_add_schedule_item(
            ATTR_DRAIN_TIMES, call.data[ATTR_TIME], duration
        )
    except GrowspaceError as err:
        raise ServiceValidationError(str(err)) from err
    except Exception as err:
        _LOGGER.exception("Unexpected error in add_drain_time")
        raise ServiceValidationError(f"Failed to add drain time: {err}") from err


async def handle_remove_drain_time(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the service call to remove a drain time from a schedule."""
    try:
        growspace_id = call.data[ATTR_GROWSPACE_ID]
        irrigation_coord = await _get_irrigation_coordinator(coordinator, growspace_id)
        await irrigation_coord.async_remove_schedule_item(
            ATTR_DRAIN_TIMES, call.data[ATTR_TIME]
        )
    except GrowspaceError as err:
        raise ServiceValidationError(str(err)) from err
    except Exception as err:
        _LOGGER.exception("Unexpected error in remove_drain_time")
        raise ServiceValidationError(f"Failed to remove drain time: {err}") from err
