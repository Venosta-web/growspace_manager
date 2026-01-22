"""Data Access Repository for Growspace Manager.

This module encapsulates data retrieval and management logic to reduce the complexity
of the GrowspaceCoordinator monolithic class.
"""

from __future__ import annotations

from custom_components.growspace_manager.models import Growspace, Plant
from custom_components.growspace_manager.utils import generate_growspace_grid


class GrowspaceRepository:
    """Repository for accessing and managing Growspace and Plant data."""

    def __init__(
        self,
        growspaces: dict[str, Growspace] | None = None,
        plants: dict[str, Plant] | None = None,
    ) -> None:
        """Initialize the GrowspaceRepository."""
        self._growspaces: dict[str, Growspace] = (
            growspaces if growspaces is not None else {}
        )
        self._plants: dict[str, Plant] = plants if plants is not None else {}

    @property
    def growspaces(self) -> dict[str, Growspace]:
        """Return the growspaces dictionary."""
        return self._growspaces

    @growspaces.setter
    def growspaces(self, value: dict[str, Growspace]) -> None:
        """Set the growspaces dictionary."""
        self._growspaces = value

    @property
    def plants(self) -> dict[str, Plant]:
        """Return the plants dictionary."""
        return self._plants

    @plants.setter
    def plants(self, value: dict[str, Plant]) -> None:
        """Set the plants dictionary."""
        self._plants = value

    def load_data(
        self, growspaces: dict[str, Growspace], plants: dict[str, Plant]
    ) -> None:
        """Update the repository with new data references."""
        self._growspaces = growspaces
        self._plants = plants

    # =========================================================================
    # PLANT OPERATIONS
    # =========================================================================

    def get_plant(self, plant_id: str) -> Plant | None:
        """Retrieve a plant by its ID."""
        return self._plants.get(plant_id)

    def get_all_plants(self) -> list[Plant]:
        """Retrieve all plants."""
        return list(self._plants.values())

    def add_plant(self, plant: Plant) -> None:
        """Add a plant to the repository."""
        self._plants[plant.plant_id] = plant

    def remove_plant(self, plant_id: str) -> Plant | None:
        """Remove a plant from the repository."""
        return self._plants.pop(plant_id, None)

    # =========================================================================
    # GROWSPACE OPERATIONS
    # =========================================================================

    def get_growspace(self, growspace_id: str) -> Growspace | None:
        """Retrieve a growspace by its ID."""
        return self._growspaces.get(growspace_id)

    def get_all_growspaces(self) -> list[Growspace]:
        """Retrieve all growspaces."""
        return list(self._growspaces.values())

    def add_growspace(self, growspace: Growspace) -> None:
        """Add a growspace to the repository."""
        self._growspaces[growspace.id] = growspace

    def remove_growspace(self, growspace_id: str) -> Growspace | None:
        """Remove a growspace from the repository."""
        return self._growspaces.pop(growspace_id, None)

    # =========================================================================
    # QUERY METHODS
    # =========================================================================

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
