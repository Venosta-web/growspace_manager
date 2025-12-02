"""Validation logic for Growspace Manager."""

from __future__ import annotations

from .utils import find_first_free_position


class GrowspaceValidator:
    """Validates growspace and plant operations."""

    def __init__(self, coordinator) -> None:
        """Initialize the GrowspaceValidator.

        Args:
            coordinator: The GrowspaceCoordinator instance.
        """
        self.coordinator = coordinator

    def validate_growspace_exists(self, growspace_id: str) -> None:
        """Validate that a growspace exists in the coordinator."""
        if growspace_id not in self.coordinator.growspaces:
            raise ValueError(f"Growspace {growspace_id} does not exist")

    def validate_plant_exists(self, plant_id: str) -> None:
        """Validate that a plant exists in the coordinator."""
        if plant_id not in self.coordinator.plants:
            raise ValueError(f"Plant {plant_id} does not exist")

    def validate_position_bounds(self, growspace_id: str, row: int, col: int) -> None:
        """Validate that a position is within the bounds of a growspace grid."""
        growspace = self.coordinator.growspaces[growspace_id]

        # Skip boundary check for special growspaces
        if growspace_id in ["mother", "clone", "dry", "cure"]:
            return

        max_rows = int(growspace.rows)
        max_cols = int(growspace.plants_per_row)

        if row < 1 or row > max_rows:
            raise ValueError(f"Row {row} is outside growspace bounds (1-{max_rows})")
        if col < 1 or col > max_cols:
            raise ValueError(f"Column {col} is outside growspace bounds (1-{max_cols})")

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
            p for p in self.coordinator.plants.values()
            if p.growspace_id == growspace_id
        ]

        for existing_plant in existing_plants:
            if (
                existing_plant.plant_id != exclude_plant_id
                and existing_plant.row == row
                and existing_plant.col == col
            ):
                raise ValueError(
                    f"Position ({row},{col}) is already occupied by {existing_plant.strain}"
                )

    def find_first_available_position(self, growspace_id: str) -> tuple[int, int]:
        """Find the first available (row, col) position in a growspace."""
        growspace = self.coordinator.growspaces[growspace_id]
        occupied = {
            (p.row, p.col)
            for p in self.coordinator.plants.values()
            if p.growspace_id == growspace_id
        }
        return find_first_free_position(growspace, occupied)
