"""Service handlers for nutrient EC ramp curves."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from custom_components.growspace_manager.const import (
    ATTR_CURVE_ID,
    ATTR_NAME,
    ATTR_POINTS,
    ATTR_STAGE,
)
from custom_components.growspace_manager.services.utils import handle_service_errors
from homeassistant.core import HomeAssistant, ServiceCall

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


@handle_service_errors
async def handle_save_ec_ramp_curve(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle saving an EC ramp curve.

    Args:
        hass: The Home Assistant instance.
        coordinator: The GrowspaceCoordinator instance.
        call: The service call with name, stage, points, and optional curve_id.
    """
    name: str = call.data[ATTR_NAME]
    stage: str = call.data[ATTR_STAGE]
    points: list[dict[str, Any]] = call.data[ATTR_POINTS]
    curve_id: str | None = call.data.get(ATTR_CURVE_ID)

    await coordinator.async_save_ec_ramp_curve(
        name=name,
        stage=stage,
        points=points,
        curve_id=curve_id,
    )

    _LOGGER.info("Saved EC ramp curve '%s' for stage %s with %d points", name, stage, len(points))


@handle_service_errors
async def handle_remove_ec_ramp_curve(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle removing an EC ramp curve.

    Args:
        hass: The Home Assistant instance.
        coordinator: The GrowspaceCoordinator instance.
        call: The service call with curve_id.
    """
    curve_id: str = call.data[ATTR_CURVE_ID]

    await coordinator.async_remove_ec_ramp_curve(curve_id=curve_id)

    _LOGGER.info("Removed EC ramp curve %s", curve_id)
