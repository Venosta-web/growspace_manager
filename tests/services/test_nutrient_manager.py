"""Tests for the Nutrient Manager."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.managers.nutrient import NutrientManager
from custom_components.growspace_manager.models import (
    ECRampCurve,
    ECRampPoint,
    IPMPreset,
    NutrientInventory,
    NutrientPreset,
)


@pytest.fixture
def repository_mock():
    """Mock the GrowspaceRepository."""
    mock = MagicMock()
    mock.get_plant.return_value = None
    return mock


@pytest.fixture
def save_callback_mock():
    """Mock the save callback."""
    return AsyncMock()


@pytest.fixture
def manager(repository_mock, save_callback_mock):
    """NutrientManager fixture."""
    return NutrientManager(
        repository=repository_mock,
        save_callback=save_callback_mock,
    )


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

    assert manager.nutrient_presets == presets
    assert manager.ipm_presets == ipm
    assert manager.inventory == inv
    assert manager.inventory_service is not None


@pytest.mark.asyncio
async def test_load_data_with_ec_ramp_curves(manager) -> None:
    """Test that ec_ramp_curves are loaded when provided."""
    curves = {
        "c1": ECRampCurve(id="c1", name="Curve 1", stage="veg", created_at="2024-01-01")
    }

    manager.load_data({}, {}, None, ec_ramp_curves=curves)

    assert manager.ec_ramp_curves == curves


@pytest.mark.asyncio
async def test_save_nutrient_preset_new(manager, save_callback_mock) -> None:
    preset = await manager.async_save_nutrient_preset(
        name="New Preset",
        nutrients=[{"nutrient_id": "id-n1", "dose_ml_l": 2.0}],
        stage="veg",
        min_days_in_stage=5,
    )

    assert preset.id in manager.nutrient_presets
    assert preset.name == "New Preset"
    assert preset.stage == "veg"
    save_callback_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_nutrient_preset_update(manager, save_callback_mock) -> None:
    # Setup existing
    existing = NutrientPreset(
        id="p1", name="Old Name", items=[], created_at="2024-01-01"
    )
    manager.nutrient_presets = {"p1": existing}

    await manager.async_save_nutrient_preset(
        preset_id="p1",
        name="New Name",
        nutrients=[{"nutrient_id": "id-n1", "dose_ml_l": 3.0}],
        stage="flower",
    )

    updated = manager.nutrient_presets["p1"]
    assert updated.name == "New Name"
    assert updated.stage == "flower"
    save_callback_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_remove_nutrient_preset(manager, save_callback_mock) -> None:
    existing = NutrientPreset(
        id="p1", name="Old Name", items=[], created_at="2024-01-01"
    )
    manager.nutrient_presets = {"p1": existing}

    await manager.async_remove_nutrient_preset("p1")

    assert "p1" not in manager.nutrient_presets
    save_callback_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_remove_nutrient_preset_not_found(manager) -> None:
    with pytest.raises(KeyError):
        await manager.async_remove_nutrient_preset("unknown")


@pytest.mark.asyncio
async def test_save_ipm_preset(manager, save_callback_mock) -> None:
    preset = await manager.async_save_ipm_preset(
        name="New IPM",
        type="spray",
        items=[{"name": "Oil", "dose_amount": 5.0, "dose_unit": "ml/L"}],
        stage="veg",
    )

    assert preset.id in manager.ipm_presets
    assert preset.name == "New IPM"
    assert preset.type == "spray"
    save_callback_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_ipm_preset_update(manager, save_callback_mock) -> None:
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
async def test_remove_ipm_preset(manager, save_callback_mock) -> None:
    existing = IPMPreset(
        id="i1", name="Old IPM", type="spray", items=[], created_at="2024-01-01"
    )
    manager.ipm_presets = {"i1": existing}

    await manager.async_remove_ipm_preset("i1")

    assert "i1" not in manager.ipm_presets
    save_callback_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_remove_ipm_preset_not_found(manager) -> None:
    with pytest.raises(KeyError):
        await manager.async_remove_ipm_preset("unknown")


def test_get_applicable_presets(manager, repository_mock) -> None:
    # Setup plant as Mock to allow method overriding
    plant = MagicMock()
    plant.strain = "Strain A"
    plant.stage = "veg"
    plant.veg_start = "2024-01-01"
    plant.growspace_id = "gs1"
    repository_mock.get_plant.return_value = plant

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

    manager.nutrient_presets = {"p1": p1, "p2": p2, "p3": p3, "p4": p4}

    with patch(
        "custom_components.growspace_manager.managers.nutrient.resolve_stage_and_age",
        return_value=("veg", 10),
    ):
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
    p1 = NutrientPreset(
        id="p1",
        name="Base",
        items=[{"nutrient_id": "id-a", "dose_ml_l": 2.0}],
        created_at="2024-01-01",
    )
    manager.nutrient_presets = {"p1": p1}

    # 1. Preset only
    mix, name = manager.resolve_nutrient_mix(None, "p1")
    assert mix == {"id-a": 2.0}
    assert name == "Base"

    # 2. Preset + Override
    mix, name = manager.resolve_nutrient_mix({"id-b": 1.0, "id-a": 3.0}, "p1")
    assert mix["id-a"] == 3.0
    assert mix["id-b"] == 1.0
    assert name == "Base"

    # 3. No preset
    mix, name = manager.resolve_nutrient_mix({"id-c": 5.0}, None)
    assert mix == {"id-c": 5.0}
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
    manager.inventory_service.deduct_nutrients.assert_called_with(
        nutrients, amount_liters
    )


def test_deduct_from_inventory_exception(manager) -> None:
    """Test exception handling in deduct_from_inventory."""
    # Mock inventory service to raise an exception
    manager.inventory_service = MagicMock()
    manager.inventory_service.deduct_nutrients.side_effect = Exception("Test exception")

    nutrients = {"A": 2.0}
    # This should not raise an exception as it's caught inside deduct_from_inventory
    manager.deduct_from_inventory(nutrients, 1.0)

    manager.inventory_service.deduct_nutrients.assert_called_once()


def test_get_serialization_data(manager) -> None:
    p1 = NutrientPreset(id="p1", name="P1", items=[], created_at="2024-01-01")
    i1 = IPMPreset(id="i1", name="I1", type="spray", items=[], created_at="2024-01-01")
    inventory = NutrientInventory()

    manager.nutrient_presets = {"p1": p1}
    manager.ipm_presets = {"i1": i1}
    manager.inventory = inventory

    data = manager.get_serialization_data()

    assert "p1" in data["nutrient_presets"]
    assert "i1" in data["ipm_presets"]
    assert "stocks" in data["nutrient_inventory"]


@pytest.mark.asyncio
async def test_save_ec_ramp_curve_new(manager, save_callback_mock) -> None:
    """Test creating a new EC ramp curve."""
    curve = await manager.async_save_ec_ramp_curve(
        name="Bloom EC",
        stage="flower",
        points=[{"week": 1, "ec_min": 1.2, "ec_max": 1.6}],
    )

    assert curve.id in manager.ec_ramp_curves
    assert curve.name == "Bloom EC"
    assert curve.stage == "flower"
    assert len(curve.points) == 1
    assert curve.points[0].week == 1
    assert curve.points[0].ec_min == 1.2
    assert curve.points[0].ec_max == 1.6
    save_callback_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_ec_ramp_curve_update(manager, save_callback_mock) -> None:
    """Test updating an existing EC ramp curve."""
    existing = ECRampCurve(
        id="c1",
        name="Old Curve",
        stage="veg",
        points=[ECRampPoint(week=1, ec_min=0.8, ec_max=1.0)],
        created_at="2024-01-01",
    )
    manager.ec_ramp_curves = {"c1": existing}

    curve = await manager.async_save_ec_ramp_curve(
        curve_id="c1",
        name="Updated Curve",
        stage="flower",
        points=[{"week": 2, "ec_min": 1.4, "ec_max": 1.8}],
    )

    assert curve is existing
    assert curve.name == "Updated Curve"
    assert curve.stage == "flower"
    assert len(curve.points) == 1
    assert curve.points[0].week == 2
    save_callback_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_remove_ec_ramp_curve(manager, save_callback_mock) -> None:
    """Test removing an existing EC ramp curve."""
    existing = ECRampCurve(
        id="c1",
        name="My Curve",
        stage="veg",
        points=[],
        created_at="2024-01-01",
    )
    manager.ec_ramp_curves = {"c1": existing}

    await manager.async_remove_ec_ramp_curve("c1")

    assert "c1" not in manager.ec_ramp_curves
    save_callback_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_remove_ec_ramp_curve_not_found(manager) -> None:
    """Test that removing a non-existent EC ramp curve raises KeyError."""
    with pytest.raises(KeyError):
        await manager.async_remove_ec_ramp_curve("missing")


@pytest.mark.asyncio
async def test_cache_invalidation(manager, save_callback_mock) -> None:
    """Test that save_callback is called (which handles invalidation)."""
    # Save
    await manager.async_save_nutrient_preset("Test", [])
    save_callback_mock.assert_awaited_once()

    # Reset
    save_callback_mock.reset_mock()

    await manager.async_save_nutrient_preset("Test 2", [])
    save_callback_mock.assert_awaited_once()

    # Reset
    save_callback_mock.reset_mock()

    await manager.async_remove_nutrient_preset(list(manager.nutrient_presets.keys())[0])
    save_callback_mock.assert_awaited_once()
