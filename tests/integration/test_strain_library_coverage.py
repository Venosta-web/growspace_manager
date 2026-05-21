from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.strain_library import StrainLibrary


@pytest.fixture
def mock_hass():
    hass = MagicMock()
    hass.config.path.return_value = "/tmp/test_db.sqlite"  # noqa: S108
    return hass


@pytest.mark.asyncio
async def test_library_methods_no_db(mock_hass) -> None:
    """Test library methods when database is not connected."""
    lib = StrainLibrary(mock_hass)
    # Ensure db is None
    lib._db = None

    # 1. load
    await lib.load()
    # Log warning should be emitted, but no error raised

    # 2. record_harvest
    await lib.record_harvest("Strain A", "Pheno 1", 30, 60)

    # 3. add_strain
    await lib.add_strain("Strain B")

    # 4. remove_strain_phenotype
    await lib.remove_strain_phenotype("Strain A", "Pheno 1")

    # 5. remove_strain
    await lib.remove_strain("Strain A")

    # 6. import_library
    result = await lib.import_library({"Strain A": {}})
    assert result == 0

    # 7. clear
    count = await lib.clear()
    assert count == 0

    # 8. ensure_strain_and_phenotype_exist (internal)
    with pytest.raises(RuntimeError, match="Database not connected"):
        await lib._ensure_strain_and_phenotype_exist("S", "P")

    # 9. import_strains with list check (though covered by type hint usually, explicit None check in code?)
    # The code has `if not isinstance(strains, list): return 0`
    assert await lib.import_strains("not a list") == 0


@pytest.mark.asyncio
async def test_ensure_phenotype_creation_failure(mock_hass) -> None:
    """Test failure to retrieve phenotype ID after insertion."""
    lib = StrainLibrary(mock_hass)

    # Mock DB connection
    mock_db = MagicMock()
    mock_db.commit = AsyncMock()
    lib._db = mock_db

    # Helper to mock an object that is both awaitable and an async context manager
    class AwaitableAsyncContextManager:
        def __init__(self, mock_cursor) -> None:
            self.mock_cursor = mock_cursor

        def __await__(self):
            async def _return_cursor():
                return self.mock_cursor

            return _return_cursor().__await__()

        async def __aenter__(self):
            return self.mock_cursor

        async def __aexit__(self, exc_type, exc, tb):
            pass

    # Mock cursor
    mock_cursor = AsyncMock()

    # Configure fetchone side effects later

    # Mock execute to return the helper
    mock_db.execute = MagicMock(return_value=AwaitableAsyncContextManager(mock_cursor))

    # Scenario:
    # 1. Check strain -> Found (return strain_id)
    # 2. Check phenotype -> Not Found
    # 3. Insert phenotype -> Success
    # 4. Check phenotype again -> Still Not Found (Simulation of race condition or failure)

    mock_cursor.fetchone = AsyncMock(
        side_effect=[
            (1,),  # Strain ID found
            None,  # Phenotype not found first time
            None,  # Phenotype still not found after insert
        ]
    )

    with pytest.raises(RuntimeError, match="Failed to retrieve phenotype ID"):
        await lib._ensure_strain_and_phenotype_exist("StrainX", "PhenoY")


@pytest.mark.asyncio
async def test_hybrid_percentage_validation(mock_hass) -> None:
    """Test hybrid percentage validation error."""
    lib = StrainLibrary(mock_hass)
    lib._db = MagicMock()  # Connected

    with pytest.raises(
        ValueError, match="Combined Sativa/Indica percentage cannot exceed 100%"
    ):
        await lib.add_strain(
            "Hybrid Strain",
            strain_type="Hybrid",
            sativa_percentage=60,
            indica_percentage=60,
        )


