from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_import_lineage_marks_ancestors_as_stubs():
    from custom_components.growspace_manager.strain_library import StrainLibrary

    hass = MagicMock()
    hass.config.path.return_value = "/tmp/test_stub.db"
    lib = StrainLibrary(hass)

    execute_calls: list[tuple] = []

    async def fake_execute(sql, params=None):
        execute_calls.append((sql.strip(), params))
        return AsyncMock()

    lib._db = MagicMock()
    lib._db.execute = fake_execute
    lib._db.commit = AsyncMock()
    lib.load = AsyncMock()
    lib._lineage_cache = {}

    root = "Blue Dream"
    tree = {
        "name": "Blue Dream",
        "parents": [
            {"name": "Blueberry", "parents": []},
            {"name": "Haze", "parents": []},
        ],
    }

    await lib.async_import_seedfinder_lineage_tree(root, tree)

    stub_insert_sqls = [
        (sql, params)
        for sql, params in execute_calls
        if "is_stub" in sql and "INSERT OR IGNORE INTO strains" in sql
    ]
    marked = {params[0] for _, params in stub_insert_sqls if params}
    assert "Blueberry" in marked
    assert "Haze" in marked
    assert "Blue Dream" not in marked
    assert not any("UPDATE strains SET is_stub = 1" in sql for sql, _ in execute_calls)


@pytest.mark.asyncio
async def test_add_strain_clears_stub_flag():
    """add_strain ON CONFLICT clause must include is_stub = 0."""
    from custom_components.growspace_manager.strain_library import StrainLibrary

    hass = MagicMock()
    hass.config.path.return_value = "/tmp/test_stub2.db"
    lib = StrainLibrary(hass)

    execute_calls: list[tuple] = []

    class FakeExecuteResult:
        """Supports both ``await execute(...)`` and ``async with execute(...) as cur``."""

        def __init__(self, fetchone_result=None):
            self._fetchone_result = fetchone_result

        def __await__(self):
            async def _noop():
                return self

            return _noop().__await__()

        async def __aenter__(self):
            cursor = AsyncMock()
            cursor.fetchone = AsyncMock(return_value=self._fetchone_result)
            return cursor

        async def __aexit__(self, *args):
            return False

    def fake_execute(sql, params=None):
        execute_calls.append((sql.strip(), params))
        sql_stripped = sql.strip()
        # Return a fake strain_id row for SELECT queries
        if sql_stripped.startswith("SELECT strain_id"):
            return FakeExecuteResult(fetchone_result=(1,))
        return FakeExecuteResult(fetchone_result=None)

    lib._db = MagicMock()
    lib._db.execute = fake_execute
    lib._db.executemany = AsyncMock()
    lib._db.commit = AsyncMock()
    lib._analytics_cache = None
    lib.load = AsyncMock()
    lib.image_manager = MagicMock()
    lib.image_manager.save_strain_image = AsyncMock(return_value="/tmp/img.webp")

    await lib.add_strain(strain="Blue Dream", breeder="DJ Short")

    upsert_sql = next(
        (sql for sql, _ in execute_calls if "INSERT OR REPLACE INTO strains" in sql),
        None,
    )
    assert upsert_sql is not None, "Expected INSERT OR REPLACE INTO strains"
    assert "is_stub=0" in upsert_sql
    assert "lineage=COALESCE(excluded.lineage, lineage)" in upsert_sql
    assert "lineage_tree=COALESCE(excluded.lineage_tree, lineage_tree)" in upsert_sql


