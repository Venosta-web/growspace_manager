"""Event management for the Growspace Manager integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .models import Growspace, Plant

# Events
EVENT_GROWSPACE_UPDATED = f"{DOMAIN}_updated"
EVENT_GROWSPACE_ADDED = f"{DOMAIN}_growspace_added"
EVENT_GROWSPACE_REMOVED = f"{DOMAIN}_growspace_removed"
EVENT_PLANT_ADDED = f"{DOMAIN}_plant_added"
EVENT_PLANT_UPDATED = f"{DOMAIN}_plant_updated"
EVENT_PLANT_REMOVED = f"{DOMAIN}_plant_removed"
EVENT_PLANT_MOVED = f"{DOMAIN}_plant_moved"
EVENT_PLANT_SWITCHED = f"{DOMAIN}_plant_switched"
EVENT_PLANT_TRANSITIONED = f"{DOMAIN}_plant_transitioned"
EVENT_PLANT_HARVESTED = f"{DOMAIN}_plant_harvested"
EVENT_CLONES_TAKEN = f"{DOMAIN}_clones_taken"


def async_fire_growspace_event(
    hass: HomeAssistant, event_type: str, growspace: Growspace
) -> None:
    """Fire a growspace-related event."""
    hass.bus.async_fire(
        event_type,
        {
            "growspace_id": growspace.id,
            "name": growspace.name,
            "device_id": growspace.device_id,
        },
    )


def async_fire_plant_event(
    hass: HomeAssistant,
    event_type: str,
    plant: Plant,
    changes: dict[str, Any] | None = None,
) -> None:
    """Fire a plant-related event."""
    payload = {
        "plant_id": plant.plant_id,
        "growspace_id": plant.growspace_id,
        "strain": plant.strain,
        "stage": str(plant.stage),
        "device_id": plant.device_id,
    }

    if changes:
        payload.update(changes)

    hass.bus.async_fire(event_type, payload)
