"""Tests for nutrient preset item migration (name → nutrient_id)."""

import pytest

from custom_components.growspace_manager.models import (
    NutrientInventory,
    NutrientPreset,
    NutrientStock,
)
from custom_components.growspace_manager.storage_manager import _migrate_preset_items


@pytest.fixture
def inventory_with_two_stocks() -> NutrientInventory:
    inventory = NutrientInventory()
    inventory.stocks = {
        "uuid-grow-a": NutrientStock(
            nutrient_id="uuid-grow-a",
            name="Grow A",
            current_ml=500.0,
            initial_ml=1000.0,
            last_updated="2024-01-01T00:00:00",
        ),
        "uuid-bloom-b": NutrientStock(
            nutrient_id="uuid-bloom-b",
            name="Bloom B",
            current_ml=300.0,
            initial_ml=1000.0,
            last_updated="2024-01-01T00:00:00",
        ),
    }
    return inventory


def _make_preset(items: list[dict]) -> NutrientPreset:
    return NutrientPreset(
        id="preset-1",
        name="Test Preset",
        items=items,
        created_at="2024-01-01T00:00:00",
    )


def test_migration_full_match_resolves_all_items(
    inventory_with_two_stocks: NutrientInventory,
) -> None:
    """All name-based items are resolved to nutrient_id when names match inventory."""
    preset = _make_preset([
        {"name": "Grow A", "dose_ml_l": 2.0},
        {"name": "Bloom B", "dose_ml_l": 1.5},
    ])
    presets = {"preset-1": preset}

    result = _migrate_preset_items(presets, inventory_with_two_stocks)

    items = result["preset-1"].items
    assert items[0] == {"nutrient_id": "uuid-grow-a", "dose_ml_l": 2.0}
    assert items[1] == {"nutrient_id": "uuid-bloom-b", "dose_ml_l": 1.5}


def test_migration_partial_match_preserves_orphan_name(
    inventory_with_two_stocks: NutrientInventory,
) -> None:
    """Matched items get nutrient_id; unmatched items keep original name as nutrient_id."""
    preset = _make_preset([
        {"name": "Grow A", "dose_ml_l": 2.0},
        {"name": "Unknown Cal Mag", "dose_ml_l": 0.5},
    ])
    presets = {"preset-1": preset}

    result = _migrate_preset_items(presets, inventory_with_two_stocks)

    items = result["preset-1"].items
    assert items[0] == {"nutrient_id": "uuid-grow-a", "dose_ml_l": 2.0}
    assert items[1] == {"nutrient_id": "Unknown Cal Mag", "dose_ml_l": 0.5}


def test_migration_no_match_all_orphaned(
    inventory_with_two_stocks: NutrientInventory,
) -> None:
    """When no names match, all items are preserved with original name as nutrient_id."""
    preset = _make_preset([
        {"name": "Mystery A", "dose_ml_l": 1.0},
        {"name": "Mystery B", "dose_ml_l": 2.0},
    ])
    presets = {"preset-1": preset}

    result = _migrate_preset_items(presets, inventory_with_two_stocks)

    items = result["preset-1"].items
    assert items[0] == {"nutrient_id": "Mystery A", "dose_ml_l": 1.0}
    assert items[1] == {"nutrient_id": "Mystery B", "dose_ml_l": 2.0}


def test_migration_already_migrated_items_untouched(
    inventory_with_two_stocks: NutrientInventory,
) -> None:
    """Items that already have nutrient_id are not modified."""
    preset = _make_preset([
        {"nutrient_id": "uuid-grow-a", "dose_ml_l": 2.0},
    ])
    presets = {"preset-1": preset}

    result = _migrate_preset_items(presets, inventory_with_two_stocks)

    assert result["preset-1"].items[0] == {"nutrient_id": "uuid-grow-a", "dose_ml_l": 2.0}


def test_migration_case_insensitive_name_match(
    inventory_with_two_stocks: NutrientInventory,
) -> None:
    """Name matching is case-insensitive."""
    preset = _make_preset([
        {"name": "grow a", "dose_ml_l": 2.0},
        {"name": "BLOOM B", "dose_ml_l": 1.5},
    ])
    presets = {"preset-1": preset}

    result = _migrate_preset_items(presets, inventory_with_two_stocks)

    items = result["preset-1"].items
    assert items[0]["nutrient_id"] == "uuid-grow-a"
    assert items[1]["nutrient_id"] == "uuid-bloom-b"


def test_migration_empty_inventory_all_orphaned() -> None:
    """With empty inventory, all items become orphans using their name as nutrient_id."""
    preset = _make_preset([{"name": "Grow A", "dose_ml_l": 2.0}])
    presets = {"preset-1": preset}

    result = _migrate_preset_items(presets, NutrientInventory())

    assert result["preset-1"].items[0] == {"nutrient_id": "Grow A", "dose_ml_l": 2.0}


def test_migration_empty_presets_is_noop() -> None:
    """Migration on empty preset dict returns empty dict without error."""
    result = _migrate_preset_items({}, NutrientInventory())
    assert result == {}


# ---------------------------------------------------------------------------
# NutrientPreset.get_nutrient_map — produces {nutrient_id: dose} map
# ---------------------------------------------------------------------------


def test_get_nutrient_map_returns_nutrient_id_keyed_dict() -> None:
    """get_nutrient_map returns {nutrient_id: dose_ml_l} after migration."""
    from custom_components.growspace_manager.models.types import NutrientPresetItem

    preset = NutrientPreset(
        id="p1",
        name="Bloom",
        items=[
            NutrientPresetItem(nutrient_id="id-a", dose_ml_l=2.0),
            NutrientPresetItem(nutrient_id="id-b", dose_ml_l=1.5),
        ],
        created_at="2024-01-01T00:00:00",
    )

    result = preset.get_nutrient_map()

    assert result == {"id-a": 2.0, "id-b": 1.5}


# ---------------------------------------------------------------------------
# NutrientPreset deserialization — nutrients key maps to items
# ---------------------------------------------------------------------------


def test_nutrient_preset_from_dict_with_nutrients_key() -> None:
    """NutrientPreset.from_dict accepts 'nutrients' key (storage format) as items."""
    data = {
        "id": "p1",
        "name": "Test",
        "nutrients": [{"nutrient_id": "id-a", "dose_ml_l": 2.0}],
        "week": 1,
        "created_at": "2024-01-01T00:00:00",
    }

    preset = NutrientPreset.from_dict(data)

    assert len(preset.items) == 1
    assert preset.items[0]["nutrient_id"] == "id-a"
