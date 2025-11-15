"""Tests for the Growspace Manager sensor platform."""
from unittest.mock import MagicMock, AsyncMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.growspace_manager.sensor import (
    async_setup_entry,
    GrowspaceOverviewSensor,
    PlantEntity,
)
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import Growspace, Plant


@pytest.fixture
def mock_coordinator() -> GrowspaceCoordinator:
    """Fixture for a mock coordinator."""
    coordinator = MagicMock(spec=GrowspaceCoordinator)
    coordinator.growspaces = {
        "test_growspace": Growspace(
            id="test_growspace", name="Test Growspace", rows=2, plants_per_row=2
        )
    }
    coordinator.plants = {
        "test_plant": Plant(
            plant_id="test_plant",
            growspace_id="test_growspace",
            strain="Test Strain",
            row=1,
            col=1,
        )
    }
    coordinator.get_growspace_plants = MagicMock(
        return_value=[coordinator.plants["test_plant"]]
    )
    coordinator.calculate_days_in_stage = MagicMock(return_value=10)
    coordinator._ensure_special_growspace = MagicMock()
    return coordinator


async def test_async_setup_entry(
    hass: HomeAssistant, mock_coordinator: GrowspaceCoordinator
) -> None:
    """Test the sensor platform setup."""
    hass.data = {"growspace_manager": {"test_entry_id": {"coordinator": mock_coordinator, "created_entities": []}}}
    async_add_entities = MagicMock()

    with patch("custom_components.growspace_manager.sensor._async_create_derivative_sensors", AsyncMock()):
        await async_setup_entry(hass, MagicMock(), async_add_entities)
    async_add_entities.assert_called_once()


def test_growspace_overview_sensor(mock_coordinator: GrowspaceCoordinator) -> None:
    """Test the GrowspaceOverviewSensor."""
    growspace = mock_coordinator.growspaces["test_growspace"]
    sensor = GrowspaceOverviewSensor(mock_coordinator, "test_growspace", growspace)

    assert sensor.name == "Test Growspace"
    assert sensor.unique_id == "growspace_test_growspace"
    assert sensor.state == 1
    attributes = sensor.extra_state_attributes
    assert attributes["total_plants"] == 1
    assert attributes["grid"]["position_1_1"]["strain"] == "Test Strain"


def test_plant_entity(mock_coordinator: GrowspaceCoordinator) -> None:
    """Test the PlantEntity."""
    plant = mock_coordinator.plants["test_plant"]
    sensor = PlantEntity(mock_coordinator, plant)

    assert sensor.name == "Test Strain (1,1)"
    assert sensor.unique_id == "growspace_manager_test_plant"
    assert sensor.state == "seedling"
    attributes = sensor.extra_state_attributes
    assert attributes["strain"] == "Test Strain"
    assert attributes["veg_days"] == 10
