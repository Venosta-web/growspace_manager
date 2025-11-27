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
from typing import Any
from collections.abc import Mapping

import aiosqlite
from homeassistant.core import HomeAssistant
from homeassistant.util import slugify

from .const import DB_FILE_STRAIN_LIBRARY

_LOGGER = logging.getLogger(__name__)


# Database Schema Definition
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
    """A class to manage the strain library with harvest analytics using a SQLite DB."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the StrainLibrary.

        Args:
            hass: The Home Assistant instance.
        """
        self.hass = hass
        self._db_path = hass.config.path(DB_FILE_STRAIN_LIBRARY)
        self._db: aiosqlite.Connection | None = None
        self.strains: dict[str, Any] = {} # In-memory cache of metadata only

    async def async_setup(self) -> None:
        """Set up the SQLite database connection and ensure schema is present."""
        if self._db is None:
            self._db = await aiosqlite.connect(self._db_path, loop=self.hass.loop)
            self._db.row_factory = aiosqlite.Row # Use dict-like rows

        async with self._db.cursor() as cursor:
            await cursor.executescript(STRAIN_LIBRARY_SCHEMA)
            await self._db.commit()

        _LOGGER.info("Strain library database successfully opened and schema verified at %s", self._db_path)
        await self.load()

    async def load(self) -> None:
        """Load the strain library metadata from the database into in-memory cache."""
        if self._db is None:
            await self.async_setup()

        self.strains = {}
        query = """
            SELECT
                s.strain_id, s.strain_name, s.breeder, s.type, s.lineage, s.sex, s.sativa_percentage, s.indica_percentage,
                p.phenotype_id, p.phenotype_name, p.description, p.image_path, p.image_crop_meta, p.flower_days_min, p.flower_days_max
            FROM strains s
            LEFT JOIN phenotypes p ON s.strain_id = p.strain_id
        """

        async with self._db.execute(query) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                strain_name = row['strain_name']
                phenotype_name = row['phenotype_name'] or 'default'

                if strain_name not in self.strains:
                    self.strains[strain_name] = {
                        "meta": {
                            k: row[k] for k in ['breeder', 'type', 'lineage', 'sex', 'sativa_percentage', 'indica_percentage'] if row[k] is not None
                        },
                        "phenotypes": {}
                    }
                
                if row['phenotype_id'] is not None:
                    # Fetch and convert JSON blob
                    image_crop_meta = row['image_crop_meta']
                    try:
                        image_crop_meta = json.loads(image_crop_meta) if image_crop_meta else None
                    except json.JSONDecodeError:
                        _LOGGER.warning("Could not decode image_crop_meta for %s (%s)", strain_name, phenotype_name)
                        image_crop_meta = None

                    phenotype_data = {
                        "phenotype_id": row['phenotype_id'],
                        "description": row['description'],
                        "image_path": row['image_path'],
                        "image_crop_meta": image_crop_meta,
                        "flower_days_min": row['flower_days_min'],
                        "flower_days_max": row['flower_days_max'],
                        "harvests": await self._fetch_harvests(row['phenotype_id'])
                    }

                    # Filter None values from phenotype_data
                    phenotype_data = {k: v for k, v in phenotype_data.items() if v is not None}
                    self.strains[strain_name]["phenotypes"][phenotype_name] = phenotype_data

        _LOGGER.info("Loaded strain library metadata for %d strains", len(self.strains))

    async def _fetch_harvests(self, phenotype_id: int) -> list[Mapping]:
        """Fetch all harvest records for a given phenotype ID."""
        query = """
            SELECT veg_days, flower_days, harvest_date FROM harvests WHERE phenotype_id = ?
        """
        async with self._db.execute(query, (phenotype_id,)) as cursor:
            # We don't need to return harvest_id, only the data required by sensor
            return [dict(row) for row in await cursor.fetchall()]

    async def save(self) -> None:
        """No-op for SQLite implementation, changes are committed immediately by caller."""
        pass # Changes are committed immediately by the methods below

    async def record_harvest(
        self, strain: str, phenotype: str, veg_days: int, flower_days: int
    ) -> None:
        """Record a harvest event for a specific strain and phenotype."""
        strain = strain.strip()
        phenotype = phenotype.strip() or "default"

        phenotype_id = await self._ensure_strain_and_phenotype_exist(strain, phenotype)
        harvest_date = datetime.now().isoformat()

        query = """
            INSERT INTO harvests (phenotype_id, veg_days, flower_days, harvest_date)
            VALUES (?, ?, ?, ?)
        """
        await self._db.execute(query, (phenotype_id, veg_days, flower_days, harvest_date))
        await self._db.commit()
        
        # Invalidate the cache for this phenotype's harvests to force recalculation on next load
        if strain in self.strains and phenotype in self.strains[strain]['phenotypes']:
             self.strains[strain]['phenotypes'][phenotype]['harvests'].append({
                 "veg_days": veg_days, 
                 "flower_days": flower_days, 
                 "harvest_date": harvest_date
             })
             
        _LOGGER.info(
            "Recorded harvest for %s (%s): veg=%d days, flower=%d days",
            strain,
            phenotype,
            veg_days,
            flower_days,
        )

    async def _ensure_strain_and_phenotype_exist(self, strain_name: str, phenotype_name: str) -> int:
        """Ensure the strain and phenotype records exist, returning the phenotype ID."""
        # 1. Ensure Strain exists (using current in-memory meta if possible)
        async with self._db.execute("SELECT strain_id FROM strains WHERE strain_name = ?", (strain_name,)) as cursor:
            strain_row = await cursor.fetchone()
            if not strain_row:
                await self.add_strain(strain_name, phenotype_name) # Uses internal method for initial add
                async with self._db.execute("SELECT strain_id FROM strains WHERE strain_name = ?", (strain_name,)) as c:
                     strain_row = await c.fetchone()
                     if not strain_row:
                         raise RuntimeError(f"Failed to create and retrieve strain ID for {strain_name}")
            strain_id = strain_row[0]

        # 2. Ensure Phenotype exists
        query = "SELECT phenotype_id FROM phenotypes WHERE strain_id = ? AND phenotype_name = ?"
        async with self._db.execute(query, (strain_id, phenotype_name)) as cursor:
            phenotype_row = await cursor.fetchone()
            if not phenotype_row:
                # Phenotype does not exist, insert default phenotype record
                insert_query = """
                    INSERT INTO phenotypes (strain_id, phenotype_name) VALUES (?, ?)
                """
                await self._db.execute(insert_query, (strain_id, phenotype_name))
                await self._db.commit()
                # Re-query for the new ID
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
        """Add a single strain/phenotype combination to the database."""
        strain = strain.strip()
        phenotype = phenotype.strip() if phenotype else "default"

        if strain_type and str(strain_type).lower() == "hybrid":
            if sativa_percentage is not None and indica_percentage is None:
                indica_percentage = 100 - sativa_percentage
            elif indica_percentage is not None and sativa_percentage is None:
                sativa_percentage = 100 - indica_percentage

            if sativa_percentage is not None and indica_percentage is not None and sativa_percentage + indica_percentage > 100:
                raise ValueError("Combined Sativa/Indica percentage cannot exceed 100%.")

        # 1. INSERT or IGNORE Strain Metadata
        strain_data = {
            "breeder": breeder, "type": strain_type, "lineage": lineage, "sex": sex,
            "sativa_percentage": sativa_percentage, "indica_percentage": indica_percentage
        }
        strain_data = {k: v for k, v in strain_data.items() if v is not None}
        
        strain_fields = ", ".join(["strain_name"] + list(strain_data.keys()))
        strain_values = ", ".join(["?"] * (len(strain_data) + 1))
        
        query = f"""
            INSERT OR REPLACE INTO strains ({strain_fields})
            VALUES ({strain_values})
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

        # 2. Get Strain ID
        async with self._db.execute("SELECT strain_id FROM strains WHERE strain_name = ?", (strain,)) as cursor:
            strain_id = (await cursor.fetchone())[0]

        # 3. Handle Phenotype-specific data
        pheno_data = {
            "description": description, "image_crop_meta": json.dumps(image_crop_meta) if image_crop_meta is not None else None,
            "flower_days_min": flower_days_min, "flower_days_max": flower_days_max
        }

        # 4. Handle Image Saving
        if image_base64:
            image_path = await self._save_strain_image(strain, phenotype, image_base64)
            pheno_data["image_path"] = image_path
        elif image_path:
            pheno_data["image_path"] = image_path

        # 5. INSERT or REPLACE Phenotype Data
        pheno_data = {k: v for k, v in pheno_data.items() if v is not None}

        if pheno_data:
            pheno_fields = ", ".join(["strain_id", "phenotype_name"] + list(pheno_data.keys()))
            pheno_values = ", ".join(["?"] * (len(pheno_data) + 2))
            
            # The Phenotype ID is auto-generated, so we use INSERT OR REPLACE on the UNIQUE constraint (strain_id, phenotype_name)
            query = f"""
                INSERT INTO phenotypes ({pheno_fields})
                VALUES ({pheno_values})
                ON CONFLICT(strain_id, phenotype_name) DO UPDATE SET
                    description=COALESCE(excluded.description, description),
                    image_path=COALESCE(excluded.image_path, image_path),
                    image_crop_meta=COALESCE(excluded.image_crop_meta, image_crop_meta),
                    flower_days_min=COALESCE(excluded.flower_days_min, flower_days_min),
                    flower_days_max=COALESCE(excluded.flower_days_max, flower_days_max)
            """
            await self._db.execute(query, (strain_id, phenotype) + tuple(pheno_data.values()))
            await self._db.commit()
            
        # Re-load into cache for immediate sensor updates
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
        """Set metadata for a specific strain by calling add_strain (which handles update logic)."""
        await self.add_strain(
            strain=strain, phenotype=phenotype, breeder=breeder, strain_type=strain_type, 
            lineage=lineage, sex=sex, flower_days_min=flower_days_min, 
            flower_days_max=flower_days_max, description=description, 
            image_base64=image_base64, image_path=image_path, 
            image_crop_meta=image_crop_meta, sativa_percentage=sativa_percentage, 
            indica_percentage=indica_percentage
        )

    async def _save_strain_image(
        self,
        strain: str,
        phenotype: str,
        image_base64: str,
    ) -> str:
        """Decode and save a strain image to disk."""
        try:
            # Handle Data URI if present
            if image_base64.startswith("data:"):
                try:
                    _, image_base64 = image_base64.split(",", 1)
                except ValueError:
                    _LOGGER.warning("Invalid Data URI format for image")

            base_dir = self.hass.config.path("www", "growspace_manager", "strains")
            if not os.path.exists(base_dir):
                os.makedirs(base_dir)

            safe_strain = slugify(strain)
            safe_pheno = slugify(phenotype)
            filename = f"{safe_strain}_{safe_pheno}.jpg"
            file_path = os.path.join(base_dir, filename)

            image_data = base64.b64decode(image_base64)

            def _write_image():
                with open(file_path, "wb") as f:
                    f.write(image_data)

            await self.hass.async_add_executor_job(_write_image)

            web_path = f"/local/growspace_manager/strains/{filename}"
            return web_path

        except Exception as err:
            _LOGGER.error("Failed to save strain image: %s", err)
            return ""

    async def remove_strain_phenotype(self, strain: str, phenotype: str) -> None:
        """Remove a specific phenotype from the database."""
        phenotype = phenotype.strip() or "default"
        
        # 1. Get IDs
        query = """
            SELECT p.phenotype_id, s.strain_id FROM phenotypes p
            JOIN strains s ON p.strain_id = s.strain_id
            WHERE s.strain_name = ? AND p.phenotype_name = ?
        """
        async with self._db.execute(query, (strain, phenotype)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return

            phenotype_id = row['phenotype_id']
            strain_id = row['strain_id']
            
        # 2. Delete harvests associated with the phenotype
        await self._db.execute("DELETE FROM harvests WHERE phenotype_id = ?", (phenotype_id,))
        
        # 3. Delete the phenotype record itself
        await self._db.execute("DELETE FROM phenotypes WHERE phenotype_id = ?", (phenotype_id,))
        await self._db.commit()

        # 4. Check if any other phenotypes exist for the strain. If not, delete the strain record.
        async with self._db.execute("SELECT COUNT(*) FROM phenotypes WHERE strain_id = ?", (strain_id,)) as cursor:
            if (await cursor.fetchone())[0] == 0:
                await self._db.execute("DELETE FROM strains WHERE strain_id = ?", (strain_id,))
                await self._db.commit()
                
        await self.load()
        _LOGGER.info("Removed phenotype %s from strain %s", phenotype, strain)

    async def remove_strain(self, strain: str) -> None:
        """Remove an entire strain and all its associated data from the database."""
        # 1. Get strain_id
        async with self._db.execute("SELECT strain_id FROM strains WHERE strain_name = ?", (strain,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return
            strain_id = row[0]
            
        # 2. Delete all related phenotypes and harvests
        query = """
            DELETE FROM harvests 
            WHERE phenotype_id IN (SELECT phenotype_id FROM phenotypes WHERE strain_id = ?)
        """
        await self._db.execute(query, (strain_id,))
        await self._db.execute("DELETE FROM phenotypes WHERE strain_id = ?", (strain_id,))
        
        # 3. Delete the strain record itself
        await self._db.execute("DELETE FROM strains WHERE strain_id = ?", (strain_id,))
        await self._db.commit()
        
        await self.load()
        _LOGGER.info("Removed strain %s from library", strain)

    def get_all(self) -> dict[str, dict[str, Any]]:
        """Return the entire raw dictionary of strain data from the in-memory cache."""
        return self.strains

    async def import_library(
        self, library_data: dict[str, Any], replace: bool = False
    ) -> int:
        """Import a strain library from a dictionary into the database."""
        if not isinstance(library_data, dict):
            _LOGGER.warning("Import failed: data must be a dictionary.")
            return len(self.strains)

        if replace:
            await self.clear()

        imported_count = 0
        for strain_name, strain_data in library_data.items():
            meta = strain_data.get("meta", {})
            phenotypes = strain_data.get("phenotypes", {})
            
            # Use the robust add_strain method to handle upsert of metadata
            await self.add_strain(
                strain=strain_name,
                breeder=meta.get("breeder"), strain_type=meta.get("type"), lineage=meta.get("lineage"),
                sex=meta.get("sex"), sativa_percentage=meta.get("sativa_percentage"), indica_percentage=meta.get("indica_percentage"),
                # Pass nulls if we want to merge, but add_strain defaults to ignoring Nones if updating.
                # Since we want to ensure phenotype data exists, we loop through phenotypes now:
            )
            
            for pheno_name, pheno_data in phenotypes.items():
                # Fix image path if it's from an export (relative path)
                image_path = pheno_data.get("image_path")
                if image_path and image_path.startswith("images/"):
                     filename = os.path.basename(image_path)
                     image_path = f"/local/growspace_manager/strains/{filename}"

                await self.add_strain(
                    strain=strain_name, phenotype=pheno_name,
                    flower_days_min=pheno_data.get("flower_days_min"), flower_days_max=pheno_data.get("flower_days_max"),
                    description=pheno_data.get("description"), image_path=image_path,
                    image_crop_meta=pheno_data.get("image_crop_meta"),
                )
                
                # Insert harvests separately
                phenotype_id = await self._ensure_strain_and_phenotype_exist(strain_name, pheno_name)
                for harvest in pheno_data.get("harvests", []):
                    await self._db.execute(
                        """
                        INSERT INTO harvests (phenotype_id, veg_days, flower_days, harvest_date)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT DO NOTHING
                        """,
                        (phenotype_id, harvest['veg_days'], harvest['flower_days'], harvest.get('harvest_date', datetime.now().isoformat()))
                    )
                await self._db.commit()

            imported_count += 1
            
        await self.load() # Reload cache after successful imports
        return len(self.strains)

    async def import_strains(
        self, strains: list[str], replace: bool = False
    ) -> int:
        """Import a list of strain names (creating default structure)."""
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
        """Clear all entries from the strain library database."""
        count = len(self.strains)
        
        query = "DELETE FROM harvests; DELETE FROM phenotypes; DELETE FROM strains;"
        await self._db.executescript(query)
        await self._db.commit()
        
        self.strains.clear()
        return count

    async def export_library_to_zip(self, output_dir: str) -> str:
        """Export the strain library and images to a ZIP file."""
        # The logic here remains functionally the same, only the source of self.strains has changed
        return await self.hass.async_add_executor_job(self._export_sync, output_dir)

    def _export_sync(self, output_dir: str) -> str:
        """Synchronous helper to create the export ZIP file."""
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_filename = f"strain_library_export_{timestamp}.zip"
        zip_path = os.path.join(output_dir, zip_filename)

        strains_export = self.get_all() # Get the current full cache for export

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for strain_data in strains_export.values():
                if "phenotypes" in strain_data:
                    for pheno_data in strain_data["phenotypes"].values():
                        if "image_path" in pheno_data:
                            image_web_path = pheno_data["image_path"]
                            if image_web_path.startswith("/local/"):
                                relative_path = image_web_path.replace("/local/", "", 1)
                                file_system_path = self.hass.config.path("www", relative_path)

                                if os.path.exists(file_system_path):
                                    filename = os.path.basename(file_system_path)
                                    zip_entry_name = f"images/{filename}"
                                    zipf.write(file_system_path, zip_entry_name)
                                    pheno_data["image_path"] = zip_entry_name
                                else:
                                    _LOGGER.warning("Image file not found for export: %s", file_system_path)

            zipf.writestr("library.json", json.dumps(strains_export, indent=2))

        _LOGGER.info("Exported strain library to %s", zip_path)
        return zip_path

    async def import_library_from_zip(self, zip_path: str, merge: bool = True) -> int:
        """Import a strain library from a ZIP file containing data and images."""
        return await self.hass.async_add_executor_job(self._import_sync, zip_path, merge)

    def _import_sync(self, zip_path: str, merge: bool) -> int:
        """Synchronous helper to import from a ZIP file."""
        if not os.path.exists(zip_path):
            raise FileNotFoundError(f"ZIP file not found: {zip_path}")

        if not zipfile.is_zipfile(zip_path):
            raise ValueError(f"Not a valid ZIP file: {zip_path}")

        target_images_dir = self.hass.config.path("www", "growspace_manager", "strains")
        if not os.path.exists(target_images_dir):
            os.makedirs(target_images_dir)

        library_data = {}

        with zipfile.ZipFile(zip_path, "r") as zipf:
            if "library.json" not in zipf.namelist():
                raise ValueError("Invalid export file: library.json not found in archive")

            with zipf.open("library.json") as f:
                library_data = json.load(f)

            for file_info in zipf.infolist():
                if file_info.filename.startswith("images/") and not file_info.is_dir():
                    filename = os.path.basename(file_info.filename)
                    target_path = os.path.join(target_images_dir, filename)

                    with zipf.open(file_info) as source, open(target_path, "wb") as target:
                        shutil.copyfileobj(source, target)

        # After sync import, call async import data method
        self.hass.create_task(self.import_library(library_data, replace=not merge))
        return len(self.strains) # Return existing count immediately, or use a reload pattern