"""Tests for GeneticsManager — seed batches, pollination events, harvest, scoring."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.data_access.growspace_repository import (
    GrowspaceRepository,
)
from custom_components.growspace_manager.managers.genetics import (
    GeneticsManager,
    _parse_strain_library_key,
)
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
    repo = GrowspaceRepository()
    return GeneticsManager(repository=repo, save_callback=save_callback)


@pytest.fixture
def manager_with_plants(save_callback: AsyncMock) -> GeneticsManager:
    """GeneticsManager with two plants pre-loaded (donor + receiver)."""
    repo = GrowspaceRepository()
    repo.add_plant(Plant(
        plant_id="plant-donor",
        growspace_id="gs-1",
        genetics=PlantGenetics(strain_name="Pollen Donor"),
        stage="flower",
    ))
    repo.add_plant(Plant(
        plant_id="plant-receiver",
        growspace_id="gs-1",
        genetics=PlantGenetics(strain_name="Female Receiver"),
        stage="flower",
    ))
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
# update_seed_batch
# ---------------------------------------------------------------------------


class TestUpdateSeedBatch:
    """Tests for the update_seed_batch operation."""

    @pytest.fixture
    def manager_with_batch(self, manager: GeneticsManager) -> GeneticsManager:
        """Manager pre-loaded with one seed batch."""
        batch = SeedBatch(
            batch_id="batch-upd",
            strain_name="OG Kush",
            breeder="DNA Genetics",
            quantity=10,
            acquisition_date="2026-03-01",
            generation="F1",
            lineage="Chemdawg x Hindu Kush",
            notes="Original notes",
        )
        manager.seed_batches["batch-upd"] = batch
        return manager

    async def test_raises_if_batch_not_found(self, manager: GeneticsManager) -> None:
        """ServiceValidationError raised for unknown batch_id."""
        with pytest.raises(ServiceValidationError, match="not found"):
            await manager.async_update_seed_batch(batch_id="missing-batch")

    async def test_updates_fields(self, manager_with_batch: GeneticsManager) -> None:
        """Updating fields sets the correct values on the batch."""
        await manager_with_batch.async_update_seed_batch(
            batch_id="batch-upd",
            strain_name="Updated Kush",
            breeder="New Breeder",
            quantity=20,
            acquisition_date="2026-03-10",
            generation="F2",
            lineage="New Lineage",
            parent_1_strain="P1",
            parent_1_phenotype="P1 Ph",
            parent_2_strain="P2",
            parent_2_phenotype="P2 Ph",
            notes="Updated notes",
        )
        batch = manager_with_batch.seed_batches["batch-upd"]
        assert batch.strain_name == "Updated Kush"
        assert batch.breeder == "New Breeder"
        assert batch.quantity == 20
        assert batch.acquisition_date == "2026-03-10"
        assert batch.generation == "F2"
        assert batch.lineage == "New Lineage"
        assert batch.parent_1_strain == "P1"
        assert batch.parent_1_phenotype == "P1 Ph"
        assert batch.parent_2_strain == "P2"
        assert batch.parent_2_phenotype == "P2 Ph"
        assert batch.notes == "Updated notes"

    async def test_partial_update_preserves_other_fields(
        self, manager_with_batch: GeneticsManager
    ) -> None:
        """Updating only one field leaves others unchanged."""
        await manager_with_batch.async_update_seed_batch(
            batch_id="batch-upd", quantity=15
        )
        batch = manager_with_batch.seed_batches["batch-upd"]
        assert batch.quantity == 15
        assert batch.strain_name == "OG Kush"
        assert batch.breeder == "DNA Genetics"

    async def test_calls_save_callback(
        self, manager_with_batch: GeneticsManager
    ) -> None:
        """Save callback is called after update."""
        manager_with_batch.save_callback.assert_not_called()  # type: ignore[attr-defined]
        await manager_with_batch.async_update_seed_batch(
            batch_id="batch-upd", quantity=15
        )
        manager_with_batch.save_callback.assert_called_once()  # type: ignore[attr-defined]


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

        manager_with_plants.repository.require_plant("plant-donor").stage = "harvested"

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

        manager_with_plants.repository.require_plant("plant-receiver").stage = "harvested"

        with pytest.raises(ServiceValidationError, match="harvested"):
            await manager_with_plants.async_log_pollination(
                date="2026-03-10",
                donor_plant_id="plant-donor",
                receiver_plant_id="plant-receiver",
            )

    async def test_library_keyed_donor_is_accepted(
        self, manager_with_plants: GeneticsManager
    ) -> None:
        """log_pollination accepts a strain||phenotype library key as donor without a plant lookup."""
        event = await manager_with_plants.async_log_pollination(
            date="2026-03-10",
            donor_plant_id="Afghani #1||default",
            receiver_plant_id="plant-receiver",
        )
        assert event.donor_plant_id == "Afghani #1||default"


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

    async def test_stub_donor_library_key_stripped_in_lineage(
        self, manager_with_plants: GeneticsManager
    ) -> None:
        """harvest_seeds strips the '||phenotype' suffix from a stub donor key."""
        manager_with_plants.pollination_events["event-stub"] = PollinationEvent(
            event_id="event-stub",
            date="2026-05-01",
            donor_plant_id="Afghani #1||default",
            receiver_plant_id="plant-receiver",
        )
        batch = await manager_with_plants.async_harvest_seeds(
            event_id="event-stub", quantity=10
        )
        assert "Afghani #1" in batch.lineage
        assert "||" not in batch.lineage

    async def test_stub_donor_empty_phenotype_stripped(
        self, manager_with_plants: GeneticsManager
    ) -> None:
        """harvest_seeds strips a trailing '||' when phenotype is empty."""
        manager_with_plants.pollination_events["event-stub2"] = PollinationEvent(
            event_id="event-stub2",
            date="2026-05-01",
            donor_plant_id="OG Kush||",
            receiver_plant_id="plant-receiver",
        )
        batch = await manager_with_plants.async_harvest_seeds(
            event_id="event-stub2", quantity=10
        )
        assert "OG Kush" in batch.lineage
        assert "||" not in batch.lineage


# ---------------------------------------------------------------------------
# score_phenotype
# ---------------------------------------------------------------------------


class TestScorePhenotype:
    """Tests for the score_phenotype operation on a plant."""

    @pytest.fixture
    def manager_with_plant(self, save_callback: AsyncMock) -> GeneticsManager:
        """GeneticsManager with a single scoreable plant."""
        repo = GrowspaceRepository()
        repo.add_plant(Plant(
            plant_id="plant-score",
            growspace_id="gs",
            genetics=PlantGenetics(strain_name="Test"),
            stage="flower",
        ))
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

        ps = manager_with_plant.repository.require_plant("plant-score").phenotype_score
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
        ps = manager_with_plant.repository.require_plant("plant-score").phenotype_score
        assert ps.updated_at is not None

    async def test_partial_update_overwrites_only_provided_fields(
        self, manager_with_plant: GeneticsManager
    ) -> None:
        """score_phenotype only updates fields explicitly passed."""
        plant = manager_with_plant.repository.require_plant("plant-score")
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


# ---------------------------------------------------------------------------
# TestUpdatePollination
# ---------------------------------------------------------------------------


class TestUpdatePollination:
    """Tests for async_update_pollination."""

    @pytest.fixture
    def manager_with_event(self, manager: GeneticsManager) -> GeneticsManager:
        """Manager pre-loaded with one pollination event and two plants."""
        manager.repository.add_plant(Plant(
            plant_id="plant-donor",
            growspace_id="gs-1",
            genetics=PlantGenetics(strain_name="Pollen Donor"),
            stage="flower",
        ))
        manager.repository.add_plant(Plant(
            plant_id="plant-receiver",
            growspace_id="gs-1",
            genetics=PlantGenetics(strain_name="Female Receiver"),
            stage="flower",
        ))
        event = PollinationEvent(
            event_id="evt-1",
            date="2026-01-10",
            donor_plant_id="plant-donor",
            receiver_plant_id="plant-receiver",
            notes="",
        )
        manager.pollination_events["evt-1"] = event
        return manager

    async def test_updates_date(self, manager_with_event: GeneticsManager) -> None:
        """Updating date changes the event's date field."""
        await manager_with_event.async_update_pollination(
            event_id="evt-1", date="2026-02-20"
        )
        assert manager_with_event.pollination_events["evt-1"].date == "2026-02-20"

    async def test_updates_notes(self, manager_with_event: GeneticsManager) -> None:
        """Updating notes changes the event's notes field."""
        await manager_with_event.async_update_pollination(
            event_id="evt-1", notes="updated note"
        )
        assert manager_with_event.pollination_events["evt-1"].notes == "updated note"

    async def test_partial_update_preserves_other_fields(
        self, manager_with_event: GeneticsManager
    ) -> None:
        """Updating only notes leaves date unchanged."""
        await manager_with_event.async_update_pollination(
            event_id="evt-1", notes="new note"
        )
        assert manager_with_event.pollination_events["evt-1"].date == "2026-01-10"

    async def test_calls_save_callback(
        self, manager_with_event: GeneticsManager
    ) -> None:
        """Save callback is called after update."""
        manager_with_event.save_callback.assert_not_called()  # type: ignore[attr-defined]
        await manager_with_event.async_update_pollination(
            event_id="evt-1", date="2026-03-01"
        )
        manager_with_event.save_callback.assert_called_once()  # type: ignore[attr-defined]

    async def test_raises_if_event_not_found(
        self, manager_with_event: GeneticsManager
    ) -> None:
        """ServiceValidationError raised for unknown event_id."""
        with pytest.raises(ServiceValidationError, match="not found"):
            await manager_with_event.async_update_pollination(
                event_id="nonexistent", date="2026-01-01"
            )

    async def test_updates_donor_plant_id(self, manager_with_event: GeneticsManager) -> None:
        """Updating donor_plant_id changes the field."""
        await manager_with_event.async_update_pollination(
            event_id="evt-1", donor_plant_id="plant-donor"
        )
        assert manager_with_event.pollination_events["evt-1"].donor_plant_id == "plant-donor"

    async def test_updates_receiver_plant_id(self, manager_with_event: GeneticsManager) -> None:
        """Updating receiver_plant_id changes the field."""
        await manager_with_event.async_update_pollination(
            event_id="evt-1", receiver_plant_id="plant-receiver"
        )
        assert manager_with_event.pollination_events["evt-1"].receiver_plant_id == "plant-receiver"

    async def test_library_keyed_donor_accepted_on_update(
        self, manager_with_event: GeneticsManager
    ) -> None:
        """update_pollination accepts a strain||phenotype library key as the new donor."""
        await manager_with_event.async_update_pollination(
            event_id="evt-1", donor_plant_id="OG Kush||pheno-A"
        )
        assert manager_with_event.pollination_events["evt-1"].donor_plant_id == "OG Kush||pheno-A"


