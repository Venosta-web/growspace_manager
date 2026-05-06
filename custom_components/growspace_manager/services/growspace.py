"""Services related to Growspaces."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from custom_components.growspace_manager.const import (
    ATTR_GROWSPACE_ID,
    ATTR_IMAGES,
    ATTR_NAME,
    ATTR_NOTES,
    ATTR_NOTIFICATION_TARGET,
    ATTR_PLANTS_PER_ROW,
    ATTR_ROWS,
    CATEGORY_NOTE,
    EVENT_GROWSPACE_LOG_ENTRY,
)
from custom_components.growspace_manager.services.utils import handle_service_errors
from custom_components.growspace_manager.strain_library import StrainLibrary
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
import homeassistant.helpers.device_registry as dr

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


@handle_service_errors
async def handle_add_growspace(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle add growspace service call."""
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

    growspace_id = await coordinator.growspace_service.add_growspace(
        name=name,
        rows=rows,
        plants_per_row=plants_per_row,
        notification_target=notification_target,
    )

    _LOGGER.info("Growspace %s added successfully via service call", growspace_id)


@handle_service_errors
async def handle_update_growspace(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle update growspace service call."""
    growspace_id = call.data[ATTR_GROWSPACE_ID]
    await coordinator.growspace_service.update_growspace(
        growspace_id=growspace_id,
        name=call.data.get(ATTR_NAME),
        rows=call.data.get(ATTR_ROWS),
        plants_per_row=call.data.get(ATTR_PLANTS_PER_ROW),
        notification_target=call.data.get(ATTR_NOTIFICATION_TARGET),
    )
    _LOGGER.info("Growspace %s updated successfully", growspace_id)


@handle_service_errors
async def handle_remove_growspace(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle remove growspace service call."""
    growspace_id = call.data[ATTR_GROWSPACE_ID]
    await coordinator.async_remove_growspace(growspace_id)
    _LOGGER.info("Growspace %s removed successfully", growspace_id)


async def async_add_growspace_note(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    growspace_id: str,
    notes: str,
    images_base64: list[str] | None = None,
) -> None:
    """Add a note to a growspace."""
    if images_base64 is None:
        images_base64 = []

    if growspace_id not in coordinator.growspaces:
        raise ServiceValidationError(f"Growspace '{growspace_id}' not found")

    image_paths: list[str] = []
    if images_base64 and strain_library.image_manager:
        for img_b64 in images_base64:
            try:
                abs_path = await strain_library.image_manager.save_timeline_image(
                    plant_id=growspace_id,
                    image_base64=img_b64,
                )
                image_paths.append(f"timeline/{Path(abs_path).name}")
            except Exception as e:  # noqa: BLE001
                _LOGGER.error("Failed to save growspace note image: %s", e)

    event_data: dict[str, Any] = {
        ATTR_GROWSPACE_ID: growspace_id,
        ATTR_NOTES: notes,
        ATTR_IMAGES: image_paths,
        "category": CATEGORY_NOTE,
    }

    hass.bus.async_fire(EVENT_GROWSPACE_LOG_ENTRY, event_data)
    _LOGGER.info("Added note for growspace %s", growspace_id)
