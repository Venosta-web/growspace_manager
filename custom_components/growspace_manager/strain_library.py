from __future__ import annotations
import logging
from typing import Any

from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)


class StrainLibrary:
    """Manages the strain library with harvest analytics."""

    def __init__(self, hass, storage_version: int, storage_key: str) -> None:
        """Initialize the StrainLibrary."""
        self.hass = hass
        self.store = Store(hass, storage_version, storage_key)
        self.strains: dict[str, dict[str, Any]] = {}

    def _get_key(self, strain: str, phenotype: str) -> str:
        """Generate a unique key for a strain and phenotype."""
        return f"{strain.strip()}|{phenotype.strip() or 'default'}"

    async def load(self) -> None:
        """Load data from storage and handle migration from old format."""
        data = await self.store.async_load()
        if isinstance(data, list):  # Old format: list of strings
            _LOGGER.info("Migrating old strain library format.")
            self.strains = {
                self._get_key(strain, ""): {"harvests": []} for strain in data
            }
            await self.save()  # Save in the new format immediately
        elif isinstance(data, dict):  # New format
            self.strains = data or {}
        else:  # No data or invalid format
            self.strains = {}

    async def save(self) -> None:
        """Save the current strain library to storage."""
        await self.store.async_save(self.strains)

    async def record_harvest(
        self, strain: str, phenotype: str, veg_days: int, flower_days: int
    ) -> None:
        """Record a harvest event for a specific strain and phenotype."""
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

    async def remove_strain_phenotype(self, strain: str, phenotype: str) -> None:
        """Remove a specific strain/phenotype combination from the library."""
        key = self._get_key(strain, phenotype)
        if key in self.strains:
            self.strains.pop(key)
            await self.save()
            _LOGGER.info("Removed strain %s from library", key)

    def get_all(self) -> dict[str, dict[str, Any]]:
        """Return the entire strain data dictionary."""
        return self.strains

    async def import_library(
        self, library_data: dict[str, Any], replace: bool = False
    ) -> int:
        """Import a strain library from a dictionary."""
        if not isinstance(library_data, dict):
            _LOGGER.warning("Import failed: data must be a dictionary.")
            return len(self.strains)

        if replace:
            self.strains = library_data
        else:
            self.strains.update(library_data)
        await self.save()
        return len(self.strains)

    async def clear(self) -> int:
        """Clear all entries from the strain library."""
        count = len(self.strains)
        self.strains.clear()
        await self.save()
        return count