# ---------------------------------------------------------------------------
# TestDeletePollination
# ---------------------------------------------------------------------------


class TestDeletePollination:
    """Tests for async_delete_pollination."""

    @pytest.fixture
    def manager_with_event(self, manager: GeneticsManager) -> GeneticsManager:
        """Manager pre-loaded with one pollination event."""
        event = PollinationEvent(
            event_id="evt-del",
            date="2026-01-15",
            donor_plant_id="plant-donor",
            receiver_plant_id="plant-receiver",
        )
        manager.pollination_events["evt-del"] = event
        return manager

    async def test_removes_event(self, manager_with_event: GeneticsManager) -> None:
        """Deleted event is no longer in pollination_events."""
        await manager_with_event.async_delete_pollination(event_id="evt-del")
        assert "evt-del" not in manager_with_event.pollination_events

    async def test_calls_save_callback(
        self, manager_with_event: GeneticsManager
    ) -> None:
        """Save callback is called after deletion."""
        await manager_with_event.async_delete_pollination(event_id="evt-del")
        manager_with_event.save_callback.assert_called_once()  # type: ignore[attr-defined]

    async def test_allows_deleting_harvested_event(
        self, manager_with_event: GeneticsManager
    ) -> None:
        """Events with a linked seed batch can still be deleted."""
        manager_with_event.pollination_events["evt-del"].result_seed_batch_id = (
            "batch-xyz"
        )
        await manager_with_event.async_delete_pollination(event_id="evt-del")
        assert "evt-del" not in manager_with_event.pollination_events

    async def test_raises_if_event_not_found(
        self, manager_with_event: GeneticsManager
    ) -> None:
        """ServiceValidationError raised for unknown event_id."""
        with pytest.raises(ServiceValidationError, match="not found"):
            await manager_with_event.async_delete_pollination(event_id="ghost")