@pytest.mark.asyncio
async def test_load_invalid_lineage_tree_json(mock_hass) -> None:
    """Test that invalid lineage_tree JSON is silently set to None (lines 311-312)."""
    lib = StrainLibrary(mock_hass)

    class FakeRow(dict):
        def __getitem__(self, key: str):
            return super().__getitem__(key)

    bad_row = FakeRow(
        strain_id=1,
        strain_name="Bad Lineage",
        lineage_tree="not valid json{{{",
        breeder=None,
        breeder_logo=None,
        type=None,
        lineage=None,
        sex=None,
        generation=None,
        sativa_percentage=None,
        indica_percentage=None,
        yield_potential=None,
        height=None,
        thc=None,
        cbd=None,
        cbg=None,
        description=None,
        strain_description=None,
        is_stub=0,
        awards=None,
        effects=None,
        aroma=None,
        taste=None,
        phenotype_id=None,
        phenotype_name=None,
    )

    mock_cursor = AsyncMock()
    # First fetchall call is the migration query (return empty → no-op), second is main load
    mock_cursor.fetchall = AsyncMock(side_effect=[[], [bad_row]])

    class AsyncCM:
        async def __aenter__(self):
            return mock_cursor

        async def __aexit__(self, *a):
            pass

    mock_db = MagicMock()
    mock_db.execute = MagicMock(return_value=AsyncCM())
    lib._db = mock_db

    await lib.load()
    # Strain should be stored without lineage_tree key (or with it absent)
    assert "Bad Lineage" in lib.strains


@pytest.mark.asyncio
async def test_load_invalid_array_json_fields(mock_hass) -> None:
    """Test that invalid JSON in awards/effects/aroma/taste falls back to [] (lines 342-343)."""
    lib = StrainLibrary(mock_hass)

    class FakeRow(dict):
        def __getitem__(self, key: str):
            return super().__getitem__(key)

    bad_row = FakeRow(
        strain_id=2,
        strain_name="Bad Arrays",
        lineage_tree=None,
        breeder=None,
        breeder_logo=None,
        type=None,
        lineage=None,
        sex=None,
        generation=None,
        sativa_percentage=None,
        indica_percentage=None,
        yield_potential=None,
        height=None,
        thc=None,
        cbd=None,
        cbg=None,
        description=None,
        strain_description=None,
        is_stub=0,
        awards="[invalid",
        effects=123,  # TypeError: not a string
        aroma="{broken",
        taste=None,
        phenotype_id=None,
        phenotype_name=None,
    )

    mock_cursor = AsyncMock()
    # First fetchall call is the migration query (return empty → no-op), second is main load
    mock_cursor.fetchall = AsyncMock(side_effect=[[], [bad_row]])

    class AsyncCM:
        async def __aenter__(self):
            return mock_cursor

        async def __aexit__(self, *a):
            pass

    mock_db = MagicMock()
    mock_db.execute = MagicMock(return_value=AsyncCM())
    lib._db = mock_db

    await lib.load()
    meta = lib.strains["Bad Arrays"]["meta"]
    assert meta["awards"] == []
    assert meta["effects"] == []
    assert meta["aroma"] == []


@pytest.mark.asyncio
async def test_load_filters_404_image_path(mock_hass) -> None:
    """=404 placeholder image_paths must not be stored in self.strains (regression test)."""

    class FakeRow(dict):
        def __getitem__(self, key: str):
            return super().__getitem__(key)

    row = FakeRow(
        strain_id=1,
        strain_name="Paradise Seeds Strain",
        lineage_tree=None,
        breeder="Paradise Seeds",
        breeder_logo=None,
        type=None,
        lineage=None,
        sex=None,
        generation=None,
        sativa_percentage=None,
        indica_percentage=None,
        yield_potential=None,
        height=None,
        thc=None,
        cbd=None,
        cbg=None,
        description=None,
        strain_description=None,
        is_stub=0,
        awards=None,
        effects=None,
        aroma=None,
        taste=None,
        phenotype_id=1,
        phenotype_name="default",
        image_path="https://seedfinder.eu/storage/pics/01seeds/Paradise_Seeds/=404",
        image_crop_meta=None,
        flower_days_min=None,
        flower_days_max=None,
        images=None,
    )

    mock_cursor = AsyncMock()
    mock_cursor.fetchall = AsyncMock(return_value=[row])

    class AsyncCM:
        async def __aenter__(self):
            return mock_cursor

        async def __aexit__(self, *a):
            pass

    mock_db = MagicMock()
    mock_db.execute = MagicMock(return_value=AsyncCM())
    mock_db.commit = AsyncMock()

    lib = StrainLibrary(mock_hass)
    lib._db = mock_db

    await lib.load()

    pheno = lib.strains["Paradise Seeds Strain"]["phenotypes"]["default"]
    assert "image_path" not in pheno, "=404 image_path must be stripped on load"


