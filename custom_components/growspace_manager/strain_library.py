"""Manages the strain library for the Growspace Manager integration using SQLite.

This file defines the `StrainLibrary` class, which is responsible for storing,
retrieving, and analyzing data about different cannabis strains using a dedicated
asynchronous SQLite database (aiosqlite).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import aiosqlite

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util, slugify

from .const import DB_FILE_STRAIN_LIBRARY
from .exceptions import GrowspaceError
from .image_manager import ImageManager
from .import_export_manager import ImportExportManager

_LOGGER = logging.getLogger(__name__)

# Two distinct formats are used for lineage data — they must not be conflated:
#
#   StoredParents  — flat list persisted in the DB `lineage_tree` column.
#                    Each entry is an immediate parent: {name, source[, phenotype]}.
#                    Written by update_strain_lineage_tree and add_strain.
#
#   LineageNode    — nested tree built lazily by get_strain_lineage_tree().
#                    Each node is {name, source, parents: [LineageNode, ...]}.
#                    Never stored; only lives in memory and WebSocket responses.
type StoredParent = dict[str, str]
type StoredParents = list[StoredParent]
type LineageNode = dict[str, Any]


def _collect_ancestors(
    node: dict[str, Any], depth: int = 1
) -> list[tuple[str, str | None, int]]:
    """Walk a lineage_tree node recursively, returning (name, url, depth) for every ancestor."""
    results: list[tuple[str, str | None, int]] = []
    for parent in node.get("parents", []):
        name = parent.get("name", "").strip()
        if name:
            results.append((name, parent.get("url"), depth))
            results.extend(_collect_ancestors(parent, depth + 1))
    return results


# Database schema
STRAIN_LIBRARY_SCHEMA = """
CREATE TABLE IF NOT EXISTS strains (
    strain_id INTEGER PRIMARY KEY,
    strain_name TEXT UNIQUE NOT NULL,
    breeder TEXT,
    breeder_logo TEXT,
    type TEXT,
    lineage TEXT,
    sex TEXT,
    sativa_percentage INTEGER,
    indica_percentage INTEGER,
    yield_potential TEXT,
    height TEXT,
    thc REAL,
    awards TEXT,
    lineage_tree TEXT,
    cbd REAL,
    cbg REAL,
    effects TEXT,
    aroma TEXT,
    taste TEXT,
    description TEXT,
    is_indoor INTEGER DEFAULT 1,
    is_outdoor INTEGER DEFAULT 1,
    is_greenhouse INTEGER DEFAULT 1,
    is_stub INTEGER DEFAULT 0
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
    wet_weight REAL,
    dry_weight REAL,
    trim_weight REAL,
    thc_percentage REAL,
    cbd_percentage REAL,
    terpene_profile TEXT,
    FOREIGN KEY(phenotype_id) REFERENCES phenotypes(phenotype_id)
);
"""


class StrainLibrary:
    """Manages the strain library using an SQLite database."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the StrainLibrary.

        Args:
            hass: Home Assistant instance.
        """
        self.hass = hass
        self._db_path = hass.config.path(DB_FILE_STRAIN_LIBRARY)
        self._db: aiosqlite.Connection | None = None
        self.strains: dict[str, dict[str, Any]] = {}
        self._analytics_cache: dict[str, Any] | None = None
        self._lineage_cache: dict[str, dict[str, Any]] = {}
        self.image_manager = ImageManager(
            hass, hass.config.path("www", "growspace_manager", "strains")
        )
        self.import_export_manager = ImportExportManager(hass)

    async def async_setup(self) -> bool:
        """Set up the database connection and schema.

        Returns:
            True if WebP migration ran and updated paths, False otherwise.
        """
        _LOGGER.debug("Setting up StrainLibrary DB at %s", self._db_path)
        await self.image_manager.async_setup()
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(STRAIN_LIBRARY_SCHEMA)
        await self._db.commit()

        # Create ancestry closure table (idempotent)
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS strain_ancestry (
                ancestor_name        TEXT NOT NULL,
                descendant_strain_id INTEGER NOT NULL,
                depth                INTEGER NOT NULL,
                ancestor_url         TEXT,
                PRIMARY KEY (ancestor_name, descendant_strain_id),
                FOREIGN KEY (descendant_strain_id) REFERENCES strains(strain_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_ancestry_ancestor ON strain_ancestry(ancestor_name);
            CREATE INDEX IF NOT EXISTS idx_ancestry_descendant ON strain_ancestry(descendant_strain_id);
        """)
        await self._db.commit()

        # Ensure breeder_logo column exists before first load
        try:
            await self._db.execute("ALTER TABLE strains ADD COLUMN breeder_logo TEXT")
            await self._db.commit()
            _LOGGER.info("Successfully added breeder_logo column to strains table")
        except aiosqlite.OperationalError:
            # Column already exists
            pass

        # Ensure lineage_tree column exists (backwards compatibility)
        try:
            await self._db.execute("ALTER TABLE strains ADD COLUMN lineage_tree TEXT")
            await self._db.commit()
            _LOGGER.info("Added lineage_tree column to strains table")
        except aiosqlite.OperationalError:
            pass  # Column already exists

        # Ensure generation column exists (backwards compatibility)
        try:
            await self._db.execute("ALTER TABLE strains ADD COLUMN generation TEXT")
            await self._db.commit()
            _LOGGER.info("Added generation column to strains table")
        except aiosqlite.OperationalError:
            pass  # Column already exists

        # Ensure images column exists on phenotypes (image gallery support)
        try:
            await self._db.execute("ALTER TABLE phenotypes ADD COLUMN images TEXT")
            await self._db.commit()
            _LOGGER.info("Added images column to phenotypes table")
        except aiosqlite.OperationalError:
            pass  # Column already exists

        # Ensure is_stub column exists (backwards compatibility)
        try:
            await self._db.execute(
                "ALTER TABLE strains ADD COLUMN is_stub INTEGER DEFAULT 0"
            )
            await self._db.commit()
            _LOGGER.info("Added is_stub column to strains table")
        except aiosqlite.OperationalError:
            pass  # Column already exists

        # Ensure score columns exist in harvests table (backwards compatibility)
        for col in ["vigor", "structure", "aroma", "resin", "pest_resistance"]:
            try:
                await self._db.execute(f"ALTER TABLE harvests ADD COLUMN {col} INTEGER")
                await self._db.commit()
                _LOGGER.info("Added column '%s' to harvests table", col)
            except aiosqlite.OperationalError:
                # Column already exists
                pass

        # Ensure new Seedfinder columns exist
        _strain_new_cols: list[tuple[str, str]] = [
            ("yield_potential", "TEXT"),
            ("height", "TEXT"),
            ("thc", "REAL"),
            ("awards", "TEXT"),
            ("lineage_tree", "TEXT"),
            ("cbd", "REAL"),
            ("cbg", "REAL"),
            ("effects", "TEXT"),
            ("aroma", "TEXT"),
            ("taste", "TEXT"),
            ("description", "TEXT"),
        ]
        for col_name, col_type in _strain_new_cols:
            try:
                await self._db.execute(
                    f"ALTER TABLE strains ADD COLUMN {col_name} {col_type}"
                )
                await self._db.commit()
                _LOGGER.info("Added column '%s' to strains table", col_name)
            except aiosqlite.OperationalError:
                pass

        await self.load()

        # Asynchronously migrate any existing JPG images to WebP
        migrated = await self.image_manager.async_migrate_to_webp(self._db)
        # Reload to pick up updated WebP paths if migration happened
        if migrated:
            await self.load()

        return migrated

    async def async_close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    async def _async_migrate_image_gallery(self) -> None:
        """One-time migration: convert image_path rows to images JSON gallery."""
        if self._db is None:
            return
        try:
            async with self._db.execute(
                "SELECT phenotype_id, image_path, image_crop_meta FROM phenotypes"
                " WHERE image_path IS NOT NULL AND images IS NULL"
            ) as cursor:
                rows = await cursor.fetchall()
        except aiosqlite.OperationalError:
            # images column not yet present — migration will run after ALTER TABLE
            return

        if not rows:
            return

        for row in rows:
            image_path = row["image_path"]
            if image_path and "=404" in image_path:
                continue
            raw_crop = row["image_crop_meta"]
            crop_meta = None
            if raw_crop:
                try:
                    crop_meta = json.loads(raw_crop)
                except json.JSONDecodeError:
                    crop_meta = None
            gallery = [{"path": image_path, "crop_meta": crop_meta, "is_thumbnail": True}]
            await self._db.execute(
                "UPDATE phenotypes SET images = ? WHERE phenotype_id = ?",
                (json.dumps(gallery), row["phenotype_id"]),
            )

        await self._db.commit()
        _LOGGER.info("Migrated %d phenotype(s) from image_path to images gallery", len(rows))

    async def load(self) -> None:
        """Load all strain and phenotype data into the in-memory cache."""
        if self._db is None:
            _LOGGER.warning("Database not connected, cannot load library")
            return
        await self._async_migrate_image_gallery()
        # Fetch all harvests first to avoid N+1 queries and async calls in the loop
        harvests_by_pheno: dict[int, list[dict[str, Any]]] = {}
        async with self._db.execute(
            "SELECT phenotype_id, veg_days, flower_days, harvest_date,"
            " vigor, structure, aroma, resin, pest_resistance,"
            " wet_weight, dry_weight, trim_weight,"
            " thc_percentage, cbd_percentage, terpene_profile FROM harvests"
        ) as cursor:
            async for row in cursor:
                pheno_id = row["phenotype_id"]
                if pheno_id not in harvests_by_pheno:
                    harvests_by_pheno[pheno_id] = []
                harvests_by_pheno[pheno_id].append(
                    {
                        "veg_days": row["veg_days"],
                        "flower_days": row["flower_days"],
                        "harvest_date": row["harvest_date"],
                        "vigor": row["vigor"],
                        "structure": row["structure"],
                        "aroma": row["aroma"],
                        "resin": row["resin"],
                        "pest_resistance": row["pest_resistance"],
                        "wet_weight": row["wet_weight"],
                        "dry_weight": row["dry_weight"],
                        "trim_weight": row["trim_weight"],
                        "thc_percentage": row["thc_percentage"],
                        "cbd_percentage": row["cbd_percentage"],
                        "terpene_profile": row["terpene_profile"],
                    }
                )

        new_strains: dict[str, dict[str, Any]] = {}
        query = """
            SELECT
                s.strain_id, s.strain_name, s.breeder, s.breeder_logo, s.type,
                s.lineage, s.lineage_tree, s.sex, s.generation,
                s.sativa_percentage, s.indica_percentage,
                s.yield_potential, s.height, s.thc, s.awards,
                s.cbd, s.cbg, s.effects, s.aroma, s.taste, s.description as strain_description,
                s.is_stub,
                p.phenotype_id, p.phenotype_name, p.description, p.image_path,
                p.image_crop_meta, p.flower_days_min, p.flower_days_max, p.images
            FROM strains s
            LEFT JOIN phenotypes p ON s.strain_id = p.strain_id
        """
        async with self._db.execute(query) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                strain_name = row["strain_name"]
                phenotype_name = row["phenotype_name"] or "default"
                if strain_name not in new_strains:
                    raw_tree = row["lineage_tree"]
                    lineage_tree = None
                    if raw_tree:
                        try:
                            lineage_tree = json.loads(raw_tree)
                        except json.JSONDecodeError:
                            lineage_tree = None
                    meta = {
                        k: row[k]
                        for k in [
                            "breeder",
                            "breeder_logo",
                            "type",
                            "lineage",
                            "sex",
                            "generation",
                            "sativa_percentage",
                            "indica_percentage",
                            "yield_potential",
                            "height",
                            "thc",
                            "cbd",
                            "cbg",
                        ]
                    }
                    meta["description"] = row["strain_description"]

                    # Filter out None values to avoid nulls in JSON (aligns with Zod's .optional())
                    meta = {k: v for k, v in meta.items() if v is not None}
                    meta["is_stub"] = bool(row["is_stub"])

                    # Parse JSON fields
                    for field in ["awards", "effects", "aroma", "taste"]:
                        val = row[field]
                        try:
                            meta[field] = json.loads(val) if val else []
                        except (json.JSONDecodeError, TypeError):
                            meta[field] = []

                    if lineage_tree is not None:
                        meta["lineage_tree"] = lineage_tree
                    new_strains[strain_name] = {"meta": meta, "phenotypes": {}}
                if row["phenotype_id"] is not None:
                    # Decode image_crop_meta JSON safely
                    image_crop_meta = row["image_crop_meta"]
                    try:
                        image_crop_meta = (
                            json.loads(image_crop_meta) if image_crop_meta else None
                        )
                    except json.JSONDecodeError:
                        _LOGGER.warning(
                            "Could not decode image_crop_meta for %s (%s)",
                            strain_name,
                            phenotype_name,
                        )
                        image_crop_meta = None

                    pheno_id = row["phenotype_id"]
                    raw_image_path = row["image_path"]

                    raw_images = row["images"]
                    images: list[dict[str, Any]] | None = None
                    if raw_images:
                        try:
                            images = json.loads(raw_images)
                        except json.JSONDecodeError:
                            _LOGGER.warning(
                                "Could not decode images for %s (%s)",
                                strain_name,
                                phenotype_name,
                            )

                    phenotype_data = {
                        "phenotype_id": pheno_id,
                        "description": row["description"],
                        "image_path": None if (raw_image_path and "=404" in raw_image_path) else raw_image_path,
                        "image_crop_meta": image_crop_meta,
                        "images": images,
                        "flower_days_min": row["flower_days_min"],
                        "flower_days_max": row["flower_days_max"],
                        "harvests": harvests_by_pheno.get(pheno_id, []),
                    }
                    # Remove None values
                    phenotype_data = {
                        k: v for k, v in phenotype_data.items() if v is not None
                    }
                    new_strains[strain_name]["phenotypes"][phenotype_name] = (
                        phenotype_data
                    )

        self.strains = new_strains
        self._analytics_cache = None  # Invalidate analytics cache
        self._lineage_cache = {}  # Invalidate lineage cache
        _LOGGER.info("Loaded strain library metadata for %d strains", len(self.strains))

    async def save(self) -> None:
        """No-op for SQLite implementation - changes are committed immediately."""

    async def record_harvest(
        self,
        strain: str,
        phenotype: str,
        veg_days: int,
        flower_days: int,
        vigor: int | None = None,
        structure: int | None = None,
        aroma: int | None = None,
        resin: int | None = None,
        pest_resistance: int | None = None,
        wet_weight: float | None = None,
        dry_weight: float | None = None,
        trim_weight: float | None = None,
        thc_percentage: float | None = None,
        cbd_percentage: float | None = None,
        terpene_profile: str | None = None,
    ) -> None:
        """Record a harvest event for a specific strain and phenotype."""
        strain = strain.strip()
        phenotype = phenotype.strip() or "default"
        if self._db is None:
            _LOGGER.warning("Database not connected, cannot record harvest")
            return
        phenotype_id = await self._ensure_strain_and_phenotype_exist(strain, phenotype)
        harvest_date = dt_util.utcnow().isoformat()
        query = """
            INSERT INTO harvests
                (phenotype_id, veg_days, flower_days, harvest_date,
                 vigor, structure, aroma, resin, pest_resistance,
                 wet_weight, dry_weight, trim_weight,
                 thc_percentage, cbd_percentage, terpene_profile)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        await self._db.execute(
            query,
            (
                phenotype_id,
                veg_days,
                flower_days,
                harvest_date,
                vigor,
                structure,
                aroma,
                resin,
                pest_resistance,
                wet_weight,
                dry_weight,
                trim_weight,
                thc_percentage,
                cbd_percentage,
                terpene_profile,
            ),
        )
        await self._db.commit()
        # Invalidate analytics cache
        self._analytics_cache = None
        # Update in-memory cache for immediate sensor use
        if strain in self.strains and phenotype in self.strains[strain]["phenotypes"]:
            self.strains[strain]["phenotypes"][phenotype]["harvests"].append(
                {
                    "veg_days": veg_days,
                    "flower_days": flower_days,
                    "harvest_date": harvest_date,
                    "vigor": vigor,
                    "structure": structure,
                    "aroma": aroma,
                    "resin": resin,
                    "pest_resistance": pest_resistance,
                    "wet_weight": wet_weight,
                    "dry_weight": dry_weight,
                    "trim_weight": trim_weight,
                    "thc_percentage": thc_percentage,
                    "cbd_percentage": cbd_percentage,
                    "terpene_profile": terpene_profile,
                }
            )
        _LOGGER.info(
            "Recorded harvest for %s (%s): veg=%d days, flower=%d days",
            strain,
            phenotype,
            veg_days,
            flower_days,
        )

    async def _ensure_strain_and_phenotype_exist(
        self, strain_name: str, phenotype_name: str
    ) -> int:
        """Ensure the strain and phenotype exist, returning the phenotype ID."""
        if self._db is None:
            raise RuntimeError("Database not connected")
        # Ensure strain exists
        async with self._db.execute(
            "SELECT strain_id FROM strains WHERE strain_name = ?", (strain_name,)
        ) as cursor:
            strain_row = await cursor.fetchone()
            if not strain_row:
                await self.add_strain(strain_name, phenotype_name)
                async with self._db.execute(
                    "SELECT strain_id FROM strains WHERE strain_name = ?",
                    (strain_name,),
                ) as c:
                    strain_row = await c.fetchone()
                    if not strain_row:
                        raise RuntimeError(f"Failed to create strain {strain_name}")
            strain_id = strain_row[0]
        # Ensure phenotype exists
        query = "SELECT phenotype_id FROM phenotypes WHERE strain_id = ? AND phenotype_name = ?"
        async with self._db.execute(query, (strain_id, phenotype_name)) as cursor:
            phenotype_row = await cursor.fetchone()
            if not phenotype_row:
                insert = (
                    "INSERT INTO phenotypes (strain_id, phenotype_name) VALUES (?, ?)"
                )
                await self._db.execute(insert, (strain_id, phenotype_name))
                await self._db.commit()
                async with self._db.execute(query, (strain_id, phenotype_name)) as c:
                    phenotype_row = await c.fetchone()
            if phenotype_row is None:
                raise RuntimeError(
                    f"Failed to retrieve phenotype ID for {strain_name} {phenotype_name}"
                )
            return int(phenotype_row[0])

    async def update_breeder(
        self,
        original_name: str,
        new_name: str,
        logo: str | None = None,
    ) -> int:
        """Update breeder name and/or logo across all strains.

        Args:
            original_name: Current breeder name to match.
            new_name: New breeder name (can be same as original for logo-only update).
            logo: New breeder logo (base64 or path). None means no change.

        Returns:
            Number of strains updated.
        """
        if self._db is None:
            _LOGGER.warning("Database not connected, cannot update breeder")
            return 0

        original_name = original_name.strip()
        new_name = new_name.strip()

        if not original_name or not new_name:
            return 0

        # Handle logo: if base64, save via image manager
        logo_path = logo
        if logo and logo.startswith("data:"):
            safe_breeder = slugify(new_name)
            abs_path = await self.image_manager.save_breeder_logo(safe_breeder, logo)
            logo_path = f"/local/growspace_manager/strains/{Path(abs_path).name}"

        # Build update query
        if logo == "":
            # Explicitly clear logo
            query = (
                "UPDATE strains SET breeder = ?, breeder_logo = NULL WHERE breeder = ?"
            )
            await self._db.execute(query, (new_name, original_name))
        elif logo_path is not None:
            query = "UPDATE strains SET breeder = ?, breeder_logo = ? WHERE breeder = ?"
            await self._db.execute(query, (new_name, logo_path, original_name))
        else:
            # This branch is taken when logo is None (no change to logo)
            query = "UPDATE strains SET breeder = ? WHERE breeder = ?"
            await self._db.execute(query, (new_name, original_name))

        changes = self._db.total_changes
        await self._db.commit()
        await self.load()

        _LOGGER.info(
            "Updated breeder '%s' → '%s' across %d strains",
            original_name,
            new_name,
            changes,
        )
        return changes

    async def delete_breeder(self, breeder_name: str) -> int:
        """Remove breeder association from all strains.

        Args:
            breeder_name: Breeder name to clear.

        Returns:
            Number of strains updated.
        """
        if self._db is None:
            _LOGGER.warning("Database not connected, cannot delete breeder")
            return 0

        breeder_name = breeder_name.strip()
        if not breeder_name:
            return 0

        query = (
            "UPDATE strains SET breeder = NULL, breeder_logo = NULL WHERE breeder = ?"
        )
        await self._db.execute(query, (breeder_name,))
        changes = self._db.total_changes
        await self._db.commit()
        await self.load()

        _LOGGER.info("Cleared breeder '%s' from %d strains", breeder_name, changes)
        return changes

    async def add_strain(
        self,
        strain: str,
        phenotype: str | None = None,
        breeder: str | None = None,
        breeder_logo: str | None = None,
        strain_type: str | None = None,
        lineage: str | None = None,
        sex: str | None = None,
        flower_days_min: int | None = None,
        flower_days_max: int | None = None,
        description: str | None = None,
        image_base64: str | None = None,
        image_path: str | None = None,
        image_crop_meta: dict[str, Any] | None = None,
        images: list[dict[str, Any]] | None = None,
        sativa_percentage: int | None = None,
        indica_percentage: int | None = None,
        yield_potential: str | None = None,
        height: str | None = None,
        thc: float | None = None,
        cbd: float | None = None,
        cbg: float | None = None,
        effects: list[str] | None = None,
        aroma: list[str] | None = None,
        taste: list[str] | None = None,
        strain_description: str | None = None,
        awards: list[str] | None = None,
        lineage_tree: LineageNode | None = None,
    ) -> None:
        """Add or update a strain/phenotype entry.

        lineage_tree, when provided, must be a LineageNode (nested tree) — not a
        StoredParents flat list.  Immediate parents are extracted and stored as
        StoredParents in the DB; the full tree is used to rebuild strain_ancestry.
        """
        if self._db is None:
            _LOGGER.warning("Database not connected, cannot add strain")
            return
        strain = strain.strip()
        phenotype = phenotype.strip() if phenotype else "default"

        # Treat 0% / 0% as unknown (NULL in DB)
        if sativa_percentage == 0 and indica_percentage == 0:
            sativa_percentage = indica_percentage = None

        # Hybrid percentage handling
        if strain_type and str(strain_type).lower() == "hybrid":
            if sativa_percentage is not None and indica_percentage is None:
                indica_percentage = 100 - sativa_percentage
            elif indica_percentage is not None and sativa_percentage is None:
                sativa_percentage = 100 - indica_percentage
            if (
                sativa_percentage is not None
                and indica_percentage is not None
                and sativa_percentage + indica_percentage > 100
            ):
                raise ValueError(
                    "Combined Sativa/Indica percentage cannot exceed 100%."
                )
        # Insert/replace strain metadata
        strain_data = {
            "breeder": breeder,
            "breeder_logo": breeder_logo,
            "type": strain_type,
            "lineage": lineage,
            "sex": sex,
            "sativa_percentage": sativa_percentage,
            "indica_percentage": indica_percentage,
            "yield_potential": yield_potential,
            "height": height,
            "thc": thc,
            "cbd": cbd,
            "cbg": cbg,
            "effects": json.dumps(effects) if effects is not None else None,
            "aroma": json.dumps(aroma) if aroma is not None else None,
            "taste": json.dumps(taste) if taste is not None else None,
            "description": strain_description,
            "awards": json.dumps(awards) if awards is not None else None,
            "lineage_tree": json.dumps(
                # Store only immediate parents (StoredParents flat list), not the
                # full nested tree — get_strain_lineage_tree() builds the tree on demand.
                [
                    {"name": p.get("name", "").strip(), "source": p.get("source", "library")}
                    for p in (lineage_tree.get("parents") or [])[:2]
                    if p.get("name", "").strip()
                ]
            )
            if lineage_tree is not None
            else None,
        }
        strain_data = {k: v for k, v in strain_data.items() if v is not None}

        # If breeder_logo is provided, update all strains from this breeder
        if breeder and breeder_logo:
            update_logo_query = "UPDATE strains SET breeder_logo = ? WHERE breeder = ?"
            await self._db.execute(update_logo_query, (breeder_logo, breeder))
        # If breeder is set but breeder_logo is NOT provided, try to find an existing one
        elif breeder and not breeder_logo:
            find_logo_query = "SELECT breeder_logo FROM strains WHERE breeder = ? AND breeder_logo IS NOT NULL LIMIT 1"
            async with self._db.execute(find_logo_query, (breeder,)) as cursor:
                row = await cursor.fetchone()
                if row and row[0]:
                    strain_data["breeder_logo"] = row[0]

        fields = ", ".join(["strain_name", *list(strain_data)])
        placeholders = ", ".join(["?"] * (len(strain_data) + 1))
        query = f"""
            INSERT OR REPLACE INTO strains ({fields})
            VALUES ({placeholders})
            ON CONFLICT(strain_name) DO UPDATE SET
                breeder=COALESCE(excluded.breeder, breeder),
                breeder_logo=COALESCE(excluded.breeder_logo, breeder_logo),
                type=COALESCE(excluded.type, type),
                lineage=COALESCE(excluded.lineage, lineage),
                sex=COALESCE(excluded.sex, sex),
                sativa_percentage=COALESCE(excluded.sativa_percentage, sativa_percentage),
                indica_percentage=COALESCE(excluded.indica_percentage, indica_percentage),
                yield_potential=COALESCE(excluded.yield_potential, yield_potential),
                height=COALESCE(excluded.height, height),
                thc=COALESCE(excluded.thc, thc),
                cbd=COALESCE(excluded.cbd, cbd),
                cbg=COALESCE(excluded.cbg, cbg),
                effects=COALESCE(excluded.effects, effects),
                aroma=COALESCE(excluded.aroma, aroma),
                taste=COALESCE(excluded.taste, taste),
                description=COALESCE(excluded.description, description),
                awards=COALESCE(excluded.awards, awards),
                lineage_tree=COALESCE(excluded.lineage_tree, lineage_tree),
                is_stub=0
            WHERE strain_name = excluded.strain_name
        """  # noqa: S608
        await self._db.execute(query, (strain, *tuple(strain_data.values())))
        await self._db.commit()
        # Get strain_id
        async with self._db.execute(
            "SELECT strain_id FROM strains WHERE strain_name = ?", (strain,)
        ) as cur:
            row = await cur.fetchone()
            if row is None:
                raise RuntimeError(f"Strain {strain} not found")
            strain_id = row[0]
        # Rebuild ancestry rows when lineage_tree is provided
        if lineage_tree is not None:
            await self._db.execute(
                "DELETE FROM strain_ancestry WHERE descendant_strain_id = ?",
                (strain_id,),
            )
            ancestors = _collect_ancestors(lineage_tree)
            if ancestors:
                await self._db.executemany(
                    "INSERT OR REPLACE INTO strain_ancestry"
                    " (ancestor_name, descendant_strain_id, depth, ancestor_url)"
                    " VALUES (?, ?, ?, ?)",
                    [(name, strain_id, depth, url) for name, url, depth in ancestors],
                )
            await self._db.commit()
        # Prepare phenotype data
        pheno_data = {
            "description": description,
            "image_crop_meta": json.dumps(image_crop_meta)
            if image_crop_meta is not None
            else None,
            "flower_days_min": flower_days_min,
            "flower_days_max": flower_days_max,
        }
        # Image handling
        if images is not None:
            pheno_data["images"] = json.dumps(images)
        elif image_base64:
            safe_strain = slugify(strain)
            safe_pheno = slugify(phenotype)

            abs_path = await self.image_manager.save_strain_image(
                safe_strain, safe_pheno, image_base64
            )
            filename = Path(abs_path).name
            image_path = f"/local/growspace_manager/strains/{filename}"
            pheno_data["image_path"] = image_path
        elif image_path:
            pheno_data["image_path"] = image_path
        # Invalidate analytics cache because data changed
        self._analytics_cache = None
        # Insert/replace phenotype data
        # Insert/replace phenotype data
        pheno_data = {k: v for k, v in pheno_data.items() if v is not None}

        if pheno_data:
            pheno_fields = ", ".join(
                ["strain_id", "phenotype_name", *list(pheno_data.keys())]
            )
            pheno_placeholders = ", ".join(["?"] * (len(pheno_data) + 2))

            # Build dynamic SET clause
            set_clause = ", ".join(
                [f"{k}=COALESCE(excluded.{k}, {k})" for k in pheno_data]
            )

            query = f"""
                INSERT INTO phenotypes ({pheno_fields})
                VALUES ({pheno_placeholders})
                ON CONFLICT(strain_id, phenotype_name) DO UPDATE SET
                    {set_clause}
            """  # noqa: S608
            await self._db.execute(
                query, (strain_id, phenotype, *tuple(pheno_data.values()))
            )
        else:
            # Just ensure it exists
            query = """
                INSERT INTO phenotypes (strain_id, phenotype_name)
                VALUES (?, ?)
                ON CONFLICT(strain_id, phenotype_name) DO NOTHING
            """
            await self._db.execute(query, (strain_id, phenotype))

        await self._db.commit()
        # Reload cache for immediate sensor updates
        await self.load()
        _LOGGER.info("Successfully added/updated strain %s (%s)", strain, phenotype)

    async def set_strain_meta(
        self,
        strain: str,
        phenotype: str | None = None,
        breeder: str | None = None,
        breeder_logo: str | None = None,
        strain_type: str | None = None,
        lineage: str | None = None,
        sex: str | None = None,
        flower_days_min: int | None = None,
        flower_days_max: int | None = None,
        description: str | None = None,
        image_base64: str | None = None,
        image_path: str | None = None,
        image_crop_meta: dict[str, Any] | None = None,
        images: list[dict[str, Any]] | None = None,
        sativa_percentage: int | None = None,
        indica_percentage: int | None = None,
        yield_potential: str | None = None,
        height: str | None = None,
        thc: float | None = None,
        cbd: float | None = None,
        cbg: float | None = None,
        effects: list[str] | None = None,
        aroma: list[str] | None = None,
        taste: list[str] | None = None,
        strain_description: str | None = None,
        awards: list[str] | None = None,
        lineage_tree: LineageNode | None = None,
    ) -> None:
        """Update metadata for a strain/phenotype."""
        # Invalidate analytics cache
        self._analytics_cache = None
        await self.add_strain(
            strain=strain,
            phenotype=phenotype,
            breeder=breeder,
            breeder_logo=breeder_logo,
            strain_type=strain_type,
            lineage=lineage,
            sex=sex,
            flower_days_min=flower_days_min,
            flower_days_max=flower_days_max,
            description=description,
            image_base64=image_base64,
            image_path=image_path,
            image_crop_meta=image_crop_meta,
            images=images,
            sativa_percentage=sativa_percentage,
            indica_percentage=indica_percentage,
            yield_potential=yield_potential,
            height=height,
            thc=thc,
            cbd=cbd,
            cbg=cbg,
            effects=effects,
            aroma=aroma,
            taste=taste,
            strain_description=strain_description,
            awards=awards,
            lineage_tree=lineage_tree,
        )

    async def _rebuild_strain_ancestry(self, strain_name: str) -> None:
        """Rebuild strain_ancestry rows for strain_name from the in-memory lineage cache.

        Resolves the full LineageNode tree via get_strain_lineage_tree() (which reads
        StoredParents from the in-memory cache), then rewrites all ancestry rows.
        Must be called after load() so the cache reflects the latest DB state.
        """
        if self._db is None:
            return
        cur = await self._db.execute(
            "SELECT strain_id FROM strains WHERE strain_name = ?", (strain_name,)
        )
        row = await cur.fetchone()
        if row is None:
            return
        strain_id = row[0]
        full_tree = self.get_strain_lineage_tree(strain_name)
        ancestors = _collect_ancestors(full_tree)
        await self._db.execute(
            "DELETE FROM strain_ancestry WHERE descendant_strain_id = ?", (strain_id,)
        )
        if ancestors:
            await self._db.executemany(
                "INSERT OR REPLACE INTO strain_ancestry"
                " (ancestor_name, descendant_strain_id, depth, ancestor_url)"
                " VALUES (?, ?, ?, ?)",
                [(name, strain_id, depth, url) for name, url, depth in ancestors],
            )
        await self._db.commit()

    async def update_strain_lineage_tree(
        self,
        strain_name: str,
        parents: StoredParents,
    ) -> str:
        """Store immediate parents for a strain and re-derive the flat lineage string.

        Args:
            strain_name: The strain to update.
            parents: StoredParents flat list with keys 'name' and 'source'.
                     Maximum 2 entries; extras are silently truncated.

        Returns:
            The derived flat lineage string (e.g. "OG Kush × Durban Poison").
        """
        if self._db is None:
            _LOGGER.warning("Database not connected, cannot update lineage tree")
            return ""

        parents = parents[:2]  # max 2 parents
        flat_lineage = " × ".join(p["name"] for p in parents)
        tree_json = json.dumps(parents)

        await self._db.execute(
            "UPDATE strains SET lineage_tree = ?, lineage = ? WHERE strain_name = ?",
            (tree_json, flat_lineage, strain_name),
        )
        await self._db.commit()
        await self.load()
        await self._rebuild_strain_ancestry(strain_name)
        _LOGGER.info("Updated lineage tree for strain '%s'", strain_name)
        return flat_lineage

    async def async_import_seedfinder_lineage_tree(
        self,
        root_strain_name: str,
        tree: dict[str, Any],
        scraper: Any | None = None,
    ) -> None:
        """Import a full multi-level seedfinder lineage tree.

        Walks every node in the tree, creates stub library entries for ancestors
        not already in the library, and stores each node's immediate parents so
        that ``get_strain_lineage_tree`` can resolve the full depth recursively.

        When ``scraper`` is provided, any parent node that has a SeedFinder URL
        but no children (i.e. the root page didn't expand that branch) is
        automatically fetched so its own lineage is included.

        The root strain itself must already exist in the library before calling
        this method (the caller is responsible for that).

        Args:
            root_strain_name: The root strain whose lineage is being imported.
            tree: Full lineage tree dict from the Seedfinder scraper
                  (``{name, parents: [{name, parents: ...}, ...]}``)
            scraper: Optional SeedfinderScraper used to follow URLs for leaf
                     parent nodes that have no children in the scraped tree.
        """
        if self._db is None:
            return

        lineage_by_node: dict[str, list[str]] = {}
        # Collect (name, url) for parent nodes that appear as leaves (no children)
        # but have a SeedFinder URL we can follow to get their lineage.
        leaf_parent_urls: dict[str, str] = {}

        def _collect(node: dict[str, Any]) -> None:
            name = (node.get("name") or "").strip()
            if not name:
                return
            parents = node.get("parents") or []
            parent_names = [
                (p.get("name") or "").strip()
                for p in parents
                if (p.get("name") or "").strip()
            ]
            if parent_names:
                lineage_by_node[name] = parent_names[:2]
            for parent in parents:
                pname = (parent.get("name") or "").strip()
                purl = (parent.get("url") or "").strip()
                if pname and purl and not (parent.get("parents") or []):
                    leaf_parent_urls[pname] = purl
                _collect(parent)

        _collect(tree)

        # For leaf parents with a known URL, fetch their own lineage page so we
        # capture branches that SeedFinder didn't expand on the root strain page.
        if scraper and leaf_parent_urls:
            for pname, purl in leaf_parent_urls.items():
                if pname in lineage_by_node:
                    continue  # already resolved from the initial tree
                try:
                    parent_details = await scraper.async_get_strain_details(purl)
                    if parent_details and parent_details.get("lineage_tree"):
                        parent_tree = parent_details["lineage_tree"]
                        parent_tree.setdefault("name", pname)
                        _collect(parent_tree)
                        _LOGGER.debug(
                            "Fetched lineage for leaf parent '%s' from %s", pname, purl
                        )
                except (
                    AttributeError,
                    KeyError,
                    ValueError,
                    ServiceValidationError,
                    GrowspaceError,
                ):
                    _LOGGER.debug("Could not fetch lineage for '%s' at %s", pname, purl)

        if not lineage_by_node:
            return

        all_names: set[str] = set()
        for name, parent_names in lineage_by_node.items():
            all_names.add(name)
            all_names.update(parent_names)

        for ancestor_name in all_names:
            if ancestor_name == root_strain_name:
                continue
            await self._db.execute(
                "INSERT OR IGNORE INTO strains (strain_name) VALUES (?)",
                (ancestor_name,),
            )
            await self._db.execute(
                """
                INSERT OR IGNORE INTO phenotypes (strain_id, phenotype_name)
                SELECT strain_id, 'default' FROM strains WHERE strain_name = ?
                """,
                (ancestor_name,),
            )

        for name, parent_names in lineage_by_node.items():
            library_parents = [{"name": n, "source": "library"} for n in parent_names]
            flat_lineage = " × ".join(parent_names)
            await self._db.execute(
                "UPDATE strains SET lineage_tree = ?, lineage = ? WHERE strain_name = ?",
                (json.dumps(library_parents), flat_lineage, name),
            )

        # Mark all ancestor nodes (not the root strain itself) as stubs
        for ancestor_name in all_names:
            if ancestor_name == root_strain_name:
                continue
            await self._db.execute(
                "UPDATE strains SET is_stub = 1 WHERE strain_name = ? AND breeder IS NULL",
                (ancestor_name,),
            )

        await self._db.commit()
        await self.load()
        self._lineage_cache.clear()
        for name in lineage_by_node:
            await self._rebuild_strain_ancestry(name)
        _LOGGER.info(
            "Imported seedfinder lineage tree for '%s' (%d nodes)",
            root_strain_name,
            len(lineage_by_node),
        )

    async def async_update_strain_generation(
        self, strain_name: str, generation: str
    ) -> None:
        """Write the generation classification tag for a strain.

        Args:
            strain_name: The strain to update.
            generation: Classification tag — e.g. "F1", "F2", "F3", "S1", "S2", "BX1", "BX2".
        """
        if self._db is None:
            _LOGGER.warning(
                "Database not connected, cannot update generation for '%s'", strain_name
            )
            return
        await self._db.execute(
            "UPDATE strains SET generation = ? WHERE strain_name = ?",
            (generation, strain_name),
        )
        await self._db.commit()
        if strain_name in self.strains:
            self.strains[strain_name].setdefault("meta", {})["generation"] = generation
        self._lineage_cache.clear()
        _LOGGER.debug("Set generation '%s' for strain '%s'", generation, strain_name)

    def get_strain_lineage_tree(
        self,
        strain_name: str,
        _seen: frozenset[str] | None = None,
        _depth: int = 0,
    ) -> LineageNode:
        """Recursively resolve the full lineage tree for a strain from the in-memory cache.

        Reads StoredParents from self.strains (no DB I/O) and builds a nested LineageNode.
        Stops recursing when a strain is already in the current path (_seen) to prevent
        infinite loops, or when _depth >= 15.

        Args:
            strain_name: Strain to resolve.
            _seen: Strain names already in the current resolution path (cycle detection).
            _depth: Current recursion depth (hard cap at 15).

        Returns:
            LineageNode: {name, source, parents: [...LineageNode]}
        """
        if _seen is None:
            if strain_name in self._lineage_cache:
                return self._lineage_cache[strain_name]
            _seen = frozenset()

        strain_meta = self.strains.get(strain_name, {}).get("meta", {})
        node: dict[str, Any] = {
            "name": strain_name,
            "source": "library",
            "parents": [],
            "generation": strain_meta.get("generation", ""),
        }

        if _depth >= 15 or strain_name in _seen:
            return node

        strain_data = self.strains.get(strain_name)
        if strain_data is None:
            return node

        parents = strain_data.get("meta", {}).get("lineage_tree") or []
        next_seen = _seen | {strain_name}

        for parent in parents[:2]:
            parent_name = parent.get("name", "")
            parent_phenotype = parent.get("phenotype") or None
            source = parent.get("source", "manual")
            if source == "library" and parent_name in self.strains:
                resolved = self.get_strain_lineage_tree(
                    parent_name, _seen=next_seen, _depth=_depth + 1
                )
                if parent_phenotype:
                    resolved["phenotype"] = parent_phenotype
            else:
                resolved = {"name": parent_name, "source": source, "parents": []}
                if parent_phenotype:
                    resolved["phenotype"] = parent_phenotype
            node["parents"].append(resolved)

        if _depth == 0:
            self._lineage_cache[strain_name] = node

        return node

    async def async_get_strains_by_ancestor(
        self, ancestor_name: str
    ) -> list[dict[str, Any]]:
        """Return all library strains that have ancestor_name anywhere in their lineage.

        Results are ordered by depth (closest first) then strain name.
        """
        if self._db is None:
            return []
        async with self._db.execute(
            """
            SELECT s.strain_id, s.strain_name, s.breeder, sa.depth
            FROM strain_ancestry sa
            JOIN strains s ON sa.descendant_strain_id = s.strain_id
            WHERE sa.ancestor_name = ?
            ORDER BY sa.depth, s.strain_name
            """,
            (ancestor_name,),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    async def async_get_shared_ancestors(
        self, strain_ids: list[int]
    ) -> list[dict[str, Any]]:
        """Return ancestors common to ALL given strains, with the shallowest depth.

        Results are ordered by closest_depth then ancestor_name.
        """
        if self._db is None or not strain_ids:
            return []
        placeholders = ",".join("?" * len(strain_ids))
        async with self._db.execute(
            f"""
            SELECT ancestor_name, ancestor_url, MIN(depth) as closest_depth
            FROM strain_ancestry
            WHERE descendant_strain_id IN ({placeholders})
            GROUP BY ancestor_name
            HAVING COUNT(DISTINCT descendant_strain_id) = ?
            ORDER BY closest_depth, ancestor_name
            """,  # noqa: S608
            (*strain_ids, len(strain_ids)),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    def get_strain_names(self) -> list[str]:
        """Return all strain names sorted alphabetically (lightweight, no image data)."""
        return sorted(self.strains.keys())

    def get_strain_entries(self) -> list[dict[str, str | None]]:
        """Return all strain+phenotype combinations for autocomplete.

        Each entry is {"name": strain_name, "phenotype": phenotype_name_or_None}.
        The 'default' phenotype is represented as phenotype=None (shown as bare strain name).
        """
        entries: list[dict[str, str | None]] = []
        for strain_name in sorted(self.strains):
            phenotypes = self.strains[strain_name].get("phenotypes", {})
            if not phenotypes:
                entries.append({"name": strain_name, "phenotype": None})
            else:
                entries.extend(
                    {
                        "name": strain_name,
                        "phenotype": None if pheno_name == "default" else pheno_name,
                    }
                    for pheno_name in sorted(phenotypes)
                )
        return entries

    def resolve_thumbnail(
        self, strain_name: str, phenotype_name: str
    ) -> dict[str, Any] | None:
        """Return the thumbnail image dict for a phenotype, with sibling fallback.

        Falls back to the 'default' phenotype, then alphabetical siblings, when the
        requested phenotype has no images. Returns None if no image exists anywhere.
        """
        strain_data = self.strains.get(strain_name)
        if strain_data is None:
            return None
        phenotypes = strain_data.get("phenotypes", {})
        normalized = phenotype_name or "default"

        def _thumbnail_from(pheno_data: dict[str, Any]) -> dict[str, Any] | None:
            imgs = pheno_data.get("images")
            if not imgs:
                return None
            for img in imgs:
                if img.get("is_thumbnail"):
                    return img
            return imgs[0]

        own = phenotypes.get(normalized, {})
        result = _thumbnail_from(own)
        if result is not None:
            return result

        # Fallback: prefer "default", then alphabetical siblings
        fallback_order = ["default"] + sorted(
            k for k in phenotypes if k != "default" and k != normalized
        )
        for sibling_name in fallback_order:
            sibling = phenotypes.get(sibling_name, {})
            result = _thumbnail_from(sibling)
            if result is not None:
                return result

        return None

    async def remove_strain_phenotype(self, strain: str, phenotype: str) -> None:
        """Remove a specific phenotype and its harvests."""
        if self._db is None:
            _LOGGER.warning("Database not connected, cannot remove phenotype")
            return
        phenotype = (phenotype or "default").strip()
        strain = strain.strip()
        # Get IDs
        query = """
            SELECT p.phenotype_id, s.strain_id FROM phenotypes p
            JOIN strains s ON p.strain_id = s.strain_id
            WHERE s.strain_name = ? AND p.phenotype_name = ?
        """
        async with self._db.execute(query, (strain, phenotype)) as cur:
            row = await cur.fetchone()
            if not row:
                _LOGGER.warning(
                    "Attempted to delete phenotype '%s' for strain '%s' but it was not found in database",
                    phenotype,
                    strain,
                )
                return
            phenotype_id = row["phenotype_id"]
            strain_id = row["strain_id"]
        # Delete harvests and phenotype
        await self._db.execute(
            "DELETE FROM harvests WHERE phenotype_id = ?", (phenotype_id,)
        )
        await self._db.execute(
            "DELETE FROM phenotypes WHERE phenotype_id = ?", (phenotype_id,)
        )
        await self._db.commit()

        # Delete image
        safe_strain = slugify(strain)
        safe_pheno = slugify(phenotype)
        self.image_manager.delete_image(safe_strain, safe_pheno)

        # If no other phenotypes, delete strain
        async with self._db.execute(
            "SELECT COUNT(*) FROM phenotypes WHERE strain_id = ?", (strain_id,)
        ) as cur:
            row = await cur.fetchone()
            if row is not None and row[0] == 0:
                await self._db.execute(
                    "DELETE FROM strains WHERE strain_id = ?", (strain_id,)
                )
                await self._db.commit()
        # Invalidate cache and reload
        self._analytics_cache = None
        await self.load()
        _LOGGER.info("Removed phenotype %s from strain %s", phenotype, strain)

    async def remove_strain(self, strain: str) -> None:
        """Remove an entire strain and all related data."""
        if self._db is None:
            _LOGGER.warning("Database not connected, cannot remove strain")
            return
        strain = strain.strip()
        async with self._db.execute(
            "SELECT strain_id FROM strains WHERE strain_name = ?", (strain,)
        ) as cur:
            row = await cur.fetchone()
            if not row:
                _LOGGER.warning(
                    "Attempted to delete strain '%s' but it was not found in database",
                    strain,
                )
                return
            strain_id = row[0]
        # Delete harvests, phenotypes, strain
        await self._db.execute(
            "DELETE FROM harvests WHERE phenotype_id IN (SELECT phenotype_id FROM phenotypes WHERE strain_id = ?)",
            (strain_id,),
        )
        await self._db.execute(
            "DELETE FROM phenotypes WHERE strain_id = ?", (strain_id,)
        )
        await self._db.execute("DELETE FROM strains WHERE strain_id = ?", (strain_id,))
        await self._db.commit()
        # Invalidate cache and reload
        self._analytics_cache = None
        await self.load()
        _LOGGER.info("Removed strain %s from library", strain)

    def get_all(self) -> dict[str, dict[str, Any]]:
        """Return the raw in‑memory strain dictionary."""
        return self.strains

    def get_analytics(self) -> dict[str, Any]:
        """Calculate and return aggregated analytics for the library.

        The result mirrors what the StrainLibrarySensor previously calculated.
        """
        if self._analytics_cache is not None:
            return self._analytics_cache
        analytics_data: dict[str, Any] = {}

        for strain_name, strain_data in self.strains.items():
            phenotypes = strain_data.get("phenotypes", {})
            strain_harvests: list[dict[str, Any]] = []
            pheno_analytics: dict[str, Any] = {}
            for pheno_name, pheno_data in phenotypes.items():
                harvests = pheno_data.get("harvests", [])
                strain_harvests.extend(harvests)
                num = len(harvests)
                if num:
                    total_veg = sum(h.get("veg_days", 0) for h in harvests)
                    total_flower = sum(h.get("flower_days", 0) for h in harvests)
                    dry_weights = [
                        h["dry_weight"]
                        for h in harvests
                        if h.get("dry_weight") is not None
                    ]
                    wet_weights = [
                        h["wet_weight"]
                        for h in harvests
                        if h.get("wet_weight") is not None
                    ]
                    stats: dict[str, Any] = {
                        "avg_veg_days": round(total_veg / num),
                        "avg_flower_days": round(total_flower / num),
                        "total_harvests": num,
                    }
                    if dry_weights:
                        stats["avg_dry_weight"] = round(
                            sum(dry_weights) / len(dry_weights), 1
                        )
                        stats["total_dry_yield"] = round(sum(dry_weights), 1)
                    if wet_weights:
                        stats["avg_wet_weight"] = round(
                            sum(wet_weights) / len(wet_weights), 1
                        )
                else:
                    stats = {
                        "avg_veg_days": 0,
                        "avg_flower_days": 0,
                        "total_harvests": 0,
                    }
                # Exclude heavy fields
                pheno_meta = {
                    k: v
                    for k, v in pheno_data.items()
                    if k
                    not in ["harvests", "description", "image_path", "image_crop_meta"]
                }
                pheno_analytics[pheno_name] = {**stats, **pheno_meta}
            num_strain_harvests = len(strain_harvests)
            if num_strain_harvests:
                strain_avg_veg = round(
                    sum(h.get("veg_days", 0) for h in strain_harvests)
                    / num_strain_harvests
                )
                strain_avg_flower = round(
                    sum(h.get("flower_days", 0) for h in strain_harvests)
                    / num_strain_harvests
                )
            else:
                strain_avg_veg = 0
                strain_avg_flower = 0


            analytics_data[strain_name] = {
                "meta": strain_data.get("meta", {}),
                "analytics": {
                    "avg_veg_days": strain_avg_veg,
                    "avg_flower_days": strain_avg_flower,
                    "total_harvests": num_strain_harvests,
                },
                "phenotypes": pheno_analytics,
            }

        result = {
            "strains": analytics_data,
            "strain_list": list(self.strains.keys()),
        }
        self._analytics_cache = result
        return result

    async def import_library(
        self, library_data: dict[str, Any], replace: bool = False
    ) -> int:
        """Import a library dictionary into the database."""
        if self._db is None:
            _LOGGER.warning("Database not connected, cannot import library")
            return 0

        # Validation
        if not isinstance(library_data, dict):
            _LOGGER.warning("Invalid library data format: expected dict")  # type: ignore[unreachable]
            return 0

        if replace:
            await self.clear()
        for strain_name, strain_data in library_data.items():
            meta = strain_data.get("meta", {})
            phenotypes = strain_data.get("phenotypes", {})
            await self.add_strain(
                strain=strain_name,
                breeder=meta.get("breeder"),
                breeder_logo=meta.get("breeder_logo"),
                strain_type=meta.get("type"),
                lineage=meta.get("lineage"),
                sex=meta.get("sex"),
                sativa_percentage=meta.get("sativa_percentage"),
                indica_percentage=meta.get("indica_percentage"),
            )
            for pheno_name, pheno_data in phenotypes.items():
                image_path = pheno_data.get("image_path")
                if image_path and image_path.startswith("images/"):
                    filename = Path(image_path).name
                    image_path = f"/local/growspace_manager/strains/{filename}"
                await self.add_strain(
                    strain=strain_name,
                    phenotype=pheno_name,
                    flower_days_min=pheno_data.get("flower_days_min"),
                    flower_days_max=pheno_data.get("flower_days_max"),
                    description=pheno_data.get("description"),
                    image_path=image_path,
                    image_crop_meta=pheno_data.get("image_crop_meta"),
                )
                phenotype_id = await self._ensure_strain_and_phenotype_exist(
                    strain_name, pheno_name
                )
                for harvest in pheno_data.get("harvests", []):
                    await self._db.execute(
                        """
                        INSERT INTO harvests (phenotype_id, veg_days, flower_days, harvest_date)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT DO NOTHING
                        """,
                        (
                            phenotype_id,
                            harvest.get("veg_days"),
                            harvest.get("flower_days"),
                            harvest.get("harvest_date", dt_util.utcnow().isoformat()),
                        ),
                    )
                await self._db.commit()
        # Invalidate analytics cache and reload
        self._analytics_cache = None
        await self.load()
        return len(self.strains)

    async def import_strains(self, strains: list[str], replace: bool = False) -> int:
        """Import a list of strain names, creating default entries."""
        # Validation
        if not isinstance(strains, list):
            _LOGGER.warning("Invalid strains format: expected list")  # type: ignore[unreachable]
            return len(self.strains)

        if replace:
            await self.clear()

        for strain in strains:
            await self.add_strain(strain)
        await self.load()
        return len(self.strains)

    async def clear(self) -> int:
        """Clear all entries from the database."""
        count = len(self.strains)
        if self._db is None:
            return count
        await self._db.executescript(
            "DELETE FROM harvests; DELETE FROM phenotypes; DELETE FROM strains;"
        )
        await self._db.commit()
        self.strains.clear()
        self._analytics_cache = None
        return count

    async def export_library_to_zip(self, output_dir: str) -> str:
        """Export the library and images to a ZIP file."""
        # Ensure analytics are up‑to‑date (cached or calculated)
        if self._analytics_cache is None:
            self.get_analytics()

        # Get all data
        library_data = self.get_all()

        # Filter out stub strains (placeholders created during lineage resolution)
        filtered_data = {
            name: data
            for name, data in library_data.items()
            if not data.get("meta", {}).get("is_stub", False)
        }

        return await self.import_export_manager.export_library(
            filtered_data, output_dir
        )

    async def import_library_from_zip(self, zip_path: str, merge: bool = True) -> int:
        """Import a library from a ZIP archive."""
        target_dir = self.hass.config.path("www", "growspace_manager", "strains")
        library_data = await self.import_export_manager.import_library(
            zip_path, target_dir
        )

        # Schedule async import of the JSON data
        # Note: import_library is async, so we can await it directly if we are in an async context.
        # But original code used create_task. Let's see if we can await it.
        # The method returns int (count), so awaiting is better.
        return await self.import_library(library_data, replace=not merge)