# ---------------------------------------------------------------------------
# StrainLibrary injection + classify_lineage integration
# ---------------------------------------------------------------------------


@pytest.fixture
def strain_library_mock() -> MagicMock:
    """A mock StrainLibrary with async_update_strain_generation."""
    lib = MagicMock()
    lib.get_strain_lineage_tree = MagicMock(
        return_value={"name": "Strain", "parents": []}
    )
    lib.async_update_strain_generation = AsyncMock()
    return lib


@pytest.fixture
def manager_with_strain_lib(
    save_callback: AsyncMock, strain_library_mock: MagicMock
) -> GeneticsManager:
    """GeneticsManager with two plants and injected StrainLibrary mock."""
    repo = GrowspaceRepository()
    repo.add_plant(Plant(
        plant_id="plant-donor",
        growspace_id="gs-1",
        genetics=PlantGenetics(strain_name="Pollen Donor"),
        stage="flower",
    ))
    repo.add_plant(Plant(
        plant_id="plant-receiver",
        growspace_id="gs-1",
        genetics=PlantGenetics(strain_name="Seed Mother"),
        stage="flower",
    ))
    return GeneticsManager(
        repository=repo,
        save_callback=save_callback,
        strain_library=strain_library_mock,
    )


@pytest.mark.asyncio
async def test_harvest_seeds_classifies_generation(
    manager_with_strain_lib: GeneticsManager,
    strain_library_mock: MagicMock,
) -> None:
    """async_harvest_seeds sets batch.generation via classify_lineage."""
    await manager_with_strain_lib.async_log_pollination(
        donor_plant_id="plant-donor",
        receiver_plant_id="plant-receiver",
        date="2026-05-07",
    )
    event_id = next(iter(manager_with_strain_lib.pollination_events))

    batch = await manager_with_strain_lib.async_harvest_seeds(event_id, quantity=10)

    assert batch.generation == "F1"
    strain_library_mock.async_update_strain_generation.assert_awaited_once_with(
        batch.strain_name, "F1"
    )


