"""Coverage tests for debug.py."""

from unittest.mock import AsyncMock, MagicMock, patch
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
    return coordinator


@pytest.mark.asyncio
async def test_restore_plants_no_space(mock_coordinator) -> None:
    """Test _restore_plants_to_canonical_growspace when no space is available."""
    canonical_id = "dry"
    plants_data_to_restore = [
        {"plant_id": "p1", "strain": "Test Strain", "old_pos": "(1,1)"}
    ]
    log_prefix = "dry"

    # Setup plant in coordinator
    mock_plant = MagicMock(spec=Plant)
    mock_plant.plant_id = "p1"
    mock_plant.growspace_id = "old_dry"
    mock_coordinator.plants = {"p1": mock_plant}

    # Setup validator to return No space (None, None)
    mock_coordinator.validator.find_first_available_position.return_value = (None, None)

    with patch(
        "custom_components.growspace_manager.services.debug._LOGGER.warning"
    ) as mock_warning:
        await _restore_plants_to_canonical_growspace(
            mock_coordinator, canonical_id, plants_data_to_restore, log_prefix
        )

        # Verify warning was logged
        mock_warning.assert_called_with(
            "Cannot restore %s: no space in %s", "p1", canonical_id
        )

        # Verify plant was NOT moved
        assert mock_plant.growspace_id == "old_dry"


@pytest.mark.asyncio
async def test_consolidate_plants_no_space(mock_coordinator) -> None:
    """Test _consolidate_plants_to_canonical_growspace when no space is available."""
    duplicate_ids = ["dry_1"]
    canonical_id = "dry"
    log_prefix = "dry"

    # Setup plant in duplicate growspace
    mock_plant = MagicMock(spec=Plant)
    mock_plant.plant_id = "p1"
    mock_plant.growspace_id = "dry_1"

    mock_coordinator.plants = {"p1": mock_plant}
    mock_coordinator.growspaces = {"dry_1": {}}  # Add duplicate growspace
    mock_coordinator.services.get_growspace_plants.return_value = [mock_plant]

    # Setup validator to return No space (None, None)
    mock_coordinator.validator.find_first_available_position.return_value = (None, None)

    with patch(
        "custom_components.growspace_manager.services.debug._LOGGER.warning"
    ) as mock_warning:
        await _consolidate_plants_to_canonical_growspace(
            mock_coordinator, duplicate_ids, canonical_id, log_prefix
        )

        # Verify warning was logged
        mock_warning.assert_called_with(
            "Cannot move plant %s to %s: No space available", "p1", canonical_id
        )

        # Verify plant was NOT moved
        assert mock_plant.growspace_id == "dry_1"

        # Verify duplicate growspace was still removed (as per logic)
        assert "dry_1" not in mock_coordinator.growspaces
