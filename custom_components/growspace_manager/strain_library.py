"""Manages the strain library for the Growspace Manager integration.

This file defines the `StrainLibrary` class, which is responsible for storing,
retrieving, and analyzing data about different cannabis strains. It tracks harvest
analytics, such as vegetative and flowering durations, to provide insights
into strain performance.
"""

from __future__ import annotations
import logging
from typing import Any

from homeassistant.helpers.storage import Store

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

        No migration is performed; the system assumes the new format or starts fresh.
        """
        data = await self.store.async_load()
        if isinstance(data, dict):
            self.strains = data
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

    async def add_strain(self, strain: str, phenotype: str | None = None) -> None:
        """Add a single strain/phenotype combination to the library.

        Args:
            strain: The name of the strain to add.
            phenotype: The phenotype of the strain (optional).
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

    async def set_strain_meta(
        self, strain: str, breeder: str | None = None, strain_type: str | None = None
    ) -> None:
        """Set metadata for a specific strain.

        Args:
            strain: The name of the strain.
            breeder: The breeder name (optional).
            strain_type: The strain type (e.g., Indica, Sativa) (optional).
        """
        strain = strain.strip()
        if strain not in self.strains:
            self.strains[strain] = {"phenotypes": {}, "meta": {}}

        if "meta" not in self.strains[strain]:
            self.strains[strain]["meta"] = {}

        if breeder is not None:
            self.strains[strain]["meta"]["breeder"] = breeder
        if strain_type is not None:
            self.strains[strain]["meta"]["type"] = strain_type

        _LOGGER.info("Updated metadata for strain %s", strain)
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
