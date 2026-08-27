"""Tests for strain ancestry closure table (TDD)."""

from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest

from custom_components.growspace_manager.strain_library import (
    StrainLibrary,
    _collect_ancestors,
)


@pytest.fixture
def mock_hass():
    """Fixture for a mock Home Assistant instance."""
    hass = MagicMock()
    hass.config.path = MagicMock(side_effect=lambda *args: "/".join(args))
    hass.async_add_executor_job = MagicMock(side_effect=lambda f, *args: f(*args))
    return hass


@pytest.fixture
async def strain_library(mock_hass):
    """Fixture for a StrainLibrary instance with in-memory DB."""
    real_connect = aiosqlite.connect

    async def mock_connect(database, **kwargs):
        return await real_connect(":memory:", **kwargs)

    mock_image_manager = MagicMock()
    mock_image_manager.save_strain_image = AsyncMock(return_value=None)
    mock_image_manager.delete_image = MagicMock()
    mock_image_manager.async_migrate_to_webp = AsyncMock(return_value=False)
    mock_image_manager.async_setup = AsyncMock()

    mock_import_export_manager = MagicMock()

    with (
        patch(
            "custom_components.growspace_manager.strain_library.ImageManager",
            return_value=mock_image_manager,
        ),
        patch(
            "custom_components.growspace_manager.strain_library.ImportExportManager",
            return_value=mock_import_export_manager,
        ),
        patch(
            "custom_components.growspace_manager.strain_library.aiosqlite.connect",
            side_effect=mock_connect,
        ),
    ):
        library = StrainLibrary(mock_hass)
        await library.async_setup()
        yield library
        await library.async_close()


# --- Unit tests for _collect_ancestors ---


def test_collect_ancestors_empty_parents() -> None:
    """A leaf node with no parents yields no ancestors."""
    node = {"name": "OG Kush", "url": None, "parents": []}
    assert _collect_ancestors(node) == []


def test_collect_ancestors_single_level() -> None:
    """Direct parents appear at depth 1."""
    node = {
        "name": "Gelato",
        "parents": [
            {
                "name": "Thin Mint GSC",
                "url": "https://seedfinder.eu/tmc",
                "parents": [],
            },
            {
                "name": "Sunset Sherbet",
                "url": "https://seedfinder.eu/ss",
                "parents": [],
            },
        ],
    }
    result = _collect_ancestors(node)
    assert len(result) == 2
    names = {r[0] for r in result}
    assert names == {"Thin Mint GSC", "Sunset Sherbet"}
    depths = {r[2] for r in result}
    assert depths == {1}


def test_collect_ancestors_two_levels() -> None:
    """Grandparents appear at depth 2."""
    node = {
        "name": "Gelato",
        "parents": [
            {
                "name": "Thin Mint GSC",
                "url": None,
                "parents": [
                    {"name": "OG Kush", "url": None, "parents": []},
                    {"name": "Durban Poison", "url": None, "parents": []},
                ],
            },
            {"name": "Sunset Sherbet", "url": None, "parents": []},
        ],
    }
    result = _collect_ancestors(node)
    by_name = {r[0]: r[2] for r in result}
    assert by_name["Thin Mint GSC"] == 1
    assert by_name["Sunset Sherbet"] == 1
    assert by_name["OG Kush"] == 2
    assert by_name["Durban Poison"] == 2


def test_collect_ancestors_five_levels() -> None:
    """Ancestors at 5 levels deep are collected correctly."""

    def _make_chain(names: list[str]) -> dict:
        node: dict = {"name": names[-1], "url": None, "parents": []}
        for name in reversed(names[:-1]):
            node = {"name": name, "url": None, "parents": [node]}
        return node

    # Chain: A -> B -> C -> D -> E  (A is the strain, E is 5 levels deep)
    node = _make_chain(["A", "B", "C", "D", "E"])
    result = _collect_ancestors(node)
    by_name = {r[0]: r[2] for r in result}
    assert by_name["B"] == 1
    assert by_name["C"] == 2
    assert by_name["D"] == 3
    assert by_name["E"] == 4


def test_collect_ancestors_skips_blank_names() -> None:
    """Ancestors with empty names are skipped."""
    node = {
        "name": "Gelato",
        "parents": [
            {"name": "", "url": None, "parents": []},
            {"name": "  ", "url": None, "parents": []},
            {"name": "OG Kush", "url": None, "parents": []},
        ],
    }
    result = _collect_ancestors(node)
    assert len(result) == 1
    assert result[0][0] == "OG Kush"