@pytest.mark.asyncio
async def test_rebuild_ancestry_no_db(mock_hass) -> None:
    """Test _rebuild_strain_ancestry returns early when _db is None (line 888)."""
    lib = StrainLibrary(mock_hass)
    lib._db = None
    # Should return immediately without error
    await lib._rebuild_strain_ancestry("Some Strain")


@pytest.mark.asyncio
async def test_rebuild_ancestry_strain_not_found(mock_hass) -> None:
    """Test _rebuild_strain_ancestry returns early when strain not in DB (line 894)."""
    lib = StrainLibrary(mock_hass)

    mock_cursor = AsyncMock()
    mock_cursor.fetchone = AsyncMock(return_value=None)
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_cursor)
    lib._db = mock_db

    await lib._rebuild_strain_ancestry("Unknown Strain")


@pytest.mark.asyncio
async def test_rebuild_ancestry_no_ancestors(mock_hass) -> None:
    """Test _rebuild_strain_ancestry skips executemany when ancestors is empty (line 902)."""
    lib = StrainLibrary(mock_hass)
    lib.strains = {"Solo": {"meta": {}, "phenotypes": {}}}

    mock_cursor = AsyncMock()
    mock_cursor.fetchone = AsyncMock(return_value=(42,))
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_cursor)
    mock_db.commit = AsyncMock()
    lib._db = mock_db

    await lib._rebuild_strain_ancestry("Solo")
    mock_db.executemany.assert_not_called()


@pytest.mark.asyncio
async def test_import_seedfinder_empty_name_node(mock_hass) -> None:
    """Test that _collect skips nodes with empty name (line 980)."""
    lib = StrainLibrary(mock_hass)

    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()
    lib._db = mock_db
    lib.strains = {"Root Strain": {"meta": {}, "phenotypes": {}}}

    # Tree has a parent with empty name — should be skipped
    tree = {
        "name": "Root Strain",
        "parents": [
            {"name": "", "parents": []},
        ],
    }
    with patch.object(lib, "load", new=AsyncMock()), patch.object(lib, "_rebuild_strain_ancestry", new=AsyncMock()):
        await lib.async_import_seedfinder_lineage_tree("Root Strain", tree)

    # lineage_by_node is empty (only parent had empty name) → early return before any execute
    mock_db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_import_seedfinder_no_lineage_nodes(mock_hass) -> None:
    """Test early return when lineage_by_node is empty (line 1023)."""
    lib = StrainLibrary(mock_hass)

    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()
    lib._db = mock_db
    lib.strains = {}

    # Tree with only the root and no parents — lineage_by_node will be empty
    tree = {"name": "Lone Strain", "parents": []}
    with patch.object(lib, "load", new=AsyncMock()), patch.object(lib, "_rebuild_strain_ancestry", new=AsyncMock()):
        await lib.async_import_seedfinder_lineage_tree("Lone Strain", tree)

    # No DB inserts/updates should occur after the early return
    mock_db.executemany.assert_not_called()


@pytest.mark.asyncio
async def test_import_seedfinder_leaf_parent_url_stored(mock_hass) -> None:
    """Test that leaf parents with a URL are stored in leaf_parent_urls (line 993)."""
    lib = StrainLibrary(mock_hass)

    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()
    lib._db = mock_db
    lib.strains = {}

    # Root has a parent that has no children but has a URL → stored as leaf_parent
    tree = {
        "name": "Root",
        "parents": [
            {"name": "LeafParent", "url": "https://seedfinder.eu/strain/LeafParent", "parents": []},
        ],
    }
    with patch.object(lib, "load", new=AsyncMock()), patch.object(lib, "_rebuild_strain_ancestry", new=AsyncMock()):
        # No scraper — leaf_parent_urls collected but not fetched
        await lib.async_import_seedfinder_lineage_tree("Root", tree)

    # lineage_by_node has Root → [LeafParent], so DB write happens
    assert mock_db.commit.called


