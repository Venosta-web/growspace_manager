"""Tests for Growspace Manager events."""

from common import create_plant

from custom_components.growspace_manager.events import (
    EVENT_CLONES_TAKEN,
    EVENT_GROWSPACE_UPDATED,
    EVENT_PLANT_ADDED,
    async_fire_clones_taken_event,
    async_fire_growspace_event,
    async_fire_plant_event,
)
from custom_components.growspace_manager.models import Growspace
from homeassistant.core import HomeAssistant, callback


async def test_async_fire_growspace_event(hass: HomeAssistant) -> None:
    """Test firing a growspace event."""
    growspace = Growspace(id="gs1", name="Test GS", device_id="dev1")

    events = []

    @callback
    def capture_event(event):
        events.append(event)

    hass.bus.async_listen(EVENT_GROWSPACE_UPDATED, capture_event)

    async_fire_growspace_event(hass, EVENT_GROWSPACE_UPDATED, growspace)
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["event_type"] == EVENT_GROWSPACE_UPDATED
    assert events[0].data["data"]["growspace_id"] == "gs1"
    assert events[0].data["data"]["name"] == "Test GS"
    assert events[0].data["data"]["device_id"] == "dev1"


async def test_async_fire_plant_event(hass: HomeAssistant) -> None:
    """Test firing a plant event."""
    plant = create_plant(
        plant_id="p1",
        strain="Strain A",
        growspace_id="gs1",
        stage="veg",
        device_id="dev1",
    )

    events = []

    @callback
    def capture_event(event):
        events.append(event)

    hass.bus.async_listen(EVENT_PLANT_ADDED, capture_event)

    async_fire_plant_event(hass, EVENT_PLANT_ADDED, plant)
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["plant_id"] == "p1"
    assert events[0].data["growspace_id"] == "gs1"
    assert events[0].data["strain"] == "Strain A"
    assert events[0].data["stage"] == "veg"
    assert events[0].data["device_id"] == "dev1"


async def test_async_fire_plant_event_with_changes(hass: HomeAssistant) -> None:
    """Test firing a plant event with changes."""
    plant = create_plant(
        plant_id="p1",
        strain="Strain A",
        growspace_id="gs1",
        stage="veg",
        device_id="dev1",
    )
    changes = {"new_stage": "flower"}

    events = []

    @callback
    def capture_event(event):
        events.append(event)

    hass.bus.async_listen(EVENT_PLANT_ADDED, capture_event)

    async_fire_plant_event(hass, EVENT_PLANT_ADDED, plant, changes)
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["plant_id"] == "p1"
    assert events[0].data["growspace_id"] == "gs1"
    assert events[0].data["strain"] == "Strain A"
    assert events[0].data["stage"] == "veg"
    assert events[0].data["device_id"] == "dev1"
    assert events[0].data["new_stage"] == "flower"


async def test_async_fire_clones_taken_event(hass: HomeAssistant) -> None:
    """Test firing clones taken event."""
    mother = create_plant(
        plant_id="mom1", strain="Strain M", growspace_id="mother", device_id="devM"
    )

    events = []

    @callback
    def capture_event(event):
        events.append(event)

    hass.bus.async_listen(EVENT_CLONES_TAKEN, capture_event)

    async_fire_clones_taken_event(hass, mother, 5, "clone_gs")
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["mother_plant_id"] == "mom1"
    assert events[0].data["num_clones"] == 5
    assert events[0].data["growspace_id"] == "clone_gs"
    assert events[0].data["device_id"] == "devM"
