from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, ServiceCall

from ..const import (
    ATTR_GROWSPACE_ID,
    ATTR_NOTES,
    ATTR_PLANT_ID,
    ATTR_TECHNIQUE,
)

if TYPE_CHECKING:
    from ..coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


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
