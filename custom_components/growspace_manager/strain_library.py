"""Manages the strain library for the Growspace Manager integration using SQLite.

This file defines the `StrainLibrary` class, which is responsible for storing,
retrieving, and analyzing data about different cannabis strains using a dedicated
asynchronous SQLite database (aiosqlite).
"""

from __future__ import annotations
import base64
import datetime
import json
import logging
import os
import shutil
import zipfile
from typing import Any, Mapping

import aiosqlite
from homeassistant.core import HomeAssistant
from homeassistant.util import slugify

from .const import DB_FILE_STRAIN_LIBRARY

_LOGGER = logging.getLogger(__name__)

# Database schema
STRAIN_LIBRARY_SCHEMA = """
CREATE TABLE IF NOT EXISTS strains (
    strain_id INTEGER PRIMARY KEY,
    strain_name TEXT UNIQUE NOT NULL,
    breeder TEXT,
    type TEXT,
    lineage TEXT,
    sex TEXT,
    sativa_percentage INTEGER,
    indica_percentage INTEGER
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

    async def async_setup(self) -> None:
        """Set up the database connection and schema."""
        _LOGGER.debug("Setting up StrainLibrary DB at %s", self._db_path)
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(STRAIN_LIBRARY_SCHEMA)
        await self._db.commit()
        await self.load()

    async def async_close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    async def load(self) -> None:
        """Load all strain and phenotype data into the in-memory cache."""
        # Fetch all harvests first to avoid N+1 queries and async calls in the loop
        harvests_by_pheno: dict[int, list[dict[str, Any]]] = {}
        async with self._db.execute("SELECT phenotype_id, veg_days, flower_days, harvest_date FROM harvests") as cursor:
            async for row in cursor:
                pheno_id = row["phenotype_id"]
                if pheno_id not in harvests_by_pheno:
                    harvests_by_pheno[pheno_id] = []
                harvests_by_pheno[pheno_id].append({
                    "veg_days": row["veg_days"],
                    "flower_days": row["flower_days"],
                    "harvest_date": row["harvest_date"],
                })

        new_strains: dict[str, dict[str, Any]] = {}
        query = """
            SELECT
                s.strain_id, s.strain_name, s.breeder, s.type, s.lineage, s.sex,
                s.sativa_percentage, s.indica_percentage,
                p.phenotype_id, p.phenotype_name, p.description, p.image_path,
                p.image_crop_meta, p.flower_days_min, p.flower_days_max
            FROM strains s
            LEFT JOIN phenotypes p ON s.strain_id = p.strain_id
        """
        async with self._db.execute(query) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                strain_name = row["strain_name"]
                phenotype_name = row["phenotype_name"] or "default"
                if strain_name not in new_strains:
                    new_strains[strain_name] = {
                        "meta": {
                            k: row[k]
                            for k in [
                                "breeder",
                                "type",
                                "lineage",
                                "sex",
                                "sativa_percentage",
                                "indica_percentage",
                            ]
                            if row[k] is not None
                        },
                        "phenotypes": {},
                    }
                if row["phenotype_id"] is not None:
                    # Decode image_crop_meta JSON safely
                    image_crop_meta = row["image_crop_meta"]
                    try:
                        image_crop_meta = json.loads(image_crop_meta) if image_crop_meta else None
                    except json.JSONDecodeError:
                        _LOGGER.warning(
                            "Could not decode image_crop_meta for %s (%s)",
                            strain_name,
                            phenotype_name,
                        )
                        image_crop_meta = None
                    
                    pheno_id = row["phenotype_id"]
                    phenotype_data = {
                        "phenotype_id": pheno_id,
                        "description": row["description"],
                        "image_path": row["image_path"],
                        "image_crop_meta": image_crop_meta,
                        "flower_days_min": row["flower_days_min"],
                        "flower_days_max": row["flower_days_max"],
                        "harvests": harvests_by_pheno.get(pheno_id, []),
                    }
                    # Remove None values
                    phenotype_data = {k: v for k, v in phenotype_data.items() if v is not None}
                    new_strains[strain_name]["phenotypes"][phenotype_name] = phenotype_data
        
        self.strains = new_strains
        self._analytics_cache = None  # Invalidate analytics cache
        _LOGGER.info("Loaded strain library metadata for %d strains", len(self.strains))

    async def save(self) -> None:
        """No-op for SQLite implementation - changes are committed immediately."""
        pass

    async def record_harvest(self, strain: str, phenotype: str, veg_days: int, flower_days: int) -> None:
        """Record a harvest event for a specific strain and phenotype."""
        strain = strain.strip()
        phenotype = phenotype.strip() or "default"
        phenotype_id = await self._ensure_strain_and_phenotype_exist(strain, phenotype)
        harvest_date = datetime.datetime.now().isoformat()
        query = """
            INSERT INTO harvests (phenotype_id, veg_days, flower_days, harvest_date)
            VALUES (?, ?, ?, ?)
        """
        await self._db.execute(query, (phenotype_id, veg_days, flower_days, harvest_date))
        await self._db.commit()
        # Invalidate analytics cache
        self._analytics_cache = None
        # Update in‑memory cache for immediate sensor use
        if strain in self.strains and phenotype in self.strains[strain]["phenotypes"]:
            self.strains[strain]["phenotypes"][phenotype]["harvests"].append(
                {"veg_days": veg_days, "flower_days": flower_days, "harvest_date": harvest_date}
            )
        _LOGGER.info(
            "Recorded harvest for %s (%s): veg=%d days, flower=%d days",
            strain,
            phenotype,
            veg_days,
            flower_days,
        )

    async def _ensure_strain_and_phenotype_exist(self, strain_name: str, phenotype_name: str) -> int:
        """Ensure the strain and phenotype exist, returning the phenotype ID."""
        # Ensure strain exists
        async with self._db.execute(
            "SELECT strain_id FROM strains WHERE strain_name = ?", (strain_name,)
        ) as cursor:
            strain_row = await cursor.fetchone()
            if not strain_row:
                await self.add_strain(strain_name, phenotype_name)
                async with self._db.execute(
                    "SELECT strain_id FROM strains WHERE strain_name = ?", (strain_name,)
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
                insert = "INSERT INTO phenotypes (strain_id, phenotype_name) VALUES (?, ?)"
                await self._db.execute(insert, (strain_id, phenotype_name))
                await self._db.commit()
                async with self._db.execute(query, (strain_id, phenotype_name)) as c:
                    phenotype_row = await c.fetchone()
            return phenotype_row[0]

    async def add_strain(
        self,
        strain: str,
        phenotype: str | None = None,
        breeder: str | None = None,
        strain_type: str | None = None,
        lineage: str | None = None,
        sex: str | None = None,
        flower_days_min: int | None = None,
        flower_days_max: int | None = None,
        description: str | None = None,
        image_base64: str | None = None,
        image_path: str | None = None,
        image_crop_meta: dict | None = None,
        sativa_percentage: int | None = None,
        indica_percentage: int | None = None,
    ) -> None:
        """Add or update a strain/phenotype entry."""
        strain = strain.strip()
        phenotype = phenotype.strip() if phenotype else "default"
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
                raise ValueError("Combined Sativa/Indica percentage cannot exceed 100%.")
        # Insert/replace strain metadata
        strain_data = {
            "breeder": breeder,
            "type": strain_type,
            "lineage": lineage,
            "sex": sex,
            "sativa_percentage": sativa_percentage,
            "indica_percentage": indica_percentage,
        }
        strain_data = {k: v for k, v in strain_data.items() if v is not None}
        fields = ", ".join(["strain_name"] + list(strain_data.keys()))
        placeholders = ", ".join(["?"] * (len(strain_data) + 1))
        query = f"""
            INSERT OR REPLACE INTO strains ({fields})
            VALUES ({placeholders})
            ON CONFLICT(strain_name) DO UPDATE SET
                breeder=COALESCE(excluded.breeder, breeder),
                type=COALESCE(excluded.type, type),
                lineage=COALESCE(excluded.lineage, lineage),
                sex=COALESCE(excluded.sex, sex),
                sativa_percentage=COALESCE(excluded.sativa_percentage, sativa_percentage),
                indica_percentage=COALESCE(excluded.indica_percentage, indica_percentage)
            WHERE strain_name = excluded.strain_name
        """
        await self._db.execute(query, (strain,) + tuple(strain_data.values()))
        await self._db.commit()
        # Get strain_id
        async with self._db.execute("SELECT strain_id FROM strains WHERE strain_name = ?", (strain,)) as cur:
            strain_id = (await cur.fetchone())[0]
        # Prepare phenotype data
        pheno_data = {
            "description": description,
            "image_crop_meta": json.dumps(image_crop_meta) if image_crop_meta is not None else None,
            "flower_days_min": flower_days_min,
            "flower_days_max": flower_days_max,
        }
        # Image handling
        if image_base64:
            image_path = await self._save_strain_image(strain, phenotype, image_base64)
            pheno_data["image_path"] = image_path
        elif image_path:
            pheno_data["image_path"] = image_path
        # Invalidate analytics cache because data changed
        self._analytics_cache = None
        # Insert/replace phenotype data
        pheno_data = {k: v for k, v in pheno_data.items() if v is not None}
        if pheno_data:
            pheno_fields = ", ".join(["strain_id", "phenotype_name"] + list(pheno_data.keys()))
            pheno_placeholders = ", ".join(["?"] * (len(pheno_data) + 2))
            query = f"""
                INSERT INTO phenotypes ({pheno_fields})
                VALUES ({pheno_placeholders})
                ON CONFLICT(strain_id, phenotype_name) DO UPDATE SET
                    description=COALESCE(excluded.description, description),
                    image_path=COALESCE(excluded.image_path, image_path),
                    image_crop_meta=COALESCE(excluded.image_crop_meta, image_crop_meta),
                    flower_days_min=COALESCE(excluded.flower_days_min, flower_days_min),
                    flower_days_max=COALESCE(excluded.flower_days_max, flower_days_max)
            """
            await self._db.execute(query, (strain_id, phenotype) + tuple(pheno_data.values()))
            await self._db.commit()
        # Reload cache for immediate sensor updates
        await self.load()
        _LOGGER.info("Successfully added/updated strain %s (%s)", strain, phenotype)

    async def set_strain_meta(
        self,
        strain: str,
        phenotype: str | None = None,
        breeder: str | None = None,
        strain_type: str | None = None,
        lineage: str | None = None,
        sex: str | None = None,
        flower_days_min: int | None = None,
        flower_days_max: int | None = None,
        description: str | None = None,
        image_base64: str | None = None,
        image_path: str | None = None,
        image_crop_meta: dict | None = None,
        sativa_percentage: int | None = None,
        indica_percentage: int | None = None,
    ) -> None:
        """Update metadata for a strain/phenotype."""
        # Invalidate analytics cache
        self._analytics_cache = None
        await self.add_strain(
            strain=strain,
            phenotype=phenotype,
            breeder=breeder,
            strain_type=strain_type,
            lineage=lineage,
            sex=sex,
            flower_days_min=flower_days_min,
            flower_days_max=flower_days_max,
            description=description,
            image_base64=image_base64,
            image_path=image_path,
            image_crop_meta=image_crop_meta,
            sativa_percentage=sativa_percentage,
            indica_percentage=indica_percentage,
        )

    async def _save_strain_image(self, strain: str, phenotype: str, image_base64: str) -> str:
        """Decode and save a strain image to the www directory, returning a web path."""
        try:
            if image_base64.startswith("data:"):
                # Strip data URI prefix
                _, image_base64 = image_base64.split(",", 1)
            base_dir = self.hass.config.path("www", "growspace_manager", "strains")
            os.makedirs(base_dir, exist_ok=True)
            safe_strain = slugify(strain)
            safe_pheno = slugify(phenotype)
            filename = f"{safe_strain}_{safe_pheno}.jpg"
            file_path = os.path.join(base_dir, filename)
            image_data = base64.b64decode(image_base64)
            def _write():
                with open(file_path, "wb") as f:
                    f.write(image_data)
            await self.hass.async_add_executor_job(_write)
            return f"/local/growspace_manager/strains/{filename}"
        except Exception as err:
            _LOGGER.error("Failed to save strain image: %s", err)
            return ""

    async def remove_strain_phenotype(self, strain: str, phenotype: str) -> None:
        """Remove a specific phenotype and its harvests."""
        phenotype = phenotype.strip() or "default"
        # Get IDs
        query = """
            SELECT p.phenotype_id, s.strain_id FROM phenotypes p
            JOIN strains s ON p.strain_id = s.strain_id
            WHERE s.strain_name = ? AND p.phenotype_name = ?
        """
        async with self._db.execute(query, (strain, phenotype)) as cur:
            row = await cur.fetchone()
            if not row:
                return
            phenotype_id = row["phenotype_id"]
            strain_id = row["strain_id"]
        # Delete harvests and phenotype
        await self._db.execute("DELETE FROM harvests WHERE phenotype_id = ?", (phenotype_id,))
        await self._db.execute("DELETE FROM phenotypes WHERE phenotype_id = ?", (phenotype_id,))
        await self._db.commit()
        # If no other phenotypes, delete strain
        async with self._db.execute("SELECT COUNT(*) FROM phenotypes WHERE strain_id = ?", (strain_id,)) as cur:
            if (await cur.fetchone())[0] == 0:
                await self._db.execute("DELETE FROM strains WHERE strain_id = ?", (strain_id,))
                await self._db.commit()
        # Invalidate cache and reload
        self._analytics_cache = None
        await self.load()
        _LOGGER.info("Removed phenotype %s from strain %s", phenotype, strain)

    async def remove_strain(self, strain: str) -> None:
        """Remove an entire strain and all related data."""
        async with self._db.execute("SELECT strain_id FROM strains WHERE strain_name = ?", (strain,)) as cur:
            row = await cur.fetchone()
            if not row:
                return
            strain_id = row[0]
        # Delete harvests, phenotypes, strain
        await self._db.execute(
            "DELETE FROM harvests WHERE phenotype_id IN (SELECT phenotype_id FROM phenotypes WHERE strain_id = ?)",
            (strain_id,),
        )
        await self._db.execute("DELETE FROM phenotypes WHERE strain_id = ?", (strain_id,))
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
                    stats = {
                        "avg_veg_days": round(total_veg / num),
                        "avg_flower_days": round(total_flower / num),
                        "total_harvests": num,
                    }
                else:
                    stats = {"avg_veg_days": 0, "avg_flower_days": 0, "total_harvests": 0}
                # Exclude heavy fields
                pheno_meta = {k: v for k, v in pheno_data.items() if k not in ["harvests", "description", "image_path", "image_crop_meta"]}
                pheno_analytics[pheno_name] = {**stats, **pheno_meta}
            num_strain_harvests = len(strain_harvests)
            if num_strain_harvests:
                strain_avg_veg = round(sum(h.get("veg_days", 0) for h in strain_harvests) / num_strain_harvests)
                strain_avg_flower = round(sum(h.get("flower_days", 0) for h in strain_harvests) / num_strain_harvests)
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
        result = {"strains": analytics_data, "strain_list": list(self.strains.keys())}
        self._analytics_cache = result
        return result

    async def import_library(self, library_data: dict[str, Any], replace: bool = False) -> int:
        """Import a library dictionary into the database."""
        if not isinstance(library_data, dict):
            _LOGGER.warning("Import failed: data must be a dictionary.")
            return len(self.strains)
        if replace:
            await self.clear()
        for strain_name, strain_data in library_data.items():
            meta = strain_data.get("meta", {})
            phenotypes = strain_data.get("phenotypes", {})
            await self.add_strain(
                strain=strain_name,
                breeder=meta.get("breeder"),
                strain_type=meta.get("type"),
                lineage=meta.get("lineage"),
                sex=meta.get("sex"),
                sativa_percentage=meta.get("sativa_percentage"),
                indica_percentage=meta.get("indica_percentage"),
            )
            for pheno_name, pheno_data in phenotypes.items():
                image_path = pheno_data.get("image_path")
                if image_path and image_path.startswith("images/"):
                    filename = os.path.basename(image_path)
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
                phenotype_id = await self._ensure_strain_and_phenotype_exist(strain_name, pheno_name)
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
                            harvest.get("harvest_date", datetime.datetime.now().isoformat()),
                        ),
                    )
                await self._db.commit()
        # Invalidate analytics cache and reload
        self._analytics_cache = None
        await self.load()
        return len(self.strains)

    async def import_strains(self, strains: list[str], replace: bool = False) -> int:
        """Import a list of strain names, creating default entries."""
        if not isinstance(strains, list):
            _LOGGER.warning("Import failed: strains must be a list.")
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
        await self._db.executescript("DELETE FROM harvests; DELETE FROM phenotypes; DELETE FROM strains;")
        await self._db.commit()
        self.strains.clear()
        self._analytics_cache = None
        return count

    async def export_library_to_zip(self, output_dir: str) -> str:
        """Export the library and images to a ZIP file."""
        # Ensure analytics are up‑to‑date (cached or calculated)
        if self._analytics_cache is None:
            self.get_analytics()
        return await self.hass.async_add_executor_job(self._export_sync, output_dir)

    def _export_sync(self, output_dir: str) -> str:
        """Synchronous helper to create the export ZIP file."""
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_path = os.path.join(output_dir, f"strain_library_export_{timestamp}.zip")
        strains_export = self.get_all()
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for strain_data in strains_export.values():
                if "phenotypes" in strain_data:
                    for pheno_data in strain_data["phenotypes"].values():
                        if "image_path" in pheno_data:
                            img_path = pheno_data["image_path"]
                            if img_path.startswith("/local/"):
                                rel = img_path.replace("/local/", "", 1)
                                fs_path = self.hass.config.path(rel)
                                if os.path.exists(fs_path):
                                    zip_name = f"images/{os.path.basename(fs_path)}"
                                    zipf.write(fs_path, zip_name)
                                    pheno_data["image_path"] = zip_name
        zipf.writestr("library.json", json.dumps(strains_export, indent=2))
        _LOGGER.info("Exported strain library to %s", zip_path)
        return zip_path

    async def import_library_from_zip(self, zip_path: str, merge: bool = True) -> int:
        """Import a library from a ZIP archive."""
        return await self.hass.async_add_executor_job(self._import_sync, zip_path, merge)

    def _import_sync(self, zip_path: str, merge: bool) -> int:
        """Synchronous helper to import from a ZIP file."""
        if not os.path.exists(zip_path):
            raise FileNotFoundError(f"ZIP file not found: {zip_path}")
        if not zipfile.is_zipfile(zip_path):
            raise ValueError(f"Not a valid ZIP file: {zip_path}")
        target_dir = self.hass.config.path("www", "growspace_manager", "strains")
        os.makedirs(target_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zipf:
            if "library.json" not in zipf.namelist():
                raise ValueError("library.json missing from archive")
            with zipf.open("library.json") as f:
                library_data = json.load(f)
            for info in zipf.infolist():
                if info.filename.startswith("images/") and not info.is_dir():
                    dest = os.path.join(target_dir, os.path.basename(info.filename))
                    with zipf.open(info) as src, open(dest, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        # Schedule async import of the JSON data
        self.hass.create_task(self.import_library(library_data, replace=not merge))
        return len(self.strains)