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

    This class handles the loading, saving, and manipulation of strain data,
    including recording harvest details to calculate average cycle times.
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

    def _get_key(self, strain: str, phenotype: str) -> str:
        """Generate a unique key for a strain and phenotype combination.

        Args:
            strain: The name of the strain.
            phenotype: The phenotype of the strain.

        Returns:
            A unique string key for storage.
        """
        return f"{strain.strip()}|{phenotype.strip() or 'default'}"

    async def load(self) -> None:
        """Load the strain library from persistent storage.

        This method also handles the migration from an old list-based format to the
        current dictionary-based format.
        """
        data = await self.store.async_load()
        if isinstance(data, list):  # Old format: list of strings
            _LOGGER.info("Migrating old strain library format.")
            self.strains = {
                self._get_key(strain, ""): {"harvests": []} for strain in data
            }
            await self.save()  # Save in the new format immediately
        elif isinstance(data, dict):  # Current format: dict
            self.strains = data or {}
        else:  # No data or unrecognized format
            self.strains = {}

    async def save(self) -> None:
        """Save the current strain library to persistent storage."""
        await self.store.async_save(self.strains)

    async def record_harvest(
        self, strain: str, phenotype: str, veg_days: int, flower_days: int
    ) -> None:
        """Record a harvest event for a specific strain and phenotype.

        This method adds the vegetative and flowering day counts to the strain's
        harvest history, which is used to calculate analytics.

        Args:
            strain: The name of the harvested strain.
            phenotype: The phenotype of the harvested strain.
            veg_days: The number of days spent in the vegetative stage.
            flower_days: The number of days spent in the flowering stage.
        """
        key = self._get_key(strain, phenotype)

        if key not in self.strains:
            self.strains[key] = {"harvests": []}

        harvest_data = {
            "veg_days": veg_days,
            "flower_days": flower_days,
        }
        self.strains[key]["harvests"].append(harvest_data)
        _LOGGER.info(
            "Recorded harvest for %s: veg=%d days, flower=%d days",
            key,
            veg_days,
            flower_days,
        )
        await self.save()

    async def add_strain(self, strain: str, phenotype: str | None = None) -> None:
        """Add a single strain/phenotype combination to the library.

        If the strain/phenotype already exists, this method does nothing.

        Args:
            strain: The name of the strain to add.
            phenotype: The phenotype of the strain (optional).
        """
        key = self._get_key(strain, phenotype or "default")
        if key not in self.strains:
            self.strains[key] = {"harvests": []}
            _LOGGER.info("Added strain %s to library", key)
            await self.save()

    async def remove_strain_phenotype(self, strain: str, phenotype: str) -> None:
        """Remove a specific strain/phenotype combination from the library.

        Args:
            strain: The name of the strain to remove.
            phenotype: The phenotype of the strain to remove.
        """
        key = self._get_key(strain, phenotype)
        if key in self.strains:
            self.strains.pop(key)
            await self.save()
            _LOGGER.info("Removed strain %s from library", key)

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
            library_data: The dictionary of strain data to import.
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
            self.strains.update(library_data)
        await self.save()
        return len(self.strains)

    async def import_strains(
        self, strains: list[str], replace: bool = False
    ) -> int:
        """Import a list of strains.

        Args:
            strains: The list of strain names to import.
            replace: If True, the existing library will be cleared before import.

        Returns:
            The total number of strains in the library after the import.
        """
        if not isinstance(strains, list):
            _LOGGER.warning("Import failed: strains must be a list.")
            return len(self.strains)

        new_data = {
            self._get_key(strain, ""): {"harvests": []} for strain in strains
        }

        if replace:
            self.strains = new_data
        else:
            for key, value in new_data.items():
                if key not in self.strains:
                    self.strains[key] = value
        
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
