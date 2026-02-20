"""Event management for the Growspace Manager integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypedDict

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


class GrowspaceEventPayload(TypedDict):
    """Payload for growspace events."""

    growspace_id: str
    name: str
    device_id: str | None


class PlantEventPayload(TypedDict, total=False):
    """Payload for plant events."""

    plant_id: str
    growspace_id: str
    strain: str
    stage: str
    device_id: str | None
    # Optional changes
    new_row: int
    new_col: int
    new_stage: str


class ClonesTakenEventPayload(TypedDict):
    """Payload for clones taken event."""

    mother_plant_id: str
    num_clones: int
    growspace_id: str
    device_id: str | None


def async_fire_growspace_event(
    hass: HomeAssistant, event_type: str, growspace: Growspace
) -> None:
    """Fire a growspace-related event."""
    data = {
        "growspace_id": growspace.id,
        "name": growspace.name,
        "device_id": growspace.device_id,
    }

    # If firing on the main update bus, use multiplexed format
    if event_type == "growspace_manager_updated":
        payload = {"event_type": event_type, "data": data}
        hass.bus.async_fire("growspace_manager_updated", payload)
    else:
        hass.bus.async_fire(event_type, data)


def async_fire_plant_event(
    hass: HomeAssistant,
    event_type: str,
    plant: Plant,
    changes: dict[str, Any] | None = None,
) -> None:
    """Fire a plant-related event."""
    data: PlantEventPayload = {
        "plant_id": plant.plant_id,
        "growspace_id": plant.growspace_id,
        "strain": plant.strain,
        "stage": str(plant.stage),
        "device_id": plant.device_id,
    }

    if changes:
        data.update(changes)  # type: ignore[typeddict-item]

    # If firing on the main update bus, use multiplexed format
    if event_type == "growspace_manager_updated":
        payload = {"event_type": event_type, "data": data}
        hass.bus.async_fire("growspace_manager_updated", payload)
    else:
        hass.bus.async_fire(event_type, data)


def async_fire_clones_taken_event(
    hass: HomeAssistant,
    mother_plant: Plant,
    num_clones: int,
    target_growspace_id: str,
) -> None:
    """Fire the clones taken event."""
    data: ClonesTakenEventPayload = {
        "mother_plant_id": mother_plant.plant_id,
        "num_clones": num_clones,
        "growspace_id": target_growspace_id,
        "device_id": mother_plant.device_id,
    }
    hass.bus.async_fire(EVENT_CLONES_TAKEN, data)
