"""Tests for alias methods in GrowspaceManager and PlantManager."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.managers.growspace import GrowspaceManager
from custom_components.growspace_manager.managers.plant import PlantManager
from custom_components.growspace_manager.models import PlantStage


@pytest.fixture
def mock_hass():
    return MagicMock()


@pytest.fixture
def mock_repository():
    repo = MagicMock()
    repo.growspaces = {}
    repo.plants = {}
    return repo


@pytest.fixture
def growspace_manager(mock_hass, mock_repository):
    mgr = GrowspaceManager(
        mock_hass,
        mock_repository,
        notification_state=MagicMock(),
        validator=MagicMock(),
        view_model_builder=MagicMock(),
        save_callback=AsyncMock(),
        lock=MagicMock()
    )
    # Define these as AsyncMocks so they can be awaited and asserted
    mgr.save_callback = AsyncMock()
    mgr.add_growspace = AsyncMock()
    mgr.remove_growspace = AsyncMock()
    mgr.update_growspace = AsyncMock()
    mgr.ensure_default_growspaces = AsyncMock()
    return mgr


@pytest.fixture
def plant_manager(mock_hass, mock_repository, growspace_manager):
    mgr = PlantManager(
        mock_hass,
        mock_repository,
        notification_state=MagicMock(),
        validator=MagicMock(),
        growspace_manager=growspace_manager,
        strain_library=MagicMock(),
        plant_view_builder=MagicMock(),
        save_callback=AsyncMock(),
        lock=MagicMock()
    )
    # Define These as AsyncMocks so they can be awaited and asserted
    mgr.add_plant = AsyncMock()
    mgr.move_plant = AsyncMock()
    mgr.take_clones = AsyncMock()
    mgr.transition_plant_stage = AsyncMock()
    mgr.update_plant = AsyncMock()
    mgr.remove_plant = AsyncMock()
    mgr.switch_plants = AsyncMock()
    mgr.harvest_plant = AsyncMock()  # Fixed: Added missing mock
    mgr.promote_clone = AsyncMock()  # Fixed: Added missing mock
    return mgr


async def test_growspace_manager_aliases(growspace_manager):
    """Test GrowspaceManager alias methods."""
    # async_add_growspace
    await growspace_manager.async_add_growspace(name="Test")
    growspace_manager.add_growspace.assert_called_once_with(name="Test")

    # async_remove_growspace
    await growspace_manager.async_remove_growspace("gs_1")
    growspace_manager.remove_growspace.assert_called_once_with("gs_1")

    # async_update_growspace
    await growspace_manager.async_update_growspace("gs_1", name="New Name")
    growspace_manager.update_growspace.assert_called_once_with("gs_1", name="New Name")

    # ensure_special_growspaces
    await growspace_manager.ensure_special_growspaces()
    growspace_manager.ensure_default_growspaces.assert_called_once()


async def test_plant_manager_aliases(plant_manager, growspace_manager):
    """Test PlantManager alias methods."""
    # add_mother_plant
    plant_manager.add_plant.reset_mock()
    await plant_manager.add_mother_plant(phenotype="OG", strain="Kush", row=0, col=0)
    plant_manager.add_plant.assert_called_once()

    # handle_move_plant
    plant_manager.move_plant.reset_mock()
    await plant_manager.handle_move_plant("p1", "gs2", 1, 1)
    plant_manager.move_plant.assert_called_once_with("p1", "gs2", 1, 1)

    # handle_take_clone
    plant_manager.take_clones.reset_mock()
    await plant_manager.handle_take_clone("p1", count=5)
    plant_manager.take_clones.assert_called_once()

    # handle_transition_plant_stage
    plant_manager.transition_plant_stage.reset_mock()
    await plant_manager.handle_transition_plant_stage("p1", PlantStage.FLOWER)
    plant_manager.transition_plant_stage.assert_called_once_with("p1", PlantStage.FLOWER)

    # handle_update_plant
    plant_manager.update_plant.reset_mock()
    await plant_manager.handle_update_plant("p1", note="Strong growth")
    plant_manager.update_plant.assert_called_once_with("p1", note="Strong growth")

    # PlantManager Aliases
    # async_move_plant
    plant_manager.move_plant.reset_mock()
    await plant_manager.async_move_plant("p1", "gs2")
    plant_manager.move_plant.assert_called_once_with("p1", "gs2")

    # async_transition_plant_stage
    plant_manager.transition_plant_stage.reset_mock()
    await plant_manager.async_transition_plant_stage("p1", "flowering")
    plant_manager.transition_plant_stage.assert_called_once_with("p1", "flowering")

    # async_harvest_plant
    plant_manager.harvest_plant.reset_mock()
    await plant_manager.async_harvest_plant("p1")
    plant_manager.harvest_plant.assert_called_once_with("p1")

    # async_switch_plants
    plant_manager.switch_plants.reset_mock()
    await plant_manager.async_switch_plants("p1", "p2")
    plant_manager.switch_plants.assert_called_once_with("p1", "p2")

    # async_take_clones
    plant_manager.take_clones.reset_mock()
    await plant_manager.async_take_clones("p1", 5)
    plant_manager.take_clones.assert_called_once_with("p1", 5)

    # async_promote_clone
    plant_manager.promote_clone.reset_mock()
    await plant_manager.async_promote_clone("c1")
    plant_manager.promote_clone.assert_called_once_with("c1")

    # GrowspaceManager Aliases
    # ensure_special_growspaces -> ensure_default_growspaces
    growspace_manager.ensure_default_growspaces.reset_mock()
    await growspace_manager.ensure_special_growspaces()
    growspace_manager.ensure_default_growspaces.assert_called_once()

    # handle_switch_plants
    plant_manager.switch_plants.reset_mock()
    await plant_manager.handle_switch_plants("p1", "p2")
    plant_manager.switch_plants.assert_called_once_with("p1", "p2")
