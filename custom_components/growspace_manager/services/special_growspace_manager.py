"""Manager for special canonical growspaces in Growspace Manager."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..models import Growspace, GrowspaceType

if TYPE_CHECKING:
    from ..coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


class SpecialGrowspaceManager:
    """Manages creation and updates of special canonical growspaces."""

    def __init__(self, coordinator: GrowspaceCoordinator) -> None:
        """Initialize special growspace manager.

        Args:
            coordinator: The main coordinator instance.
        """
        self._coordinator = coordinator

    def create_special_growspace(
        self,
        canonical_id: str,
        canonical_name: str,
        rows: int,
        plants_per_row: int,
        growspace_type: GrowspaceType,
    ) -> None:
        """Create a new special growspace with the given parameters.

        Args:
            canonical_id: The canonical ID for the growspace.
            canonical_name: The canonical name for the growspace.
            rows: Number of rows in the growspace.
            plants_per_row: Number of plants per row.
            growspace_type: The type of the growspace.
        """
        self._coordinator.growspaces[canonical_id] = Growspace(
            id=canonical_id,
            name=canonical_name,
            rows=rows,
            plants_per_row=plants_per_row,
            growspace_type=growspace_type,
        )
        _LOGGER.info(
            "Created canonical growspace: %s with name '%s'",
            canonical_id,
            canonical_name,
        )

    def update_special_growspace_name(
        self, canonical_id: str, canonical_name: str
    ) -> None:
        """Update the name of an existing special growspace if it has changed.

        Args:
            canonical_id: The canonical ID of the growspace.
            canonical_name: The new canonical name.
        """
        existing = self._coordinator.growspaces[canonical_id]
        if existing.name != canonical_name:
            existing.name = canonical_name
            _LOGGER.info(
                "Updated growspace name: %s -> '%s'", canonical_id, canonical_name
            )

    def get_canonical_special(self, gs_id: str) -> tuple[str, str]:
        """Return the canonical ID and name for a special growspace.

        This also triggers a migration check to ensure any legacy aliases are handled.

        Args:
            gs_id: The growspace ID to look up.

        Returns:
            A tuple containing the canonical ID and canonical name.
        """
        growspace = self._coordinator.growspaces.get(gs_id)
        if growspace:
            return gs_id, growspace.name  # access attribute, not dict key
        return gs_id, gs_id
