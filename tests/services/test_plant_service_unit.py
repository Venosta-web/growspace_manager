"""Unit tests for PlantService."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from custom_components.growspace_manager.managers.plant import PlantManager
from custom_components.growspace_manager.models import Plant


@pytest.fixture
def mock_hass():
    hass = Mock()
    hass.bus = Mock()
    hass.bus.async_fire = Mock()
    return hass


@pytest.fixture
def mock_repository():
    repo = Mock()
    repo.plants = {}
    repo.growspaces = {}
    return repo


@pytest.fixture
def mock_validator():
    return Mock()


@pytest.fixture
def mock_lifecycle_manager():
    return AsyncMock()


@pytest.fixture
def mockgrowspace_manager():
    return Mock()


@pytest.fixture
def mock_plant_view_builder():
    return Mock()


@pytest.fixture
def mock_save_callback():
    return AsyncMock()


@pytest.fixture
def plant_service(
    mock_hass,
    mock_repository,
    mock_validator,
    mock_lifecycle_manager,
    mockgrowspace_manager,
    mock_plant_view_builder,
    mock_save_callback,
):
    lock = asyncio.Lock()
    return PlantManager(
        hass=mock_hass,
        repository=mock_repository,
        validator=mock_validator,
        growspace_manager=mockgrowspace_manager,
        strain_library=MagicMock(),
        plant_view_builder=mock_plant_view_builder,
        save_callback=mock_save_callback,
        lock=lock,
    )


@pytest.mark.asyncio
async def test_take_clones_growspace_full(
    plant_service,
    mock_repository,
    mock_validator,
    mockgrowspace_manager,
):
    """Test take_clones raises ValueError when growspace is full."""
    # Setup mother plant
    mother_id = "mother_1"
    mother_plant = Mock(spec=Plant)
    mother_plant.strain = "Test Strain"
    mother_plant.phenotype = "Test Pheno"
    mock_repository.plants[mother_id] = mother_plant

    # Setup target growspace
    clone_gs_id = "clone_room"

    # Mock validator to pass plant existence check
    mock_validator.validate_plant_exists.return_value = None

    # Mock growspace service to return clone room id (if default used) or we pass explicit
    # If we pass explicit target_growspace_id, we need it in repo.growspaces
    mock_repository.growspaces[clone_gs_id] = Mock()

    # Mock find_first_available_position to return None (Full)
    mock_validator.find_first_available_position.return_value = (None, None)

    with pytest.raises(ValueError, match=f"Growspace '{clone_gs_id}' is full"):
        await plant_service.take_clones(
            mother_plant_id=mother_id, num_clones=1, target_growspace_id=clone_gs_id
        )


@pytest.mark.asyncio
async def test_take_clones_explicit_target_growspace_not_found(
    plant_service,
    mock_repository,
    mock_validator,
):
    """Test take_clones raises ValueError when explicit target growspace not found."""
    # Setup mother plant
    mother_id = "mother_1"
    mother_plant = Mock(spec=Plant)
    mock_repository.plants[mother_id] = mother_plant

    target_gs_id = "non_existent_room"

    # Ensure target not in repo
    if target_gs_id in mock_repository.growspaces:
        del mock_repository.growspaces[target_gs_id]

    with pytest.raises(
        ValueError, match=f"Target growspace '{target_gs_id}' does not exist"
    ):
        await plant_service.take_clones(
            mother_plant_id=mother_id, num_clones=1, target_growspace_id=target_gs_id
        )
