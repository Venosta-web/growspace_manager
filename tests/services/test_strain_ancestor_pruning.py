"""Pruning of Ancestor Strains once their last lineage reference is gone.

An Ancestor Strain (``strains.is_stub = 1``) exists only to hold a position in
someone's lineage. Two things create them: the seedfinder import, which inserts
a stub per ancestor node, and ``remove_strain``, which demotes a Catalogued
Strain that is still referenced by another lineage. Both are exercised here.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest

from custom_components.growspace_manager.strain_library import StrainLibrary


@pytest.fixture
def mock_hass() -> MagicMock:
    """Mock Home Assistant instance."""
    hass = MagicMock()
    hass.config.path = MagicMock(side_effect=lambda *args: "/".join(args))
    hass.async_add_executor_job = AsyncMock(side_effect=lambda f, *args: f(*args))
    hass.config_entries.async_entries = MagicMock(return_value=[])
    return hass


@pytest.fixture
async def strain_library(mock_hass: MagicMock) -> Any:
    """A StrainLibrary backed by an in-memory database."""
    real_connect = aiosqlite.connect

    async def mock_connect(database: str, **kwargs: Any) -> Any:
        return await real_connect(":memory:", **kwargs)

    with (
        patch(
            "custom_components.growspace_manager.strain_library.ImageManager",
            return_value=MagicMock(
                delete_image=MagicMock(),
                async_setup=AsyncMock(),
                async_migrate_to_webp=AsyncMock(return_value=False),
            ),
        ),
        patch(
            "custom_components.growspace_manager.strain_library.ImportExportManager",
            return_value=MagicMock(),
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


def _node(name: str, *parents: dict[str, Any]) -> dict[str, Any]:
    """Build a lineage_tree node."""
    return {"name": name, "parents": list(parents)}


async def _strain_names(library: StrainLibrary) -> set[str]:
    """Every strain row currently in the database."""
    async with library._db.execute("SELECT strain_name FROM strains") as cursor:
        return {row[0] for row in await cursor.fetchall()}


async def _stub_names(library: StrainLibrary) -> set[str]:
    """Every Ancestor Strain (stub) row currently in the database."""
    async with library._db.execute(
        "SELECT strain_name FROM strains WHERE is_stub = 1"
    ) as cursor:
        return {row[0] for row in await cursor.fetchall()}


async def _orphan_phenotype_count(library: StrainLibrary) -> int:
    """Phenotype rows whose strain no longer exists."""
    async with library._db.execute(
        """
        SELECT COUNT(*) FROM phenotypes p
        WHERE NOT EXISTS (SELECT 1 FROM strains s WHERE s.strain_id = p.strain_id)
        """
    ) as cursor:
        return (await cursor.fetchone())[0]


async def _add_root(library: StrainLibrary, name: str = "Root") -> None:
    """Add a Catalogued Strain to hang a lineage off."""
    await library.add_strain(name, "default", breeder="Breeder")


async def _import_chain(library: StrainLibrary, root: str = "Root") -> None:
    """Import Root <- Parent <- Grandparent, creating two ancestor stubs."""
    await library.async_import_seedfinder_lineage_tree(
        root, _node(root, _node("Parent", _node("Grandparent")))
    )


@pytest.mark.asyncio
async def test_final_reference_removal_prunes_the_ancestor(
    strain_library: StrainLibrary,
) -> None:
    """Dropping the last lineage referencing an ancestor deletes it."""
    await _add_root(strain_library)
    await _import_chain(strain_library)
    assert await _stub_names(strain_library) == {"Parent", "Grandparent"}

    await strain_library.update_strain_lineage_tree("Root", [])

    assert await _stub_names(strain_library) == set()
    assert await _strain_names(strain_library) == {"Root"}


@pytest.mark.asyncio
async def test_ancestor_shared_by_another_lineage_survives(
    strain_library: StrainLibrary,
) -> None:
    """An ancestor another strain still descends from is kept.

    Both ancestors are flat, one level up, so this isolates sharing from the
    recursive-ancestry rule covered by the next test.
    """
    await _add_root(strain_library, "Root")
    await _add_root(strain_library, "Sibling")
    await strain_library.async_import_seedfinder_lineage_tree(
        "Root", _node("Root", _node("Shared"), _node("RootOnly"))
    )
    await strain_library.async_import_seedfinder_lineage_tree(
        "Sibling", _node("Sibling", _node("Shared"))
    )

    await strain_library.update_strain_lineage_tree("Root", [])

    # Sibling still descends from Shared; nothing references RootOnly.
    assert await _stub_names(strain_library) == {"Shared"}


@pytest.mark.asyncio
async def test_recursively_required_ancestors_are_kept(
    strain_library: StrainLibrary,
) -> None:
    """Ancestors of a retained ancestor are not pruned."""
    await _add_root(strain_library, "Root")
    await _add_root(strain_library, "Sibling")
    await strain_library.async_import_seedfinder_lineage_tree(
        "Root", _node("Root", _node("Parent", _node("Grandparent")))
    )
    await strain_library.async_import_seedfinder_lineage_tree(
        "Sibling", _node("Sibling", _node("Parent", _node("Grandparent")))
    )

    await strain_library.update_strain_lineage_tree("Root", [])

    # Sibling keeps Parent alive, and Parent's own ancestry keeps Grandparent.
    assert await _stub_names(strain_library) == {"Parent", "Grandparent"}


@pytest.mark.asyncio
async def test_catalogued_strain_is_never_pruned(
    strain_library: StrainLibrary,
) -> None:
    """A Catalogued Strain with no descendants is left alone."""
    await _add_root(strain_library, "Root")
    await _add_root(strain_library, "Lonely")
    await _import_chain(strain_library, "Root")

    await strain_library.update_strain_lineage_tree("Root", [])

    assert "Lonely" in await _strain_names(strain_library)
    assert await _stub_names(strain_library) == set()


@pytest.mark.asyncio
async def test_pruning_cascades_through_a_chain(
    strain_library: StrainLibrary,
) -> None:
    """Deleting a stub orphans its own ancestors, which go in the same call."""
    await _add_root(strain_library)
    await strain_library.async_import_seedfinder_lineage_tree(
        "Root",
        _node("Root", _node("P1", _node("P2", _node("P3", _node("P4"))))),
    )
    assert await _stub_names(strain_library) == {"P1", "P2", "P3", "P4"}

    await strain_library.update_strain_lineage_tree("Root", [])

    assert await _stub_names(strain_library) == set()


@pytest.mark.asyncio
async def test_pruning_leaves_no_orphaned_phenotype_rows(
    strain_library: StrainLibrary,
) -> None:
    """The import gives each stub a 'default' phenotype; pruning clears it."""
    await _add_root(strain_library)
    await _import_chain(strain_library)
    assert await _orphan_phenotype_count(strain_library) == 0

    await strain_library.update_strain_lineage_tree("Root", [])

    assert await _orphan_phenotype_count(strain_library) == 0


@pytest.mark.asyncio
async def test_import_does_not_prune_the_stubs_it_just_created(
    strain_library: StrainLibrary,
) -> None:
    """Pruning runs after the whole import, not per rebuilt node."""
    await _add_root(strain_library)
    await _import_chain(strain_library)

    assert await _stub_names(strain_library) == {"Parent", "Grandparent"}
    async with strain_library._db.execute(
        "SELECT COUNT(*) FROM strain_ancestry sa"
        " WHERE NOT EXISTS ("
        "   SELECT 1 FROM strains s WHERE s.strain_name = sa.ancestor_name"
        " )"
    ) as cursor:
        dangling = (await cursor.fetchone())[0]
    assert dangling == 0


@pytest.mark.asyncio
async def test_add_strain_lineage_replacement_prunes(
    strain_library: StrainLibrary,
) -> None:
    """The add_strain upsert path prunes too, not just the lineage-tree path."""
    await _add_root(strain_library)
    await _import_chain(strain_library)

    await strain_library.add_strain(
        "Root",
        "default",
        lineage_tree=_node("Root"),
    )

    assert await _stub_names(strain_library) == set()


@pytest.mark.asyncio
async def test_remove_strain_prunes_ancestors_it_orphans(
    strain_library: StrainLibrary,
) -> None:
    """Deleting the only descendant prunes the ancestors it leaves behind."""
    await _add_root(strain_library)
    await _import_chain(strain_library)

    await strain_library.remove_strain("Root")

    assert await _strain_names(strain_library) == set()


@pytest.mark.asyncio
async def test_demoted_strain_is_not_pruned_while_referenced(
    strain_library: StrainLibrary,
) -> None:
    """remove_strain demotes a referenced strain; the prune must not undo that."""
    await _add_root(strain_library, "Parent")
    await _add_root(strain_library, "Child")
    await strain_library.async_import_seedfinder_lineage_tree(
        "Child", _node("Child", _node("Parent"))
    )

    await strain_library.remove_strain("Parent")

    # Demoted to an ancestor stub, but Child still descends from it.
    assert "Parent" in await _stub_names(strain_library)


@pytest.mark.asyncio
async def test_import_for_an_unknown_root_keeps_its_stubs(
    strain_library: StrainLibrary,
) -> None:
    """A root with no strains row yet must not lose the stubs just created.

    _rebuild_strain_ancestry early-returns when the root has no row, so nothing
    names the new stubs — only the protected set stands between them and the
    prune.
    """
    await strain_library.async_import_seedfinder_lineage_tree(
        "Ghost", _node("Ghost", _node("GhostParent"))
    )

    assert await _stub_names(strain_library) == {"GhostParent"}


@pytest.mark.asyncio
async def test_reimport_prunes_the_previous_trees_ancestors(
    strain_library: StrainLibrary,
) -> None:
    """Re-importing a lineage prunes the ancestors the old tree left behind."""
    await _add_root(strain_library)
    await strain_library.async_import_seedfinder_lineage_tree(
        "Root", _node("Root", _node("Old"))
    )
    assert await _stub_names(strain_library) == {"Old"}

    await strain_library.async_import_seedfinder_lineage_tree(
        "Root", _node("Root", _node("New"))
    )

    assert await _stub_names(strain_library) == {"New"}