@pytest.mark.asyncio
async def test_import_seedfinder_scraper_fetches_leaf_parent(mock_hass) -> None:
    """Test that scraper fetches lineage for leaf parents (lines 1001-1020)."""
    lib = StrainLibrary(mock_hass)

    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()
    lib._db = mock_db
    lib.strains = {}

    tree = {
        "name": "Root",
        "parents": [
            {"name": "LeafParent", "url": "https://seedfinder.eu/strain/LeafParent", "parents": []},
        ],
    }

    mock_scraper = AsyncMock()
    mock_scraper.async_get_strain_details = AsyncMock(
        return_value={
            "lineage_tree": {
                "name": "LeafParent",
                "parents": [{"name": "GrandParent", "parents": []}],
            }
        }
    )

    with patch.object(lib, "load", new=AsyncMock()), patch.object(lib, "_rebuild_strain_ancestry", new=AsyncMock()):
        await lib.async_import_seedfinder_lineage_tree("Root", tree, scraper=mock_scraper)

    mock_scraper.async_get_strain_details.assert_awaited_once()


@pytest.mark.asyncio
async def test_import_seedfinder_scraper_error_silenced(mock_hass) -> None:
    """Test that scraper errors for leaf parents are silently caught (lines 1013-1020)."""
    lib = StrainLibrary(mock_hass)

    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()
    lib._db = mock_db
    lib.strains = {}

    tree = {
        "name": "Root",
        "parents": [
            {"name": "LeafParent", "url": "https://seedfinder.eu/strain/LeafParent", "parents": []},
        ],
    }

    mock_scraper = AsyncMock()
    mock_scraper.async_get_strain_details = AsyncMock(side_effect=ValueError("scrape failed"))

    with patch.object(lib, "load", new=AsyncMock()), patch.object(lib, "_rebuild_strain_ancestry", new=AsyncMock()):
        # Should not raise
        await lib.async_import_seedfinder_lineage_tree("Root", tree, scraper=mock_scraper)


def test_get_strain_lineage_tree_cache_hit(mock_hass) -> None:
    """Test that a cached result is returned on the second call (line 1119)."""
    lib = StrainLibrary(mock_hass)
    lib.strains = {
        "Cached Strain": {"meta": {"lineage_tree": []}, "phenotypes": {}},
    }

    lib.get_strain_lineage_tree("Cached Strain")
    # Manually place a different value in the cache to confirm cache is returned
    lib._lineage_cache["Cached Strain"] = {"name": "FROM_CACHE", "parents": [], "source": "library", "generation": ""}

    result2 = lib.get_strain_lineage_tree("Cached Strain")
    assert result2["name"] == "FROM_CACHE"


def test_get_strain_lineage_tree_library_parent_with_phenotype(mock_hass) -> None:
    """Test library-source parent with phenotype is tagged (line 1149)."""
    lib = StrainLibrary(mock_hass)
    lib.strains = {
        "Child": {
            "meta": {
                "lineage_tree": [
                    {"name": "LibParent", "source": "library", "phenotype": "P1"},
                ]
            },
            "phenotypes": {},
        },
        "LibParent": {"meta": {}, "phenotypes": {}},
    }

    result = lib.get_strain_lineage_tree("Child")
    assert len(result["parents"]) == 1
    assert result["parents"][0].get("phenotype") == "P1"


def test_get_strain_lineage_tree_non_library_parent_with_phenotype(mock_hass) -> None:
    """Test non-library source parent with phenotype is tagged (line 1153)."""
    lib = StrainLibrary(mock_hass)
    lib.strains = {
        "Child": {
            "meta": {
                "lineage_tree": [
                    {"name": "ExternalParent", "source": "seedfinder", "phenotype": "PX"},
                ]
            },
            "phenotypes": {},
        },
    }

    result = lib.get_strain_lineage_tree("Child")
    assert result["parents"][0].get("phenotype") == "PX"


@pytest.mark.asyncio
async def test_get_strains_by_ancestor_no_db(mock_hass) -> None:
    """Test async_get_strains_by_ancestor returns [] when _db is None (line 1169)."""
    lib = StrainLibrary(mock_hass)
    lib._db = None
    result = await lib.async_get_strains_by_ancestor("Some Ancestor")
    assert result == []


