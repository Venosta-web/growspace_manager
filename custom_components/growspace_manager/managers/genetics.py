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

from .lineage_classifier import classify_lineage

if TYPE_CHECKING:
    from custom_components.growspace_manager.data_access.growspace_repository import (
        GrowspaceRepository,
    )
    from custom_components.growspace_manager.strain_library import StrainLibrary

_LOGGER = logging.getLogger(__name__)

_HARVESTED_STAGES = {"harvested", "dry", "cure"}
MAX_LINEAGE_DEPTH = 20
_LIBRARY_KEY_SEPARATOR = "||"
_DEFAULT_PHENOTYPE_SENTINEL = "default"


def _parse_strain_library_key(key: str) -> str:
    """Return the strain name from a 'strain||phenotype' library key, or the key itself."""
    if _LIBRARY_KEY_SEPARATOR not in key:
        return key
    strain, phenotype = key.split(_LIBRARY_KEY_SEPARATOR, 1)
    if phenotype and phenotype != _DEFAULT_PHENOTYPE_SENTINEL:
        return f"{strain} ({phenotype})"
    return strain


class GeneticsManager:
    """Manages seed batches, pollination events, and phenotype scoring."""

    def __init__(
        self,
        repository: GrowspaceRepository,
        save_callback: Callable[[], Awaitable[None]],
        strain_library: StrainLibrary | None = None,
    ) -> None:
        """Initialize the GeneticsManager."""
        self.repository = repository
        self.save_callback = save_callback
        self.strain_library = strain_library
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
        generation: str = "",
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
        # Auto-classify when both parents are known and generation was not set explicitly
        if (
            not generation
            and parent_1_strain
            and parent_2_strain
            and self.strain_library is not None
        ):
            tree_a = self.strain_library.get_strain_lineage_tree(parent_1_strain)
            tree_b = self.strain_library.get_strain_lineage_tree(parent_2_strain)
            batch.generation = classify_lineage(
                parent_1_strain, parent_2_strain, tree_a, tree_b
            )
            await self.strain_library.async_update_strain_generation(
                strain_name, batch.generation
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

        # Re-classify when parent strains changed and caller did not set generation explicitly
        parents_changed = parent_1_strain is not None or parent_2_strain is not None
        if (
            parents_changed
            and generation is None
            and batch.parent_1_strain
            and batch.parent_2_strain
            and self.strain_library is not None
        ):
            tree_a = self.strain_library.get_strain_lineage_tree(batch.parent_1_strain)
            tree_b = self.strain_library.get_strain_lineage_tree(batch.parent_2_strain)
            batch.generation = classify_lineage(
                batch.parent_1_strain, batch.parent_2_strain, tree_a, tree_b
            )
            await self.strain_library.async_update_strain_generation(
                batch.strain_name, batch.generation
            )

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
            self._validate_plant_for_pollination(donor_plant_id, "donor")
            event.donor_plant_id = donor_plant_id
        if receiver_plant_id is not None:
            self._validate_plant_for_pollination(receiver_plant_id, "receiver")
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

        receiver = self.repository.get_plant(event.receiver_plant_id)
        donor = self.repository.get_plant(event.donor_plant_id)

        receiver_name = (
            receiver.genetics.strain_name
            if receiver
            else _parse_strain_library_key(event.receiver_plant_id)
        )
        donor_name = (
            donor.genetics.strain_name
            if donor
            else _parse_strain_library_key(event.donor_plant_id)
        )

        lineage = f"{receiver_name} x {donor_name}"
        strain_name = f"{receiver_name} x {donor_name}"

        # Classify cross type from plant lineage trees (exclude current event
        # so it doesn't appear in its own parents)
        tree_receiver = self.get_lineage_tree(
            event.receiver_plant_id, exclude_event_id=event_id
        )
        tree_donor = self.get_lineage_tree(
            event.donor_plant_id, exclude_event_id=event_id
        )
        generation = classify_lineage(
            receiver_name, donor_name, tree_receiver, tree_donor
        )

        batch = SeedBatch(
            batch_id=str(uuid.uuid4()),
            strain_name=strain_name,
            breeder="Self",
            quantity=quantity,
            acquisition_date=dt_util.now().date().isoformat(),
            generation=generation,
            lineage=lineage,
            notes=notes,
        )
        self.seed_batches[batch.batch_id] = batch
        event.result_seed_batch_id = batch.batch_id

        if self.strain_library is not None:
            await self.strain_library.async_update_strain_generation(
                batch.strain_name, generation
            )

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
        plant = self.repository.get_plant(plant_id)
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

    async def async_sow_seed(self, batch_id: str, plant_id: str) -> None:
        """Link a plant to its origin seed batch.

        Decrements batch quantity by one, copies the batch generation into the
        plant's genetics, and records the batch association on the plant.

        Raises:
            ServiceValidationError: If the batch or plant is not found, or the
                batch has no remaining seeds.
        """
        batch = self.seed_batches.get(batch_id)
        if batch is None:
            raise ServiceValidationError(f"Seed batch '{batch_id}' not found")
        if batch.quantity <= 0:
            raise ServiceValidationError(
                f"Seed batch '{batch_id}' has no remaining seeds (quantity=0)"
            )
        plant = self.repository.get_plant(plant_id)
        if plant is None:
            raise ServiceValidationError(f"Plant '{plant_id}' not found")

        batch.quantity -= 1
        plant.seed_batch_id = batch_id
        plant.genetics.generation = batch.generation

        await self.save_callback()
        _LOGGER.info(
            "Sowed seed: plant %s linked to batch %s (generation=%s, remaining=%d)",
            plant_id,
            batch_id,
            batch.generation,
            batch.quantity,
        )

    async def async_set_plant_sex(self, plant_id: str, sex: str) -> None:
        """Set the biological sex of a plant.

        Raises:
            ServiceValidationError: If the plant is not found.
        """
        plant = self.repository.get_plant(plant_id)
        if plant is None:
            raise ServiceValidationError(f"Plant '{plant_id}' not found")

        plant.sex = sex
        await self.save_callback()
        _LOGGER.info("Set plant %s sex to '%s'", plant_id, sex)

    async def async_unlink_seed_batch(self, plant_id: str) -> None:
        """Clear a plant's seed batch association.

        Raises:
            ServiceValidationError: If the plant is not found.
        """
        plant = self.repository.get_plant(plant_id)
        if plant is None:
            raise ServiceValidationError(f"Plant '{plant_id}' not found")

        plant.seed_batch_id = None
        await self.save_callback()
        _LOGGER.info("Unlinked plant %s from its seed batch", plant_id)

    # ------------------------------------------------------------------
    # Lineage tree
    # ------------------------------------------------------------------

    def get_lineage_tree(
        self,
        plant_id: str,
        exclude_event_id: str | None = None,
        visited_events: set[str] | None = None,
        depth: int = 0,
    ) -> dict[str, Any]:
        """Build a pollination-based lineage tree for a plant.

        Walks the pollination_events to find which event produced the plant
        (as a receiver), then recurses to find the donor and receiver parents.
        Returns a node dict matching the strain-library tree format:
        ``{name, parents: [...]}``.

        Args:
            plant_id: The plant whose lineage tree is requested.
            exclude_event_id: Optional event ID to exclude when searching for
                the producing event — used to avoid including the current cross
                in its own classification.
            visited_events: Set of event IDs already visited in this traversal to detect cycles.
            depth: Current recursion depth.

        Returns:
            A nested dict ``{name, parents}`` rooted at the given plant.
            When a pollination event is found, parents are ``[receiver_leaf, donor_subtree]``
            where the receiver is always a terminal leaf (its own strain name, no parents)
            because the data model does not link a live plant back to the specific seed batch
            it was grown from.
        """
        if visited_events is None:
            visited_events = set()

        plant = self.repository.get_plant(plant_id)
        plant_name = (
            plant.genetics.strain_name
            if plant and plant.genetics.strain_name
            else plant_id
        )
        node: dict[str, Any] = {
            "name": plant_name,
            "parents": [],
            "generation": plant.genetics.generation if plant else "",
        }

        if depth >= MAX_LINEAGE_DEPTH:
            _LOGGER.warning("Max lineage depth reached for plant %s", plant_id)
            return node

        # Find a pollination event where this plant is the receiver
        event = next(
            (
                e
                for e in self.pollination_events.values()
                if e.receiver_plant_id == plant_id
                and e.event_id != exclude_event_id
                and e.event_id not in visited_events
            ),
            None,
        )
        if event is None:
            return node

        visited_events.add(event.event_id)

        # Emit receiver as a terminal leaf — the data model does not record which
        # seed batch a live plant grew from, so recursing into the receiver's own
        # pollination history would make the plant appear as its own ancestor.
        node["parents"].append({"name": plant_name, "parents": []})
        node["parents"].append(
            self.get_lineage_tree(
                event.donor_plant_id,
                exclude_event_id=event.event_id,
                visited_events=visited_events,
                depth=depth + 1,
            )
        )

        return node

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
        if role == "donor" and "||" in plant_id:
            return
        plant = self.repository.get_plant(plant_id)
        if plant is None:
            raise ServiceValidationError(
                f"Pollination {role} plant '{plant_id}' not found"
            )
        if str(plant.stage).lower() in _HARVESTED_STAGES:
            raise ServiceValidationError(
                f"Pollination {role} plant '{plant_id}' has already been harvested "
                f"(stage={plant.stage})"
            )
