"""Data Access Repository for Growspace Manager."""

from __future__ import annotations

from custom_components.growspace_manager.models import Growspace, Plant
from custom_components.growspace_manager.utils import generate_growspace_grid


class GrowspaceRepository:
    """Repository for accessing and managing Growspace and Plant data."""

    def __init__(self) -> None:
        """Initialize the GrowspaceRepository."""
        self._growspaces: dict[str, Growspace] = {}
        self._plants: dict[str, Plant] = {}

    # =========================================================================
    # BULK LOAD (startup / reload only)
    # =========================================================================

    def load_growspaces(self, growspaces: dict[str, Growspace]) -> None:
        """Replace the growspace collection (called by StorageManager on load)."""
        self._growspaces = growspaces

    def load_plants(self, plants: dict[str, Plant]) -> None:
        """Replace the plant collection (called by StorageManager on load)."""
        self._plants = plants

    # =========================================================================
    # PLANT OPERATIONS
    # =========================================================================

    def get_plant(self, plant_id: str) -> Plant | None:
        """Return a plant by ID, or None if not found."""
        return self._plants.get(plant_id)

    def require_plant(self, plant_id: str) -> Plant:
        """Return a plant by ID, raising KeyError if not found."""
        try:
            return self._plants[plant_id]
        except KeyError:
            raise KeyError(f"Plant '{plant_id}' not found") from None

    def has_plant(self, plant_id: str) -> bool:
        """Return True if a plant with this ID exists."""
        return plant_id in self._plants

    def get_all_plants(self) -> list[Plant]:
        """Return all plants."""
        return list(self._plants.values())

    def add_plant(self, plant: Plant) -> None:
        """Add or replace a plant in the repository."""
        self._plants[plant.plant_id] = plant

    def remove_plant(self, plant_id: str) -> Plant | None:
        """Remove a plant by ID and return it, or None if not found."""
        return self._plants.pop(plant_id, None)

    # =========================================================================
    # GROWSPACE OPERATIONS
    # =========================================================================

    def get_growspace(self, growspace_id: str) -> Growspace | None:
        """Return a growspace by ID, or None if not found."""
        return self._growspaces.get(growspace_id)

    def require_growspace(self, growspace_id: str) -> Growspace:
        """Return a growspace by ID, raising KeyError if not found."""
        try:
            return self._growspaces[growspace_id]
        except KeyError:
            raise KeyError(f"Growspace '{growspace_id}' not found") from None

    def has_growspace(self, growspace_id: str) -> bool:
        """Return True if a growspace with this ID exists."""
        return growspace_id in self._growspaces

    def get_all_growspaces(self) -> list[Growspace]:
        """Return all growspaces."""
        return list(self._growspaces.values())

    def add_growspace(self, growspace: Growspace) -> None:
        """Add or replace a growspace in the repository."""
        self._growspaces[growspace.id] = growspace

    def remove_growspace(self, growspace_id: str) -> Growspace | None:
        """Remove a growspace by ID and return it, or None if not found."""
        return self._growspaces.pop(growspace_id, None)

    # =========================================================================
    # QUERY METHODS
    # =========================================================================

    def get_growspace_plants(self, growspace_id: str) -> list[Plant]:
        """Return all plants located in a specific growspace."""
        return [p for p in self._plants.values() if p.growspace_id == growspace_id]

    def get_growspace_grid(self, growspace_id: str) -> list[list[str | None]]:
        """Return a 2D grid representation of a growspace's plant layout."""
        growspace = self.require_growspace(growspace_id)
        plants = self.get_growspace_plants(growspace_id)
        return generate_growspace_grid(
            int(growspace.rows), int(growspace.plants_per_row), plants
        )

    def get_growspace_options(self) -> dict[str, str]:
        """Return growspaces as {id: name} for dropdown selection."""
        return {
            gs.id: getattr(gs, "name", gs.id) for gs in self._growspaces.values()
        }

    def get_sorted_growspace_options(self) -> list[tuple[str, str]]:
        """Return a sorted list of (id, name) tuples for dropdown selection."""
        return sorted(
            ((gs.id, getattr(gs, "name", gs.id)) for gs in self._growspaces.values()),
            key=lambda x: x[1].lower(),
        )
