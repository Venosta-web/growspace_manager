"""Tests for GrowspaceValidator."""

import pytest

from custom_components.growspace_manager.const import PlantStage
from custom_components.growspace_manager.data_access.growspace_repository import (
    GrowspaceRepository,
)
from custom_components.growspace_manager.exceptions import (
    GrowspaceNotFoundError,
    PlantNotFoundError,
    ValidationChangeError,
)
from custom_components.growspace_manager.growspace_validator import GrowspaceValidator
from custom_components.growspace_manager.models import Growspace

from .common import create_plant


@pytest.fixture
def repo() -> GrowspaceRepository:
    return GrowspaceRepository()


@pytest.fixture
def validator(repo: GrowspaceRepository) -> GrowspaceValidator:
    return GrowspaceValidator(repo)


def test_validate_growspace_exists(validator, repo) -> None:
    """Test validate_growspace_exists."""
    repo.add_growspace(Growspace(id="g1", name="G1"))
    validator.validate_growspace_exists("g1")

    with pytest.raises(GrowspaceNotFoundError):
        validator.validate_growspace_exists("g2")


def test_validate_plant_exists(validator, repo) -> None:
    """Test validate_plant_exists."""
    repo.add_plant(create_plant(plant_id="p1", growspace_id="g1", strain="A"))
    validator.validate_plant_exists("p1")

    with pytest.raises(PlantNotFoundError):
        validator.validate_plant_exists("p2")


def test_validate_position_bounds(validator, repo) -> None:
    """Test validate_position_bounds."""
    repo.add_growspace(Growspace(id="g1", name="G1", rows=2, plants_per_row=3))

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


def test_validate_position_bounds_special(validator, repo) -> None:
    """Test validate_position_bounds for special growspaces (covers line 46)."""
    repo.add_growspace(
        Growspace(id=PlantStage.MOTHER, name="Mother", rows=1, plants_per_row=1)
    )

    # Special growspaces skip bounds check
    validator.validate_position_bounds(PlantStage.MOTHER, 99, 99)


def test_validate_position_not_occupied(validator, repo) -> None:
    """Test validate_position_not_occupied."""
    p1 = create_plant(plant_id="p1", growspace_id="g1", row=1, col=1, strain="A")
    repo.add_plant(p1)

    # Not occupied
    validator.validate_position_not_occupied("g1", 1, 2)
    validator.validate_position_not_occupied("g1", 2, 1)

    # Occupied
    with pytest.raises(ValidationChangeError):
        validator.validate_position_not_occupied("g1", 1, 1)

    # Occupied by self (exclude_plant_id)
    validator.validate_position_not_occupied("g1", 1, 1, exclude_plant_id="p1")


def test_find_first_available_position(validator, repo) -> None:
    """Test find_first_available_position."""
    repo.add_growspace(Growspace(id="g1", name="G1", rows=2, plants_per_row=2))
    repo.add_plant(
        create_plant(plant_id="p1", growspace_id="g1", row=1, col=1, strain="A")
    )

    assert validator.find_first_available_position("g1") == (1, 2)


@pytest.mark.parametrize(
    "growspace_id",
    [PlantStage.MOTHER, PlantStage.CLONE, PlantStage.DRY, PlantStage.CURE],
)
def test_special_growspaces_accept_positions_outside_grid(
    validator, repo, growspace_id
) -> None:
    """Every special growspace bypasses the ordinary grid boundary check."""
    repo.add_growspace(
        Growspace(id=growspace_id, name=str(growspace_id), rows=1, plants_per_row=1)
    )

    validator.validate_position_bounds(growspace_id, -1, 99)


def test_occupied_position_excludes_only_the_named_plant(validator, repo) -> None:
    """Excluding a moving plant must not hide another plant in the target cell."""
    repo.add_plant(create_plant(plant_id="moving", growspace_id="g1", row=2, col=2))
    repo.add_plant(
        create_plant(plant_id="occupant", growspace_id="g1", row=1, col=1, strain="B")
    )

    with pytest.raises(ValidationChangeError, match=r"Position \(1,1\).*B"):
        validator.validate_position_not_occupied("g1", 1, 1, exclude_plant_id="moving")


def test_find_first_available_position_when_grid_is_full(validator, repo) -> None:
    """A full grid returns the utility's documented last-cell fallback."""
    repo.add_growspace(Growspace(id="g1", name="G1", rows=1, plants_per_row=1))
    repo.add_plant(create_plant(plant_id="p1", growspace_id="g1", row=1, col=1))

    assert validator.find_first_available_position("g1") == (1, 1)
