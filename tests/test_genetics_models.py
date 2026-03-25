"""Tests for genetics-related data models: SeedBatch, PollinationEvent, PhenotypeScore."""

from __future__ import annotations

from dataclasses import asdict

import pytest

from custom_components.growspace_manager.models import (
    PhenotypeScore,
    Plant,
    PollinationEvent,
    SeedBatch,
)

# ---------------------------------------------------------------------------
# SeedBatch
# ---------------------------------------------------------------------------


class TestSeedBatch:
    """Tests for the SeedBatch model."""

    def test_creation_with_required_fields(self) -> None:
        """SeedBatch can be created with all required fields."""
        batch = SeedBatch(
            batch_id="batch-001",
            strain_name="OG Kush",
            breeder="DNA Genetics",
            quantity=10,
            acquisition_date="2026-01-15",
            generation="F1",
            lineage="Chemdawg x Hindu Kush",
        )

        assert batch.batch_id == "batch-001"
        assert batch.strain_name == "OG Kush"
        assert batch.breeder == "DNA Genetics"
        assert batch.quantity == 10
        assert batch.acquisition_date == "2026-01-15"
        assert batch.generation == "F1"
        assert batch.lineage == "Chemdawg x Hindu Kush"

    def test_notes_default_empty_string(self) -> None:
        """Notes field defaults to an empty string."""
        batch = SeedBatch(
            batch_id="b",
            strain_name="X",
            breeder="Y",
            quantity=5,
            acquisition_date="2026-01-01",
            generation="S1",
            lineage="X x X",
        )
        assert batch.notes == ""

    def test_round_trip_serialization(self) -> None:
        """SeedBatch serializes and deserializes without data loss."""
        batch = SeedBatch(
            batch_id="batch-abc",
            strain_name="Gelato",
            breeder="Cookies",
            quantity=20,
            acquisition_date="2026-02-10",
            generation="BX1",
            lineage="Sunset Sherbet x Thin Mint GSC",
            notes="Purchased at expo",
        )
        data = asdict(batch)
        restored = SeedBatch.from_dict(data)

        assert restored.batch_id == batch.batch_id
        assert restored.strain_name == batch.strain_name
        assert restored.quantity == batch.quantity
        assert restored.generation == batch.generation
        assert restored.lineage == batch.lineage
        assert restored.notes == batch.notes


# ---------------------------------------------------------------------------
# PollinationEvent
# ---------------------------------------------------------------------------


class TestPollinationEvent:
    """Tests for the PollinationEvent model."""

    def test_creation_with_required_fields(self) -> None:
        """PollinationEvent can be created with all required fields."""
        event = PollinationEvent(
            event_id="event-001",
            date="2026-03-01",
            donor_plant_id="plant-male-001",
            receiver_plant_id="plant-female-001",
        )

        assert event.event_id == "event-001"
        assert event.date == "2026-03-01"
        assert event.donor_plant_id == "plant-male-001"
        assert event.receiver_plant_id == "plant-female-001"
        assert event.notes == ""
        assert event.result_seed_batch_id is None

    def test_result_seed_batch_id_defaults_to_none(self) -> None:
        """result_seed_batch_id is None until seeds are harvested."""
        event = PollinationEvent(
            event_id="e",
            date="2026-01-01",
            donor_plant_id="d",
            receiver_plant_id="r",
        )
        assert event.result_seed_batch_id is None

    def test_round_trip_serialization(self) -> None:
        """PollinationEvent serializes and deserializes without data loss."""
        event = PollinationEvent(
            event_id="event-xyz",
            date="2026-03-15",
            donor_plant_id="plant-A",
            receiver_plant_id="plant-B",
            notes="Pollen collected from top cola",
            result_seed_batch_id="batch-999",
        )
        data = asdict(event)
        restored = PollinationEvent.from_dict(data)

        assert restored.event_id == event.event_id
        assert restored.donor_plant_id == event.donor_plant_id
        assert restored.receiver_plant_id == event.receiver_plant_id
        assert restored.notes == event.notes
        assert restored.result_seed_batch_id == event.result_seed_batch_id


