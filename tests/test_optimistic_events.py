from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import Plant


@pytest.fixture
def mock_coordinator(hass: HomeAssistant):
    coordinator = GrowspaceCoordinator(hass, "entry")
    coordinator.lifecycle_manager = AsyncMock()
    coordinator.serializer = MagicMock()
    # Mock serializer behavior
    coordinator.serializer.serialize_plant.return_value = {
        "plant_id": "test_plant",
        "stage": "veg",
        "veg_days": 10,
    }
    # Mock async_save
    coordinator.async_save = AsyncMock()
    # Mock invalidate
    coordinator._invalidate_cache = MagicMock()
    return coordinator


@pytest.mark.asyncio
async def test_async_add_plant_fires_event(
    mock_coordinator, hass: HomeAssistant
) -> None:
    # Setup
    plant_data = Plant(
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
        fired_events.append(event)

    hass.bus.async_listen("growspace_manager_updated", event_listener)

    # Execute
    await mock_coordinator.async_add_plant(growspace_id="test_gs", strain="Test Strain")
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
    updated_plant = Plant(
        plant_id="test_plant",
        growspace_id="test_gs",
        strain="Test Strain",
        stage="flower",
    )
    mock_coordinator.plants = {"test_plant": updated_plant}  # Needed for old_gs check
    mock_coordinator.lifecycle_manager.async_update_plant.return_value = updated_plant

    fired_events = []
    hass.bus.async_listen("growspace_manager_updated", lambda e: fired_events.append(e))

    # Execute
    await mock_coordinator.async_update_plant(plant_id="test_plant", stage="flower")
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
    plant = Plant(plant_id="test_plant", growspace_id="test_gs", strain="Test Strain")
    mock_coordinator.plants = {"test_plant": plant}
    mock_coordinator.lifecycle_manager.async_remove_plant.return_value = True

    fired_events = []
    hass.bus.async_listen("growspace_manager_updated", lambda e: fired_events.append(e))

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
