"""Tests for the PlantLifecycleManager class."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import PlantStage
from custom_components.growspace_manager.exceptions import GrowspaceNotFoundError
from custom_components.growspace_manager.models import Plant
from custom_components.growspace_manager.plant_lifecycle_manager import (
    PlantLifecycleManager,
)


@pytest.fixture
def repository_mock():
    """Mock the GrowspaceRepository."""
    mock = MagicMock()
    mock.plants = {}
    mock.growspaces = {}
    mock.notifications_sent = {}
    return mock


@pytest.fixture
def validator_mock():
    """Mock the GrowspaceValidator."""
    mock = MagicMock()
    mock.find_first_available_position = MagicMock(return_value=(1, 1))
    mock.validate_position_not_occupied = MagicMock()
    mock.validate_plant_exists = MagicMock()
    return mock


@pytest.fixture
def gs_service_mock():
    """Mock the GrowspaceService."""
    mock = MagicMock()
    mock.ensure_special_growspace = MagicMock(return_value="mock_growspace_id")
    return mock


@pytest.fixture
def strain_library_mock():
    """Mock the StrainLibrary."""
    mock = MagicMock()
    mock.record_harvest = AsyncMock()
    return mock


@pytest.fixture
def serializer_mock():
    """Mock the GrowspaceSerializer."""
    mock = MagicMock()
    mock.calculate_days_in_stage = MagicMock(return_value=10)
    return mock


@pytest.fixture
def lock_mock():
    """Mock the asyncio Lock."""
    mock = MagicMock()
    mock.__aenter__ = AsyncMock(return_value=None)
    mock.__aexit__ = AsyncMock(return_value=None)
    return mock


@pytest.fixture
def save_callback_mock():
    """Mock the save callback."""
    return AsyncMock()


@pytest.fixture
def manager(
    repository_mock,
    validator_mock,
    gs_service_mock,
    strain_library_mock,
    serializer_mock,
    save_callback_mock,
    lock_mock,
):
    """Fixture for PlantLifecycleManager."""
    return PlantLifecycleManager(
        repository=repository_mock,
        validator=validator_mock,
        growspace_service=gs_service_mock,
        strain_library=strain_library_mock,
        serializer=serializer_mock,
        save_callback=save_callback_mock,
        lock=lock_mock,
    )


@pytest.mark.asyncio
async def test_handle_clone_creation(
    manager, repository_mock, save_callback_mock
) -> None:
    """Test handle_clone_creation adds plant to repository."""
    mother_plant = MagicMock(spec=Plant)
    mother_plant.phenotype = "Pheno1"

    plant_id = await manager.handle_clone_creation(
        growspace_id="clone_tent",
        strain="OG Kush",
        row=1,
        col=2,
        source_mother_id="mother_id",
        mother_plant=mother_plant,
        extra_param="extra_value",
    )

    assert plant_id is not None
    # Check that a plant was added to repository.plants
    assert len(repository_mock.plants) == 1
    added_plant = list(repository_mock.plants.values())[0]

    assert added_plant.growspace_id == "clone_tent"
    assert added_plant.strain == "OG Kush"
    assert added_plant.phenotype == "Pheno1"
    assert added_plant.row == 1
    assert added_plant.col == 2
    assert added_plant.stage == PlantStage.CLONE
    assert added_plant.type == PlantStage.CLONE
    assert added_plant.source_mother == "mother_id"

    save_callback_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_harvest_auto_flow_strict_matching_audreys_garden(
    manager, repository_mock
) -> None:
    """Test that 'Audrey's Garden' does NOT trigger 'dry' logic via loose matching."""

    plant = MagicMock()
    plant.stage = PlantStage.VEG
    plant.growspace_id = "initial_gs"
    plant.strain = "Test Strain"
    plant.phenotype = "Test Pheno"

    # Let's mock the move methods on the manager instance itself to track calls
    with (
        patch.object(
            manager, "move_to_dry_growspace", new_callable=AsyncMock
        ) as mock_move_dry,
        patch.object(manager, "move_to_cure_growspace", new_callable=AsyncMock) as _,
        patch.object(manager, "move_to_clone_growspace", new_callable=AsyncMock) as _,
    ):
        mock_move_dry.return_value = True

        await manager._harvest_auto_flow(
            plant_id="plant1",
            plant=plant,
            target_growspace_name="Audrey's Garden",
            transition_date="2023-01-01",
        )

        # It should call move_to_dry_growspace (fallback)
        mock_move_dry.assert_awaited()


@pytest.mark.asyncio
async def test_harvest_auto_flow_explicit_dry(manager, repository_mock) -> None:
    """Test explicit 'dry' match."""
    plant = MagicMock()
    plant.stage = PlantStage.VEG
    plant.growspace_id = "initial_gs"
    plant.strain = "Test Strain"
    plant.phenotype = "Test Pheno"
    plant.plant_id = "p1"
    repository_mock.plants = {"p1": plant}  # Ensure plant exists

    with patch.object(
        manager, "_move_to_special_growspace", new_callable=AsyncMock
    ) as mock_move_special:
        mock_move_special.return_value = True

        await manager._harvest_auto_flow("p1", plant, "dry", "2023-01-01")

        mock_move_special.assert_awaited_once_with(
            "p1", plant, PlantStage.DRY, "2023-01-01"
        )


@pytest.mark.asyncio
async def test_move_to_dry_growspace_device_id_ghosting(
    manager, repository_mock, gs_service_mock
) -> None:
    """Test that moving to a growspace without a device ID clears the plant's device ID."""
    plant = MagicMock(spec=Plant)
    plant.plant_id = "p1"
    plant.growspace_id = "gs1"
    plant.device_id = "device_1"
    plant.strain = "Strain"
    plant.phenotype = "Pheno"

    # Mock the destination dry growspace having NO device_id
    gs_service_mock.ensure_special_growspace.return_value = "dry_gs"
    mock_dry_gs = MagicMock()
    mock_dry_gs.device_id = None  # Crucial: destination has no device
    repository_mock.growspaces = {"dry_gs": mock_dry_gs, "gs1": MagicMock()}
    repository_mock.plants = {"p1": plant}

    await manager.move_to_dry_growspace("p1", plant, "2023-01-01")

    # Verify that async_update_plant was called with device_id=None
    # (Since async_update_plant is a method on manager, we check the repository update)
    # Wait, in the actual implementation, move_to_dry_growspace calls _move_to_special_growspace
    # which calls async_update_plant.
    # Since we are testing the REAL manager, it will update repository.plants
    assert plant.device_id is None


@pytest.mark.asyncio
async def test_handle_harvest_logic_fallthrough(manager, repository_mock) -> None:
    """Test that invalid target_growspace_id raises ValueError and does not fall through."""
    plant = MagicMock(spec=Plant)
    plant.plant_id = "p1"
    # Mock growspaces not containing 'invalid_gs'
    repository_mock.growspaces = {"valid_gs": MagicMock()}

    with pytest.raises(
        GrowspaceNotFoundError, match="Target growspace invalid_gs not found"
    ):
        await manager.handle_harvest_logic(
            "p1", plant, "invalid_gs", "Invalid Name", "2023-01-01"
        )
