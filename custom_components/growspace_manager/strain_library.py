"""Manages the strain library for the Growspace Manager integration.

This file defines the `StrainLibrary` class, which is responsible for storing,
retrieving, and analyzing data about different cannabis strains. It tracks harvest
analytics, such as vegetative and flowering durations, to provide insights
into strain performance.
"""

from __future__ import annotations
import base64
import logging
import os
from typing import Any

from homeassistant.helpers.storage import Store
from homeassistant.util import slugify

_LOGGER = logging.getLogger(__name__)


class StrainLibrary:
    """A class to manage the strain library with harvest analytics.

    This class handles the loading, saving, and manipulation of strain data
    using a hierarchical structure:
    {
      "Strain Name": {
        "phenotypes": {
          "Pheno Name": { "harvests": [...] },
          "default": { "harvests": [...] }
        },
        "meta": { "breeder": "...", "type": "..." }
      }
    }
    """

    def __init__(self, hass, storage_version: int, storage_key: str) -> None:
        """Initialize the StrainLibrary.

        Args:
            hass: The Home Assistant instance.
            storage_version: The version of the storage schema.
            storage_key: The key under which to store the data in Home Assistant's
                         storage.
        """
        self.hass = hass
        self.store = Store(hass, storage_version, storage_key)
        self.strains: dict[str, dict[str, Any]] = {}

    async def load(self) -> None:
        """Load the strain library from persistent storage.

        Performs migration: renames 'notes' key to 'description' if found.
        """
        data = await self.store.async_load()
        if isinstance(data, dict):
            self.strains = data

            # Migration: Rename 'notes' to 'description'
            migrated_count = 0
            for strain_data in self.strains.values():
                if "phenotypes" in strain_data:
                    for pheno_data in strain_data["phenotypes"].values():
                        if "notes" in pheno_data and "description" not in pheno_data:
                            pheno_data["description"] = pheno_data.pop("notes")
                            migrated_count += 1

            if migrated_count > 0:
                _LOGGER.info("Migrated %d strain phenotypes from 'notes' to 'description'", migrated_count)
                await self.save()

            _LOGGER.info("Loaded strain library with %d strains", len(self.strains))
        else:
            self.strains = {}
            _LOGGER.info("Initialized empty strain library (no valid data found)")

    async def save(self) -> None:
        """Save the current strain library to persistent storage."""
        _LOGGER.debug("Saving strain library with %d strains", len(self.strains))
        await self.store.async_save(self.strains)

    async def record_harvest(
        self, strain: str, phenotype: str, veg_days: int, flower_days: int
    ) -> None:
        """Record a harvest event for a specific strain and phenotype.

        Args:
            strain: The name of the harvested strain.
            phenotype: The phenotype of the harvested strain.
            veg_days: The number of days spent in the vegetative stage.
            flower_days: The number of days spent in the flowering stage.
        """
        strain = strain.strip()
        phenotype = phenotype.strip() or "default"

        if strain not in self.strains:
            self.strains[strain] = {"phenotypes": {}, "meta": {}}

        if phenotype not in self.strains[strain]["phenotypes"]:
            self.strains[strain]["phenotypes"][phenotype] = {"harvests": []}

        harvest_data = {
            "veg_days": veg_days,
            "flower_days": flower_days,
        }
        self.strains[strain]["phenotypes"][phenotype]["harvests"].append(harvest_data)
        _LOGGER.info(
            "Recorded harvest for %s (%s): veg=%d days, flower=%d days",
            strain,
            phenotype,
            veg_days,
            flower_days,
        )
        await self.save()

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
    ) -> None:
        """Add a single strain/phenotype combination to the library.

        Args:
            strain: The name of the strain to add.
            phenotype: The phenotype of the strain (optional).
            breeder: The breeder name.
            strain_type: The strain type (e.g., Indica, Sativa).
            lineage: The lineage or parent strains.
            sex: The sex of the strain (e.g., Feminized, Regular, Autoflower).
            flower_days_min: Minimum flowering days.
            flower_days_max: Maximum flowering days.
            description: Grower description or notes.
            image_base64: Base64 encoded image string.
        """
        strain = strain.strip()
        phenotype = phenotype.strip() if phenotype else "default"

        if strain not in self.strains:
            self.strains[strain] = {"phenotypes": {}, "meta": {}}
            _LOGGER.info("Created new strain entry: %s", strain)

        if phenotype not in self.strains[strain]["phenotypes"]:
            self.strains[strain]["phenotypes"][phenotype] = {"harvests": []}
            _LOGGER.info("Added phenotype %s to strain %s", phenotype, strain)
            await self.save()

        # Apply metadata if provided
        if any(
            [
                breeder,
                strain_type,
                lineage,
                sex,
                flower_days_min,
                flower_days_max,
                description,
                image_base64,
            ]
        ):
            await self.set_strain_meta(
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
            )

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
    ) -> None:
        """Set metadata for a specific strain.

        Args:
            strain: The name of the strain.
            phenotype: The specific phenotype (defaults to "default").
            breeder: The breeder name.
            strain_type: The strain type (e.g., Indica, Sativa).
            lineage: The lineage or parent strains.
            sex: The sex of the strain (e.g., Feminized, Regular, Autoflower).
            flower_days_min: Minimum flowering days.
            flower_days_max: Maximum flowering days.
            description: Grower description or notes.
            image_base64: Base64 encoded image string.
        """
        strain = strain.strip()
        phenotype = phenotype.strip() if phenotype else "default"

        if strain not in self.strains:
            self.strains[strain] = {"phenotypes": {}, "meta": {}}

        # Strain-level metadata
        if "meta" not in self.strains[strain]:
            self.strains[strain]["meta"] = {}
        if breeder is not None:
            self.strains[strain]["meta"]["breeder"] = breeder
        if strain_type is not None:
            self.strains[strain]["meta"]["type"] = strain_type
        if lineage is not None:
            self.strains[strain]["meta"]["lineage"] = lineage
        if sex is not None:
            self.strains[strain]["meta"]["sex"] = sex

        # Phenotype-level metadata
        if phenotype not in self.strains[strain]["phenotypes"]:
            self.strains[strain]["phenotypes"][phenotype] = {"harvests": []}

        pheno_data = self.strains[strain]["phenotypes"][phenotype]
        if flower_days_min is not None:
            pheno_data["flower_days_min"] = flower_days_min
        if flower_days_max is not None:
            pheno_data["flower_days_max"] = flower_days_max
        if description is not None:
            pheno_data["description"] = description

        # Image Handling
        if image_base64:
            try:
                # Determine write path
                # Use standard 'www' folder which maps to '/local/'
                base_dir = self.hass.config.path("www", "growspace_manager", "strain-images")
                if not os.path.exists(base_dir):
                    os.makedirs(base_dir)

                # Generate filename
                safe_strain = slugify(strain)
                safe_pheno = slugify(phenotype)
                filename = f"{safe_strain}_{safe_pheno}.jpg"
                file_path = os.path.join(base_dir, filename)

                # Decode and write
                image_data = base64.b64decode(image_base64)

                def _write_image():
                    with open(file_path, "wb") as f:
                        f.write(image_data)

                await self.hass.async_add_executor_job(_write_image)

                # Store relative web path
                web_path = f"/local/growspace_manager/strain-images/{filename}"
                pheno_data["image_path"] = web_path
                _LOGGER.info("Saved image for %s (%s) to %s", strain, phenotype, file_path)

            except Exception as err:
                _LOGGER.error("Failed to save strain image: %s", err)

        _LOGGER.info("Updated metadata for strain %s (%s)", strain, phenotype)
        await self.save()

    async def remove_strain_phenotype(self, strain: str, phenotype: str) -> None:
        """Remove a specific phenotype from a strain.

        Args:
            strain: The name of the strain.
            phenotype: The phenotype to remove.
        """
        strain = strain.strip()
        phenotype = phenotype.strip() or "default"

        if strain in self.strains:
            if phenotype in self.strains[strain]["phenotypes"]:
                self.strains[strain]["phenotypes"].pop(phenotype)
                _LOGGER.info("Removed phenotype %s from strain %s", phenotype, strain)
                await self.save()

    async def remove_strain(self, strain: str) -> None:
        """Remove an entire strain and all its phenotypes.

        Args:
            strain: The name of the strain to remove.
        """
        strain = strain.strip()
        if strain in self.strains:
            self.strains.pop(strain)
            _LOGGER.info("Removed strain %s from library", strain)
            await self.save()

    def get_all(self) -> dict[str, dict[str, Any]]:
        """Return the entire raw dictionary of strain data.

        Returns:
            A dictionary containing all stored strain and harvest data.
        """
        return self.strains

    async def import_library(
        self, library_data: dict[str, Any], replace: bool = False
    ) -> int:
        """Import a strain library from a dictionary.

        Args:
            library_data: The dictionary of strain data to import (new format).
            replace: If True, the existing library will be cleared before import.

        Returns:
            The total number of strains in the library after the import.
        """
        if not isinstance(library_data, dict):
            _LOGGER.warning("Import failed: data must be a dictionary.")
            return len(self.strains)

        if replace:
            self.strains = library_data
        else:
            # Deep merge logic is complex; for now we do top-level strain merge/update
            for strain, data in library_data.items():
                if strain not in self.strains:
                    self.strains[strain] = data
                else:
                    # Merge phenotypes
                    if "phenotypes" in data:
                        if "phenotypes" not in self.strains[strain]:
                            self.strains[strain]["phenotypes"] = {}
                        self.strains[strain]["phenotypes"].update(data["phenotypes"])
                    # Merge meta
                    if "meta" in data:
                        if "meta" not in self.strains[strain]:
                            self.strains[strain]["meta"] = {}
                        self.strains[strain]["meta"].update(data["meta"])

        await self.save()
        return len(self.strains)

    async def import_strains(
        self, strains: list[str], replace: bool = False
    ) -> int:
        """Import a list of strain names (creating default structure).

        Args:
            strains: The list of strain names to import.
            replace: If True, the existing library will be cleared before import.

        Returns:
            The total number of strains in the library after the import.
        """
        if not isinstance(strains, list):
            _LOGGER.warning("Import failed: strains must be a list.")
            return len(self.strains)

        new_data = {}
        for strain in strains:
            new_data[strain] = {
                "phenotypes": {"default": {"harvests": []}},
                "meta": {}
            }

        if replace:
            self.strains = new_data
        else:
            for strain, data in new_data.items():
                if strain not in self.strains:
                    self.strains[strain] = data
                # If strain exists, we don't overwrite it with empty defaults

        await self.save()
        return len(self.strains)

    async def clear(self) -> int:
        """Clear all entries from the strain library.

        Returns:
            The number of strains that were cleared.
        """
        count = len(self.strains)
        self.strains.clear()
        await self.save()
        return count
