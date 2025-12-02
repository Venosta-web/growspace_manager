"""Tests for the PlantConfigHandler."""

from unittest.mock import AsyncMock, MagicMock

import pytest
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.growspace_manager.config_handlers.plant_config_handler import (
    PlantConfigHandler,
)
from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.models import Growspace, Plant

ENTRY_ID = "test_entry_id"
GROWSPACE_ID = "test_growspace"


@pytest.fixture
def mock_coordinator() -> MagicMock:
    """Mock the GrowspaceCoordinator."""
    coordinator = MagicMock()
    coordinator.get_sorted_growspace_options.return_value = [
        (GROWSPACE_ID, "Test Growspace")
    ]
    coordinator.growspaces = {
        GROWSPACE_ID: Growspace(
            id=GROWSPACE_ID,
            name="Test Growspace",
            rows=5,
            plants_per_row=5,
        )
    }
    coordinator.get_strain_options.return_value = ["Strain A", "Strain B"]

    # Async methods
    coordinator.async_harvest_plant = AsyncMock()
    coordinator.async_remove_plant = AsyncMock()
    coordinator.async_add_plant = AsyncMock()
    coordinator.async_update_plant = AsyncMock()

    return coordinator


@pytest.fixture
def mock_hass(mock_coordinator) -> MagicMock:
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {DOMAIN: {ENTRY_ID: {"coordinator": mock_coordinator}}}
    return hass


@pytest.fixture
def mock_config_entry() -> MagicMock:
    """Mock Config Entry."""
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = ENTRY_ID
    return entry


@pytest.fixture
def handler(mock_hass: MagicMock, mock_config_entry: MagicMock) -> PlantConfigHandler:
    """Fixture for PlantConfigHandler."""
    return PlantConfigHandler(mock_hass, mock_config_entry)


def test_initialization(
    handler: PlantConfigHandler, mock_hass: MagicMock, mock_config_entry: MagicMock
):
    """Test initialization."""
    assert handler.hass == mock_hass
    assert handler.config_entry == mock_config_entry


def test_get_plant_management_schema(
    handler: PlantConfigHandler, mock_coordinator: MagicMock
):
    """Test generating the plant management schema."""
    schema = handler.get_plant_management_schema(mock_coordinator)
    assert isinstance(schema, vol.Schema)
    # We can't easily inspect the schema structure deeply, but we can verify it runs without error
    # and calls the coordinator method
    mock_coordinator.get_sorted_growspace_options.assert_called_once()


async def test_async_harvest_plant(
    handler: PlantConfigHandler, mock_coordinator: MagicMock
):
    """Test harvesting a plant."""
    await handler.async_harvest_plant(GROWSPACE_ID, "plant_1", 100.5)
    mock_coordinator.async_harvest_plant.assert_awaited_once_with(
        GROWSPACE_ID, "plant_1", 100.5
    )


async def test_async_destroy_plant(
    handler: PlantConfigHandler, mock_coordinator: MagicMock
):
    """Test destroying a plant."""
    await handler.async_destroy_plant(GROWSPACE_ID, "plant_1")
    mock_coordinator.async_remove_plant.assert_awaited_once_with("plant_1")


async def test_async_add_plant(
    handler: PlantConfigHandler, mock_coordinator: MagicMock
):
    """Test adding a plant."""
    await handler.async_add_plant(
        growspace_id=GROWSPACE_ID,
        strain="Strain A",
        row=1,
        col=2,
        phenotype="Pheno X",
        veg_start="2023-01-01",
        flower_start="2023-02-01",
    )
    mock_coordinator.async_add_plant.assert_awaited_once_with(
        growspace_id=GROWSPACE_ID,
        strain="Strain A",
        row=1,
        col=2,
        phenotype="Pheno X",
        veg_start="2023-01-01",
        flower_start="2023-02-01",
    )


async def test_async_update_plant(
    handler: PlantConfigHandler, mock_coordinator: MagicMock
):
    """Test updating a plant."""
    await handler.async_update_plant("plant_1", strain="New Strain")
    mock_coordinator.async_update_plant.assert_awaited_once_with(
        "plant_1", strain="New Strain"
    )


def test_get_growspace_selection_schema(
    handler: PlantConfigHandler, mock_coordinator: MagicMock
):
    """Test generating growspace selection schema."""
    # Mock devices
    device1 = MagicMock()
    device1.name = "Device 1"
    device1.identifiers = {(DOMAIN, GROWSPACE_ID)}

    devices = [device1]

    schema = handler.get_growspace_selection_schema(devices, mock_coordinator)
    assert isinstance(schema, vol.Schema)


def test_get_add_plant_schema(handler: PlantConfigHandler, mock_coordinator: MagicMock):
    """Test generating add plant schema."""
    growspace = mock_coordinator.growspaces[GROWSPACE_ID]

    # With coordinator (strains available)
    schema = handler.get_add_plant_schema(growspace, mock_coordinator)
    assert isinstance(schema, vol.Schema)
    mock_coordinator.get_strain_options.assert_called_once()

    # Without coordinator
    schema_no_coord = handler.get_add_plant_schema(growspace)
    assert isinstance(schema_no_coord, vol.Schema)

    # Without growspace
    schema_no_gs = handler.get_add_plant_schema(None)
    assert isinstance(schema_no_gs, vol.Schema)


def test_get_update_plant_schema(
    handler: PlantConfigHandler, mock_coordinator: MagicMock
):
    """Test generating update plant schema."""
    plant = Plant(
        plant_id="plant_1", growspace_id=GROWSPACE_ID, strain="Strain A", row=1, col=1
    )

    schema = handler.get_update_plant_schema(plant, mock_coordinator)
    assert isinstance(schema, vol.Schema)
    mock_coordinator.get_strain_options.assert_called()
