"""Services related to Growspaces."""

import logging

import homeassistant.helpers.device_registry as dr
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

from ..const import (
    ATTR_GROWSPACE_ID,
    ATTR_NAME,
    ATTR_NOTIFICATION_TARGET,
    ATTR_PLANTS_PER_ROW,
    ATTR_ROWS,
)
from ..coordinator import GrowspaceCoordinator
from ..strain_library import StrainLibrary

_LOGGER = logging.getLogger(__name__)


async def handle_add_growspace(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,  # Keep for consistency
    call: ServiceCall,
) -> None:
    """Handle add growspace service call."""
    try:
        device_registry = dr.async_get(hass)
        mobile_devices = [
            d.name
            for d in device_registry.devices.values()
            if any("mobile_app" in entry_id for entry_id in d.config_entries)
        ]
        notification_target = call.data.get(ATTR_NOTIFICATION_TARGET)
        if notification_target and notification_target not in mobile_devices:
            notification_target = None

        name = call.data[ATTR_NAME]
        rows = call.data[ATTR_ROWS]
        plants_per_row = call.data[ATTR_PLANTS_PER_ROW]

        growspace_id = await coordinator.async_add_growspace(
            name=name,
            rows=rows,
            plants_per_row=plants_per_row,
            notification_target=notification_target,
        )

        _LOGGER.info("Growspace %s added successfully via service call", growspace_id)

    except Exception as err:
        _LOGGER.error("Failed to add growspace: %s", err)
        raise ServiceValidationError(f"Failed to add growspace: {err!s}") from err


async def handle_update_growspace(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle update growspace service call."""
    try:
        growspace_id = call.data[ATTR_GROWSPACE_ID]
        await coordinator.async_update_growspace(
            growspace_id=growspace_id,
            name=call.data.get(ATTR_NAME),
            rows=call.data.get(ATTR_ROWS),
            plants_per_row=call.data.get(ATTR_PLANTS_PER_ROW),
            notification_target=call.data.get(ATTR_NOTIFICATION_TARGET),
        )
        _LOGGER.info("Growspace %s updated successfully", growspace_id)
    except Exception as err:
        _LOGGER.error("Failed to update growspace: %s", err)
        raise ServiceValidationError(f"Failed to update growspace: {err!s}") from err


async def handle_remove_growspace(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle remove growspace service call."""
    try:
        growspace_id = call.data[ATTR_GROWSPACE_ID]
        await coordinator.async_remove_growspace(growspace_id)
        _LOGGER.info("Growspace %s removed successfully", growspace_id)
    except Exception as err:
        _LOGGER.error("Failed to remove growspace: %s", err)
        raise ServiceValidationError(f"Failed to remove growspace: {err!s}") from err
