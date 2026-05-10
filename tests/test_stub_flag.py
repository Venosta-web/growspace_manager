import pytest
from unittest.mock import AsyncMock, MagicMock


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

    stub_update_sqls = [
        (sql, params)
        for sql, params in execute_calls
        if "is_stub" in sql and "UPDATE" in sql
    ]
    marked = {params[0] for _, params in stub_update_sqls if params}
    assert "Blueberry" in marked
    assert "Haze" in marked
    assert "Blue Dream" not in marked
    for sql, _ in stub_update_sqls:
        assert "breeder IS NULL" in sql, "Stub UPDATE must guard against overwriting real entries"


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
    lib.image_manager = MagicMock()
    lib.image_manager.save_strain_image = AsyncMock(return_value="/tmp/img.webp")

    await lib.add_strain(strain="Blue Dream", breeder="DJ Short")

    upsert_sql = next(
        (sql for sql, _ in execute_calls if "INSERT OR REPLACE INTO strains" in sql),
        None,
    )
    assert upsert_sql is not None, "Expected INSERT OR REPLACE INTO strains"
    assert "is_stub" in upsert_sql, "ON CONFLICT clause must set is_stub = 0"