@pytest.mark.asyncio
async def test_editing_ancestor_uses_promoting_add_path() -> None:
    """Editing an ancestor uses add_strain, which clears the ancestor flag."""
    from custom_components.growspace_manager.strain_library import StrainLibrary

    lib = StrainLibrary(MagicMock())
    lib.add_strain = AsyncMock()

    await lib.set_strain_meta(strain="Haze", strain_description="Managed")

    lib.add_strain.assert_awaited_once_with(
        strain="Haze",
        phenotype=None,
        breeder=None,
        breeder_logo=None,
        strain_type=None,
        lineage=None,
        sex=None,
        flower_days_min=None,
        flower_days_max=None,
        description=None,
        image_base64=None,
        image_path=None,
        image_crop_meta=None,
        images=None,
        sativa_percentage=None,
        indica_percentage=None,
        yield_potential=None,
        height=None,
        thc=None,
        cbd=None,
        cbg=None,
        effects=None,
        aroma=None,
        taste=None,
        strain_description="Managed",
        awards=None,
        lineage_tree=None,
    )


@pytest.mark.asyncio
async def test_importing_ancestor_uses_promoting_add_path() -> None:
    """Explicitly importing an ancestor uses add_strain to promote it."""
    from custom_components.growspace_manager.strain_library import StrainLibrary

    lib = StrainLibrary(MagicMock())
    lib.add_strain = AsyncMock()
    lib.load = AsyncMock()

    await lib.import_strains(["Haze"])

    lib.add_strain.assert_awaited_once_with("Haze")


@pytest.mark.asyncio
async def test_load_populates_is_stub_from_db():
    """A managed ancestor is promoted while retaining its lineage."""
    import aiosqlite

    from custom_components.growspace_manager.sensor import StrainLibrarySensor
    from custom_components.growspace_manager.strain_library import (
        STRAIN_LIBRARY_SCHEMA,
        StrainLibrary,
    )

    hass = MagicMock()
    hass.config.path.return_value = "/tmp/test_load_is_stub.db"
    lib = StrainLibrary(hass)

    async with aiosqlite.connect(":memory:") as db:
        db.row_factory = aiosqlite.Row
        await db.executescript(STRAIN_LIBRARY_SCHEMA)
        await db.commit()

        # columns added via ALTER TABLE in async_setup, not in the schema constant
        await db.execute("ALTER TABLE strains ADD COLUMN generation TEXT")
        await db.execute("ALTER TABLE phenotypes ADD COLUMN images TEXT")
        await db.commit()

        await db.execute(
            """
            INSERT INTO strains (strain_name, lineage, lineage_tree, is_stub)
            VALUES (?, ?, ?, ?)
            """,
            (
                "Haze",
                "Thai",
                '[{"name": "Thai", "source": "library"}]',
                1,
            ),
        )
        await db.execute(
            "INSERT INTO strains (strain_name, breeder, is_stub) VALUES (?, ?, ?)",
            ("OG Kush", "DJ Short", 0),
        )
        await db.execute(
            "INSERT INTO phenotypes (strain_id, phenotype_name) SELECT strain_id, 'default' FROM strains WHERE strain_name = 'Haze'"
        )
        await db.execute(
            "INSERT INTO phenotypes (strain_id, phenotype_name) SELECT strain_id, 'default' FROM strains WHERE strain_name = 'OG Kush'"
        )
        await db.commit()

        lib._db = db
        await lib.load()

        coordinator = MagicMock()
        coordinator.services.config.strain_library = lib
        sensor = StrainLibrarySensor(coordinator)

        assert sensor.native_value == 1
        assert sensor.extra_state_attributes["ancestor_strain_count"] == 1
        assert sensor.extra_state_attributes["total_strain_count"] == 2

        await lib.add_strain("Haze", breeder="Explicitly managed")

        assert sensor.native_value == 2
        assert sensor.extra_state_attributes["ancestor_strain_count"] == 0
        assert sensor.extra_state_attributes["total_strain_count"] == 2

    assert lib.strains["Haze"]["meta"]["is_stub"] is False
    assert lib.strains["Haze"]["meta"]["lineage"] == "Thai"
    assert lib.strains["Haze"]["meta"]["lineage_tree"] == [
        {"name": "Thai", "source": "library"}
    ]
    assert "OG Kush" in lib.strains
    assert lib.strains["OG Kush"]["meta"]["is_stub"] is False
