"""Tests for genetics service handlers (add_seed_batch, log_pollination,
score_phenotype, harvest_seeds)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.models import (
    Plant,
    PlantGenetics,
    PollinationEvent,
    SeedBatch,
)
from custom_components.growspace_manager.services.genetics import (
    handle_add_seed_batch,
    handle_harvest_seeds,
    handle_log_pollination,
    handle_score_phenotype,
)
from homeassistant.exceptions import ServiceValidationError

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_hass() -> AsyncMock:
    """Mock Home Assistant instance."""
    return AsyncMock()


@pytest.fixture
def genetics_manager() -> AsyncMock:
    """Mock GeneticsManager with sensible defaults."""
    mgr = AsyncMock()
    mgr.async_add_seed_batch = AsyncMock(
        return_value=SeedBatch(
            batch_id="batch-new",
            strain_name="OG Kush",
            breeder="DNA",
            quantity=10,
            acquisition_date="2026-03-01",
            generation="F1",
            lineage="A x B",
        )
    )
    mgr.async_log_pollination = AsyncMock(
        return_value=PollinationEvent(
            event_id="event-new",
            date="2026-03-10",
            donor_plant_id="plant-donor",
            receiver_plant_id="plant-receiver",
        )
    )
    mgr.async_harvest_seeds = AsyncMock(
        return_value=SeedBatch(
            batch_id="batch-harvest",
            strain_name="Receiver x Donor",
            breeder="Self",
            quantity=20,
            acquisition_date="2026-03-20",
            generation="F1",
            lineage="Receiver x Donor",
        )
    )
    mgr.async_score_phenotype = AsyncMock()
    return mgr


@pytest.fixture
def mock_coordinator(genetics_manager: AsyncMock) -> MagicMock:
    """Mock GrowspaceCoordinator exposing genetics_manager and plants."""
    coord = MagicMock()
    coord.genetics_manager = genetics_manager
    coord.plants = {
        "plant-donor": Plant(
            plant_id="plant-donor",
            growspace_id="gs-1",
            genetics=PlantGenetics(strain_name="Donor"),
            stage="flower",
        ),
        "plant-receiver": Plant(
            plant_id="plant-receiver",
            growspace_id="gs-1",
            genetics=PlantGenetics(strain_name="Receiver"),
            stage="flower",
        ),
    }
    return coord


def _make_call(**data: object) -> MagicMock:
    """Create a minimal mock ServiceCall."""
    call = MagicMock()
    call.data = data
    return call


# ---------------------------------------------------------------------------
# handle_add_seed_batch
# ---------------------------------------------------------------------------


class TestHandleAddSeedBatch:
    """Tests for the add_seed_batch service handler."""

    async def test_delegates_to_genetics_manager(
        self,
        mock_hass: AsyncMock,
        mock_coordinator: MagicMock,
        genetics_manager: AsyncMock,
    ) -> None:
        """Handler calls genetics_manager.async_add_seed_batch with correct args."""
        call = _make_call(
            strain_name="OG Kush",
            breeder="DNA Genetics",
            quantity=10,
            acquisition_date="2026-03-01",
            generation="F1",
            lineage="Chemdawg x Hindu Kush",
            notes="Expo purchase",
        )

        await handle_add_seed_batch(mock_hass, mock_coordinator, call)

        genetics_manager.async_add_seed_batch.assert_called_once_with(
            strain_name="OG Kush",
            breeder="DNA Genetics",
            quantity=10,
            acquisition_date="2026-03-01",
            generation="F1",
            lineage="Chemdawg x Hindu Kush",
            notes="Expo purchase",
        )

    async def test_notes_defaults_to_empty_string(
        self,
        mock_hass: AsyncMock,
        mock_coordinator: MagicMock,
        genetics_manager: AsyncMock,
    ) -> None:
        """Handler passes empty string for notes when not provided."""
        call = _make_call(
            strain_name="X",
            breeder="B",
            quantity=5,
            acquisition_date="2026-01-01",
            generation="S1",
            lineage="X x X",
        )

        await handle_add_seed_batch(mock_hass, mock_coordinator, call)

        _, kwargs = genetics_manager.async_add_seed_batch.call_args
        assert kwargs["notes"] == ""


# ---------------------------------------------------------------------------
# handle_log_pollination
# ---------------------------------------------------------------------------


class TestHandleLogPollination:
    """Tests for the log_pollination service handler."""

    async def test_delegates_to_genetics_manager(
        self,
        mock_hass: AsyncMock,
        mock_coordinator: MagicMock,
        genetics_manager: AsyncMock,
    ) -> None:
        """Handler calls genetics_manager.async_log_pollination with correct args."""
        call = _make_call(
            date="2026-03-10",
            donor_plant_id="plant-donor",
            receiver_plant_id="plant-receiver",
            notes="Pollen from top cola",
        )

        await handle_log_pollination(mock_hass, mock_coordinator, call)

        genetics_manager.async_log_pollination.assert_called_once_with(
            date="2026-03-10",
            donor_plant_id="plant-donor",
            receiver_plant_id="plant-receiver",
            notes="Pollen from top cola",
        )

    async def test_notes_defaults_to_empty_string(
        self,
        mock_hass: AsyncMock,
        mock_coordinator: MagicMock,
        genetics_manager: AsyncMock,
    ) -> None:
        """Handler passes empty string for notes when omitted."""
        call = _make_call(
            date="2026-03-10",
            donor_plant_id="plant-donor",
            receiver_plant_id="plant-receiver",
        )

        await handle_log_pollination(mock_hass, mock_coordinator, call)

        _, kwargs = genetics_manager.async_log_pollination.call_args
        assert kwargs["notes"] == ""

    async def test_propagates_service_validation_error_from_manager(
        self,
        mock_hass: AsyncMock,
        mock_coordinator: MagicMock,
        genetics_manager: AsyncMock,
    ) -> None:
        """ServiceValidationError raised by the manager is propagated to the caller."""
        genetics_manager.async_log_pollination.side_effect = ServiceValidationError(
            "Pollination donor plant 'x' not found"
        )
        call = _make_call(
            date="2026-03-10",
            donor_plant_id="x",
            receiver_plant_id="plant-receiver",
        )

        with pytest.raises(ServiceValidationError, match="donor"):
            await handle_log_pollination(mock_hass, mock_coordinator, call)


# ---------------------------------------------------------------------------
# handle_score_phenotype
# ---------------------------------------------------------------------------


class TestHandleScorePhenotype:
    """Tests for the score_phenotype service handler."""

    async def test_delegates_all_rubric_fields(
        self,
        mock_hass: AsyncMock,
        mock_coordinator: MagicMock,
        genetics_manager: AsyncMock,
    ) -> None:
        """Handler passes all rubric fields to async_score_phenotype."""
        call = _make_call(
            plant_id="plant-donor",
            vigor=9,
            internodal_spacing=7,
            terpene_intensity=10,
            resin=8,
            mold_resistance=6,
            yield_potential=9,
            keeper=True,
            notes="Exceptional pheno",
        )

        await handle_score_phenotype(mock_hass, mock_coordinator, call)

        genetics_manager.async_score_phenotype.assert_called_once_with(
            plant_id="plant-donor",
            vigor=9,
            internodal_spacing=7,
            terpene_intensity=10,
            resin=8,
            mold_resistance=6,
            yield_potential=9,
            keeper=True,
            notes="Exceptional pheno",
        )

    async def test_partial_call_passes_none_for_missing_fields(
        self,
        mock_hass: AsyncMock,
        mock_coordinator: MagicMock,
        genetics_manager: AsyncMock,
    ) -> None:
        """When only some fields are provided, others are passed as None."""
        call = _make_call(plant_id="plant-donor", vigor=8)

        await handle_score_phenotype(mock_hass, mock_coordinator, call)

        _, kwargs = genetics_manager.async_score_phenotype.call_args
        assert kwargs["vigor"] == 8
        assert kwargs["internodal_spacing"] is None
        assert kwargs["terpene_intensity"] is None
        assert kwargs["resin"] is None
        assert kwargs["mold_resistance"] is None
        assert kwargs["yield_potential"] is None
        assert kwargs["keeper"] is None
        assert kwargs["notes"] is None

    async def test_propagates_service_validation_error_for_missing_plant(
        self,
        mock_hass: AsyncMock,
        mock_coordinator: MagicMock,
        genetics_manager: AsyncMock,
    ) -> None:
        """ServiceValidationError from the manager is propagated."""
        genetics_manager.async_score_phenotype.side_effect = ServiceValidationError(
            "Plant 'ghost' not found"
        )
        call = _make_call(plant_id="ghost", vigor=5)

        with pytest.raises(ServiceValidationError, match="ghost"):
            await handle_score_phenotype(mock_hass, mock_coordinator, call)


# ---------------------------------------------------------------------------
# handle_harvest_seeds
# ---------------------------------------------------------------------------


class TestHandleHarvestSeeds:
    """Tests for the harvest_seeds service handler."""

    async def test_delegates_to_genetics_manager(
        self,
        mock_hass: AsyncMock,
        mock_coordinator: MagicMock,
        genetics_manager: AsyncMock,
    ) -> None:
        """Handler calls genetics_manager.async_harvest_seeds with correct args."""
        call = _make_call(
            event_id="event-001",
            quantity=20,
            notes="Good seed set",
        )

        await handle_harvest_seeds(mock_hass, mock_coordinator, call)

        genetics_manager.async_harvest_seeds.assert_called_once_with(
            event_id="event-001",
            quantity=20,
            notes="Good seed set",
        )

    async def test_notes_defaults_to_empty_string(
        self,
        mock_hass: AsyncMock,
        mock_coordinator: MagicMock,
        genetics_manager: AsyncMock,
    ) -> None:
        """Handler passes empty string for notes when not provided."""
        call = _make_call(event_id="event-001", quantity=15)

        await handle_harvest_seeds(mock_hass, mock_coordinator, call)

        _, kwargs = genetics_manager.async_harvest_seeds.call_args
        assert kwargs["notes"] == ""

    async def test_propagates_service_validation_error_for_missing_event(
        self,
        mock_hass: AsyncMock,
        mock_coordinator: MagicMock,
        genetics_manager: AsyncMock,
    ) -> None:
        """ServiceValidationError from the manager is propagated."""
        genetics_manager.async_harvest_seeds.side_effect = ServiceValidationError(
            "Pollination event 'ghost' not found"
        )
        call = _make_call(event_id="ghost", quantity=10)

        with pytest.raises(ServiceValidationError, match="ghost"):
            await handle_harvest_seeds(mock_hass, mock_coordinator, call)

    async def test_propagates_service_validation_error_for_duplicate_harvest(
        self,
        mock_hass: AsyncMock,
        mock_coordinator: MagicMock,
        genetics_manager: AsyncMock,
    ) -> None:
        """ServiceValidationError for already-harvested events is propagated."""
        genetics_manager.async_harvest_seeds.side_effect = ServiceValidationError(
            "Pollination event 'event-001' already has a seed batch"
        )
        call = _make_call(event_id="event-001", quantity=5)

        with pytest.raises(ServiceValidationError, match="already"):
            await handle_harvest_seeds(mock_hass, mock_coordinator, call)
