"""Vision checkup service handler for Growspace Manager."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from custom_components.growspace_manager.const import GrowspaceService
from custom_components.growspace_manager.schemas import (
    SERVICE_TRIGGER_VISION_CHECKUP_SCHEMA,
)
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError

from ._definition import ServiceDefinition

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

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
            f"Vision checkup could not be performed for '{growspace_id}'."
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


SERVICES = [
    ServiceDefinition(
        GrowspaceService.TRIGGER_VISION_CHECKUP,
        handle_trigger_vision_checkup,
        SERVICE_TRIGGER_VISION_CHECKUP_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    ),
]
