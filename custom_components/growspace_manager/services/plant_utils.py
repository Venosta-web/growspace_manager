"""Shared utilities for plant service handlers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from custom_components.growspace_manager.exceptions import GrowspaceError
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


def _resolve_plant_id(hass: HomeAssistant, plant_id: str) -> str:
    """Resolve plant ID from entity ID if necessary."""
    if "." not in plant_id:
        return plant_id

    try:
        entity_registry = hass.data.get(er.DATA_REGISTRY)
        if entity_registry:
            state = hass.states.get(plant_id)
            if state and state.attributes.get("plant_id"):
                resolved_id = state.attributes["plant_id"]
                _LOGGER.debug(
                    "Resolved entity ID '%s' to plant ID '%s'", plant_id, resolved_id
                )
                return resolved_id  # type: ignore[no-any-return]
            _LOGGER.warning(
                "Could not resolve entity ID '%s' to a plant_id attribute", plant_id
            )
        else:
            _LOGGER.warning("Entity Registry not available, cannot resolve entity ID")
    except (
        AttributeError,
        KeyError,
        ValueError,
        ServiceValidationError,
        GrowspaceError,
    ) as e:
        _LOGGER.warning("Error resolving entity ID '%s': %s", plant_id, e)

    return plant_id


async def _ensure_plant_loaded(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, plant_id: str
) -> bool:
    """Ensure plant is loaded in coordinator, attempting reload if missing."""
    if plant_id in coordinator.plants:
        return True

    _LOGGER.warning(
        "Plant %s not found in current coordinator data. Attempting to reload from storage",
        plant_id,
    )
    try:
        await coordinator.async_load()
    except (
        AttributeError,
        KeyError,
        ValueError,
        ServiceValidationError,
        GrowspaceError,
    ) as load_err:
        _LOGGER.error("Error reloading coordinator data: %s", load_err)

    if plant_id not in coordinator.plants:
        _LOGGER.error(
            "Plant %s still does not exist after storage reload attempt", plant_id
        )
        raise ServiceValidationError(
            f"Plant {plant_id} not found and could not be reloaded from storage."
        )
    return True