@pytest.mark.asyncio
async def test_harvest_seeds_not_misclassified_as_bx_due_to_prior_event(
    save_callback: AsyncMock,
    strain_library_mock: MagicMock,
) -> None:
    """Receiver plant has a prior pollination event but harvest must still classify F1.

    Without exclude_event_id, get_lineage_tree would find the current pollination
    event and treat the donor as a parent of the receiver, producing BX instead of F1.
    """
    repo = GrowspaceRepository()
    repo.add_plant(Plant(
        plant_id="plant-a",
        growspace_id="gs-1",
        genetics=PlantGenetics(strain_name="Strain A"),
        stage="flower",
    ))
    repo.add_plant(Plant(
        plant_id="plant-b",
        growspace_id="gs-1",
        genetics=PlantGenetics(strain_name="Strain B"),
        stage="flower",
    ))
    mgr = GeneticsManager(
        repository=repo,
        save_callback=save_callback,
        strain_library=strain_library_mock,
    )
    # Log and harvest — receiver has no prior history, but the current event
    # would cause BX if not excluded during classification
    await mgr.async_log_pollination(
        donor_plant_id="plant-b",
        receiver_plant_id="plant-a",
        date="2026-05-07",
    )
    event_id = next(iter(mgr.pollination_events))

    batch = await mgr.async_harvest_seeds(event_id, quantity=10)

    # Two distinct strains, no shared ancestry → must be F1, not BX
    assert batch.generation == "F1"


