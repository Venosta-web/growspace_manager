"""Service handlers for irrigation-related services."""
import logging
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

from ..const import DOMAIN

if TYPE_CHECKING:
    from ..coordinator import GrowspaceCoordinator
    from ..irrigation_coordinator import IrrigationCoordinator
    from ..strain_library import StrainLibrary

_LOGGER = logging.getLogger(__name__)


async def _get_irrigation_coordinator(
    hass: HomeAssistant, growspace_id: str
) -> "IrrigationCoordinator":
    """Get the irrigation coordinator for a specific growspace, raising on failure."""
    # This integration assumes a single config entry.
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError("Growspace Manager integration not yet set up.")

    entry_id = entries[0].entry_id

    try:
        domain_data = hass.data[DOMAIN][entry_id]
        irrigation_coordinators = domain_data["irrigation_coordinators"]

        if growspace_id not in irrigation_coordinators:
            raise ServiceValidationError(
                f"Growspace '{growspace_id}' not found or has no irrigation setup."
            )
        return irrigation_coordinators[growspace_id]
    except KeyError:
        raise ServiceValidationError(
            "Irrigation coordinators not found. Setup may be incomplete."
        )


async def handle_set_irrigation_settings(
    hass: HomeAssistant,
    coordinator: "GrowspaceCoordinator",
    strain_library: "StrainLibrary",
    call: ServiceCall,
) -> None:
    """Handle the service call to set irrigation settings for a growspace."""
    growspace_id = call.data["growspace_id"]
    irrigation_coord = await _get_irrigation_coordinator(hass, growspace_id)

    settings = {key: value for key, value in call.data.items() if key != "growspace_id"}

    await irrigation_coord.async_set_settings(settings)
    _LOGGER.info("Set irrigation settings for growspace '%s'", growspace_id)


async def handle_add_irrigation_time(
    hass: HomeAssistant,
    coordinator: "GrowspaceCoordinator",
    strain_library: "StrainLibrary",
    call: ServiceCall,
) -> None:
    """Handle the service call to add an irrigation time to a schedule."""
    growspace_id = call.data["growspace_id"]
    irrigation_coord = await _get_irrigation_coordinator(hass, growspace_id)

    duration = call.data.get("duration")
    if duration is None:
        duration = irrigation_coord.get_default_duration("irrigation")

    await irrigation_coord.async_add_schedule_item(
        "irrigation_times", call.data["time"], duration
    )


async def handle_remove_irrigation_time(
    hass: HomeAssistant,
    coordinator: "GrowspaceCoordinator",
    strain_library: "StrainLibrary",
    call: ServiceCall,
) -> None:
    """Handle the service call to remove an irrigation time from a schedule."""
    growspace_id = call.data["growspace_id"]
    irrigation_coord = await _get_irrigation_coordinator(hass, growspace_id)
    await irrigation_coord.async_remove_schedule_item(
        "irrigation_times", call.data["time"]
    )


async def handle_add_drain_time(
    hass: HomeAssistant,
    coordinator: "GrowspaceCoordinator",
    strain_library: "StrainLibrary",
    call: ServiceCall,
) -> None:
    """Handle the service call to add a drain time to a schedule."""
    growspace_id = call.data["growspace_id"]
    irrigation_coord = await _get_irrigation_coordinator(hass, growspace_id)

    duration = call.data.get("duration")
    if duration is None:
        duration = irrigation_coord.get_default_duration("drain")

    await irrigation_coord.async_add_schedule_item(
        "drain_times", call.data["time"], duration
    )


async def handle_remove_drain_time(
    hass: HomeAssistant,
    coordinator: "GrowspaceCoordinator",
    strain_library: "StrainLibrary",
    call: ServiceCall,
) -> None:
    """Handle the service call to remove a drain time from a schedule."""
    growspace_id = call.data["growspace_id"]
    irrigation_coord = await _get_irrigation_coordinator(hass, growspace_id)
    await irrigation_coord.async_remove_schedule_item(
        "drain_times", call.data["time"]
    )
