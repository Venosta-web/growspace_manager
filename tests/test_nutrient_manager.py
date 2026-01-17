"""Tests for the Nutrient Manager."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.managers.nutrient import NutrientManager
from custom_components.growspace_manager.models import (
    IPMPreset,
    NutrientInventory,
    NutrientPreset,
)
from .conftest import create_plant



@pytest.fixture
def mock_coordinator():
    mock = MagicMock()
    mock.async_save = AsyncMock()
    mock.plants = {}
    return mock


@pytest.fixture
def manager(mock_coordinator):
    return NutrientManager(mock_coordinator)


@pytest.mark.asyncio
async def test_load_data(manager) -> None:
    presets = {
        "p1": NutrientPreset(
            id="p1", name="Preset 1", items=[], created_at="2024-01-01"
        )
    }
    ipm = {
        "i1": IPMPreset(
            id="i1", name="IPM 1", type="spray", items=[], created_at="2024-01-01"
        )
    }
    inv = NutrientInventory()

    manager.load_data(presets, ipm, inv)

    assert manager.presets == presets
    assert manager.ipm_presets == ipm
    assert manager.inventory == inv
    assert manager.inventory_service is not None


@pytest.mark.asyncio
async def test_save_nutrient_preset_new(manager, mock_coordinator) -> None:
    preset = await manager.async_save_nutrient_preset(
        name="New Preset",
        nutrients=[{"name": "N1", "dose_ml_l": 2.0}],
        stage="veg",
        min_days_in_stage=5,
    )

    assert preset.id in manager.presets
    assert preset.name == "New Preset"
    assert preset.stage == "veg"
    mock_coordinator.async_save.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_nutrient_preset_update(manager, mock_coordinator) -> None:
    # Setup existing
    existing = NutrientPreset(
        id="p1", name="Old Name", items=[], created_at="2024-01-01"
    )
    manager.presets = {"p1": existing}

    await manager.async_save_nutrient_preset(
        preset_id="p1",
        name="New Name",
        nutrients=[{"name": "N1", "dose_ml_l": 3.0}],
        stage="flower",
    )

    updated = manager.presets["p1"]
    assert updated.name == "New Name"
    assert updated.stage == "flower"
    mock_coordinator.async_save.assert_awaited_once()


@pytest.mark.asyncio
async def test_remove_nutrient_preset(manager, mock_coordinator) -> None:
    existing = NutrientPreset(
        id="p1", name="Old Name", items=[], created_at="2024-01-01"
    )
    manager.presets = {"p1": existing}

    await manager.async_remove_nutrient_preset("p1")

    assert "p1" not in manager.presets
    mock_coordinator.async_save.assert_awaited_once()


@pytest.mark.asyncio
async def test_remove_nutrient_preset_not_found(manager) -> None:
    with pytest.raises(KeyError):
        await manager.async_remove_nutrient_preset("unknown")


@pytest.mark.asyncio
async def test_save_ipm_preset(manager, mock_coordinator) -> None:
    preset = await manager.async_save_ipm_preset(
        name="New IPM", type="spray", items=[{"name": "Oil", "dose": 5.0}], stage="veg"
    )

    assert preset.id in manager.ipm_presets
    assert preset.name == "New IPM"
    assert preset.type == "spray"
    mock_coordinator.async_save.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_ipm_preset_update(manager, mock_coordinator) -> None:
    existing = IPMPreset(
        id="i1", name="Old IPM", type="spray", items=[], created_at="2024-01-01"
    )
    manager.ipm_presets = {"i1": existing}

    await manager.async_save_ipm_preset(
        preset_id="i1",
        name="New IPM",
        type="drench",
        items=[],
    )

    updated = manager.ipm_presets["i1"]
    assert updated.name == "New IPM"
    assert updated.type == "drench"


@pytest.mark.asyncio
async def test_remove_ipm_preset(manager, mock_coordinator) -> None:
    existing = IPMPreset(
        id="i1", name="Old IPM", type="spray", items=[], created_at="2024-01-01"
    )
    manager.ipm_presets = {"i1": existing}

    await manager.async_remove_ipm_preset("i1")

    assert "i1" not in manager.ipm_presets
    mock_coordinator.async_save.assert_awaited_once()


@pytest.mark.asyncio
async def test_remove_ipm_preset_not_found(manager) -> None:
    with pytest.raises(KeyError):
        await manager.async_remove_ipm_preset("unknown")


def test_get_applicable_presets(manager, mock_coordinator) -> None:
    # Setup plant as Mock to allow method overriding
    plant = MagicMock()
    plant.strain = "Strain A"
    plant.stage = "veg"
    plant.veg_start = "2024-01-01"
    plant.growspace_id = "gs1"
    mock_coordinator.plants["plant1"] = plant

    # Setup presets
    # 1. Matches stage (veg)
    p1 = NutrientPreset(
        id="p1", name="Veg Preset", items=[], stage="veg", created_at="2024-01-01"
    )
    # 2. Mismatch stage (flower)
    p2 = NutrientPreset(
        id="p2", name="Flower Preset", items=[], stage="flower", created_at="2024-01-01"
    )
    # 3. Matches stage, mismatch days (min 20 days, plant has ~0/mocked)
    p3 = NutrientPreset(
        id="p3",
        name="Late Veg",
        items=[],
        stage="veg",
        min_days_in_stage=20,
        created_at="2024-01-01",
    )
    # 4. No stage filter (applies to all)
    p4 = NutrientPreset(id="p4", name="General", items=[], created_at="2024-01-01")

    manager.presets = {"p1": p1, "p2": p2, "p3": p3, "p4": p4}

    # Mock plant days calculation
    # Return 10 days for veg
    plant.get_days_in_stage.return_value = 10

    applicable = manager.get_applicable_presets("plant1")

    # Should get p1 (veg match), p4 (no filter)
    # p2 (flower mismatch) skipped
    # p3 (min days 20 > 10) skipped
    ids = {p.id for p in applicable}
    assert "p1" in ids
    assert "p4" in ids
    assert "p2" not in ids
    assert "p3" not in ids


def test_get_applicable_presets_plant_not_found(manager) -> None:
    with pytest.raises(ValueError):
        manager.get_applicable_presets("non_existent")


def test_resolve_nutrient_mix(manager) -> None:
    # Setup preset
    p1 = NutrientPreset(
        id="p1",
        name="Base",
        items=[{"name": "A", "dose_ml_l": 2.0}],
        created_at="2024-01-01",
    )
    manager.presets = {"p1": p1}

    # 1. Preset only
    mix, name = manager.resolve_nutrient_mix(None, "p1")
    assert mix == {"A": 2.0}
    assert name == "Base"

    # 2. Preset + Override
    mix, name = manager.resolve_nutrient_mix({"B": 1.0, "A": 3.0}, "p1")
    assert mix["A"] == 3.0  # Override
    assert mix["B"] == 1.0
    assert name == "Base"

    # 3. No preset
    mix, name = manager.resolve_nutrient_mix({"C": 5.0}, None)
    assert mix == {"C": 5.0}
    assert name is None


def test_resolve_nutrient_mix_not_found(manager) -> None:
    with pytest.raises(KeyError):
        manager.resolve_nutrient_mix(None, "missing_preset")


def test_deduct_from_inventory(manager) -> None:
    # Mock inventory service
    manager.inventory_service = MagicMock()

    nutrients = {"A": 2.0, "B": 1.0}
    amount_liters = 10.0

    manager.deduct_from_inventory(nutrients, amount_liters)

    # Check calls
    # A: 2.0 * 10 = 20.0
    # B: 1.0 * 10 = 10.0
    calls = manager.inventory_service.deduct_usage.call_args_list
    # Order not guaranteed, check content
    assert len(calls) == 2


def test_get_serialization_data(manager) -> None:
    p1 = NutrientPreset(id="p1", name="P1", items=[], created_at="2024-01-01")
    i1 = IPMPreset(id="i1", name="I1", type="spray", items=[], created_at="2024-01-01")
    inventory = NutrientInventory()

    manager.presets = {"p1": p1}
    manager.ipm_presets = {"i1": i1}
    manager.inventory = inventory

    data = manager.get_serialization_data()

    assert "p1" in data["nutrient_presets"]
    assert "i1" in data["ipm_presets"]
    assert "stocks" in data["nutrient_inventory"]


@pytest.mark.asyncio
async def test_cache_invalidation(manager, mock_coordinator) -> None:
    """Test cache invalidation on save/remove."""
    # Setup cache mock - must be a Mock object to have methods like clear
    mock_coordinator._serialized_cache = MagicMock()

    # Save
    await manager.async_save_nutrient_preset("Test", [])
    mock_coordinator._serialized_cache.clear.assert_called_once()

    # Reset
    mock_coordinator._serialized_cache.reset_mock()

    await manager.async_save_nutrient_preset("Test 2", [])
    mock_coordinator._serialized_cache.clear.assert_called_once()

    # Reset
    mock_coordinator._serialized_cache.reset_mock()

    await manager.async_remove_nutrient_preset(list(manager.presets.keys())[0])
    mock_coordinator._serialized_cache.clear.assert_called_once()