@pytest.mark.asyncio
async def test_harvest_seeds_s1_when_same_plant(
    save_callback: AsyncMock,
    strain_library_mock: MagicMock,
) -> None:
    """Same plant as donor and receiver → S1."""
    repo = MagicMock()
    repo.plants = {
        "plant-self": Plant(
            plant_id="plant-self",
            growspace_id="gs-1",
            genetics=PlantGenetics(strain_name="Self Strain"),
            stage="flower",
        ),
    }
    mgr = GeneticsManager(
        repository=repo,
        save_callback=save_callback,
        strain_library=strain_library_mock,
    )
    await mgr.async_log_pollination(
        donor_plant_id="plant-self",
        receiver_plant_id="plant-self",
        date="2026-05-07",
    )
    event_id = next(iter(mgr.pollination_events))
    batch = await mgr.async_harvest_seeds(event_id, quantity=5)

    assert batch.generation == "S1"


@pytest.mark.asyncio
async def test_add_seed_batch_auto_classifies_f1(
    save_callback: AsyncMock,
    strain_library_mock: MagicMock,
) -> None:
    """When both parent strains given and generation is empty, auto-classify."""
    strain_library_mock.get_strain_lineage_tree = MagicMock(
        return_value={"name": "Strain", "parents": []}
    )
    repo = MagicMock()
    repo.plants = {}
    mgr = GeneticsManager(
        repository=repo,
        save_callback=save_callback,
        strain_library=strain_library_mock,
    )

    batch = await mgr.async_add_seed_batch(
        strain_name="OG x Diesel",
        breeder="Self",
        quantity=10,
        acquisition_date="2026-05-07",
        generation="",
        parent_1_strain="OG Kush",
        parent_2_strain="Sour Diesel",
    )

    assert batch.generation == "F1"
    strain_library_mock.async_update_strain_generation.assert_awaited_once_with(
        "OG x Diesel", "F1"
    )


@pytest.mark.asyncio
async def test_add_seed_batch_respects_explicit_generation(
    save_callback: AsyncMock,
    strain_library_mock: MagicMock,
) -> None:
    """When generation explicitly set, do not overwrite it."""
    repo = MagicMock()
    repo.plants = {}
    mgr = GeneticsManager(
        repository=repo,
        save_callback=save_callback,
        strain_library=strain_library_mock,
    )

    batch = await mgr.async_add_seed_batch(
        strain_name="Special BX",
        breeder="Self",
        quantity=5,
        acquisition_date="2026-05-07",
        generation="BX2",
        parent_1_strain="OG Kush",
        parent_2_strain="Sour Diesel",
    )

    assert batch.generation == "BX2"
    strain_library_mock.async_update_strain_generation.assert_not_called()


@pytest.mark.asyncio
async def test_update_seed_batch_reclassifies_on_parent_change(
    save_callback: AsyncMock,
    strain_library_mock: MagicMock,
) -> None:
    """Changing parent strains triggers reclassification when generation not explicitly set."""
    strain_library_mock.get_strain_lineage_tree = MagicMock(
        return_value={"name": "Strain", "parents": []}
    )
    repo = MagicMock()
    repo.plants = {}
    mgr = GeneticsManager(
        repository=repo,
        save_callback=save_callback,
        strain_library=strain_library_mock,
    )
    # Create batch with explicit generation
    batch = await mgr.async_add_seed_batch(
        strain_name="My Cross",
        breeder="Self",
        quantity=5,
        acquisition_date="2026-05-07",
        generation="F1",
        parent_1_strain="Strain A",
        parent_2_strain="Strain B",
    )

    # Update with new parents — generation not passed → reclassify
    updated = await mgr.async_update_seed_batch(
        batch_id=batch.batch_id,
        parent_1_strain="New Strain A",
        parent_2_strain="New Strain B",
    )

    # Two distinct strains, no ancestry → F1
    assert updated.generation == "F1"
    # add_seed_batch skips auto-classify because generation="F1" is explicit;
    # only the update call triggers reclassification.
    assert strain_library_mock.async_update_strain_generation.await_count == 1


