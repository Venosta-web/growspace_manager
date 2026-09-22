"""Vision checkup service handler for Growspace Manager."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from custom_components.growspace_manager.const import DOMAIN, GrowspaceService
from custom_components.growspace_manager.presentation.vision import (
    async_serialize_vision_checkup,
)
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

    Captures camera snapshots and assembles local visual and environmental evidence.
    """
    growspace_id = call.data["growspace_id"]

    if growspace_id not in coordinator.growspaces:
        raise ServiceValidationError(f"Growspace '{growspace_id}' not found")

    outcome = await coordinator.vision_scheduler.run_vision_analysis(
        growspace_id, "manual"
    )
    reports = [capture.report for capture in outcome.captures if capture.report]
    recommendations = [
        recommendation
        for report in reports
        for recommendation in report.recommendations
    ]
    analysis = "\n\n".join(
        part
        for report in reports
        for part in (report.observation, report.environmental_risk, report.hypothesis)
        if part
    )
    if outcome.checkup.status is None:  # pragma: no cover - finished by the pipeline
        raise RuntimeError("Vision Checkup returned before reaching a terminal status")
    store = hass.data.get(DOMAIN, {}).get("vision_evidence_store")
    if store is None:  # pragma: no cover - the pipeline rejects this before capture
        raise RuntimeError("Vision Evidence Store disappeared during the checkup")
    media_dirs = hass.config.media_dirs
    media_source = "local" if "local" in media_dirs else next(iter(media_dirs))
    checkup = await async_serialize_vision_checkup(
        store, outcome.checkup, media_source=media_source
    )
    return {
        "growspace_id": outcome.checkup.growspace_id,
        "check_type": "manual",
        "analysis": analysis,
        "issues_detected": [],
        "severity": "none",
        "recommendations": recommendations,
        "timestamp": outcome.checkup.completed_at,
        "snapshot_paths": [capture.media_content_id for capture in outcome.captures],
        "checkup_id": outcome.checkup.checkup_id,
        "status": outcome.checkup.status.value,
        "checkup": checkup,
    }


SERVICES = [
    ServiceDefinition(
        GrowspaceService.TRIGGER_VISION_CHECKUP,
        handle_trigger_vision_checkup,
        SERVICE_TRIGGER_VISION_CHECKUP_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    ),
]
