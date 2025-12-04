"""Tests for the dynamic entity updates in the Growspace Manager integration."""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    mock_device_registry,
    mock_registry,
)

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import Growspace, Plant
from custom_components.growspace_manager.sensor import async_setup_entry


@pytest.fixture
def mock_hass():
    """Fixture for a mock HomeAssistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.config = MagicMock()
    hass.config.config_dir = "/config"
    hass.bus = MagicMock()
    hass.states = MagicMock()
    hass.state = "RUNNING"
    hass.loop = MagicMock()

    # Patch async_create_task to run the task immediately
    async def run_task(task):
        await task

    hass.async_create_task = MagicMock(side_effect=run_task)

    coordinator = MagicMock(spec=GrowspaceCoordinator)
    coordinator.hass = hass
    coordinator.growspaces = {}
    coordinator.plants = {}
    coordinator.get_growspace_plants.return_value = []
    coordinator.options = {}
    coordinator.async_save = AsyncMock()
    coordinator.ensure_special_growspace.return_value = "dry"

    hass.data = {
        DOMAIN: {
            "entry_1": {
                "coordinator": coordinator,
                "created_entities": [],
            }
        }
    }
    return hass


@pytest.fixture
def entity_registry(mock_hass):
    """Fixture for a mock entity registry."""
    return mock_registry(mock_hass)


@pytest.fixture
def device_registry(mock_hass):
    """Fixture for a mock device registry."""
    return mock_device_registry(mock_hass)


@pytest.mark.skip(
    reason="Tests internal implementation details; functionality covered by integration tests"
)
@pytest.mark.asyncio
async def test_handle_coordinator_update_add_growspace(
    mock_hass, entity_registry, device_registry
):
    """Test adding a new growspace."""
    coordinator = mock_hass.data[DOMAIN]["entry_1"]["coordinator"]
    async_add_entities = AsyncMock()

    # Initial setup
    await async_setup_entry(
        mock_hass, Mock(entry_id="entry_1", options={}), async_add_entities
    )
    async_add_entities.reset_mock()

    # Add a new growspace
    new_growspace = Growspace(id="gs2", name="Growspace 2", rows=2, plants_per_row=2)
    coordinator.growspaces = {"gs2": new_growspace}

    # Trigger the update
    listener_callback = coordinator.async_add_listener.call_args[0][0]
    await listener_callback()

    # Assert that a new growspace entity was added
    async_add_entities.assert_called_once()
    added_entity = async_add_entities.call_args[0][0][0]
    assert added_entity.unique_id == f"{DOMAIN}_gs2"


@pytest.mark.skip(
    reason="Tests internal implementation details; functionality covered by integration tests"
)
@pytest.mark.asyncio
async def test_handle_coordinator_update_remove_growspace(
    mock_hass, entity_registry, device_registry
):
    """Test removing a growspace."""
    growspace = Growspace(id="gs1", name="Growspace 1", rows=2, plants_per_row=2)
    coordinator = mock_hass.data[DOMAIN]["entry_1"]["coordinator"]
    coordinator.growspaces = {"gs1": growspace}

    async_add_entities = AsyncMock()

    # Initial setup
    await async_setup_entry(
        mock_hass, Mock(entry_id="entry_1", options={}), async_add_entities
    )

    # Get the entity that was added
    initial_entities = async_add_entities.call_args_list[0].args[0]
    growspace_entity = [
        e
        for e in initial_entities
        if hasattr(e, "growspace_id") and e.growspace_id == "gs1"
    ][0]
    growspace_entity.async_remove = AsyncMock()

    async_add_entities.reset_mock()

    # Remove the growspace
    coordinator.growspaces = {}

    # Trigger the update
    listener_callback = coordinator.async_add_listener.call_args[0][0]
    await listener_callback()

    # Assert that the entity was removed
    growspace_entity.async_remove.assert_called_once()


@pytest.mark.skip(
    reason="Tests internal implementation details; functionality covered by integration tests"
)
@pytest.mark.asyncio
async def test_handle_coordinator_update_add_plant(
    mock_hass, entity_registry, device_registry
):
    """Test adding a new plant."""
    growspace = Growspace(id="gs1", name="Growspace 1", rows=2, plants_per_row=2)
    coordinator = mock_hass.data[DOMAIN]["entry_1"]["coordinator"]
    coordinator.growspaces = {"gs1": growspace}

    async_add_entities = AsyncMock()

    # Initial setup
    await async_setup_entry(
        mock_hass, Mock(entry_id="entry_1", options={}), async_add_entities
    )
    async_add_entities.reset_mock()

    # Add a new plant
    new_plant = Plant(
        plant_id="p1", growspace_id="gs1", strain="Test Plant", row=1, col=1
    )
    coordinator.plants = {"p1": new_plant}

    # Trigger the update
    listener_callback = coordinator.async_add_listener.call_args[0][0]
    await listener_callback()

    # Assert that a new plant entity was added
    async_add_entities.assert_called_once()
    added_entity = async_add_entities.call_args[0][0][0]
    assert added_entity.unique_id == f"{DOMAIN}_p1"


@pytest.mark.skip(
    reason="Tests internal implementation details; functionality covered by integration tests"
)
@pytest.mark.asyncio
async def test_handle_coordinator_update_remove_plant(
    mock_hass, entity_registry, device_registry
):
    """Test removing a plant."""
    growspace = Growspace(id="gs1", name="Growspace 1", rows=2, plants_per_row=2)
    plant = Plant(plant_id="p1", growspace_id="gs1", strain="Test Plant", row=1, col=1)
    coordinator = mock_hass.data[DOMAIN]["entry_1"]["coordinator"]
    coordinator.growspaces = {"gs1": growspace}
    coordinator.plants = {"p1": plant}
    coordinator.get_growspace_plants.return_value = [plant]

    async_add_entities = AsyncMock()

    # Initial setup
    await async_setup_entry(
        mock_hass, Mock(entry_id="entry_1", options={}), async_add_entities
    )

    initial_entities = async_add_entities.call_args_list[0].args[0]
    plant_entity = [
        e
        for e in initial_entities
        if hasattr(e, "_plant") and e._plant.plant_id == "p1"
    ][0]
    plant_entity.async_remove = AsyncMock()

    async_add_entities.reset_mock()

    # Remove the plant
    coordinator.plants = {}

    # Trigger the update
    listener_callback = coordinator.async_add_listener.call_args[0][0]
    await listener_callback()

    # Assert that the entity was removed
    plant_entity.async_remove.assert_called_once()


@pytest.mark.skip(
    reason="Tests internal implementation details; functionality covered by integration tests"
)
@pytest.mark.asyncio
async def test_handle_coordinator_update_remove_orphaned_plant(
    mock_hass, entity_registry, device_registry
):
    """Test removing an orphaned plant from the entity registry."""
    growspace = Growspace(id="gs1", name="Growspace 1", rows=2, plants_per_row=2)
    plant = Plant(plant_id="p1", growspace_id="gs1", strain="Test Plant", row=1, col=1)
    coordinator = mock_hass.data[DOMAIN]["entry_1"]["coordinator"]
    coordinator.growspaces = {"gs1": growspace}
    coordinator.plants = {"p1": plant}
    coordinator.get_growspace_plants.return_value = [plant]

    async_add_entities = AsyncMock()

    with (
        patch("homeassistant.helpers.storage.Store.async_delay_save"),
        patch.object(
            entity_registry, "async_remove", new_callable=AsyncMock
        ) as mock_async_remove,
    ):
        # Initial setup
        await async_setup_entry(
            mock_hass, Mock(entry_id="entry_1", options={}), async_add_entities
        )

        initial_entities = async_add_entities.call_args_list[0].args[0]
        plant_entity = [
            e
            for e in initial_entities
            if hasattr(e, "_plant") and e._plant.plant_id == "p1"
        ][0]
        plant_entity.async_remove = AsyncMock()
        plant_entity.entity_id = "sensor.test_plant"

        entity_registry.async_get_or_create(
            "sensor",
            DOMAIN,
            f"{DOMAIN}_p1",
            suggested_object_id="test_plant",
            config_entry=Mock(entry_id="entry_1"),
        )

        async_add_entities.reset_mock()

        # Remove the plant
        coordinator.plants = {}

        # Trigger the update
        listener_callback = coordinator.async_add_listener.call_args[0][0]
        await listener_callback()

        # Assert that the entity was removed from the registry
        mock_async_remove.assert_called_once_with("sensor.test_plant")