@pytest.mark.asyncio
async def test_get_shared_ancestors_no_db(mock_hass) -> None:
    """Test async_get_shared_ancestors returns [] when _db is None (line 1190)."""
    lib = StrainLibrary(mock_hass)
    lib._db = None
    result = await lib.async_get_shared_ancestors([1, 2])
    assert result == []


@pytest.mark.asyncio
async def test_get_shared_ancestors_empty_ids(mock_hass) -> None:
    """Test async_get_shared_ancestors returns [] for empty strain_ids (line 1190)."""
    lib = StrainLibrary(mock_hass)
    lib._db = MagicMock()
    result = await lib.async_get_shared_ancestors([])
    assert result == []


def test_get_strain_entries_with_phenotypes(mock_hass) -> None:
    """Test get_strain_entries returns entries for strains with phenotypes (lines 1215-1228)."""
    lib = StrainLibrary(mock_hass)
    lib.strains = {
        "Plain": {"meta": {}, "phenotypes": {}},
        "Multi": {
            "meta": {},
            "phenotypes": {
                "default": {"description": "baseline"},
                "pheno_a": {"description": "pheno A"},
            },
        },
    }

    entries = lib.get_strain_entries()
    names_and_phenotypes = [(e["name"], e["phenotype"]) for e in entries]

    assert ("Plain", None) in names_and_phenotypes
    # default phenotype → None
    assert ("Multi", None) in names_and_phenotypes
    assert ("Multi", "pheno_a") in names_and_phenotypes


@pytest.mark.asyncio
async def test_rebuild_ancestry_with_ancestors(mock_hass) -> None:
    """Test _rebuild_strain_ancestry calls executemany when ancestors exist (line 902)."""
    lib = StrainLibrary(mock_hass)
    # Strain has a parent so _collect_ancestors returns a non-empty list
    lib.strains = {
        "Child": {
            "meta": {
                "lineage_tree": [{"name": "Parent", "source": "library", "parents": []}]
            },
            "phenotypes": {},
        },
        "Parent": {"meta": {}, "phenotypes": {}},
    }

    mock_cursor = AsyncMock()
    mock_cursor.fetchone = AsyncMock(return_value=(1,))
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_cursor)
    mock_db.executemany = AsyncMock()
    mock_db.commit = AsyncMock()
    lib._db = mock_db

    await lib._rebuild_strain_ancestry("Child")
    mock_db.executemany.assert_called_once()


@pytest.mark.asyncio
async def test_import_seedfinder_scraper_skips_already_resolved_parent(mock_hass) -> None:
    """Test scraper skips leaf parents already in lineage_by_node (line 1003).

    GrandParent appears as a leaf-with-URL in one branch (→ leaf_parent_urls)
    and as a non-leaf with its own parents in another branch (→ lineage_by_node).
    The scraper loop must skip it via the `continue` guard.
    """
    lib = StrainLibrary(mock_hass)

    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()
    lib._db = mock_db
    lib.strains = {}

    tree = {
        "name": "Root",
        "parents": [
            {
                # ParentA has GrandParent as a leaf (URL, no children) → leaf_parent_urls
                "name": "ParentA",
                "parents": [
                    {"name": "GrandParent", "url": "https://seedfinder.eu/strain/GrandParent", "parents": []},
                ],
            },
            {
                # ParentB has GrandParent with its own children → lineage_by_node[GrandParent]
                "name": "ParentB",
                "parents": [
                    {
                        "name": "GrandParent",
                        "parents": [{"name": "GreatGrand", "parents": []}],
                    },
                ],
            },
        ],
    }

    mock_scraper = AsyncMock()
    mock_scraper.async_get_strain_details = AsyncMock()

    with patch.object(lib, "load", new=AsyncMock()), patch.object(lib, "_rebuild_strain_ancestry", new=AsyncMock()):
        await lib.async_import_seedfinder_lineage_tree("Root", tree, scraper=mock_scraper)

    # GrandParent was already resolved from the tree — scraper should NOT be called for it
    mock_scraper.async_get_strain_details.assert_not_awaited()
