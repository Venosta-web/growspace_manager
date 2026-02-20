"""Batch action service."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from custom_components.growspace_manager.const import (
    ATTR_STAGE,
    ATTR_TARGET_GROWSPACE_ID,
    ATTR_TRANSITION_DATE,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


async def handle_batch_action(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle batch action service."""
    entity_ids = call.data["entity_ids"]
    action = call.data["action"]
    data = call.data.get("data", {})

    _LOGGER.debug(
        "Processing batch action '%s' for %s entities", action, len(entity_ids)
    )

    errors = []

    for entity_id in entity_ids:
        try:
            if action == "transition":
                await coordinator.plant_manager.transition_plant_stage(
                    plant_id=entity_id,
                    new_stage=data[ATTR_STAGE],
                    transition_date=data.get(ATTR_TRANSITION_DATE),
                )
            elif action == "harvest":
                await coordinator.async_harvest_plant(
                    plant_id=entity_id,
                    target_growspace_id=data.get(ATTR_TARGET_GROWSPACE_ID),
                    target_growspace_name=None,
                    transition_date=data.get(ATTR_TRANSITION_DATE),
                )
            elif action == "remove":
                await coordinator.async_remove_plant(plant_id=entity_id)
            else:
                msg = f"Unknown or unsupported batch action: {action}"
                _LOGGER.warning(msg)
                errors.append(msg)
                # Fail fast on unknown action or continue?
                # Better to just log. But since it repeats for all, break.
                break

        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Error processing batch action for %s: %s", entity_id, err)
            errors.append(str(err))

    if errors:
        error_count = len(errors)
        _LOGGER.error("Batch action completed with %s errors", error_count)
        raise ServiceValidationError(
            f"Batch action '{action}' failed for {error_count} entities. First error: {errors[0]}"
        )