# ---------------------------------------------------------------------------
# PhenotypeScore (fused)
# ---------------------------------------------------------------------------


class TestPhenotypeScore:
    """Tests for the fused PhenotypeScore model."""

    def test_all_fields_default_to_none(self) -> None:
        """All score fields default to None before any scoring."""
        score = PhenotypeScore()
        assert score.vigor is None
        assert score.internodal_spacing is None
        assert score.terpene_intensity is None
        assert score.resin is None
        assert score.mold_resistance is None
        assert score.yield_potential is None

    def test_keeper_defaults_false(self) -> None:
        """keeper flag defaults to False."""
        assert PhenotypeScore().keeper is False

    def test_total_score_none_when_no_scores_set(self) -> None:
        """total_score is None when no individual scores have been set."""
        assert PhenotypeScore().total_score is None

    def test_total_score_averages_all_fields(self) -> None:
        """total_score is the average of all six rubric fields."""
        score = PhenotypeScore(
            vigor=8,
            internodal_spacing=6,
            terpene_intensity=9,
            resin=7,
            mold_resistance=5,
            yield_potential=8,
        )
        expected = (8 + 6 + 9 + 7 + 5 + 8) / 6  # 7.166...
        assert score.total_score == pytest.approx(expected)

    def test_total_score_averages_partial_fields(self) -> None:
        """total_score only averages fields that have been set."""
        score = PhenotypeScore(vigor=10, resin=6)
        assert score.total_score == pytest.approx(8.0)

    def test_total_score_single_field(self) -> None:
        """total_score equals the single set field when only one is provided."""
        score = PhenotypeScore(terpene_intensity=9)
        assert score.total_score == pytest.approx(9.0)

    def test_round_trip_serialization(self) -> None:
        """PhenotypeScore serializes and deserializes without data loss."""
        score = PhenotypeScore(
            vigor=9,
            internodal_spacing=7,
            terpene_intensity=10,
            resin=8,
            mold_resistance=6,
            yield_potential=8,
            keeper=True,
            notes="Exceptional terp expression",
            updated_at="2026-03-20T10:00:00",
        )
        data = asdict(score)
        restored = PhenotypeScore.from_dict(data)

        assert restored.vigor == 9
        assert restored.internodal_spacing == 7
        assert restored.terpene_intensity == 10
        assert restored.resin == 8
        assert restored.mold_resistance == 6
        assert restored.yield_potential == 8
        assert restored.keeper is True
        assert restored.notes == "Exceptional terp expression"
        assert restored.updated_at == "2026-03-20T10:00:00"


# ---------------------------------------------------------------------------
# Plant.phenotype_score field
# ---------------------------------------------------------------------------


class TestPlantPhenotypeScore:
    """Tests that Plant carries the fused PhenotypeScore field."""

    def test_plant_has_phenotype_score_field(self) -> None:
        """Plant has a phenotype_score attribute of type PhenotypeScore."""
        plant = Plant(plant_id="p1", growspace_id="g1")
        assert hasattr(plant, "phenotype_score")
        assert isinstance(plant.phenotype_score, PhenotypeScore)

    def test_plant_phenotype_score_defaults_to_empty(self) -> None:
        """Plant.phenotype_score defaults to an empty PhenotypeScore."""
        plant = Plant(plant_id="p1", growspace_id="g1")
        assert plant.phenotype_score.vigor is None
        assert plant.phenotype_score.total_score is None

    def test_plant_no_longer_has_scores_field(self) -> None:
        """Plant no longer exposes the old 'scores' attribute."""
        plant = Plant(plant_id="p1", growspace_id="g1")
        assert not hasattr(plant, "scores")

    def test_plant_round_trip_with_phenotype_score(self) -> None:
        """Plant serializes and deserializes phenotype_score correctly."""
        plant = Plant(plant_id="p2", growspace_id="g2")
        plant.phenotype_score.vigor = 9
        plant.phenotype_score.terpene_intensity = 10
        plant.phenotype_score.keeper = True

        data = asdict(plant)
        restored = Plant.from_dict(data)

        assert restored.phenotype_score.vigor == 9
        assert restored.phenotype_score.terpene_intensity == 10
        assert restored.phenotype_score.keeper is True


