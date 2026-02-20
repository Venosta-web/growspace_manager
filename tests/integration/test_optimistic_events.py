from unittest.mock import AsyncMock, MagicMock

from common import create_plant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from homeassistant.core import HomeAssistant


@pytest.fixture
def mock_coordinator(hass: HomeAssistant):
    entry = MockConfigEntry(domain="growspace_manager", data={}, options={})
    entry.add_to_hass(hass)

    coordinator = GrowspaceCoordinator(hass, entry, data={})

    # Mock lifecycle manager and inject it into the service
    coordinator.lifecycle_manager = AsyncMock()
    coordinator.plant_manager.lifecycle_manager = coordinator.lifecycle_manager

    # Mock plant_view_builder behavior
    coordinator.plant_manager.plant_view_builder = MagicMock()
    coordinator.plant_manager.plant_view_builder.build.return_value = {
        "plant_id": "test_plant",
        "stage": "veg",
        "veg_days": 10,
    }

    # Mock async_commit to avoid generic events interfering
    coordinator.async_commit = AsyncMock()

    return coordinator


@pytest.mark.asyncio
async def test_async_add_plant_fires_event(
    mock_coordinator, hass: HomeAssistant
) -> None:
    # Setup
    plant_data = create_plant(
        plant_id="test_plant",
        growspace_id="test_gs",
        strain="Test Strain",
        stage="veg",
        veg_start="2023-01-01",
    )
    mock_coordinator.lifecycle_manager.async_add_plant.return_value = plant_data

    # Capture events
    fired_events = []

    def event_listener(event):
        # Only capture the events we care about for this test
        if event.data.get("event_type") == "plant_added":
            fired_events.append(event)

    hass.bus.async_listen("growspace_manager_updated", event_listener)

    # Execute
    await mock_coordinator.plant_manager.add_plant(
        growspace_id="test_gs", strain="Test Strain"
    )
    await hass.async_block_till_done()

    # Verify
    assert len(fired_events) > 0
    event = fired_events[0]
    payload = event.data

    assert payload["event_type"] == "plant_added"
    assert payload["data"]["plant"]["plant_id"] == "test_plant"
    assert payload["data"]["plant"]["veg_days"] == 10


@pytest.mark.asyncio
async def test_async_update_plant_fires_event(
    mock_coordinator, hass: HomeAssistant
) -> None:
    # Setup
    updated_plant = create_plant(
        plant_id="test_plant",
        growspace_id="test_gs",
        strain="Test Strain",
        stage="flower",
    )
    mock_coordinator.plants = {"test_plant": updated_plant}
    mock_coordinator.lifecycle_manager.async_update_plant.return_value = updated_plant

    fired_events = []

    def event_listener(event):
        if event.data.get("event_type") == "plant_updated":
            fired_events.append(event)

    hass.bus.async_listen("growspace_manager_updated", event_listener)

    # Execute
    await mock_coordinator.plant_manager.update_plant(
        plant_id="test_plant", stage="flower"
    )
    await hass.async_block_till_done()

    # Verify
    assert len(fired_events) > 0
    event = fired_events[0]
    payload = event.data

    assert payload["event_type"] == "plant_updated"
    assert payload["data"]["plant"] is not None


@pytest.mark.asyncio
async def test_async_remove_plant_fires_event(
    mock_coordinator, hass: HomeAssistant
) -> None:
    # Setup
    plant = create_plant(
        plant_id="test_plant", growspace_id="test_gs", strain="Test Strain"
    )
    mock_coordinator.plants["test_plant"] = plant
    mock_coordinator.lifecycle_manager.async_remove_plant.return_value = True

    fired_events = []

    def event_listener(event):
        if event.data.get("event_type") == "plant_removed":
            fired_events.append(event)

    hass.bus.async_listen("growspace_manager_updated", event_listener)

    # Execute
    await mock_coordinator.async_remove_plant("test_plant")
    await hass.async_block_till_done()

    # Verify
    assert len(fired_events) > 0
    event = fired_events[0]
    payload = event.data

    assert payload["event_type"] == "plant_removed"
    assert payload["data"]["plant_id"] == "test_plant"
    assert payload["data"]["growspace_id"] == "test_gs"
