"""Manages seed batch inventory and pollination event tracking."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import date
from typing import TYPE_CHECKING, Any
import uuid

from custom_components.growspace_manager.models import PollinationEvent, SeedBatch

if TYPE_CHECKING:
    from custom_components.growspace_manager.data_access.growspace_repository import (
        GrowspaceRepository,
    )


class GeneticsManager:
    """Manages seed batches and pollination events."""

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

    def load_data(
        self,
        seed_batches: dict[str, SeedBatch],
        pollination_events: dict[str, PollinationEvent],
    ) -> None:
        """Load data into the manager."""
        self.seed_batches = seed_batches
        self.pollination_events = pollination_events

    async def async_add_seed_batch(
        self,
        strain_name: str,
        breeder: str,
        quantity: int,
        acquisition_date: str,
        generation: str,
        lineage: str,
        notes: str = "",
    ) -> SeedBatch:
        """Add a new seed batch to the inventory."""
        batch_id = str(uuid.uuid4())
        batch = SeedBatch(
            batch_id=batch_id,
            strain_name=strain_name,
            breeder=breeder,
            quantity=quantity,
            acquisition_date=acquisition_date,
            generation=generation,
            lineage=lineage,
            notes=notes,
        )
        self.seed_batches[batch_id] = batch
        await self.save_callback()
        return batch

    async def async_log_pollination(
        self,
        event_date: str,
        donor_plant_id: str,
        receiver_plant_id: str,
        notes: str = "",
    ) -> PollinationEvent:
        """Log a pollination event between two plants."""
        event_id = str(uuid.uuid4())
        event = PollinationEvent(
            event_id=event_id,
            date=event_date,
            donor_plant_id=donor_plant_id,
            receiver_plant_id=receiver_plant_id,
            notes=notes,
        )
        self.pollination_events[event_id] = event
        await self.save_callback()
        return event

    async def async_harvest_seeds(
        self,
        event_id: str,
        quantity: int,
        notes: str = "",
    ) -> SeedBatch:
        """Convert a pollination event into a new seed batch."""
        event = self.pollination_events.get(event_id)
        if event is None:
            msg = f"Pollination event {event_id} not found"
            raise ValueError(msg)
        if event.result_seed_batch_id is not None:
            msg = f"Event {event_id} already has a seed batch"
            raise ValueError(msg)

        donor = self.repository.plants.get(event.donor_plant_id)
        receiver = self.repository.plants.get(event.receiver_plant_id)
        donor_name = donor.genetics.strain_name if donor else event.donor_plant_id
        receiver_name = (
            receiver.genetics.strain_name if receiver else event.receiver_plant_id
        )

        batch_id = str(uuid.uuid4())
        batch = SeedBatch(
            batch_id=batch_id,
            strain_name=f"{receiver_name} x {donor_name}",
            breeder="Self",
            quantity=quantity,
            acquisition_date=date.today().isoformat(),
            generation="F1",
            lineage=f"{receiver_name} x {donor_name}",
            notes=notes,
        )
        self.seed_batches[batch_id] = batch
        event.result_seed_batch_id = batch_id
        await self.save_callback()
        return batch

    def get_serialization_data(self) -> dict[str, Any]:
        """Return data for serialization."""
        return {
            "seed_batches": {bid: asdict(b) for bid, b in self.seed_batches.items()},
            "pollination_events": {
                eid: asdict(e) for eid, e in self.pollination_events.items()
            },
        }
