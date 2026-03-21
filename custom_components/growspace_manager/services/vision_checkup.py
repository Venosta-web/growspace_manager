"""Vision checkup service handler for Growspace Manager."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import ServiceValidationError

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
    from homeassistant.core import HomeAssistant, ServiceCall

_LOGGER = logging.getLogger(__name__)


async def handle_trigger_vision_checkup(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> dict[str, Any]:
    """Handle the trigger_vision_checkup service call.

    Captures camera snapshot(s) and runs AI vision analysis for a growspace.
    """
    growspace_id = call.data["growspace_id"]

    if growspace_id not in coordinator.growspaces:
        raise ServiceValidationError(
            f"Growspace '{growspace_id}' not found"
        )

    result = await coordinator.vision_scheduler.run_vision_analysis(
        growspace_id, "manual"
    )

    if result is None:
        raise ServiceValidationError(
            f"Vision checkup could not be performed for '{growspace_id}'. "
            "Ensure cameras are configured and an AI task entity is set up."
        )

    return {
        "growspace_id": result.growspace_id,
        "check_type": result.check_type,
        "analysis": result.analysis,
        "issues_detected": result.issues_detected,
        "severity": result.severity,
        "recommendations": result.recommendations,
        "timestamp": result.timestamp,
    }