# ---------------------------------------------------------------------------
# Plant migration: old 'scores' dict → new 'phenotype_score'
# ---------------------------------------------------------------------------


class TestPlantScoresMigration:
    """Tests for backward-compatible migration of old PlantScores data."""

    def test_migrates_vigor(self) -> None:
        """Old scores.vigor migrates to phenotype_score.vigor."""
        data = {
            "plant_id": "p1",
            "growspace_id": "g1",
            "scores": {
                "vigor": 4,
                "structure": None,
                "aroma": None,
                "resin": None,
                "pest_resistance": None,
            },
        }
        plant = Plant.from_dict(data)
        assert plant.phenotype_score.vigor == 4

    def test_migrates_structure_to_internodal_spacing(self) -> None:
        """Old scores.structure migrates to phenotype_score.internodal_spacing."""
        data = {
            "plant_id": "p1",
            "growspace_id": "g1",
            "scores": {
                "vigor": None,
                "structure": 3,
                "aroma": None,
                "resin": None,
                "pest_resistance": None,
            },
        }
        plant = Plant.from_dict(data)
        assert plant.phenotype_score.internodal_spacing == 3

    def test_migrates_aroma_to_terpene_intensity(self) -> None:
        """Old scores.aroma migrates to phenotype_score.terpene_intensity."""
        data = {
            "plant_id": "p1",
            "growspace_id": "g1",
            "scores": {
                "vigor": None,
                "structure": None,
                "aroma": 5,
                "resin": None,
                "pest_resistance": None,
            },
        }
        plant = Plant.from_dict(data)
        assert plant.phenotype_score.terpene_intensity == 5

    def test_migrates_resin(self) -> None:
        """Old scores.resin migrates to phenotype_score.resin."""
        data = {
            "plant_id": "p1",
            "growspace_id": "g1",
            "scores": {
                "vigor": None,
                "structure": None,
                "aroma": None,
                "resin": 4,
                "pest_resistance": None,
            },
        }
        plant = Plant.from_dict(data)
        assert plant.phenotype_score.resin == 4

    def test_migrates_pest_resistance_to_mold_resistance(self) -> None:
        """Old scores.pest_resistance migrates to phenotype_score.mold_resistance."""
        data = {
            "plant_id": "p1",
            "growspace_id": "g1",
            "scores": {
                "vigor": None,
                "structure": None,
                "aroma": None,
                "resin": None,
                "pest_resistance": 2,
            },
        }
        plant = Plant.from_dict(data)
        assert plant.phenotype_score.mold_resistance == 2

    def test_migrates_full_old_scores_dict(self) -> None:
        """All five old score fields are correctly migrated in one shot."""
        data = {
            "plant_id": "p1",
            "growspace_id": "g1",
            "scores": {
                "vigor": 3,
                "structure": 4,
                "aroma": 5,
                "resin": 2,
                "pest_resistance": 4,
            },
        }
        plant = Plant.from_dict(data)
        ps = plant.phenotype_score
        assert ps.vigor == 3
        assert ps.internodal_spacing == 4
        assert ps.terpene_intensity == 5
        assert ps.resin == 2
        assert ps.mold_resistance == 4
        # New fields not in old data default to None
        assert ps.yield_potential is None

    def test_phenotype_score_key_takes_precedence_over_scores(self) -> None:
        """If both 'scores' and 'phenotype_score' keys are present, phenotype_score wins."""
        data = {
            "plant_id": "p1",
            "growspace_id": "g1",
            "scores": {
                "vigor": 2,
                "structure": None,
                "aroma": None,
                "resin": None,
                "pest_resistance": None,
            },
            "phenotype_score": {"vigor": 9, "internodal_spacing": 8},
        }
        plant = Plant.from_dict(data)
        assert plant.phenotype_score.vigor == 9
        assert plant.phenotype_score.internodal_spacing == 8
