"""Genetics Manager — seed batches, pollination events, and phenotype scoring."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict
import logging
from typing import TYPE_CHECKING, Any
import uuid

from custom_components.growspace_manager.models import PollinationEvent, SeedBatch
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from custom_components.growspace_manager.data_access.growspace_repository import (
        GrowspaceRepository,
    )

_LOGGER = logging.getLogger(__name__)

_HARVESTED_STAGES = {"harvested", "dry", "cure"}


class GeneticsManager:
    """Manages seed batches, pollination events, and phenotype scoring."""

    def __init__(
        self,
        repository: GrowspaceRepository,
        save_callback: Callable[[], Awaitable[None]],
    ) -> None:
        """Initialize the GeneticsManager."""
        self.repository = repository
        self.save_callback = save_callback
        self.seed_batches: dict[str, SeedBatch] = {}
        self.pollination_events: dict[str, PollinationEvent] = {}

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def load_data(
        self,
        seed_batches: dict[str, SeedBatch],
        pollination_events: dict[str, PollinationEvent],
    ) -> None:
        """Load persisted data into the manager."""
        self.seed_batches = seed_batches
        self.pollination_events = pollination_events

    # ------------------------------------------------------------------
    # Seed batches
    # ------------------------------------------------------------------

    async def async_add_seed_batch(
        self,
        strain_name: str,
        breeder: str,
        quantity: int,
        acquisition_date: str,
        generation: str,
        lineage: str = "",
        parent_1_strain: str | None = None,
        parent_1_phenotype: str | None = None,
        parent_2_strain: str | None = None,
        parent_2_phenotype: str | None = None,
        notes: str = "",
    ) -> SeedBatch:
        """Create and store a new seed batch."""
        batch = SeedBatch(
            batch_id=str(uuid.uuid4()),
            strain_name=strain_name,
            breeder=breeder,
            quantity=quantity,
            acquisition_date=acquisition_date,
            generation=generation,
            lineage=lineage,
            parent_1_strain=parent_1_strain,
            parent_1_phenotype=parent_1_phenotype,
            parent_2_strain=parent_2_strain,
            parent_2_phenotype=parent_2_phenotype,
            notes=notes,
        )
        self.seed_batches[batch.batch_id] = batch
        await self.save_callback()
        _LOGGER.info(
            "Added seed batch '%s' x%d (id=%s)", strain_name, quantity, batch.batch_id
        )
        return batch

    async def async_update_seed_batch(
        self,
        batch_id: str,
        strain_name: str | None = None,
        breeder: str | None = None,
        quantity: int | None = None,
        acquisition_date: str | None = None,
        generation: str | None = None,
        lineage: str | None = None,
        parent_1_strain: str | None = None,
        parent_1_phenotype: str | None = None,
        parent_2_strain: str | None = None,
        parent_2_phenotype: str | None = None,
        notes: str | None = None,
    ) -> SeedBatch:
        """Update an existing seed batch (partial overwrite).

        Raises:
            ServiceValidationError: If the batch is not found.
        """
        batch = self.seed_batches.get(batch_id)
        if batch is None:
            raise ServiceValidationError(f"Seed batch '{batch_id}' not found")

        if strain_name is not None:
            batch.strain_name = strain_name
        if breeder is not None:
            batch.breeder = breeder
        if quantity is not None:
            batch.quantity = quantity
        if acquisition_date is not None:
            batch.acquisition_date = acquisition_date
        if generation is not None:
            batch.generation = generation
        if lineage is not None:
            batch.lineage = lineage
        if parent_1_strain is not None:
            batch.parent_1_strain = parent_1_strain
        if parent_1_phenotype is not None:
            batch.parent_1_phenotype = parent_1_phenotype
        if parent_2_strain is not None:
            batch.parent_2_strain = parent_2_strain
        if parent_2_phenotype is not None:
            batch.parent_2_phenotype = parent_2_phenotype
        if notes is not None:
            batch.notes = notes

        await self.save_callback()
        _LOGGER.info("Updated seed batch '%s' (id=%s)", batch.strain_name, batch_id)
        return batch

    def get_total_seed_count(self) -> int:
        """Return the total number of seeds across all batches."""
        return sum(b.quantity for b in self.seed_batches.values())

    # ------------------------------------------------------------------
    # Pollination events
    # ------------------------------------------------------------------

    async def async_log_pollination(
        self,
        date: str,
        donor_plant_id: str,
        receiver_plant_id: str,
        notes: str = "",
    ) -> PollinationEvent:
        """Record a pollination event between two existing plants.

        Raises:
            ServiceValidationError: If either plant is missing or already harvested.
        """
        self._validate_plant_for_pollination(donor_plant_id, "donor")
        self._validate_plant_for_pollination(receiver_plant_id, "receiver")

        event = PollinationEvent(
            event_id=str(uuid.uuid4()),
            date=date,
            donor_plant_id=donor_plant_id,
            receiver_plant_id=receiver_plant_id,
            notes=notes,
        )
        self.pollination_events[event.event_id] = event
        await self.save_callback()
        _LOGGER.info(
            "Logged pollination event: donor=%s receiver=%s (id=%s)",
            donor_plant_id,
            receiver_plant_id,
            event.event_id,
        )
        return event

    async def async_update_pollination(
        self,
        event_id: str,
        date: str | None = None,
        donor_plant_id: str | None = None,
        receiver_plant_id: str | None = None,
        notes: str | None = None,
    ) -> PollinationEvent:
        """Update an existing pollination event (partial overwrite).

        Raises:
            ServiceValidationError: If the event is not found.
        """
        event = self.pollination_events.get(event_id)
        if event is None:
            raise ServiceValidationError(f"Pollination event '{event_id}' not found")

        if date is not None:
            event.date = date
        if donor_plant_id is not None:
            event.donor_plant_id = donor_plant_id
        if receiver_plant_id is not None:
            event.receiver_plant_id = receiver_plant_id
        if notes is not None:
            event.notes = notes

        await self.save_callback()
        _LOGGER.info("Updated pollination event %s", event_id)
        return event

    async def async_delete_pollination(self, event_id: str) -> None:
        """Remove a pollination event.

        Raises:
            ServiceValidationError: If the event is not found.
        """
        if event_id not in self.pollination_events:
            raise ServiceValidationError(f"Pollination event '{event_id}' not found")

        del self.pollination_events[event_id]
        await self.save_callback()
        _LOGGER.info("Deleted pollination event %s", event_id)

    # ------------------------------------------------------------------
    # Seed harvesting
    # ------------------------------------------------------------------

    async def async_harvest_seeds(
        self,
        event_id: str,
        quantity: int,
        notes: str = "",
    ) -> SeedBatch:
        """Transition a pollination event into a new seed batch.

        Generates the lineage string as "<Receiver Strain> x <Donor Strain>"
        and links the event to the new batch.

        Raises:
            ServiceValidationError: If the event is not found or already has a batch.
        """
        event = self.pollination_events.get(event_id)
        if event is None:
            raise ServiceValidationError(f"Pollination event '{event_id}' not found")
        if event.result_seed_batch_id is not None:
            raise ServiceValidationError(
                f"Pollination event '{event_id}' already has a seed batch "
                f"(batch_id={event.result_seed_batch_id})"
            )

        receiver = self.repository.plants.get(event.receiver_plant_id)
        donor = self.repository.plants.get(event.donor_plant_id)

        receiver_name = (
            receiver.genetics.strain_name if receiver else event.receiver_plant_id
        )
        donor_name = donor.genetics.strain_name if donor else event.donor_plant_id

        lineage = f"{receiver_name} x {donor_name}"
        strain_name = f"{receiver_name} x {donor_name}"

        batch = SeedBatch(
            batch_id=str(uuid.uuid4()),
            strain_name=strain_name,
            breeder="Self",
            quantity=quantity,
            acquisition_date=dt_util.now().date().isoformat(),
            generation="F1",
            lineage=lineage,
            notes=notes,
        )
        self.seed_batches[batch.batch_id] = batch
        event.result_seed_batch_id = batch.batch_id

        await self.save_callback()
        _LOGGER.info(
            "Harvested %d seeds from event %s → batch %s (%s)",
            quantity,
            event_id,
            batch.batch_id,
            lineage,
        )
        return batch

    # ------------------------------------------------------------------
    # Phenotype scoring
    # ------------------------------------------------------------------

    async def async_score_phenotype(
        self,
        plant_id: str,
        vigor: int | None = None,
        internodal_spacing: int | None = None,
        terpene_intensity: int | None = None,
        resin: int | None = None,
        mold_resistance: int | None = None,
        yield_potential: int | None = None,
        keeper: bool | None = None,
        notes: str | None = None,
    ) -> None:
        """Update the PhenotypeScore on a plant (partial overwrite).

        Only fields explicitly passed (non-sentinel) are updated; existing
        values are preserved for fields not supplied.

        Raises:
            ServiceValidationError: If the plant is not found.
        """
        plant = self.repository.plants.get(plant_id)
        if plant is None:
            raise ServiceValidationError(f"Plant '{plant_id}' not found")

        ps = plant.phenotype_score
        if vigor is not None:
            ps.vigor = vigor
        if internodal_spacing is not None:
            ps.internodal_spacing = internodal_spacing
        if terpene_intensity is not None:
            ps.terpene_intensity = terpene_intensity
        if resin is not None:
            ps.resin = resin
        if mold_resistance is not None:
            ps.mold_resistance = mold_resistance
        if yield_potential is not None:
            ps.yield_potential = yield_potential
        if keeper is not None:
            ps.keeper = keeper
        if notes is not None:
            ps.notes = notes

        ps.updated_at = dt_util.now().isoformat()

        await self.save_callback()
        _LOGGER.info(
            "Scored plant %s: total=%.1f keeper=%s",
            plant_id,
            ps.total_score or 0.0,
            ps.keeper,
        )

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def get_serialization_data(self) -> dict[str, Any]:
        """Return a dict suitable for storage."""
        return {
            "seed_batches": {bid: asdict(b) for bid, b in self.seed_batches.items()},
            "pollination_events": {
                eid: asdict(e) for eid, e in self.pollination_events.items()
            },
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_plant_for_pollination(self, plant_id: str, role: str) -> None:
        """Ensure a plant exists and has not been harvested.

        Args:
            plant_id: The plant to validate.
            role: "donor" or "receiver" — used in error messages.

        Raises:
            ServiceValidationError: If plant is absent or in a post-harvest stage.
        """
        plant = self.repository.plants.get(plant_id)
        if plant is None:
            raise ServiceValidationError(
                f"Pollination {role} plant '{plant_id}' not found"
            )
        if str(plant.stage).lower() in _HARVESTED_STAGES:
            raise ServiceValidationError(
                f"Pollination {role} plant '{plant_id}' has already been harvested "
                f"(stage={plant.stage})"
            )
