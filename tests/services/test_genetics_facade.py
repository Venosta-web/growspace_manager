"""Tests for GeneticsFacade delegation contract."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.services.genetics_facade import GeneticsFacade


def _make_coordinator(seed_batches: dict | None = None) -> MagicMock:
    """Build a minimal coordinator mock with a genetics_manager."""
    coordinator = MagicMock()
    coordinator.genetics_manager = MagicMock()
    coordinator.genetics_manager.seed_batches = seed_batches or {}
    coordinator.genetics_manager.get_total_seed_count = MagicMock(return_value=0)
    coordinator.genetics_manager.get_lineage_tree = MagicMock(return_value={})
    coordinator.genetics_manager.get_serialization_data = MagicMock(return_value={})
    coordinator.genetics_manager.async_add_seed_batch = AsyncMock()
    coordinator.genetics_manager.async_update_seed_batch = AsyncMock()
    coordinator.genetics_manager.async_log_pollination = AsyncMock()
    coordinator.genetics_manager.async_score_phenotype = AsyncMock()
    coordinator.genetics_manager.async_harvest_seeds = AsyncMock()
    coordinator.genetics_manager.async_update_pollination = AsyncMock()
    coordinator.genetics_manager.async_delete_pollination = AsyncMock()
    coordinator.genetics_manager.async_sow_seed = AsyncMock()
    coordinator.genetics_manager.async_set_plant_sex = AsyncMock()
    coordinator.genetics_manager.async_unlink_seed_batch = AsyncMock()
    return coordinator


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------


def test_seed_batches_returns_genetics_manager_data() -> None:
    """seed_batches property exposes genetics_manager.seed_batches directly."""
    batches = {"b1": MagicMock(), "b2": MagicMock()}
    coordinator = _make_coordinator(seed_batches=batches)
    facade = GeneticsFacade(coordinator)

    assert facade.seed_batches is batches


def test_seed_batch_by_id_returns_batch_when_present() -> None:
    """seed_batch_by_id returns the batch for a known ID."""
    batch = MagicMock()
    coordinator = _make_coordinator(seed_batches={"b1": batch})
    facade = GeneticsFacade(coordinator)

    assert facade.seed_batch_by_id("b1") is batch


def test_seed_batch_by_id_returns_none_for_unknown_id() -> None:
    """seed_batch_by_id returns None for an unknown batch ID."""
    coordinator = _make_coordinator()
    facade = GeneticsFacade(coordinator)

    assert facade.seed_batch_by_id("nope") is None


def test_get_total_seed_count_delegates() -> None:
    """get_total_seed_count delegates to genetics_manager."""
    coordinator = _make_coordinator()
    coordinator.genetics_manager.get_total_seed_count.return_value = 42
    facade = GeneticsFacade(coordinator)

    assert facade.get_total_seed_count() == 42
    coordinator.genetics_manager.get_total_seed_count.assert_called_once()


def test_get_lineage_tree_delegates() -> None:
    """get_lineage_tree delegates to genetics_manager with the given plant_id."""
    tree = {"nodes": []}
    coordinator = _make_coordinator()
    coordinator.genetics_manager.get_lineage_tree.return_value = tree
    facade = GeneticsFacade(coordinator)

    result = facade.get_lineage_tree("plant-1")

    assert result is tree
    coordinator.genetics_manager.get_lineage_tree.assert_called_once_with("plant-1")


def test_get_serialization_data_delegates() -> None:
    """get_serialization_data delegates to genetics_manager."""
    data = {"seed_batches": {}}
    coordinator = _make_coordinator()
    coordinator.genetics_manager.get_serialization_data.return_value = data
    facade = GeneticsFacade(coordinator)

    assert facade.get_serialization_data() is data


# ---------------------------------------------------------------------------
# Mutation operations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_add_seed_batch_delegates() -> None:
    """async_add_seed_batch forwards kwargs to genetics_manager."""
    coordinator = _make_coordinator()
    facade = GeneticsFacade(coordinator)

    await facade.async_add_seed_batch(strain_name="OG Kush", breeder="DNA", quantity=10)

    coordinator.genetics_manager.async_add_seed_batch.assert_awaited_once_with(
        strain_name="OG Kush", breeder="DNA", quantity=10
    )


@pytest.mark.asyncio
async def test_async_update_seed_batch_delegates() -> None:
    """async_update_seed_batch forwards kwargs to genetics_manager."""
    coordinator = _make_coordinator()
    facade = GeneticsFacade(coordinator)

    await facade.async_update_seed_batch(batch_id="b1", quantity=5)

    coordinator.genetics_manager.async_update_seed_batch.assert_awaited_once_with(
        batch_id="b1", quantity=5
    )


@pytest.mark.asyncio
async def test_async_log_pollination_delegates() -> None:
    """async_log_pollination forwards kwargs to genetics_manager."""
    coordinator = _make_coordinator()
    facade = GeneticsFacade(coordinator)

    await facade.async_log_pollination(donor_plant_id="p1", receiver_plant_id="p2")

    coordinator.genetics_manager.async_log_pollination.assert_awaited_once_with(
        donor_plant_id="p1", receiver_plant_id="p2"
    )


@pytest.mark.asyncio
async def test_async_score_phenotype_delegates() -> None:
    """async_score_phenotype forwards kwargs to genetics_manager."""
    coordinator = _make_coordinator()
    facade = GeneticsFacade(coordinator)

    await facade.async_score_phenotype(plant_id="p1", vigor=8)

    coordinator.genetics_manager.async_score_phenotype.assert_awaited_once_with(
        plant_id="p1", vigor=8
    )


@pytest.mark.asyncio
async def test_async_harvest_seeds_delegates() -> None:
    """async_harvest_seeds forwards kwargs to genetics_manager."""
    coordinator = _make_coordinator()
    facade = GeneticsFacade(coordinator)

    await facade.async_harvest_seeds(plant_id="p1", quantity=20)

    coordinator.genetics_manager.async_harvest_seeds.assert_awaited_once_with(
        plant_id="p1", quantity=20
    )


@pytest.mark.asyncio
async def test_async_update_pollination_delegates() -> None:
    """async_update_pollination forwards kwargs to genetics_manager."""
    coordinator = _make_coordinator()
    facade = GeneticsFacade(coordinator)

    await facade.async_update_pollination(event_id="e1", notes="updated")

    coordinator.genetics_manager.async_update_pollination.assert_awaited_once_with(
        event_id="e1", notes="updated"
    )


@pytest.mark.asyncio
async def test_async_delete_pollination_delegates() -> None:
    """async_delete_pollination forwards to genetics_manager."""
    coordinator = _make_coordinator()
    facade = GeneticsFacade(coordinator)

    await facade.async_delete_pollination("e1")

    coordinator.genetics_manager.async_delete_pollination.assert_awaited_once_with("e1")


@pytest.mark.asyncio
async def test_async_sow_seed_delegates() -> None:
    """async_sow_seed forwards to genetics_manager."""
    coordinator = _make_coordinator()
    facade = GeneticsFacade(coordinator)

    await facade.async_sow_seed("b1", "p1")

    coordinator.genetics_manager.async_sow_seed.assert_awaited_once_with("b1", "p1")


@pytest.mark.asyncio
async def test_async_set_plant_sex_delegates() -> None:
    """async_set_plant_sex forwards to genetics_manager."""
    coordinator = _make_coordinator()
    facade = GeneticsFacade(coordinator)

    await facade.async_set_plant_sex("p1", "female")

    coordinator.genetics_manager.async_set_plant_sex.assert_awaited_once_with(
        "p1", "female"
    )


@pytest.mark.asyncio
async def test_async_unlink_seed_batch_delegates() -> None:
    """async_unlink_seed_batch forwards to genetics_manager."""
    coordinator = _make_coordinator()
    facade = GeneticsFacade(coordinator)

    await facade.async_unlink_seed_batch("p1")

    coordinator.genetics_manager.async_unlink_seed_batch.assert_awaited_once_with("p1")


# ---------------------------------------------------------------------------
# ServiceFacade integration
# ---------------------------------------------------------------------------


def test_service_facade_exposes_genetics() -> None:
    """coordinator.services.genetics is a GeneticsFacade instance."""
    from custom_components.growspace_manager.services.facade import ServiceFacade

    coordinator = _make_coordinator()
    coordinator.nutrient_manager = MagicMock()
    coordinator.ipm_service = MagicMock()
    coordinator.notification_manager = MagicMock()
    coordinator.notification_settings = MagicMock()
    coordinator.notification_state = MagicMock()
    coordinator.growspaces = {}
    coordinator.strain_library = None
    coordinator.data_repository = MagicMock()
    coordinator.growspace_manager = MagicMock()
    coordinator.validator = MagicMock()
    coordinator.config_entry = MagicMock()
    coordinator.hass = MagicMock()
    coordinator.watering_service = MagicMock()
    coordinator.subsystem_manager = MagicMock()

    services = ServiceFacade(coordinator)

    assert isinstance(services.genetics, GeneticsFacade)
