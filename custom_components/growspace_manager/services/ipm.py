"""Service handlers for IPM presets."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from custom_components.growspace_manager.const import (
    ATTR_GROWSPACE_ID,
    ATTR_ITEMS,
    ATTR_MIN_DAYS_IN_STAGE,
    ATTR_NAME,
    ATTR_NOTES,
    ATTR_PLANT_ID,
    ATTR_PRESET_ID,
    ATTR_STAGE,
    ATTR_TYPE,
)
from custom_components.growspace_manager.exceptions import GrowspaceError
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


async def handle_save_ipm_preset(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, call: ServiceCall
) -> None:
    """Handle saving an IPM preset."""
    try:
        name = call.data[ATTR_NAME]
        type_ = call.data[ATTR_TYPE]
        items = call.data[ATTR_ITEMS]
        preset_id = call.data.get(ATTR_PRESET_ID)
        stage = call.data.get(ATTR_STAGE)
        min_days_in_stage = call.data.get(ATTR_MIN_DAYS_IN_STAGE)

        await coordinator.async_save_ipm_preset(
            name=name,
            type=type_,
            items=items,
            stage=stage,
            min_days_in_stage=min_days_in_stage,
            preset_id=preset_id,
        )
    except GrowspaceError as err:
        raise ServiceValidationError(str(err)) from err
    except Exception as err:
        _LOGGER.exception("Unexpected error in save_ipm_preset")
        raise ServiceValidationError(f"Failed to save IPM preset: {err}") from err


async def handle_remove_ipm_preset(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, call: ServiceCall
) -> None:
    """Handle removing an IPM preset."""
    try:
        preset_id = call.data[ATTR_PRESET_ID]
        await coordinator.async_remove_ipm_preset(preset_id)
    except GrowspaceError as err:
        raise ServiceValidationError(str(err)) from err
    except Exception as err:
        _LOGGER.exception("Unexpected error in remove_ipm_preset")
        raise ServiceValidationError(f"Failed to remove IPM preset: {err}") from err


async def handle_apply_ipm(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, call: ServiceCall
) -> None:
    """Handle applying an IPM preset."""
    try:
        preset_id = call.data[ATTR_PRESET_ID]
        growspace_id = call.data.get(ATTR_GROWSPACE_ID)
        plant_ids = call.data.get(ATTR_PLANT_ID)
        notes = call.data.get(ATTR_NOTES)

        await coordinator.async_apply_ipm(
            preset_id=preset_id,
            growspace_id=growspace_id,
            plant_ids=plant_ids,
            notes=notes,
        )
    except GrowspaceError as err:
        raise ServiceValidationError(str(err)) from err
    except Exception as err:
        _LOGGER.exception("Unexpected error in apply_ipm")
        raise ServiceValidationError(f"Failed to apply IPM: {err}") from err
