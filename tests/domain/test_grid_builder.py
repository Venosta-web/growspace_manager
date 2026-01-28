"""Tests for grid_builder domain logic."""

from custom_components.growspace_manager.domain.grid_builder import (
    build_position_grid,
    get_grid_dimensions,
    get_total_positions,
    is_position_valid,
)
from custom_components.growspace_manager.models import Growspace, Plant


def test_get_grid_dimensions():
    """Test extracting dimensions from growspace."""
    gs = Growspace(id="test", name="Test GS", rows=3, plants_per_row=4)
    assert get_grid_dimensions(gs) == (3, 4)


def test_get_total_positions():
    """Test calculating total positions."""
    gs = Growspace(id="test", name="Test GS", rows=3, plants_per_row=4)
    assert get_total_positions(gs) == 12


def test_is_position_valid():
    """Test position validation logic."""
    gs = Growspace(id="test", name="Test GS", rows=2, plants_per_row=2)

    # Valid positions
    assert is_position_valid(gs, 1, 1) is True
    assert is_position_valid(gs, 1, 2) is True
    assert is_position_valid(gs, 2, 1) is True
    assert is_position_valid(gs, 2, 2) is True

    # Invalid positions (boundaries)
    assert is_position_valid(gs, 0, 1) is False
    assert is_position_valid(gs, 1, 0) is False
    assert is_position_valid(gs, 3, 1) is False
    assert is_position_valid(gs, 1, 3) is False
    assert is_position_valid(gs, -1, 1) is False


def test_build_position_grid_empty():
    """Test building grid with no plants."""
    gs = Growspace(id="test", name="Test GS", rows=2, plants_per_row=2)
    grid = build_position_grid(gs, [])

    assert len(grid) == 4
    assert grid == {
        "position_1_1": None,
        "position_1_2": None,
        "position_2_1": None,
        "position_2_2": None,
    }


def test_build_position_grid_with_plants():
    """Test building grid with plants assigned to positions."""
    gs = Growspace(id="test", name="Test GS", rows=2, plants_per_row=2)
    p1 = Plant(plant_id="p1", growspace_id="test", row=1, col=1)
    p2 = Plant(plant_id="p2", growspace_id="test", row=2, col=2)

    grid = build_position_grid(gs, [p1, p2])

    assert len(grid) == 4
    assert grid["position_1_1"] == "p1"
    assert grid["position_1_2"] is None
    assert grid["position_2_1"] is None
    assert grid["position_2_2"] == "p2"


def test_build_position_grid_string_dimensions():
    """Test building grid when dimensions are stored as strings (migration cases)."""
    # Note: Growspace model __pre_deserialize__ converts them to int,
    # but the function uses int() to be safe.
    gs = Growspace(id="test", name="Test GS", rows="2", plants_per_row="3")  # type: ignore
    grid = build_position_grid(gs, [])
    assert len(grid) == 6
    assert "position_1_1" in grid
    assert "position_2_3" in grid
