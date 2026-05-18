"""Tests for the data access layer."""

from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.data_access.growspace_repository import (
    GrowspaceRepository,
)
from custom_components.growspace_manager.models import Growspace, Plant


@pytest.fixture
def repository():
    """Fixture for GrowspaceRepository."""
    return GrowspaceRepository()


def test_growspace_repository_init() -> None:
    """Test repository initializes empty."""
    repo = GrowspaceRepository()
    assert repo.get_all_growspaces() == []
    assert repo.get_all_plants() == []


def test_growspace_repository_load_growspaces(repository) -> None:
    """Test bulk-loading growspaces via load_growspaces."""
    gs = MagicMock(spec=Growspace)
    gs.id = "gs1"
    repository.load_growspaces({"gs1": gs})
    assert repository.get_growspace("gs1") is gs


def test_growspace_repository_load_plants(repository) -> None:
    """Test bulk-loading plants via load_plants."""
    plant = MagicMock(spec=Plant)
    plant.plant_id = "p1"
    repository.load_plants({"p1": plant})
    assert repository.get_plant("p1") is plant


def test_plant_operations(repository) -> None:
    """Test plant-related operations."""
    plant = MagicMock(spec=Plant)
    plant.plant_id = "p1"

    repository.add_plant(plant)
    assert repository.get_plant("p1") == plant
    assert repository.get_all_plants() == [plant]

    removed = repository.remove_plant("p1")
    assert removed == plant
    assert repository.get_plant("p1") is None


def test_growspace_operations(repository) -> None:
    """Test growspace-related operations."""
    gs = MagicMock(spec=Growspace)
    gs.id = "gs1"

    repository.add_growspace(gs)
    assert repository.get_growspace("gs1") == gs
    assert repository.get_all_growspaces() == [gs]

    removed = repository.remove_growspace("gs1")
    assert removed == gs
    assert repository.get_growspace("gs1") is None


def test_query_methods(repository) -> None:
    """Test repository query methods."""
    gs = MagicMock(spec=Growspace)
    gs.id = "gs1"
    gs.name = "Test GS"
    gs.rows = 2
    gs.plants_per_row = 2

    plant = MagicMock(spec=Plant)
    plant.plant_id = "p1"
    plant.growspace_id = "gs1"
    plant.row = 1
    plant.col = 1

    repository.add_growspace(gs)
    repository.add_plant(plant)

    assert repository.get_growspace_plants("gs1") == [plant]

    # Test grid generation
    grid = repository.get_growspace_grid("gs1")
    assert len(grid) == 2
    assert len(grid[0]) == 2
    assert grid[0][0] == "p1"

    # Test grid for non-existent growspace
    with pytest.raises(KeyError):
        repository.get_growspace_grid("invalid")

    # Test options
    assert repository.get_growspace_options() == {"gs1": "Test GS"}
    assert repository.get_sorted_growspace_options() == [("gs1", "Test GS")]


def test_sorted_growspace_options(repository) -> None:
    """Test sorting of growspace options."""
    gs1 = MagicMock(spec=Growspace)
    gs1.id = "gs1"
    gs1.name = "B"

    gs2 = MagicMock(spec=Growspace)
    gs2.id = "gs2"
    gs2.name = "A"

    repository.add_growspace(gs1)
    repository.add_growspace(gs2)

    sorted_opts = repository.get_sorted_growspace_options()
    assert sorted_opts == [("gs2", "A"), ("gs1", "B")]
