"""Tests for GrowspaceValidator."""

from unittest.mock import MagicMock

from .common import create_plant
import pytest

from custom_components.growspace_manager.const import PlantStage
from custom_components.growspace_manager.exceptions import (
    GrowspaceNotFoundError,
    PlantNotFoundError,
    ValidationChangeError,
)
from custom_components.growspace_manager.growspace_validator import GrowspaceValidator
from custom_components.growspace_manager.models import Growspace


@pytest.fixture
def mock_coordinator():
    coordinator = MagicMock()
    coordinator.growspaces = {}
    coordinator.plants = {}
    return coordinator


@pytest.fixture
def validator(mock_coordinator):
    return GrowspaceValidator(mock_coordinator)


def test_validate_growspace_exists(validator, mock_coordinator) -> None:
    """Test validate_growspace_exists."""
    mock_coordinator.growspaces = {"g1": MagicMock()}
    validator.validate_growspace_exists("g1")

    with pytest.raises(GrowspaceNotFoundError):
        validator.validate_growspace_exists("g2")


def test_validate_plant_exists(validator, mock_coordinator) -> None:
    """Test validate_plant_exists."""
    mock_coordinator.plants = {"p1": MagicMock()}
    validator.validate_plant_exists("p1")

    with pytest.raises(PlantNotFoundError):
        validator.validate_plant_exists("p2")


def test_validate_position_bounds(validator, mock_coordinator) -> None:
    """Test validate_position_bounds."""
    gs = Growspace(id="g1", name="G1", rows=2, plants_per_row=3)
    mock_coordinator.growspaces = {"g1": gs}

    # Valid
    validator.validate_position_bounds("g1", 1, 1)
    validator.validate_position_bounds("g1", 2, 3)

    # Invalid
    with pytest.raises(ValidationChangeError):
        validator.validate_position_bounds("g1", 0, 1)
    with pytest.raises(ValidationChangeError):
        validator.validate_position_bounds("g1", 3, 1)
    with pytest.raises(ValidationChangeError):
        validator.validate_position_bounds("g1", 1, 0)
    with pytest.raises(ValidationChangeError):
        validator.validate_position_bounds("g1", 1, 4)


def test_validate_position_bounds_special(validator, mock_coordinator) -> None:
    """Test validate_position_bounds for special growspaces (covers line 46)."""
    gs = Growspace(id=PlantStage.MOTHER, name="Mother", rows=1, plants_per_row=1)
    mock_coordinator.growspaces = {PlantStage.MOTHER: gs}

    # Special growspaces skip bounds check
    validator.validate_position_bounds(PlantStage.MOTHER, 99, 99)


def test_validate_position_not_occupied(validator, mock_coordinator) -> None:
    """Test validate_position_not_occupied."""
    p1 = create_plant(plant_id="p1", growspace_id="g1", row=1, col=1, strain="A")
    mock_coordinator.plants = {"p1": p1}

    # Not occupied
    validator.validate_position_not_occupied("g1", 1, 2)
    validator.validate_position_not_occupied("g1", 2, 1)

    # Occupied
    with pytest.raises(ValidationChangeError):
        validator.validate_position_not_occupied("g1", 1, 1)

    # Occupied by self (exclude_plant_id)
    validator.validate_position_not_occupied("g1", 1, 1, exclude_plant_id="p1")


def test_find_first_available_position(validator, mock_coordinator) -> None:
    """Test find_first_available_position."""
    gs = Growspace(id="g1", name="G1", rows=2, plants_per_row=2)
    mock_coordinator.growspaces = {"g1": gs}
    mock_coordinator.plants = {
        "p1": create_plant(plant_id="p1", growspace_id="g1", row=1, col=1, strain="A")
    }

    assert validator.find_first_available_position("g1") == (1, 2)


def test_validate_plants_after_resize_no_invalid(
    validator, mock_coordinator, caplog
) -> None:
    """Test validate_plants_after_resize with no invalid plants."""
    p1 = create_plant(plant_id="p1", growspace_id="g1", row=1, col=1, strain="A")
    mock_coordinator.plants = {"p1": p1}

    # All within bounds (2x2)
    validator.validate_plants_after_resize("g1", 2, 2)

    # Verify no warnings logged
    assert "Found 0 plants outside new grid boundaries" not in caplog.text


def test_validate_plants_after_resize_with_invalid(
    validator, mock_coordinator, caplog
) -> None:
    """Test validate_plants_after_resize with invalid plants."""
    p1 = create_plant(plant_id="p1", growspace_id="g1", row=3, col=1, strain="A")
    p2 = create_plant(plant_id="p2", growspace_id="g1", row=1, col=3, strain="B")
    p3 = create_plant(plant_id="p3", growspace_id="g1", row=1, col=1, strain="C")
    mock_coordinator.plants = {"p1": p1, "p2": p2, "p3": p3}

    # p1 and p2 are outside 2x2 grid
    validator.validate_plants_after_resize("g1", 2, 2)

    # Verify warnings logged
    assert "Found 2 plants outside new grid boundaries" in caplog.text
    assert "Plant p1 (A) at position (3,1) is outside new grid" in caplog.text
    assert "Plant p2 (B) at position (1,3) is outside new grid" in caplog.text
    assert (
        "Please update these plants' positions manually or they may not display correctly"
        in caplog.text
    )
