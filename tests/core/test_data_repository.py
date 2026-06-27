"""Tests for the Growspace Manager DataRepository."""

import pytest

from custom_components.growspace_manager.data_access.growspace_repository import (
    GrowspaceRepository as DataRepository,
)
from custom_components.growspace_manager.models import Growspace

from .common import create_plant


@pytest.fixture
def mock_growspaces():
    """Return specific growspaces for testing."""
    return {
        "gs1": Growspace(id="gs1", name="Growspace 1", rows=2, plants_per_row=2),
        "gs2": Growspace(id="gs2", name="Growspace 2", rows=1, plants_per_row=1),
    }


@pytest.fixture
def mock_plants():
    """Return specific plants for testing."""
    return {
        "p1": create_plant(plant_id="p1", growspace_id="gs1", strain="Plant 1"),
        "p2": create_plant(plant_id="p2", growspace_id="gs1", strain="Plant 2"),
        "p3": create_plant(plant_id="p3", growspace_id="gs2", strain="Plant 3"),
    }


def test_initialization() -> None:
    """Test repository initialization."""
    repo = DataRepository()
    assert repo.get_all_plants() == []
    assert repo.get_all_growspaces() == []

    plants = {"p1": create_plant(plant_id="p1", growspace_id="gs1", strain="Plant 1")}
    growspaces = {"gs1": Growspace(id="gs1", name="Growspace 1")}
    repo_init = DataRepository()
    repo_init.load_growspaces(growspaces)
    repo_init.load_plants(plants)
    assert len(repo_init.get_all_plants()) == 1
    assert len(repo_init.get_all_growspaces()) == 1


def test_load_data(mock_growspaces, mock_plants) -> None:
    """Test loading data into the repository."""
    repo = DataRepository()
    repo.load_growspaces(mock_growspaces)
    repo.load_plants(mock_plants)
    assert len(repo.get_all_plants()) == 3
    assert len(repo.get_all_growspaces()) == 2


def test_get_plant(mock_plants) -> None:
    """Test retrieving a single plant."""
    repo = DataRepository()
    repo.load_plants(mock_plants)
    assert repo.get_plant("p1") == mock_plants["p1"]
    assert repo.get_plant("nonexistent") is None


def test_get_growspace(mock_growspaces) -> None:
    """Test retrieving a single growspace."""
    repo = DataRepository()
    repo.load_growspaces(mock_growspaces)
    assert repo.get_growspace("gs1") == mock_growspaces["gs1"]
    assert repo.get_growspace("nonexistent") is None


def test_get_growspace_plants(mock_growspaces, mock_plants) -> None:
    """Test retrieving plants for a specific growspace."""
    repo = DataRepository()
    repo.load_growspaces(mock_growspaces)
    repo.load_plants(mock_plants)
    gs1_plants = repo.get_growspace_plants("gs1")
    assert len(gs1_plants) == 2
    assert {p.plant_id for p in gs1_plants} == {"p1", "p2"}

    gs2_plants = repo.get_growspace_plants("gs2")
    assert len(gs2_plants) == 1
    assert gs2_plants[0].plant_id == "p3"

    empty_plants = repo.get_growspace_plants("nonexistent")
    assert empty_plants == []


def test_get_growspace_grid(mock_growspaces, mock_plants) -> None:
    """Test generating a growspace grid."""
    repo = DataRepository()
    repo.load_growspaces(mock_growspaces)
    repo.load_plants(mock_plants)

    # Test valid grid generation
    grid = repo.get_growspace_grid("gs1")
    # gs1 is 2x2, should have 2 rows
    assert len(grid) == 2
    # Check that it calls generate_growspace_grid logic (just structural check here)
    assert isinstance(grid, list)

    # Test nonexistent growspace handling
    # The current implementation raises KeyError if growspace doesn't exist in _growspaces
    with pytest.raises(KeyError):
        repo.get_growspace_grid("nonexistent")


def test_get_growspace_options(mock_growspaces) -> None:
    """Test retrieving growspace options."""
    repo = DataRepository()
    repo.load_growspaces(mock_growspaces)
    options = repo.get_growspace_options()
    assert options == {"gs1": "Growspace 1", "gs2": "Growspace 2"}


def test_get_sorted_growspace_options() -> None:
    """Test retrieving sorted growspace options."""
    unordered_gs = {
        "b": Growspace(id="b", name="Zebra"),
        "a": Growspace(id="a", name="Apple"),
    }
    repo = DataRepository()
    repo.load_growspaces(unordered_gs)
    sorted_options = repo.get_sorted_growspace_options()
    assert sorted_options == [("a", "Apple"), ("b", "Zebra")]
