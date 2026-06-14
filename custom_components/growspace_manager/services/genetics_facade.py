"""Genetics sub-facade for the Growspace Manager integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
    from custom_components.growspace_manager.models import SeedBatch


class GeneticsFacade:
    """Facade for all genetics-domain operations (seed batches, pollination, lineage)."""

    def __init__(self, coordinator: GrowspaceCoordinator) -> None:
        """Initialise the facade with the coordinator."""
        self._coordinator = coordinator

    # -------------------------------------------------------------------------
    # Read operations
    # -------------------------------------------------------------------------

    @property
    def seed_batches(self) -> dict[str, Any]:
        """Return all seed batches keyed by batch ID."""
        return self._coordinator._genetics_manager.seed_batches

    def seed_batch_by_id(self, batch_id: str) -> SeedBatch | None:
        """Return a seed batch by ID, or None if not found."""
        return self._coordinator._genetics_manager.seed_batches.get(batch_id)

    def get_total_seed_count(self) -> int:
        """Return the total number of seeds across all batches."""
        return self._coordinator._genetics_manager.get_total_seed_count()

    def get_lineage_tree(self, plant_id: str) -> dict[str, Any]:
        """Return the lineage tree for a plant."""
        return self._coordinator._genetics_manager.get_lineage_tree(plant_id)

    def get_serialization_data(self) -> dict[str, Any]:
        """Return serialized genetics data for storage/WebSocket consumers."""
        return self._coordinator._genetics_manager.get_serialization_data()

    # -------------------------------------------------------------------------
    # Mutation operations
    # -------------------------------------------------------------------------

    async def async_add_seed_batch(self, **kwargs: Any) -> Any:
        """Add a new seed batch."""
        return await self._coordinator._genetics_manager.async_add_seed_batch(**kwargs)

    async def async_update_seed_batch(self, **kwargs: Any) -> Any:
        """Update an existing seed batch."""
        return await self._coordinator._genetics_manager.async_update_seed_batch(**kwargs)

    async def async_log_pollination(self, **kwargs: Any) -> Any:
        """Log a pollination event."""
        return await self._coordinator._genetics_manager.async_log_pollination(**kwargs)

    async def async_score_phenotype(self, **kwargs: Any) -> Any:
        """Score a plant's phenotype."""
        return await self._coordinator._genetics_manager.async_score_phenotype(**kwargs)

    async def async_harvest_seeds(self, **kwargs: Any) -> Any:
        """Record a seed harvest from a plant."""
        return await self._coordinator._genetics_manager.async_harvest_seeds(**kwargs)

    async def async_update_pollination(self, **kwargs: Any) -> Any:
        """Update an existing pollination event."""
        return await self._coordinator._genetics_manager.async_update_pollination(**kwargs)

    async def async_delete_pollination(self, event_id: str) -> None:
        """Delete a pollination event."""
        await self._coordinator._genetics_manager.async_delete_pollination(event_id)

    async def async_sow_seed(self, batch_id: str, plant_id: str) -> None:
        """Link a seed batch to a plant (sow)."""
        await self._coordinator._genetics_manager.async_sow_seed(batch_id, plant_id)

    async def async_set_plant_sex(self, plant_id: str, sex: str) -> None:
        """Set the sex of a plant."""
        await self._coordinator._genetics_manager.async_set_plant_sex(plant_id, sex)

    async def async_unlink_seed_batch(self, plant_id: str) -> None:
        """Unlink the seed batch from a plant."""
        await self._coordinator._genetics_manager.async_unlink_seed_batch(plant_id)
