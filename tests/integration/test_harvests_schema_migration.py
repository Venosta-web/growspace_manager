"""Regression test: upgrading from an old DB that lacks wet_weight etc. on harvests.

The bug: wet_weight, dry_weight, trim_weight, thc_percentage, cbd_percentage,
terpene_profile were added to the CREATE TABLE schema without ALTER TABLE
migrations, so existing databases would fail on load with:
  sqlite3.OperationalError: no such column: wet_weight
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest

from custom_components.growspace_manager.strain_library import StrainLibrary


_OLD_HARVESTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS strains (
    strain_id INTEGER PRIMARY KEY,
    strain_name TEXT UNIQUE NOT NULL,
    breeder TEXT,
    type TEXT,
    lineage TEXT,
    sex TEXT,
    sativa_percentage INTEGER,
    indica_percentage INTEGER,
    is_indoor INTEGER DEFAULT 1,
    is_outdoor INTEGER DEFAULT 1,
    is_greenhouse INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS phenotypes (
    phenotype_id INTEGER PRIMARY KEY,
    strain_id INTEGER,
    phenotype_name TEXT NOT NULL,
    description TEXT,
    image_path TEXT,
    image_crop_meta TEXT,
    flower_days_min INTEGER,
    flower_days_max INTEGER,
    UNIQUE (strain_id, phenotype_name),
    FOREIGN KEY(strain_id) REFERENCES strains(strain_id)
);
CREATE TABLE IF NOT EXISTS harvests (
    harvest_id INTEGER PRIMARY KEY,
    phenotype_id INTEGER,
    veg_days INTEGER NOT NULL,
    flower_days INTEGER NOT NULL,
    harvest_date TEXT NOT NULL,
    vigor INTEGER,
    structure INTEGER,
    aroma INTEGER,
    resin INTEGER,
    pest_resistance INTEGER,
    FOREIGN KEY(phenotype_id) REFERENCES phenotypes(phenotype_id)
);
"""


async def _seed_old_db(db_path: Path) -> None:
    """Create a DB with the old schema and one harvest row."""
    async with aiosqlite.connect(str(db_path)) as db:
        await db.executescript(_OLD_HARVESTS_SCHEMA)
        await db.execute("INSERT INTO strains (strain_name) VALUES ('OG Kush')")
        await db.execute(
            "INSERT INTO phenotypes (strain_id, phenotype_name) VALUES (1, 'Cut A')"
        )
        await db.execute(
            "INSERT INTO harvests (phenotype_id, veg_days, flower_days, harvest_date)"
            " VALUES (1, 30, 60, '2024-01-01')"
        )
        await db.commit()


def _make_hass(db_path: Path) -> MagicMock:
    hass = MagicMock()
    hass.config.path.return_value = str(db_path)
    return hass


async def _make_migrated_lib(db_path: Path) -> StrainLibrary:
    lib = StrainLibrary(_make_hass(db_path))
    lib.image_manager = MagicMock()
    lib.image_manager.async_setup = AsyncMock()
    lib.image_manager.async_migrate_to_webp = AsyncMock(return_value=False)
    await lib.async_setup()
    return lib


async def test_setup_succeeds_on_old_db_missing_wet_weight(tmp_path: Path) -> None:
    """async_setup must not raise when harvests table lacks wet_weight."""
    db_path = tmp_path / "strain_library.db"
    await _seed_old_db(db_path)

    lib = await _make_migrated_lib(db_path)
    # Must not raise sqlite3.OperationalError: no such column: wet_weight
    await lib._db.close()


async def test_harvest_loaded_after_migration(tmp_path: Path) -> None:
    """After migration the seeded harvest is visible in the in-memory cache."""
    db_path = tmp_path / "strain_library.db"
    await _seed_old_db(db_path)

    lib = await _make_migrated_lib(db_path)

    harvests = lib.strains["OG Kush"]["phenotypes"]["Cut A"]["harvests"]
    assert len(harvests) == 1
    assert harvests[0]["veg_days"] == 30
    assert harvests[0]["wet_weight"] is None  # migrated column defaults to NULL

    await lib._db.close()


async def test_new_columns_accept_values_after_migration(tmp_path: Path) -> None:
    """After migration, recording a harvest with wet_weight persists correctly."""
    db_path = tmp_path / "strain_library.db"
    await _seed_old_db(db_path)

    lib = await _make_migrated_lib(db_path)

    await lib.record_harvest(
        "OG Kush", "Cut A", veg_days=28, flower_days=56, wet_weight=120.5
    )
    await lib.load()

    harvests = lib.strains["OG Kush"]["phenotypes"]["Cut A"]["harvests"]
    new_harvest = next(h for h in harvests if h["wet_weight"] is not None)
    assert new_harvest["wet_weight"] == pytest.approx(120.5)

    await lib._db.close()
