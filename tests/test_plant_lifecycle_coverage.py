"""Additional tests for plant_lifecycle_manager coverage."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.const import PlantStage
from custom_components.growspace_manager.models import Growspace, Plant
from .conftest import create_plant
from custom_components.growspace_manager.plant_lifecycle_manager import (
    PlantLifecycleManager,
)


@pytest.fixture
def mock_coordinator():
    """Mock coordinator fixture."""
    coordinator = MagicMock()
    coordinator.plants = {}
    coordinator.growspaces = {
        "test_growspace": Growspace(
            id="test_growspace",
            name="Test Growspace",
        )
    }
    coordinator._notifications_sent = {}
    coordinator._lock = AsyncMock()
    coordinator.async_commit = AsyncMock()
    coordinator.validator = MagicMock()
    coordinator.serializer = MagicMock()
    coordinator.strain_library = MagicMock()
    coordinator.ensure_special_growspace = MagicMock(return_value="dry")
    return coordinator


async def test_async_remove_plant_not_found(mock_coordinator):
    """Test async_remove_plant when plant doesn't exist."""
    manager = PlantLifecycleManager(mock_coordinator)

    # Try to remove non-existent plant
    result = await manager.async_remove_plant("nonexistent_plant_id")

    # Should return False (line 126)
    assert result is False
    mock_coordinator.async_commit.assert_not_awaited()


async def test_async_remove_plant_with_notifications(mock_coordinator):
    """Test async_remove_plant removes from notifications_sent dict."""
    manager = PlantLifecycleManager(mock_coordinator)

    # Add a plant and notification
    plant_id = "test_plant_123"
    mock_coordinator.plants[plant_id] = create_plant(
        plant_id=plant_id,
        growspace_id="test_growspace",
        strain="Test Strain",
    )
    mock_coordinator._notifications_sent[plant_id] = True

    # Remove the plant
    result = await manager.async_remove_plant(plant_id)

    # Should remove from notifications_sent (line 123)
    assert result is True
    assert plant_id not in mock_coordinator._notifications_sent
    assert plant_id not in mock_coordinator.plants
    mock_coordinator.async_commit.assert_awaited_once()


async def test_record_analytics_exception_handling(mock_coordinator):
    """Test _record_analytics handles exceptions gracefully."""
    manager = PlantLifecycleManager(mock_coordinator)

    # Create a plant with veg and flower days
    plant = create_plant(
        plant_id="test_plant",
        growspace_id="test_growspace",
        strain="Test Strain",
        veg_start="2024-01-01",
        flower_start="2024-02-01",
    )

    # Mock serializer to return positive days
    mock_coordinator.serializer.calculate_days_in_stage.side_effect = [30, 60]

    # Mock strain_library.record_harvest to raise exception (lines 331-332)
    mock_coordinator.strain_library.record_harvest = AsyncMock(
        side_effect=Exception("Database error")
    )

    # Should not raise, exception is caught and logged
    await manager._record_analytics(plant)

    # Verify record_harvest was called
    mock_coordinator.strain_library.record_harvest.assert_awaited_once_with(
        "Test Strain", "", 30, 60
    )


async def test_transition_plant_stage_to_clone(mock_coordinator):
    """Test transition_plant_stage to CLONE stage."""
    manager = PlantLifecycleManager(mock_coordinator)

    # Create a plant
    plant_id = "test_plant"
    plant = create_plant(
        plant_id=plant_id,
        growspace_id="test_growspace",
        strain="Test Strain",
    )
    mock_coordinator.plants[plant_id] = plant

    # Mock validator to find position
    mock_coordinator.validator.find_first_available_position.return_value = (1, 1)

    # Transition to CLONE stage (line 428)
    await manager.transition_plant_stage(plant_id, PlantStage.CLONE, date(2024, 1, 15))

    # Verify move_to_clone_growspace was called
    mock_coordinator.ensure_special_growspace.assert_called()