# ---------------------------------------------------------------------------
# _parse_strain_library_key
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("plain-plant-id", "plain-plant-id"),          # no separator → return as-is
        ("Gorilla Glue||default", "Gorilla Glue"),     # default phenotype → strain only
        ("Gorilla Glue||", "Gorilla Glue"),            # empty phenotype → strain only
        ("Gorilla Glue||#4", "Gorilla Glue (#4)"),     # named phenotype → strain (phenotype)
    ],
)
def test_parse_strain_library_key(key: str, expected: str) -> None:
    assert _parse_strain_library_key(key) == expected


# ---------------------------------------------------------------------------
# async_sow_seed
# ---------------------------------------------------------------------------


class TestSowSeed:
    """Tests for async_sow_seed."""

    @pytest.fixture
    def manager_with_batch_and_plant(self, save_callback: AsyncMock) -> GeneticsManager:
        repo = GrowspaceRepository()
        repo.add_plant(Plant(
            plant_id="plant-1",
            growspace_id="gs-1",
            genetics=PlantGenetics(strain_name="OG Kush"),
            stage="seedling",
        ))
        mgr = GeneticsManager(repository=repo, save_callback=save_callback)
        mgr.seed_batches["batch-1"] = SeedBatch(
            batch_id="batch-1",
            strain_name="OG Kush",
            breeder="DNA",
            quantity=3,
            acquisition_date="2026-01-01",
            generation="F1",
            lineage="A x B",
        )
        return mgr

    async def test_decrements_quantity_and_links_plant(
        self,
        manager_with_batch_and_plant: GeneticsManager,
        save_callback: AsyncMock,
    ) -> None:
        mgr = manager_with_batch_and_plant
        await mgr.async_sow_seed(batch_id="batch-1", plant_id="plant-1")

        assert mgr.seed_batches["batch-1"].quantity == 2
        plant = mgr.repository.get_plant("plant-1")
        assert plant is not None
        assert plant.seed_batch_id == "batch-1"
        assert plant.genetics.generation == "F1"
        save_callback.assert_called_once()

    async def test_raises_if_batch_not_found(
        self, manager_with_batch_and_plant: GeneticsManager
    ) -> None:
        with pytest.raises(ServiceValidationError, match="not found"):
            await manager_with_batch_and_plant.async_sow_seed(
                batch_id="no-such-batch", plant_id="plant-1"
            )

    async def test_raises_if_batch_quantity_zero(
        self, manager_with_batch_and_plant: GeneticsManager
    ) -> None:
        manager_with_batch_and_plant.seed_batches["batch-1"].quantity = 0
        with pytest.raises(ServiceValidationError, match="no remaining seeds"):
            await manager_with_batch_and_plant.async_sow_seed(
                batch_id="batch-1", plant_id="plant-1"
            )

    async def test_raises_if_plant_not_found(
        self, manager_with_batch_and_plant: GeneticsManager
    ) -> None:
        with pytest.raises(ServiceValidationError, match="not found"):
            await manager_with_batch_and_plant.async_sow_seed(
                batch_id="batch-1", plant_id="ghost-plant"
            )


# ---------------------------------------------------------------------------
# async_set_plant_sex
# ---------------------------------------------------------------------------


class TestSetPlantSex:
    """Tests for async_set_plant_sex."""

    @pytest.fixture
    def manager_with_plant(self, save_callback: AsyncMock) -> GeneticsManager:
        repo = GrowspaceRepository()
        repo.add_plant(Plant(
            plant_id="plant-1",
            growspace_id="gs-1",
            genetics=PlantGenetics(strain_name="Blue Dream"),
            stage="veg",
        ))
        return GeneticsManager(repository=repo, save_callback=save_callback)

    async def test_sets_sex_and_saves(
        self, manager_with_plant: GeneticsManager, save_callback: AsyncMock
    ) -> None:
        await manager_with_plant.async_set_plant_sex(plant_id="plant-1", sex="female")

        plant = manager_with_plant.repository.get_plant("plant-1")
        assert plant is not None
        assert plant.sex == "female"
        save_callback.assert_called_once()

    async def test_raises_if_plant_not_found(
        self, manager_with_plant: GeneticsManager
    ) -> None:
        with pytest.raises(ServiceValidationError, match="not found"):
            await manager_with_plant.async_set_plant_sex(
                plant_id="ghost-plant", sex="male"
            )


