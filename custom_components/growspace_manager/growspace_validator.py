"""Validation logic for Growspace Manager."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .const import PlantStage
from .exceptions import (
    GrowspaceNotFoundError,
    PlantNotFoundError,
    ValidationChangeError,
)

if TYPE_CHECKING:
    from .data_access.growspace_repository import GrowspaceRepository

from .utils import find_first_free_position

_LOGGER = logging.getLogger(__name__)


class GrowspaceValidator:
    """Validates growspace and plant operations."""

    def __init__(self, repository: GrowspaceRepository) -> None:
        """Initialize the GrowspaceValidator.

        Args:
            repository: The data repository.
        """
        self.repository = repository

    def validate_growspace_exists(self, growspace_id: str) -> None:
        """Validate that a growspace exists in the repository."""
        if growspace_id not in self.repository.growspaces:
            raise GrowspaceNotFoundError(f"Growspace {growspace_id} does not exist")

    def validate_plant_exists(self, plant_id: str) -> None:
        """Validate that a plant exists in the repository."""
        if plant_id not in self.repository.plants:
            raise PlantNotFoundError(f"Plant {plant_id} does not exist")

    def validate_position_bounds(self, growspace_id: str, row: int, col: int) -> None:
        """Validate that a position is within the bounds of a growspace grid."""
        growspace = self.repository.growspaces[growspace_id]

        # Skip boundary check for special growspaces
        if growspace_id in [
            PlantStage.MOTHER,
            PlantStage.CLONE,
            PlantStage.DRY,
            PlantStage.CURE,
        ]:
            return

        max_rows = int(growspace.rows)
        max_cols = int(growspace.plants_per_row)

        if row < 1 or row > max_rows:
            raise ValidationChangeError(
                f"Row {row} is outside growspace bounds (1-{max_rows})"
            )
        if col < 1 or col > max_cols:
            raise ValidationChangeError(
                f"Column {col} is outside growspace bounds (1-{max_cols})"
            )

    def validate_position_not_occupied(
        self,
        growspace_id: str,
        row: int,
        col: int,
        exclude_plant_id: str | None = None,
    ) -> None:
        """Validate that a grid position is not already occupied by another plant."""
        # We need to access get_growspace_plants from coordinator or implement it here
        # Implementing it here might be better to avoid circular dependency on method
        # But accessing coordinator.plants is fine.

        existing_plants = [
            p for p in self.repository.plants.values() if p.growspace_id == growspace_id
        ]

        for existing_plant in existing_plants:
            if (
                existing_plant.plant_id != exclude_plant_id
                and existing_plant.row == row
                and existing_plant.col == col
            ):
                raise ValidationChangeError(
                    f"Position ({row},{col}) is already occupied by {existing_plant.strain}"
                )

    def find_first_available_position(
        self, growspace_id: str
    ) -> tuple[int | None, int | None]:
        """Find the first available (row, col) position in a growspace."""
        growspace = self.repository.growspaces[growspace_id]
        occupied = {
            (p.row, p.col)
            for p in self.repository.plants.values()
            if p.growspace_id == growspace_id
        }
        return find_first_free_position(growspace, occupied)

    def validate_plants_after_resize(
        self, growspace_id: str, new_rows: int, new_plants_per_row: int
    ) -> None:
        """Log warnings for plants outside new grid boundaries after resize.

        Args:
            growspace_id: The ID of the growspace that was resized
            new_rows: The new number of rows
            new_plants_per_row: The new number of plants per row
        """
        # Get all plants in this growspace
        plants_to_check = [
            p for p in self.repository.plants.values() if p.growspace_id == growspace_id
        ]

        # Find plants outside new boundaries
        invalid_plants = [
            plant
            for plant in plants_to_check
            if int(plant.row) > new_rows or int(plant.col) > new_plants_per_row
        ]

        if invalid_plants:
            _LOGGER.warning(
                "Growspace %s resized to %dx%d. Found %d plants outside new grid boundaries:",
                growspace_id,
                new_rows,
                new_plants_per_row,
                len(invalid_plants),
            )

            for plant in invalid_plants:
                _LOGGER.warning(
                    "  - Plant %s (%s) at position (%d,%d) is outside new grid",
                    plant.plant_id,
                    plant.strain,
                    plant.row,
                    plant.col,
                )

            _LOGGER.warning(
                "Please update these plants' positions manually or they may not display correctly"
            )