# --- Integration tests for ancestry table population ---


@pytest.mark.asyncio
async def test_ancestry_populated_on_add_strain(strain_library: StrainLibrary) -> None:
    """Adding a strain with lineage_tree populates the ancestry table."""
    lineage_tree = {
        "name": "Gelato",
        "url": None,
        "parents": [
            {
                "name": "Thin Mint GSC",
                "url": "https://seedfinder.eu/tmc",
                "parents": [],
            },
            {"name": "Sunset Sherbet", "url": None, "parents": []},
        ],
    }
    await strain_library.add_strain("Gelato", lineage_tree=lineage_tree)

    async with strain_library._db.execute(
        "SELECT ancestor_name, depth FROM strain_ancestry ORDER BY ancestor_name"
    ) as cursor:
        rows = await cursor.fetchall()

    names = {row["ancestor_name"]: row["depth"] for row in rows}
    assert "Thin Mint GSC" in names
    assert "Sunset Sherbet" in names
    assert names["Thin Mint GSC"] == 1
    assert names["Sunset Sherbet"] == 1


@pytest.mark.asyncio
async def test_ancestry_multi_level(strain_library: StrainLibrary) -> None:
    """Ancestry table includes grandparent rows at depth 2."""
    lineage_tree = {
        "name": "Gelato",
        "parents": [
            {
                "name": "Thin Mint GSC",
                "url": None,
                "parents": [
                    {"name": "OG Kush", "url": None, "parents": []},
                ],
            },
            {"name": "Sunset Sherbet", "url": None, "parents": []},
        ],
    }
    await strain_library.add_strain("Gelato", lineage_tree=lineage_tree)

    async with strain_library._db.execute(
        "SELECT ancestor_name, depth FROM strain_ancestry ORDER BY depth, ancestor_name"
    ) as cursor:
        rows = await cursor.fetchall()

    by_name = {r["ancestor_name"]: r["depth"] for r in rows}
    assert by_name["Thin Mint GSC"] == 1
    assert by_name["Sunset Sherbet"] == 1
    assert by_name["OG Kush"] == 2


@pytest.mark.asyncio
async def test_ancestry_rebuilt_on_update(strain_library: StrainLibrary) -> None:
    """Updating a strain's lineage_tree replaces ancestry rows."""
    lineage_tree_v1 = {
        "name": "Gelato",
        "parents": [{"name": "Old Parent", "url": None, "parents": []}],
    }
    await strain_library.add_strain("Gelato", lineage_tree=lineage_tree_v1)

    lineage_tree_v2 = {
        "name": "Gelato",
        "parents": [{"name": "New Parent", "url": None, "parents": []}],
    }
    await strain_library.add_strain("Gelato", lineage_tree=lineage_tree_v2)

    async with strain_library._db.execute(
        "SELECT ancestor_name FROM strain_ancestry"
    ) as cursor:
        rows = await cursor.fetchall()

    names = {r["ancestor_name"] for r in rows}
    assert "New Parent" in names
    assert "Old Parent" not in names


@pytest.mark.asyncio
async def test_ancestry_not_populated_without_lineage_tree(
    strain_library: StrainLibrary,
) -> None:
    """Adding a strain without lineage_tree leaves ancestry table empty."""
    await strain_library.add_strain("Blue Dream")

    async with strain_library._db.execute(
        "SELECT COUNT(*) as n FROM strain_ancestry"
    ) as cursor:
        row = await cursor.fetchone()

    assert row["n"] == 0


# --- Integration tests for query methods ---


@pytest.mark.asyncio
async def test_get_strains_by_ancestor(strain_library: StrainLibrary) -> None:
    """Returns strains that have the given ancestor in their lineage."""
    og_kush_tree = {
        "name": "OG Kush",
        "parents": [{"name": "ChemDawg", "url": None, "parents": []}],
    }
    gelato_tree = {
        "name": "Gelato",
        "parents": [
            {
                "name": "Thin Mint GSC",
                "url": None,
                "parents": [{"name": "ChemDawg", "url": None, "parents": []}],
            }
        ],
    }
    await strain_library.add_strain("OG Kush", lineage_tree=og_kush_tree)
    await strain_library.add_strain("Gelato", lineage_tree=gelato_tree)
    await strain_library.add_strain("Blue Dream")  # no ChemDawg ancestry

    results = await strain_library.async_get_strains_by_ancestor("ChemDawg")

    result_names = {r["strain_name"] for r in results}
    assert "OG Kush" in result_names
    assert "Gelato" in result_names
    assert "Blue Dream" not in result_names


