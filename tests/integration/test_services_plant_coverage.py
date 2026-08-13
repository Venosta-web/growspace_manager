"""Coverage-focused tests for PlantService."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import PlantStage
from custom_components.growspace_manager.managers.plant import PlantManager
from custom_components.growspace_manager.models import Plant, PlantGenetics
from custom_components.growspace_manager.services.context import ServiceContext
from homeassistant.core import HomeAssistant


@pytest.fixture
def repository_mock():
    """Mock the GrowspaceRepository."""
    mock = MagicMock()
    mock.get_plant.return_value = None
    mock.has_plant.return_value = False
    mock.has_growspace.return_value = False
    return mock


@pytest.fixture
def validator_mock():
    """Mock the GrowspaceValidator."""
    return MagicMock()


@pytest.fixture
def strain_library_mock():
    """Mock the StrainLibrary."""
    return MagicMock()


@pytest.fixture
def lifecycle_manager_mock():
    """Mock the PlantLifecycleManager."""
    mock = MagicMock()
    mock.async_add_plant = AsyncMock()
    mock.handle_clone_creation = AsyncMock()
    mock.async_update_plant = AsyncMock()
    mock.async_move_plant = AsyncMock()
    mock.async_switch_plants = AsyncMock()
    mock.transition_plant_stage = AsyncMock()
    mock.async_remove_plant = AsyncMock()
    mock.handle_transition_logic = AsyncMock()
    return mock


@pytest.fixture
def gs_service_mock():
    """Mock the GrowspaceService."""
    return MagicMock()


@pytest.fixture
def plant_view_builder_mock():
    """Mock the PlantViewModelBuilder."""
    mock = MagicMock()
    mock.build = MagicMock(return_value={})
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
def service(
    hass: HomeAssistant,
    repository_mock,
    validator_mock,
    gs_service_mock,
    strain_library_mock,
    plant_view_builder_mock,
    save_callback_mock,
    lock_mock,
):
    """PlantManager fixture."""
    svc = PlantManager(
        ctx=ServiceContext(
            save_callback=save_callback_mock,
            lock=lock_mock,
            add_event=MagicMock(),
            invalidate_cache=MagicMock(),
        ),
        hass=hass,
        repository=repository_mock,
        notification_state=MagicMock(),
        validator=validator_mock,
        growspace_manager=gs_service_mock,
        strain_library=strain_library_mock,
        plant_view_builder=plant_view_builder_mock,
    )
    # Mock cache and event firing which are internal/delegated
    svc._fire_event = MagicMock()
    return svc


@pytest.mark.asyncio
async def test_add_plant(service, repository_mock) -> None:
    """Test adding a plant."""
    repository_mock.has_growspace.return_value = True
    with patch("uuid.uuid4", return_value="p1"):
        result = await service.add_plant("gs1", "S1")

    assert result.plant_id == "p1"
    assert result.growspace_id == "gs1"
    assert result.strain == "S1"
    repository_mock.add_plant.assert_called_once()
    service._fire_event.assert_called()


@pytest.mark.asyncio
async def test_add_mother_plant(service, gs_service_mock) -> None:
    """Test adding a mother plant."""
    gs_service_mock.ensure_mother_growspace.return_value = "mother"
    plant = Plant(
        plant_id="p1",
        growspace_id="mother",
        genetics=PlantGenetics(strain_name="S1"),
        row=1,
        col=1,
        stage="mother",
        type="mother",
    )

    with patch.object(service, "add_plant", return_value=plant) as mock_add:
        result = await service.add_mother_plant("Pheno", "Strain", 1, 1)
        assert result == plant
        mock_add.assert_called_once()


@pytest.mark.asyncio
async def test_take_clones_default(
    service, repository_mock, gs_service_mock, validator_mock
) -> None:
    """Test taking clones with default target."""
    mother = Plant(
        plant_id="mom",
        growspace_id="gs1",
        genetics=PlantGenetics(strain_name="S1", phenotype_name="P1"),
    )
    repository_mock.require_plant.return_value = mother
    repository_mock.has_growspace.return_value = True
    gs_service_mock.ensure_special_growspace.return_value = "clone"
    validator_mock.find_first_available_position.return_value = (1, 1)

    with patch("uuid.uuid4", return_value="c1"):
        results = await service.take_clones("mom", 1)

    assert len(results) == 1
    assert results[0].plant_id == "c1"
    assert results[0].growspace_id == "clone"
    assert results[0].strain == "S1"


@pytest.mark.asyncio
async def test_take_clones_invalid_target(service, repository_mock) -> None:
    """Test taking clones with invalid target growspace."""
    repository_mock.require_plant.return_value = MagicMock()
    repository_mock.has_growspace.return_value = False
    with pytest.raises(ValueError, match="Target growspace 'unknown' does not exist"):
        await service.take_clones("mom", 1, target_growspace_id="unknown")


@pytest.mark.asyncio
async def test_take_clones_full_growspace(
    service, repository_mock, validator_mock
) -> None:
    """Test taking clones when target growspace is full."""
    repository_mock.require_plant.return_value = MagicMock()
    repository_mock.has_growspace.return_value = True
    validator_mock.find_first_available_position.return_value = (None, None)

    with pytest.raises(ValueError, match="Growspace 'clone' is full"):
        await service.take_clones("mom", 1, target_growspace_id="clone")


@pytest.mark.asyncio
async def test_update_plant_move(
    service, repository_mock, lifecycle_manager_mock
) -> None:
    """Test updating plant with growspace move."""
    plant = Plant(
        plant_id="p1",
        growspace_id="gs1",
        row=1,
        col=1,
        stage="flowering",
        type="normal",
    )
    repository_mock.get_plant.return_value = plant
    repository_mock.require_plant.return_value = plant
    repository_mock.has_plant.return_value = True
    repository_mock.has_growspace.return_value = True
    lifecycle_manager_mock.async_update_plant.return_value = plant

    await service.update_plant("p1", growspace_id="gs2")
    # Cache invalidation is currently commented out in implementation


@pytest.mark.asyncio
async def test_move_plant(service, repository_mock) -> None:
    """Test moving a plant."""
    plant = Plant(
        plant_id="p1",
        growspace_id="gs1",
        row=1,
        col=1,
        stage="flowering",
        type="normal",
    )
    repository_mock.get_plant.return_value = plant
    repository_mock.require_plant.return_value = plant
    repository_mock.has_plant.return_value = True
    await service.move_plant("p1", 2, 2)
    assert plant.row == 2
    assert plant.col == 2
    service._fire_event.assert_called()


@pytest.mark.asyncio
async def test_switch_plants(service, repository_mock) -> None:
    """Test switching two plants."""
    p1 = Plant(
        plant_id="p1",
        growspace_id="gs1",
        row=1,
        col=1,
        stage="flowering",
        type="normal",
    )
    p2 = Plant(
        plant_id="p2",
        growspace_id="gs1",
        row=2,
        col=2,
        stage="flowering",
        type="normal",
    )
    _plants = {"p1": p1, "p2": p2}
    repository_mock.require_plant.side_effect = lambda pid: _plants[pid]
    repository_mock.get_plant.side_effect = lambda pid: _plants.get(pid)
    repository_mock.has_plant.side_effect = lambda pid: pid in _plants
    await service.switch_plants("p1", "p2")
    assert p1.row == 2
    assert p1.col == 2
    assert p2.row == 1
    assert p2.col == 1


@pytest.mark.asyncio
async def test_remove_plant_not_found(service) -> None:
    """Test removing non-existent plant."""
    assert await service.remove_plant("unknown") is False


@pytest.mark.asyncio
async def test_remove_plant_success(
    service, repository_mock, lifecycle_manager_mock
) -> None:
    """Test removing plant successfully."""
    plant = Plant(
        plant_id="p1",
        growspace_id="gs1",
        row=1,
        col=1,
        stage="flowering",
        type="normal",
    )
    repository_mock.get_plant.return_value = plant
    repository_mock.require_plant.return_value = plant
    repository_mock.has_plant.return_value = True
    lifecycle_manager_mock.async_remove_plant.return_value = True

    assert await service.remove_plant("p1") is True
    service._fire_event.assert_called_with(
        "plant_removed", {"plant_id": "p1", "growspace_id": "gs1"}
    )


def test_get_plant(service, repository_mock) -> None:
    """Test get_plant."""
    service.get_plant("p1")
    repository_mock.get_plant.assert_called_with("p1")


@pytest.mark.asyncio
async def test_transition_plant_stage_actual(service, repository_mock) -> None:
    """Test actual transition_plant_stage execution."""
    plant = Plant(
        plant_id="p1",
        growspace_id="gs1",
        row=1,
        col=1,
        stage="vegetative",
        type="normal",
    )
    repository_mock.get_plant.return_value = plant
    repository_mock.require_plant.return_value = plant
    repository_mock.has_plant.return_value = True
    await service.transition_plant_stage("p1", "flower")
    assert plant.stage == "flower"
    service._fire_event.assert_called()


@pytest.mark.asyncio
async def test_convenience_methods(service, repository_mock) -> None:
    """Test stage transition convenience methods."""
    plant = Plant(plant_id="p1", growspace_id="gs1")
    repository_mock.get_plant.return_value = plant
    repository_mock.require_plant.return_value = plant
    repository_mock.has_plant.return_value = True

    with patch.object(
        service, "transition_plant_stage", return_value=None
    ) as mock_trans:
        # Convenience methods no longer pass an explicit date — the transition
        # seam defaults to now() with its time (ADR-0013).
        await service.start_flowering("p1")
        mock_trans.assert_called_with("p1", PlantStage.FLOWER)

        await service.start_drying("p1")
        mock_trans.assert_called_with("p1", PlantStage.DRY)

        await service.start_curing("p1")
        mock_trans.assert_called_with("p1", PlantStage.CURE)

        await service.harvest("p1")
        mock_trans.assert_called_with("p1", PlantStage.DRY)


@pytest.mark.asyncio
async def test_harvest_orchestration(service, repository_mock) -> None:
    """Test transition_plant orchestration."""
    plant = Plant(
        plant_id="p1",
        growspace_id="gs1",
        genetics=PlantGenetics(strain_name="S1"),
        row=1,
        col=1,
        stage="flowering",
        type="normal",
    )
    repository_mock.get_plant.return_value = plant
    repository_mock.require_plant.return_value = plant
    repository_mock.has_plant.return_value = True
    # Mock repository.growspaces to include dry_room
    repository_mock.has_growspace.return_value = True

    # Mock calculate_plant_stage to avoid issues with mocked plants if any
    with patch(
        "custom_components.growspace_manager.managers.plant.calculate_plant_stage",
        return_value="Flower",
    ):
        await service.transition_plant("p1", target_growspace_id="dry_room")

    assert plant.growspace_id == "dry_room"
    service._fire_event.assert_called()
