"""Tests for GeneticsManager — seed batches, pollination events, harvest, scoring."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.managers.genetics import GeneticsManager
from custom_components.growspace_manager.models import (
    Plant,
    PlantGenetics,
    PollinationEvent,
    SeedBatch,
)
from homeassistant.exceptions import ServiceValidationError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def save_callback() -> AsyncMock:
    """A mock async save callback."""
    return AsyncMock()


@pytest.fixture
def manager(save_callback: AsyncMock) -> GeneticsManager:
    """A fresh GeneticsManager with an in-memory plant repository."""
    repo = MagicMock()
    repo.plants = {}
    return GeneticsManager(repository=repo, save_callback=save_callback)


@pytest.fixture
def manager_with_plants(save_callback: AsyncMock) -> GeneticsManager:
    """GeneticsManager with two plants pre-loaded (donor + receiver)."""
    repo = MagicMock()
    repo.plants = {
        "plant-donor": Plant(
            plant_id="plant-donor",
            growspace_id="gs-1",
            genetics=PlantGenetics(strain_name="Pollen Donor"),
            stage="flower",
        ),
        "plant-receiver": Plant(
            plant_id="plant-receiver",
            growspace_id="gs-1",
            genetics=PlantGenetics(strain_name="Female Receiver"),
            stage="flower",
        ),
    }
    return GeneticsManager(repository=repo, save_callback=save_callback)


# ---------------------------------------------------------------------------
# load_data / serialization round-trip
# ---------------------------------------------------------------------------


class TestLoadAndSerialize:
    """Tests for loading existing data and serialization."""

    def test_starts_empty(self, manager: GeneticsManager) -> None:
        """Manager starts with no batches or events."""
        assert manager.seed_batches == {}
        assert manager.pollination_events == {}

    def test_load_data_populates_collections(self, manager: GeneticsManager) -> None:
        """load_data fills both collections."""
        batch = SeedBatch(
            batch_id="b1",
            strain_name="OG",
            breeder="X",
            quantity=5,
            acquisition_date="2026-01-01",
            generation="F1",
            lineage="A x B",
        )
        event = PollinationEvent(
            event_id="e1",
            date="2026-02-01",
            donor_plant_id="d",
            receiver_plant_id="r",
        )
        manager.load_data({"b1": batch}, {"e1": event})

        assert "b1" in manager.seed_batches
        assert "e1" in manager.pollination_events

    def test_get_serialization_data_round_trip(self, manager: GeneticsManager) -> None:
        """Serialization data can be reloaded without data loss."""
        batch = SeedBatch(
            batch_id="b1",
            strain_name="Gelato",
            breeder="Cookies",
            quantity=10,
            acquisition_date="2026-01-15",
            generation="S1",
            lineage="Sunset Sherbet x Thin Mint GSC",
            notes="Keeper pack",
        )
        manager.seed_batches["b1"] = batch

        data = manager.get_serialization_data()
        restored_batch = SeedBatch.from_dict(data["seed_batches"]["b1"])

        assert restored_batch.strain_name == "Gelato"
        assert restored_batch.quantity == 10
        assert restored_batch.notes == "Keeper pack"


# ---------------------------------------------------------------------------
# add_seed_batch
# ---------------------------------------------------------------------------


class TestAddSeedBatch:
    """Tests for the add_seed_batch operation."""

    async def test_creates_batch_with_correct_fields(
        self, manager: GeneticsManager, save_callback: AsyncMock
    ) -> None:
        """add_seed_batch returns a SeedBatch with all provided fields."""
        batch = await manager.async_add_seed_batch(
            strain_name="OG Kush",
            breeder="DNA Genetics",
            quantity=12,
            acquisition_date="2026-03-01",
            generation="F1",
            lineage="Chemdawg x Hindu Kush",
            notes="Expo purchase",
        )

        assert batch.strain_name == "OG Kush"
        assert batch.breeder == "DNA Genetics"
        assert batch.quantity == 12
        assert batch.acquisition_date == "2026-03-01"
        assert batch.generation == "F1"
        assert batch.lineage == "Chemdawg x Hindu Kush"
        assert batch.notes == "Expo purchase"
        assert batch.batch_id  # UUID auto-generated

    async def test_stores_batch_in_collection(self, manager: GeneticsManager) -> None:
        """add_seed_batch adds the batch to seed_batches."""
        batch = await manager.async_add_seed_batch(
            strain_name="X",
            breeder="B",
            quantity=5,
            acquisition_date="2026-01-01",
            generation="S1",
            lineage="X x X",
        )
        assert batch.batch_id in manager.seed_batches

    async def test_calls_save_callback(
        self, manager: GeneticsManager, save_callback: AsyncMock
    ) -> None:
        """add_seed_batch triggers persistence."""
        await manager.async_add_seed_batch(
            strain_name="X",
            breeder="B",
            quantity=1,
            acquisition_date="2026-01-01",
            generation="F1",
            lineage="A x B",
        )
        save_callback.assert_called_once()

    async def test_each_batch_gets_unique_id(self, manager: GeneticsManager) -> None:
        """Two batches created in sequence have different IDs."""
        b1 = await manager.async_add_seed_batch(
            strain_name="A",
            breeder="X",
            quantity=5,
            acquisition_date="2026-01-01",
            generation="F1",
            lineage="A x B",
        )
        b2 = await manager.async_add_seed_batch(
            strain_name="B",
            breeder="X",
            quantity=5,
            acquisition_date="2026-01-02",
            generation="F1",
            lineage="C x D",
        )
        assert b1.batch_id != b2.batch_id

    async def test_add_seed_batch_with_parent_fields(
        self, manager: GeneticsManager
    ) -> None:
        """async_add_seed_batch stores parent strain/phenotype fields."""
        batch = await manager.async_add_seed_batch(
            strain_name="Test F1",
            breeder="Tester",
            quantity=5,
            acquisition_date="2026-01-01",
            generation="F1",
            lineage="",
            parent_1_strain="OG Kush",
            parent_1_phenotype="#1",
            parent_2_strain="Chemdawg",
            parent_2_phenotype="D",
        )
        assert batch.parent_1_strain == "OG Kush"
        assert batch.parent_1_phenotype == "#1"
        assert batch.parent_2_strain == "Chemdawg"
        assert batch.parent_2_phenotype == "D"


# ---------------------------------------------------------------------------
# log_pollination
# ---------------------------------------------------------------------------


class TestLogPollination:
    """Tests for the log_pollination operation."""

    async def test_creates_event_with_correct_fields(
        self, manager_with_plants: GeneticsManager, save_callback: AsyncMock
    ) -> None:
        """log_pollination returns a PollinationEvent with all fields set."""
        event = await manager_with_plants.async_log_pollination(
            date="2026-03-10",
            donor_plant_id="plant-donor",
            receiver_plant_id="plant-receiver",
            notes="Top cola pollen",
        )

        assert event.date == "2026-03-10"
        assert event.donor_plant_id == "plant-donor"
        assert event.receiver_plant_id == "plant-receiver"
        assert event.notes == "Top cola pollen"
        assert event.result_seed_batch_id is None
        assert event.event_id  # UUID auto-generated

    async def test_stores_event_in_collection(
        self, manager_with_plants: GeneticsManager
    ) -> None:
        """log_pollination adds the event to pollination_events."""
        event = await manager_with_plants.async_log_pollination(
            date="2026-03-10",
            donor_plant_id="plant-donor",
            receiver_plant_id="plant-receiver",
        )
        assert event.event_id in manager_with_plants.pollination_events

    async def test_calls_save_callback(
        self, manager_with_plants: GeneticsManager, save_callback: AsyncMock
    ) -> None:
        """log_pollination triggers persistence."""
        await manager_with_plants.async_log_pollination(
            date="2026-03-10",
            donor_plant_id="plant-donor",
            receiver_plant_id="plant-receiver",
        )
        save_callback.assert_called_once()

    async def test_raises_if_donor_not_found(
        self, manager_with_plants: GeneticsManager
    ) -> None:
        """log_pollination raises ServiceValidationError if donor plant is missing."""

        with pytest.raises(ServiceValidationError, match="donor"):
            await manager_with_plants.async_log_pollination(
                date="2026-03-10",
                donor_plant_id="nonexistent-donor",
                receiver_plant_id="plant-receiver",
            )

    async def test_raises_if_receiver_not_found(
        self, manager_with_plants: GeneticsManager
    ) -> None:
        """log_pollination raises ServiceValidationError if receiver plant is missing."""

        with pytest.raises(ServiceValidationError, match="receiver"):
            await manager_with_plants.async_log_pollination(
                date="2026-03-10",
                donor_plant_id="plant-donor",
                receiver_plant_id="nonexistent-receiver",
            )

    async def test_raises_if_donor_is_harvested(
        self, manager_with_plants: GeneticsManager
    ) -> None:
        """log_pollination raises if donor plant has already been harvested."""

        manager_with_plants.repository.plants["plant-donor"].stage = "harvested"

        with pytest.raises(ServiceValidationError, match="harvested"):
            await manager_with_plants.async_log_pollination(
                date="2026-03-10",
                donor_plant_id="plant-donor",
                receiver_plant_id="plant-receiver",
            )

    async def test_raises_if_receiver_is_harvested(
        self, manager_with_plants: GeneticsManager
    ) -> None:
        """log_pollination raises if receiver plant has already been harvested."""

        manager_with_plants.repository.plants["plant-receiver"].stage = "harvested"

        with pytest.raises(ServiceValidationError, match="harvested"):
            await manager_with_plants.async_log_pollination(
                date="2026-03-10",
                donor_plant_id="plant-donor",
                receiver_plant_id="plant-receiver",
            )


# ---------------------------------------------------------------------------
# harvest_seeds
# ---------------------------------------------------------------------------


class TestHarvestSeeds:
    """Tests for the harvest_seeds operation."""

    @pytest.fixture
    def manager_with_event(
        self, manager_with_plants: GeneticsManager
    ) -> GeneticsManager:
        """GeneticsManager with a pre-loaded pollination event."""
        manager_with_plants.pollination_events["event-001"] = PollinationEvent(
            event_id="event-001",
            date="2026-03-01",
            donor_plant_id="plant-donor",
            receiver_plant_id="plant-receiver",
        )
        return manager_with_plants

    async def test_creates_seed_batch_with_auto_lineage(
        self, manager_with_event: GeneticsManager
    ) -> None:
        """harvest_seeds builds lineage as 'Receiver x Donor'."""
        batch = await manager_with_event.async_harvest_seeds(
            event_id="event-001",
            quantity=30,
        )
        assert "Female Receiver" in batch.lineage
        assert "Pollen Donor" in batch.lineage

    async def test_batch_strain_name_from_receiver(
        self, manager_with_event: GeneticsManager
    ) -> None:
        """harvest_seeds names the batch after the receiver strain."""
        batch = await manager_with_event.async_harvest_seeds(
            event_id="event-001",
            quantity=30,
        )
        assert "Female Receiver" in batch.strain_name

    async def test_links_event_to_new_batch(
        self, manager_with_event: GeneticsManager
    ) -> None:
        """harvest_seeds sets result_seed_batch_id on the pollination event."""
        batch = await manager_with_event.async_harvest_seeds(
            event_id="event-001",
            quantity=30,
        )
        event = manager_with_event.pollination_events["event-001"]
        assert event.result_seed_batch_id == batch.batch_id

    async def test_stores_batch_in_collection(
        self, manager_with_event: GeneticsManager
    ) -> None:
        """harvest_seeds adds the new SeedBatch to seed_batches."""
        batch = await manager_with_event.async_harvest_seeds(
            event_id="event-001",
            quantity=15,
        )
        assert batch.batch_id in manager_with_event.seed_batches

    async def test_uses_provided_notes(
        self, manager_with_event: GeneticsManager
    ) -> None:
        """harvest_seeds stores the optional notes on the batch."""
        batch = await manager_with_event.async_harvest_seeds(
            event_id="event-001",
            quantity=20,
            notes="Excellent seed set, 20 seeds recovered",
        )
        assert batch.notes == "Excellent seed set, 20 seeds recovered"

    async def test_raises_if_event_not_found(self, manager: GeneticsManager) -> None:
        """harvest_seeds raises ServiceValidationError for unknown event IDs."""

        with pytest.raises(ServiceValidationError, match="event"):
            await manager.async_harvest_seeds(event_id="no-such-event", quantity=10)

    async def test_raises_if_event_already_harvested(
        self, manager_with_event: GeneticsManager
    ) -> None:
        """harvest_seeds raises if the event already has a linked seed batch."""

        manager_with_event.pollination_events[
            "event-001"
        ].result_seed_batch_id = "existing-batch"

        with pytest.raises(ServiceValidationError, match="already"):
            await manager_with_event.async_harvest_seeds(
                event_id="event-001", quantity=10
            )

    async def test_calls_save_callback(
        self, manager_with_event: GeneticsManager, save_callback: AsyncMock
    ) -> None:
        """harvest_seeds triggers persistence."""
        await manager_with_event.async_harvest_seeds(event_id="event-001", quantity=5)
        save_callback.assert_called()


# ---------------------------------------------------------------------------
# score_phenotype
# ---------------------------------------------------------------------------


class TestScorePhenotype:
    """Tests for the score_phenotype operation on a plant."""

    @pytest.fixture
    def manager_with_plant(self, save_callback: AsyncMock) -> GeneticsManager:
        """GeneticsManager with a single scoreable plant."""
        repo = MagicMock()
        repo.plants = {
            "plant-score": Plant(
                plant_id="plant-score",
                growspace_id="gs",
                genetics=PlantGenetics(strain_name="Test"),
                stage="flower",
            )
        }
        return GeneticsManager(repository=repo, save_callback=save_callback)

    async def test_updates_phenotype_score_fields(
        self, manager_with_plant: GeneticsManager
    ) -> None:
        """score_phenotype sets all provided rubric values on the plant."""
        await manager_with_plant.async_score_phenotype(
            plant_id="plant-score",
            vigor=9,
            internodal_spacing=7,
            terpene_intensity=10,
            resin=8,
            mold_resistance=6,
            yield_potential=9,
            keeper=True,
            notes="Outstanding pheno",
        )

        ps = manager_with_plant.repository.plants["plant-score"].phenotype_score
        assert ps.vigor == 9
        assert ps.internodal_spacing == 7
        assert ps.terpene_intensity == 10
        assert ps.resin == 8
        assert ps.mold_resistance == 6
        assert ps.yield_potential == 9
        assert ps.keeper is True
        assert ps.notes == "Outstanding pheno"

    async def test_sets_updated_at_timestamp(
        self, manager_with_plant: GeneticsManager
    ) -> None:
        """score_phenotype records an updated_at ISO timestamp."""
        await manager_with_plant.async_score_phenotype(
            plant_id="plant-score",
            vigor=8,
        )
        ps = manager_with_plant.repository.plants["plant-score"].phenotype_score
        assert ps.updated_at is not None

    async def test_partial_update_overwrites_only_provided_fields(
        self, manager_with_plant: GeneticsManager
    ) -> None:
        """score_phenotype only updates fields explicitly passed."""
        plant = manager_with_plant.repository.plants["plant-score"]
        plant.phenotype_score.resin = 7
        plant.phenotype_score.yield_potential = 5

        await manager_with_plant.async_score_phenotype(
            plant_id="plant-score",
            vigor=9,
        )

        ps = plant.phenotype_score
        assert ps.vigor == 9
        assert ps.resin == 7  # untouched
        assert ps.yield_potential == 5  # untouched

    async def test_calls_save_callback(
        self, manager_with_plant: GeneticsManager, save_callback: AsyncMock
    ) -> None:
        """score_phenotype triggers persistence."""
        await manager_with_plant.async_score_phenotype(plant_id="plant-score", vigor=8)
        save_callback.assert_called_once()

    async def test_raises_if_plant_not_found(self, manager: GeneticsManager) -> None:
        """score_phenotype raises ServiceValidationError for unknown plant IDs."""

        with pytest.raises(ServiceValidationError, match="plant"):
            await manager.async_score_phenotype(plant_id="missing-plant", vigor=5)


# ---------------------------------------------------------------------------
# get_total_seed_count
# ---------------------------------------------------------------------------


class TestGetTotalSeedCount:
    """Tests for the get_total_seed_count helper."""

    def test_returns_zero_when_empty(self, manager: GeneticsManager) -> None:
        """Returns 0 when there are no seed batches."""
        assert manager.get_total_seed_count() == 0

    def test_sums_all_batch_quantities(self, manager: GeneticsManager) -> None:
        """Returns the sum of all batch quantities."""
        manager.seed_batches["b1"] = SeedBatch(
            batch_id="b1",
            strain_name="A",
            breeder="X",
            quantity=10,
            acquisition_date="2026-01-01",
            generation="F1",
            lineage="A x B",
        )
        manager.seed_batches["b2"] = SeedBatch(
            batch_id="b2",
            strain_name="B",
            breeder="X",
            quantity=25,
            acquisition_date="2026-01-02",
            generation="S1",
            lineage="B x B",
        )
        assert manager.get_total_seed_count() == 35

    def test_single_batch(self, manager: GeneticsManager) -> None:
        """Returns the quantity of the single batch."""
        manager.seed_batches["b1"] = SeedBatch(
            batch_id="b1",
            strain_name="A",
            breeder="X",
            quantity=7,
            acquisition_date="2026-01-01",
            generation="F2",
            lineage="A x A",
        )
        assert manager.get_total_seed_count() == 7
