"""Grid building logic - pure domain functions."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from custom_components.growspace_manager.models import Growspace, Plant


def build_position_grid(
    growspace: Growspace, plants: list[Plant]
) -> dict[str, str | None]:
    """Build a grid mapping positions to plant IDs.

    This is a pure function that creates position keys and maps them to plant IDs.
    It does NOT include entity lookups or other HA-specific data.

    Args:
        growspace: The growspace to build grid for.
        plants: List of plants in this growspace.

    Returns:
        Dictionary mapping position keys (e.g., "position_1_1") to plant IDs.
        Empty positions have None values.
    """
    grid: dict[str, str | None] = {}

    # Initialize all positions as empty
    for row in range(1, int(growspace.rows) + 1):
        for col in range(1, int(growspace.plants_per_row) + 1):
            position_key = f"position_{row}_{col}"
            grid[position_key] = None

    # Fill grid with plant IDs
    for plant in plants:
        row_i = int(plant.row)
        col_i = int(plant.col)
        position_key = f"position_{row_i}_{col_i}"
        grid[position_key] = plant.plant_id

    return grid


def get_grid_dimensions(growspace: Growspace) -> tuple[int, int]:
    """Get grid dimensions (rows, cols) for a growspace.

    Args:
        growspace: The growspace to get dimensions for.

    Returns:
        Tuple of (rows, plants_per_row).
    """
    return (int(growspace.rows), int(growspace.plants_per_row))


def get_total_positions(growspace: Growspace) -> int:
    """Calculate total number of positions in a growspace grid.

    Args:
        growspace: The growspace to calculate for.

    Returns:
        Total number of positions (rows * plants_per_row).
    """
    rows, plants_per_row = get_grid_dimensions(growspace)
    return rows * plants_per_row


def is_position_valid(growspace: Growspace, row: int, col: int) -> bool:
    """Check if a position is valid within the growspace grid.

    Args:
        growspace: The growspace to check against.
        row: Row number (1-indexed).
        col: Column number (1-indexed).

    Returns:
        True if position is valid, False otherwise.
    """
    rows, plants_per_row = get_grid_dimensions(growspace)
    return 1 <= row <= rows and 1 <= col <= plants_per_row
