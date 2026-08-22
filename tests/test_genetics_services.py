"""Tests for genetics service handlers.

This includes tests for add_seed_batch, log_pollination, score_phenotype,
harvest_seeds, sow_seed, set_plant_sex, and unlink_seed_batch.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.const import (
    ATTR_ACQUISITION_DATE,
    ATTR_BATCH_ID,
    ATTR_BREEDER,
    ATTR_GENERATION,
    ATTR_PARENT_1_PHENOTYPE,
    ATTR_PARENT_1_STRAIN,
    ATTR_PARENT_2_PHENOTYPE,
    ATTR_PARENT_2_STRAIN,
    ATTR_PLANT_ID,
    ATTR_QUANTITY,
    ATTR_SEX,
    ATTR_STRAIN_NAME,
)
from custom_components.growspace_manager.models import (
    Plant,
    PlantGenetics,
    PollinationEvent,
    SeedBatch,
)
from custom_components.growspace_manager.services.genetics import (
    handle_add_seed_batch,
    handle_delete_pollination,
    handle_harvest_seeds,
    handle_log_pollination,
    handle_score_phenotype,
    handle_set_plant_sex,
    handle_sow_seed,
    handle_unlink_seed_batch,
    handle_update_pollination,
    handle_update_seed_batch,
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
    mgr.async_update_seed_batch = AsyncMock(
        return_value=SeedBatch(
            batch_id="batch-upd",
            strain_name="Updated Kush",
            breeder="DNA",
            quantity=15,
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
    """Mock GrowspaceCoordinator exposing services.genetics facade and plants."""
    coord = MagicMock()
    coord._genetics_manager = genetics_manager
    coord.services.genetics = genetics_manager
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
            acquisition_date=date(2026, 3, 1),
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
            parent_1_strain=None,
            parent_1_phenotype=None,
            parent_2_strain=None,
            parent_2_phenotype=None,
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
            acquisition_date=date(2026, 1, 1),
            generation="S1",
            lineage="X x X",
        )

        await handle_add_seed_batch(mock_hass, mock_coordinator, call)

        _, kwargs = genetics_manager.async_add_seed_batch.call_args
        assert kwargs["notes"] == ""

    async def test_passes_parent_fields_to_manager(
        self,
        mock_hass: AsyncMock,
        mock_coordinator: MagicMock,
        genetics_manager: AsyncMock,
    ) -> None:
        """Handler forwards parent strain/phenotype fields to genetics_manager."""
        call = _make_call(
            **{
                ATTR_STRAIN_NAME: "Test F1",
                ATTR_BREEDER: "Tester",
                ATTR_QUANTITY: 5,
                ATTR_ACQUISITION_DATE: date(2026, 1, 1),
                ATTR_GENERATION: "F1",
                ATTR_PARENT_1_STRAIN: "OG Kush",
                ATTR_PARENT_1_PHENOTYPE: "#1",
                ATTR_PARENT_2_STRAIN: "Chemdawg",
                ATTR_PARENT_2_PHENOTYPE: "D",
            }
        )

        await handle_add_seed_batch(mock_hass, mock_coordinator, call)

        genetics_manager.async_add_seed_batch.assert_called_once_with(
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
            notes="",
        )


# ---------------------------------------------------------------------------
# handle_update_seed_batch
# ---------------------------------------------------------------------------


class TestHandleUpdateSeedBatch:
    """Tests for the update_seed_batch service handler."""

    async def test_delegates_to_genetics_manager(
        self,
        mock_hass: AsyncMock,
        mock_coordinator: MagicMock,
        genetics_manager: AsyncMock,
    ) -> None:
        """Handler calls genetics_manager.async_update_seed_batch with correct args."""
        call = _make_call(
            batch_id="batch-test",
            strain_name="OG Kush Update",
            breeder="DNA Genetics",
            quantity=15,
            acquisition_date=date(2026, 3, 2),
            generation="F2",
            lineage="Test Lineage",
            notes="Updated notes",
        )

        await handle_update_seed_batch(mock_hass, mock_coordinator, call)

        genetics_manager.async_update_seed_batch.assert_called_once_with(
            batch_id="batch-test",
            strain_name="OG Kush Update",
            breeder="DNA Genetics",
            quantity=15,
            acquisition_date="2026-03-02",
            generation="F2",
            lineage="Test Lineage",
            parent_1_strain=None,
            parent_1_phenotype=None,
            parent_2_strain=None,
            parent_2_phenotype=None,
            notes="Updated notes",
        )

    async def test_omitted_fields_pass_none(
        self,
        mock_hass: AsyncMock,
        mock_coordinator: MagicMock,
        genetics_manager: AsyncMock,
    ) -> None:
        """Handler passes None for fields that are omitted."""
        call = _make_call(batch_id="batch-test", quantity=20)

        await handle_update_seed_batch(mock_hass, mock_coordinator, call)

        genetics_manager.async_update_seed_batch.assert_called_once_with(
            batch_id="batch-test",
            strain_name=None,
            breeder=None,
            quantity=20,
            acquisition_date=None,
            generation=None,
            lineage=None,
            parent_1_strain=None,
            parent_1_phenotype=None,
            parent_2_strain=None,
            parent_2_phenotype=None,
            notes=None,
        )


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


# ---------------------------------------------------------------------------
# handle_update_pollination
# ---------------------------------------------------------------------------


class TestHandleUpdatePollination:
    """Tests for the update_pollination service handler."""

    @pytest.fixture(autouse=True)
    def _setup_mock(self, genetics_manager: AsyncMock) -> None:
        genetics_manager.async_update_pollination = AsyncMock(
            return_value=PollinationEvent(
                event_id="evt-1",
                date="2026-02-20",
                donor_plant_id="plant-donor",
                receiver_plant_id="plant-receiver",
                notes="edited",
            )
        )

    async def test_delegates_to_manager(
        self,
        mock_hass: AsyncMock,
        mock_coordinator: MagicMock,
        genetics_manager: AsyncMock,
    ) -> None:
        """Handler calls genetics_manager.async_update_pollination."""
        call = _make_call(
            event_id="evt-1",
            date=date(2026, 2, 20),
            notes="edited",
        )
        await handle_update_pollination(mock_hass, mock_coordinator, call)

        genetics_manager.async_update_pollination.assert_called_once_with(
            event_id="evt-1",
            date="2026-02-20",
            donor_plant_id=None,
            receiver_plant_id=None,
            notes="edited",
        )

    async def test_omitted_fields_pass_none(
        self,
        mock_hass: AsyncMock,
        mock_coordinator: MagicMock,
        genetics_manager: AsyncMock,
    ) -> None:
        """Optional fields omitted from call data are passed as None."""
        call = _make_call(event_id="evt-1")
        await handle_update_pollination(mock_hass, mock_coordinator, call)

        _, kwargs = genetics_manager.async_update_pollination.call_args
        assert kwargs["date"] is None
        assert kwargs["notes"] is None


# ---------------------------------------------------------------------------
# handle_delete_pollination
# ---------------------------------------------------------------------------


class TestHandleDeletePollination:
    """Tests for the delete_pollination service handler."""

    @pytest.fixture(autouse=True)
    def _setup_mock(self, genetics_manager: AsyncMock) -> None:
        genetics_manager.async_delete_pollination = AsyncMock()

    async def test_delegates_to_manager(
        self,
        mock_hass: AsyncMock,
        mock_coordinator: MagicMock,
        genetics_manager: AsyncMock,
    ) -> None:
        """Handler calls genetics_manager.async_delete_pollination with event_id."""
        call = _make_call(event_id="evt-del")
        await handle_delete_pollination(mock_hass, mock_coordinator, call)

        genetics_manager.async_delete_pollination.assert_called_once_with(
            event_id="evt-del"
        )

    async def test_propagates_service_validation_error(
        self,
        mock_hass: AsyncMock,
        mock_coordinator: MagicMock,
        genetics_manager: AsyncMock,
    ) -> None:
        """ServiceValidationError from manager propagates to caller."""
        genetics_manager.async_delete_pollination.side_effect = ServiceValidationError(
            "Pollination event 'x' not found"
        )
        call = _make_call(event_id="x")
        with pytest.raises(ServiceValidationError, match="not found"):
            await handle_delete_pollination(mock_hass, mock_coordinator, call)


# ---------------------------------------------------------------------------
# handle_sow_seed
# ---------------------------------------------------------------------------


class TestHandleSowSeed:
    """Tests for the sow_seed service handler."""

    @pytest.fixture(autouse=True)
    def _setup_mock(self, genetics_manager: AsyncMock) -> None:
        genetics_manager.async_sow_seed = AsyncMock()

    async def test_delegates_to_manager(
        self,
        mock_hass: AsyncMock,
        mock_coordinator: MagicMock,
        genetics_manager: AsyncMock,
    ) -> None:
        """Handler calls genetics_manager.async_sow_seed with correct arguments."""
        call = _make_call(
            **{
                ATTR_BATCH_ID: "batch-123",
                ATTR_PLANT_ID: "plant-456",
            }
        )
        await handle_sow_seed(mock_hass, mock_coordinator, call)

        genetics_manager.async_sow_seed.assert_called_once_with(
            batch_id="batch-123",
            plant_id="plant-456",
        )

    async def test_propagates_service_validation_error(
        self,
        mock_hass: AsyncMock,
        mock_coordinator: MagicMock,
        genetics_manager: AsyncMock,
    ) -> None:
        """ServiceValidationError from manager propagates to caller."""
        genetics_manager.async_sow_seed.side_effect = ServiceValidationError(
            "Batch 'batch-123' not found"
        )
        call = _make_call(
            **{
                ATTR_BATCH_ID: "batch-123",
                ATTR_PLANT_ID: "plant-456",
            }
        )
        with pytest.raises(ServiceValidationError, match="not found"):
            await handle_sow_seed(mock_hass, mock_coordinator, call)


# ---------------------------------------------------------------------------
# handle_set_plant_sex
# ---------------------------------------------------------------------------


class TestHandleSetPlantSex:
    """Tests for the set_plant_sex service handler."""

    @pytest.fixture(autouse=True)
    def _setup_mock(self, genetics_manager: AsyncMock) -> None:
        genetics_manager.async_set_plant_sex = AsyncMock()

    async def test_delegates_to_manager(
        self,
        mock_hass: AsyncMock,
        mock_coordinator: MagicMock,
        genetics_manager: AsyncMock,
    ) -> None:
        """Handler calls genetics_manager.async_set_plant_sex with correct arguments."""
        call = _make_call(
            **{
                ATTR_PLANT_ID: "plant-456",
                ATTR_SEX: "female",
            }
        )
        await handle_set_plant_sex(mock_hass, mock_coordinator, call)

        genetics_manager.async_set_plant_sex.assert_called_once_with(
            plant_id="plant-456",
            sex="female",
        )

    async def test_propagates_service_validation_error(
        self,
        mock_hass: AsyncMock,
        mock_coordinator: MagicMock,
        genetics_manager: AsyncMock,
    ) -> None:
        """ServiceValidationError from manager propagates to caller."""
        genetics_manager.async_set_plant_sex.side_effect = ServiceValidationError(
            "Plant 'plant-456' not found"
        )
        call = _make_call(
            **{
                ATTR_PLANT_ID: "plant-456",
                ATTR_SEX: "female",
            }
        )
        with pytest.raises(ServiceValidationError, match="not found"):
            await handle_set_plant_sex(mock_hass, mock_coordinator, call)


# ---------------------------------------------------------------------------
# handle_unlink_seed_batch
# ---------------------------------------------------------------------------


class TestHandleUnlinkSeedBatch:
    """Tests for the unlink_seed_batch service handler."""

    @pytest.fixture(autouse=True)
    def _setup_mock(self, genetics_manager: AsyncMock) -> None:
        genetics_manager.async_unlink_seed_batch = AsyncMock()

    async def test_delegates_to_manager(
        self,
        mock_hass: AsyncMock,
        mock_coordinator: MagicMock,
        genetics_manager: AsyncMock,
    ) -> None:
        """Handler calls genetics_manager.async_unlink_seed_batch with correct arguments."""
        call = _make_call(
            **{
                ATTR_PLANT_ID: "plant-456",
            }
        )
        await handle_unlink_seed_batch(mock_hass, mock_coordinator, call)

        genetics_manager.async_unlink_seed_batch.assert_called_once_with(
            plant_id="plant-456",
        )

    async def test_propagates_service_validation_error(
        self,
        mock_hass: AsyncMock,
        mock_coordinator: MagicMock,
        genetics_manager: AsyncMock,
    ) -> None:
        """ServiceValidationError from manager propagates to caller."""
        genetics_manager.async_unlink_seed_batch.side_effect = ServiceValidationError(
            "Plant 'plant-456' not found"
        )
        call = _make_call(
            **{
                ATTR_PLANT_ID: "plant-456",
            }
        )
        with pytest.raises(ServiceValidationError, match="not found"):
            await handle_unlink_seed_batch(mock_hass, mock_coordinator, call)