@pytest.mark.asyncio
async def test_get_strains_by_ancestor_returns_depth(
    strain_library: StrainLibrary,
) -> None:
    """Result includes depth field indicating how far the ancestor is."""
    tree = {
        "name": "Gelato",
        "parents": [
            {
                "name": "Thin Mint GSC",
                "url": None,
                "parents": [{"name": "OG Kush", "url": None, "parents": []}],
            }
        ],
    }
    await strain_library.add_strain("Gelato", lineage_tree=tree)

    results = await strain_library.async_get_strains_by_ancestor("OG Kush")
    assert len(results) == 1
    assert results[0]["strain_name"] == "Gelato"
    assert results[0]["depth"] == 2


@pytest.mark.asyncio
async def test_get_strains_by_ancestor_no_match(strain_library: StrainLibrary) -> None:
    """Returns empty list when no strains have the ancestor."""
    await strain_library.add_strain("Blue Dream")

    results = await strain_library.async_get_strains_by_ancestor("OG Kush")
    assert results == []


@pytest.mark.asyncio
async def test_get_shared_ancestors(strain_library: StrainLibrary) -> None:
    """Returns ancestors common to all given strains."""
    og_tree = {
        "name": "OG Kush",
        "parents": [
            {"name": "ChemDawg", "url": None, "parents": []},
            {"name": "Hindu Kush", "url": None, "parents": []},
        ],
    }
    gelato_tree = {
        "name": "Gelato",
        "parents": [
            {
                "name": "Thin Mint GSC",
                "url": None,
                "parents": [{"name": "ChemDawg", "url": None, "parents": []}],
            },
            {"name": "Sunset Sherbet", "url": None, "parents": []},
        ],
    }
    await strain_library.add_strain("OG Kush", lineage_tree=og_tree)
    await strain_library.add_strain("Gelato", lineage_tree=gelato_tree)

    async with strain_library._db.execute(
        "SELECT strain_id FROM strains WHERE strain_name IN ('OG Kush', 'Gelato')"
    ) as cursor:
        ids = [row["strain_id"] for row in await cursor.fetchall()]

    results = await strain_library.async_get_shared_ancestors(ids)

    ancestor_names = {r["ancestor_name"] for r in results}
    assert "ChemDawg" in ancestor_names
    assert "Hindu Kush" not in ancestor_names
    assert "Sunset Sherbet" not in ancestor_names


@pytest.mark.asyncio
async def test_get_shared_ancestors_returns_shallowest_depth(
    strain_library: StrainLibrary,
) -> None:
    """Shared ancestor depth is the minimum across all strains."""
    # OG Kush has ChemDawg at depth 1
    og_tree = {
        "name": "OG Kush",
        "parents": [{"name": "ChemDawg", "url": None, "parents": []}],
    }
    # Gelato has ChemDawg at depth 2 (via Thin Mint GSC)
    gelato_tree = {
        "name": "Gelato",
        "parents": [
            {
                "name": "Thin Mint GSC",
                "url": None,
                "parents": [{"name": "ChemDawg", "url": None, "parents": []}],
            }
        ],
    }
    await strain_library.add_strain("OG Kush", lineage_tree=og_tree)
    await strain_library.add_strain("Gelato", lineage_tree=gelato_tree)

    async with strain_library._db.execute(
        "SELECT strain_id FROM strains WHERE strain_name IN ('OG Kush', 'Gelato')"
    ) as cursor:
        ids = [row["strain_id"] for row in await cursor.fetchall()]

    results = await strain_library.async_get_shared_ancestors(ids)
    chemdawg = next(r for r in results if r["ancestor_name"] == "ChemDawg")
    assert chemdawg["closest_depth"] == 1


@pytest.mark.asyncio
async def test_get_shared_ancestors_empty_when_no_common(
    strain_library: StrainLibrary,
) -> None:
    """Returns empty list when strains share no ancestors."""
    tree_a = {
        "name": "A",
        "parents": [{"name": "Parent A", "url": None, "parents": []}],
    }
    tree_b = {
        "name": "B",
        "parents": [{"name": "Parent B", "url": None, "parents": []}],
    }
    await strain_library.add_strain("A", lineage_tree=tree_a)
    await strain_library.add_strain("B", lineage_tree=tree_b)

    async with strain_library._db.execute(
        "SELECT strain_id FROM strains WHERE strain_name IN ('A', 'B')"
    ) as cursor:
        ids = [row["strain_id"] for row in await cursor.fetchall()]

    results = await strain_library.async_get_shared_ancestors(ids)
    assert results == []
