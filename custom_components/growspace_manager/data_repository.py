"""Data Access Repository for Growspace Manager.

This module encapsulates data retrieval logic to reduce the complexity
of the GrowspaceCoordinator monolithic class.
"""

from __future__ import annotations

from .models import Growspace, Plant
from .utils import generate_growspace_grid


class DataRepository:
    """Repository for accessing Growspace and Plant data."""

    def __init__(
        self,
        growspaces: dict[str, Growspace] | None = None,
        plants: dict[str, Plant] | None = None,
    ) -> None:
        """Initialize the DataRepository."""
        self._growspaces: dict[str, Growspace] = growspaces or {}
        self._plants: dict[str, Plant] = plants or {}

    def load_data(
        self, growspaces: dict[str, Growspace], plants: dict[str, Plant]
    ) -> None:
        """Update the repository with new data references."""
        self._growspaces = growspaces
        self._plants = plants

    def get_plant(self, plant_id: str) -> Plant | None:
        """Retrieve a plant by its ID."""
        return self._plants.get(plant_id)

    def get_all_plants(self) -> list[Plant]:
        """Retrieve all plants."""
        return list(self._plants.values())

    def get_growspace(self, growspace_id: str) -> Growspace | None:
        """Retrieve a growspace by its ID."""
        return self._growspaces.get(growspace_id)

    def get_all_growspaces(self) -> list[Growspace]:
        """Retrieve all growspaces."""
        return list(self._growspaces.values())

    def get_growspace_plants(self, growspace_id: str) -> list[Plant]:
        """Get all plants located in a specific growspace.

        Args:
            growspace_id: The ID of the growspace.

        Returns:
            A list of Plant objects.
        """
        return [
            plant
            for plant in self._plants.values()
            if plant.growspace_id == growspace_id
        ]

    def get_growspace_grid(self, growspace_id: str) -> list[list[str | None]]:
        """Generate a 2D grid representation of a growspace's plant layout.

        Args:
            growspace_id: The ID of the growspace.

        Returns:
            A list of lists representing the grid, with plant IDs or None.
        """
        growspace = self.get_growspace(growspace_id)
        if not growspace:
            # Consistent with previous behavior if accessed via key (KeyError)
            # or safer lookup. The original code used self.growspaces[growspace_id]
            # which raises KeyError. We mimic that if we want exact parity,
            # but let's return empty grid for now to be safe, or raise.
            # To match original logic:
            raise KeyError(growspace_id)

        plants = self.get_growspace_plants(growspace_id)
        return generate_growspace_grid(
            int(growspace.rows), int(growspace.plants_per_row), plants
        )

    def get_growspace_options(self) -> dict[str, str]:
        """Return growspaces for dropdown selection."""
        return {
            gs_id: getattr(gs, "name", gs_id) for gs_id, gs in self._growspaces.items()
        }

    def get_sorted_growspace_options(self) -> list[tuple[str, str]]:
        """Return a sorted list of growspaces for dropdown selection."""
        return sorted(
            (
                (gs_id, getattr(gs, "name", gs_id))
                for gs_id, gs in self._growspaces.items()
            ),
            key=lambda x: x[1].lower(),
        )
