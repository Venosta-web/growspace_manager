"""Coverage-focused tests for PlantService."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.models import Plant, PlantGenetics
from custom_components.growspace_manager.services.plant_service import PlantService


@pytest.fixture
def mock_coordinator():
    """Mock coordinator."""
    coordinator = MagicMock()
    coordinator.plants = {}
    coordinator.growspaces = {}

    coordinator.lifecycle_manager = MagicMock()
    coordinator.lifecycle_manager.async_add_plant = AsyncMock()
    coordinator.lifecycle_manager.handle_clone_creation = AsyncMock()
    coordinator.lifecycle_manager.async_update_plant = AsyncMock()
    coordinator.lifecycle_manager.async_move_plant = AsyncMock()
    coordinator.lifecycle_manager.async_switch_plants = AsyncMock()
    coordinator.lifecycle_manager.transition_plant_stage = AsyncMock()
    coordinator.lifecycle_manager.async_remove_plant = AsyncMock()
    coordinator.lifecycle_manager.handle_harvest_logic = AsyncMock()

    coordinator.growspace_service = MagicMock()
    coordinator.cache = MagicMock()
    coordinator.validator = MagicMock()
    coordinator.serializer = MagicMock()
    coordinator.data_repository = MagicMock()
    coordinator.hass = MagicMock()
    coordinator.async_commit = AsyncMock()
    return coordinator


@pytest.fixture
def service(mock_coordinator):
    """PlantService fixture."""
    return PlantService(mock_coordinator)


@pytest.mark.asyncio
async def test_add_plant(service, mock_coordinator) -> None:
    """Test adding a plant."""
    plant = Plant(
        plant_id="p1", growspace_id="gs1", genetics=PlantGenetics(strain_name="S1")
    )
    mock_coordinator.lifecycle_manager.async_add_plant.return_value = plant

    result = await service.add_plant("gs1", "S1")
    assert result == plant
    mock_coordinator.cache.invalidate.assert_called_with("gs1")
    mock_coordinator.fire_event.assert_called()


@pytest.mark.asyncio
async def test_add_mother_plant(service, mock_coordinator) -> None:
    """Test adding a mother plant."""
    mock_coordinator.growspace_service.ensure_mother_growspace.return_value = "mother"
    plant = Plant(
        plant_id="p1", growspace_id="mother", genetics=PlantGenetics(strain_name="S1")
    )

    with patch.object(service, "add_plant", return_value=plant) as mock_add:
        result = await service.add_mother_plant("Pheno", "Strain", 1, 1)
        assert result == plant
        mock_add.assert_called_once()


@pytest.mark.asyncio
async def test_take_clones_default(service, mock_coordinator) -> None:
    """Test taking clones with default target."""
    mother = Plant(
        plant_id="mom",
        growspace_id="gs1",
        genetics=PlantGenetics(strain_name="S1", phenotype_name="P1"),
    )
    mock_coordinator.plants = {"mom": mother}
    mock_coordinator.growspace_service.ensure_special_growspace.return_value = "clone"
    mock_coordinator.validator.find_first_available_position.return_value = (1, 1)

    # Mock lifecycle manager returning a clone ID
    mock_coordinator.lifecycle_manager.handle_clone_creation.return_value = "c1"
    clone = Plant(
        plant_id="c1", growspace_id="clone", genetics=PlantGenetics(strain_name="S1")
    )
    mock_coordinator.plants["c1"] = clone

    results = await service.take_clones("mom", 1)
    assert len(results) == 1
    assert results[0] == clone


@pytest.mark.asyncio
async def test_take_clones_invalid_target(service, mock_coordinator) -> None:
    """Test taking clones with invalid target growspace."""
    mock_coordinator.plants = {"mom": MagicMock()}
    mock_coordinator.growspaces = {}
    with pytest.raises(ValueError, match="Target growspace 'unknown' does not exist"):
        await service.take_clones("mom", 1, target_growspace_id="unknown")


@pytest.mark.asyncio
async def test_take_clones_full_growspace(service, mock_coordinator) -> None:
    """Test taking clones when target growspace is full."""
    mock_coordinator.plants = {"mom": MagicMock()}
    mock_coordinator.growspaces = {"clone": MagicMock()}
    mock_coordinator.validator.find_first_available_position.return_value = (None, None)

    with pytest.raises(ValueError, match="Growspace 'clone' is full"):
        await service.take_clones("mom", 1, target_growspace_id="clone")


@pytest.mark.asyncio
async def test_update_plant_move(service, mock_coordinator) -> None:
    """Test updating plant with growspace move."""
    plant = Plant(plant_id="p1", growspace_id="gs1")
    mock_coordinator.plants = {"p1": plant}
    mock_coordinator.lifecycle_manager.async_update_plant.return_value = plant

    await service.update_plant("p1", growspace_id="gs2")
    assert mock_coordinator.cache.invalidate.call_count == 2


@pytest.mark.asyncio
async def test_move_plant(service, mock_coordinator) -> None:
    """Test moving a plant."""
    plant = Plant(plant_id="p1", growspace_id="gs1")
    mock_coordinator.plants = {"p1": plant}
    await service.move_plant("p1", 2, 2)
    mock_coordinator.lifecycle_manager.async_move_plant.assert_called_with("p1", 2, 2)


@pytest.mark.asyncio
async def test_switch_plants(service, mock_coordinator) -> None:
    """Test switching two plants."""
    p1 = Plant(plant_id="p1", growspace_id="gs1")
    p2 = Plant(plant_id="p2", growspace_id="gs2")
    mock_coordinator.plants = {"p1": p1, "p2": p2}
    await service.switch_plants("p1", "p2")
    mock_coordinator.lifecycle_manager.async_switch_plants.assert_called_with(
        "p1", "p2"
    )


@pytest.mark.asyncio
async def test_remove_plant_not_found(service, mock_coordinator) -> None:
    """Test removing non-existent plant."""
    assert await service.remove_plant("unknown") is False


@pytest.mark.asyncio
async def test_remove_plant_success(service, mock_coordinator) -> None:
    """Test removing plant successfully."""
    plant = Plant(plant_id="p1", growspace_id="gs1")
    mock_coordinator.plants = {"p1": plant}
    mock_coordinator.lifecycle_manager.async_remove_plant.return_value = True

    assert await service.remove_plant("p1") is True
    mock_coordinator.fire_event.assert_called_with(
        "plant_removed", {"plant_id": "p1", "growspace_id": "gs1"}
    )


def test_get_plant(service, mock_coordinator) -> None:
    """Test get_plant."""
    service.get_plant("p1")
    mock_coordinator.data_repository.get_plant.assert_called_with("p1")


@pytest.mark.asyncio
async def test_transition_plant_stage_actual(service, mock_coordinator) -> None:
    """Test actual transition_plant_stage execution."""
    plant = Plant(plant_id="p1", growspace_id="gs1")
    mock_coordinator.plants = {"p1": plant}
    await service.transition_plant_stage("p1", "flower")
    mock_coordinator.lifecycle_manager.transition_plant_stage.assert_called()


@pytest.mark.asyncio
async def test_convenience_methods(service, mock_coordinator) -> None:
    """Test stage transition convenience methods."""
    plant = Plant(plant_id="p1", growspace_id="gs1")
    mock_coordinator.plants = {"p1": plant}

    with patch.object(
        service, "transition_plant_stage", return_value=None
    ) as mock_trans:
        await service.start_flowering("p1")
        mock_trans.assert_called_with("p1", "flower", date.today())

        await service.start_drying("p1")
        mock_trans.assert_called_with("p1", "dry", date.today())

        await service.start_curing("p1")
        mock_trans.assert_called_with("p1", "cure", date.today())

        await service.harvest("p1")
        mock_trans.assert_called_with("p1", "dry", date.today())


@pytest.mark.asyncio
async def test_harvest_orchestration(service, mock_coordinator) -> None:
    """Test harvest_plant orchestration."""
    plant = Plant(
        plant_id="p1", growspace_id="gs1", genetics=PlantGenetics(strain_name="S1")
    )
    mock_coordinator.plants = {"p1": plant}
    mock_coordinator.lifecycle_manager.handle_harvest_logic.return_value = True

    # Mock calculate_plant_stage to avoid issues with mocked plants if any
    with patch(
        "custom_components.growspace_manager.services.plant_service.calculate_plant_stage",
        return_value="Flower",
    ):
        await service.harvest_plant("p1", target_growspace_id="dry_room")

    mock_coordinator.lifecycle_manager.handle_harvest_logic.assert_called()
    mock_coordinator.cache.invalidate.assert_any_call("gs1")
    mock_coordinator.cache.invalidate.assert_any_call("dry_room")