# ---------------------------------------------------------------------------
# async_unlink_seed_batch
# ---------------------------------------------------------------------------


class TestUnlinkSeedBatch:
    """Tests for async_unlink_seed_batch."""

    @pytest.fixture
    def manager_with_linked_plant(self, save_callback: AsyncMock) -> GeneticsManager:
        repo = GrowspaceRepository()
        plant = Plant(
            plant_id="plant-1",
            growspace_id="gs-1",
            genetics=PlantGenetics(strain_name="Runtz"),
            stage="veg",
        )
        plant.seed_batch_id = "batch-99"
        repo.add_plant(plant)
        return GeneticsManager(repository=repo, save_callback=save_callback)

    async def test_clears_seed_batch_id_and_saves(
        self, manager_with_linked_plant: GeneticsManager, save_callback: AsyncMock
    ) -> None:
        await manager_with_linked_plant.async_unlink_seed_batch(plant_id="plant-1")

        plant = manager_with_linked_plant.repository.get_plant("plant-1")
        assert plant is not None
        assert plant.seed_batch_id is None
        save_callback.assert_called_once()

    async def test_raises_if_plant_not_found(
        self, manager_with_linked_plant: GeneticsManager
    ) -> None:
        with pytest.raises(ServiceValidationError, match="not found"):
            await manager_with_linked_plant.async_unlink_seed_batch(
                plant_id="ghost-plant"
            )


# ---------------------------------------------------------------------------
# get_lineage_tree
# ---------------------------------------------------------------------------


class TestGetLineageTree:
    """Tests for get_lineage_tree."""

    @pytest.fixture
    def manager_with_cross(self, save_callback: AsyncMock) -> GeneticsManager:
        """Manager with a donor, a receiver, and one pollination event linking them."""
        repo = GrowspaceRepository()
        repo.add_plant(Plant(
            plant_id="donor-1",
            growspace_id="gs-1",
            genetics=PlantGenetics(strain_name="Pollen Donor"),
            stage="flower",
        ))
        repo.add_plant(Plant(
            plant_id="receiver-1",
            growspace_id="gs-1",
            genetics=PlantGenetics(strain_name="Female Receiver"),
            stage="flower",
        ))
        mgr = GeneticsManager(repository=repo, save_callback=save_callback)
        mgr.pollination_events["evt-1"] = PollinationEvent(
            event_id="evt-1",
            date="2026-05-01",
            donor_plant_id="donor-1",
            receiver_plant_id="receiver-1",
        )
        return mgr

    def test_builds_parents_when_event_found(
        self, manager_with_cross: GeneticsManager
    ) -> None:
        tree = manager_with_cross.get_lineage_tree("receiver-1")

        assert tree["name"] == "Female Receiver"
        assert len(tree["parents"]) == 2
        # First parent is a terminal leaf of the receiver itself
        assert tree["parents"][0] == {"name": "Female Receiver", "parents": []}
        # Second parent is the donor subtree
        assert tree["parents"][1]["name"] == "Pollen Donor"

    def test_max_depth_guard_returns_node_without_parents(
        self, manager_with_cross: GeneticsManager
    ) -> None:
        import custom_components.growspace_manager.managers.genetics as genetics_module

        original = genetics_module.MAX_LINEAGE_DEPTH
        try:
            genetics_module.MAX_LINEAGE_DEPTH = 0
            tree = manager_with_cross.get_lineage_tree("receiver-1")
        finally:
            genetics_module.MAX_LINEAGE_DEPTH = original

        assert tree["parents"] == []
