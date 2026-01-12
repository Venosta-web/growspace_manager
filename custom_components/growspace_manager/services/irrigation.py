"""Service handlers for irrigation-related services."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

from ..const import (
    ATTR_DRAIN_TIMES,
    ATTR_DURATION,
    ATTR_GROWSPACE_ID,
    ATTR_IRRIGATION_TIMES,
    ATTR_TIME,
    DOMAIN,
)
from ..exceptions import GrowspaceError

if TYPE_CHECKING:
    from ..coordinator import GrowspaceCoordinator
    from ..irrigation_coordinator import IrrigationCoordinator

_LOGGER = logging.getLogger(__name__)


async def _get_irrigation_coordinator(
    hass: HomeAssistant, growspace_id: str
) -> IrrigationCoordinator:
    """Get the irrigation coordinator for a specific growspace, raising on failure."""
    # This integration assumes a single config entry.
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError("Growspace Manager integration not yet set up.")

    entry = entries[0]

    try:
        irrigation_coordinators = entry.runtime_data.irrigation_coordinators

        if growspace_id not in irrigation_coordinators:
            raise ServiceValidationError(
                f"Growspace '{growspace_id}' not found or has no irrigation setup."
            )
        return irrigation_coordinators[growspace_id]
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
        irrigation_coord = await _get_irrigation_coordinator(hass, growspace_id)

        settings = {
            key: value for key, value in call.data.items() if key != ATTR_GROWSPACE_ID
        }

        await irrigation_coord.async_set_settings(settings)
        _LOGGER.info("Set irrigation settings for growspace '%s'", growspace_id)
    except GrowspaceError as err:
        raise ServiceValidationError(str(err)) from err
    except Exception as err:
        _LOGGER.exception("Unexpected error in set_irrigation_settings: %s", err)
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
        irrigation_coord = await _get_irrigation_coordinator(hass, growspace_id)

        duration = call.data.get(ATTR_DURATION)
        if duration is None:
            duration = irrigation_coord.get_default_duration("irrigation")

        await irrigation_coord.async_add_schedule_item(
            ATTR_IRRIGATION_TIMES, call.data[ATTR_TIME], duration
        )
    except GrowspaceError as err:
        raise ServiceValidationError(str(err)) from err
    except Exception as err:
        _LOGGER.exception("Unexpected error in add_irrigation_time: %s", err)
        raise ServiceValidationError(f"Failed to add irrigation time: {err}") from err


async def handle_remove_irrigation_time(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the service call to remove an irrigation time from a schedule."""
    try:
        growspace_id = call.data[ATTR_GROWSPACE_ID]
        irrigation_coord = await _get_irrigation_coordinator(hass, growspace_id)
        await irrigation_coord.async_remove_schedule_item(
            ATTR_IRRIGATION_TIMES, call.data[ATTR_TIME]
        )
    except GrowspaceError as err:
        raise ServiceValidationError(str(err)) from err
    except Exception as err:
        _LOGGER.exception("Unexpected error in remove_irrigation_time: %s", err)
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
        irrigation_coord = await _get_irrigation_coordinator(hass, growspace_id)

        duration = call.data.get(ATTR_DURATION)
        if duration is None:
            duration = irrigation_coord.get_default_duration("drain")

        await irrigation_coord.async_add_schedule_item(
            ATTR_DRAIN_TIMES, call.data[ATTR_TIME], duration
        )
    except GrowspaceError as err:
        raise ServiceValidationError(str(err)) from err
    except Exception as err:
        _LOGGER.exception("Unexpected error in add_drain_time: %s", err)
        raise ServiceValidationError(f"Failed to add drain time: {err}") from err


async def handle_remove_drain_time(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the service call to remove a drain time from a schedule."""
    try:
        growspace_id = call.data[ATTR_GROWSPACE_ID]
        irrigation_coord = await _get_irrigation_coordinator(hass, growspace_id)
        await irrigation_coord.async_remove_schedule_item(
            ATTR_DRAIN_TIMES, call.data[ATTR_TIME]
        )
    except GrowspaceError as err:
        raise ServiceValidationError(str(err)) from err
    except Exception as err:
        _LOGGER.exception("Unexpected error in remove_drain_time: %s", err)
        raise ServiceValidationError(f"Failed to remove drain time: {err}") from err
