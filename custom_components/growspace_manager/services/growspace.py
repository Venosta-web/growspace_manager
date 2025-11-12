"""Services related to Growspaces."""

import logging

import homeassistant.helpers.device_registry as dr
from homeassistant.components.persistent_notification import (
    async_create as create_notification,
)
from homeassistant.core import HomeAssistant, ServiceCall

from ..const import DOMAIN
from ..coordinator import GrowspaceCoordinator
from ..strain_library import StrainLibrary

_LOGGER = logging.getLogger(__name__)


async def handle_add_growspace(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,  # Keep for consistency, though not used here
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
        notification_target = call.data.get("notification_target")
        if notification_target and notification_target not in mobile_devices:
            notification_target = None

        growspace_id = await coordinator.async_add_growspace(
            name=call.data["name"],
            rows=call.data["rows"],
            plants_per_row=call.data["plants_per_row"],
            notification_target=notification_target,
        )

        _LOGGER.info("Growspace %s added successfully via service call", growspace_id)
        hass.bus.async_fire(
            f"{DOMAIN}_growspace_added",
            {"growspace_id": growspace_id, "name": call.data["name"]},
        )

    except (ValueError, TypeError, KeyError) as err:
        _LOGGER.error("Failed to add growspace: %s", err)
        create_notification(
            hass,
            f"Failed to add growspace: {err!s}",
            title="Growspace Manager Error",
        )
        raise


async def handle_remove_growspace(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,  # Keep for consistency
    call: ServiceCall,
) -> None:
    """Handle remove growspace service call."""
    try:
        await coordinator.async_remove_growspace(call.data["growspace_id"])
        _LOGGER.info("Growspace %s removed successfully", call.data["growspace_id"])
        hass.bus.async_fire(
            f"{DOMAIN}_growspace_removed",
            {"growspace_id": call.data["growspace_id"]},
        )
    except (ValueError, KeyError) as err:
        _LOGGER.error("Failed to remove growspace: %s", err)
        create_notification(
            hass,
            f"Failed to remove growspace: {err!s}",
            title="Growspace Manager Error",
        )
        raise
