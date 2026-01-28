"""Services related to Plant Training."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from custom_components.growspace_manager.const import (
    ATTR_GROWSPACE_ID,
    ATTR_NOTES,
    ATTR_PLANT_ID,
    ATTR_TECHNIQUE,
)
from custom_components.growspace_manager.services.utils import handle_service_errors
from homeassistant.core import HomeAssistant, ServiceCall

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


@handle_service_errors
async def handle_log_training_event(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle log_training_event service call."""
    growspace_id: str | None = call.data.get(ATTR_GROWSPACE_ID)
    technique: str = call.data[ATTR_TECHNIQUE]
    notes: str | None = call.data.get(ATTR_NOTES)
    plant_ids: list[str] | None = call.data.get(ATTR_PLANT_ID)

    # If no plant_ids and no growspace_id, try to infer growspace from context if possible,
    # but strictly we require at least one.

    await coordinator.async_log_training_event(
        growspace_id=growspace_id,
        technique=technique,
        notes=notes,
        plant_ids=plant_ids,
    )
