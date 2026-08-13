"""Coverage tests for debug.py."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.models import Plant
from custom_components.growspace_manager.services.debug import (
    _consolidate_plants_to_canonical_growspace,
    _restore_plants_to_canonical_growspace,
)


@pytest.fixture
def mock_coordinator():
    """Fixture for a mock GrowspaceCoordinator."""
    coordinator = MagicMock()
    coordinator.plants = {}
    coordinator.growspaces = {}
    coordinator.validator = MagicMock()
    coordinator.services = MagicMock()
    coordinator.services.plants.relocate_to_growspace = AsyncMock(return_value=[])
    return coordinator


@pytest.mark.asyncio
async def test_restore_plants_no_space(mock_coordinator) -> None:
    """Test _restore_plants_to_canonical_growspace when no plant could be placed."""
    mock_plant = MagicMock(spec=Plant)
    mock_plant.plant_id = "p1"
    mock_plant.growspace_id = "old_dry"
    mock_coordinator.plants = {"p1": mock_plant}

    await _restore_plants_to_canonical_growspace(
        mock_coordinator,
        "dry",
        [{"plant_id": "p1", "strain": "Test Strain", "old_pos": "(1,1)"}],
        "dry",
    )

    mock_coordinator.services.plants.relocate_to_growspace.assert_awaited_once_with(
        "dry", ["p1"]
    )
    assert mock_plant.growspace_id == "old_dry"


@pytest.mark.asyncio
async def test_consolidate_plants_no_space(mock_coordinator) -> None:
    """Test _consolidate_plants_to_canonical_growspace when no plant could be placed."""
    mock_plant = MagicMock(spec=Plant)
    mock_plant.plant_id = "p1"
    mock_plant.growspace_id = "dry_1"

    mock_coordinator.plants = {"p1": mock_plant}
    mock_coordinator.growspaces = {"dry_1": MagicMock(layout_revision=1)}
    mock_coordinator.services.growspaces.get_growspace_plants.return_value = [
        mock_plant
    ]

    await _consolidate_plants_to_canonical_growspace(
        mock_coordinator, ["dry_1"], "dry", "dry"
    )

    mock_coordinator.services.plants.relocate_to_growspace.assert_awaited_once_with(
        "dry", ["p1"]
    )
    assert mock_plant.growspace_id == "dry_1"

    # Verify duplicate growspace was still removed (as per logic)
    assert "dry_1" not in mock_coordinator.growspaces
