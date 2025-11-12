"""Strain library for the Growspace Manager component."""
from collections.abc import Iterable

from homeassistant.helpers.storage import Store


class StrainLibrary:
    """Manages the strain library."""

    def __init__(self, hass, storage_version: int, storage_key: str) -> None:
        """Initialize the Strain Library."""
        self.hass = hass
        self.store = Store(hass, storage_version, storage_key)
        self.strains: set[str] = set()

    async def load(self) -> None:
        """Load strains from storage."""
        data = await self.store.async_load() or []
        self.strains = set(data)

    async def save(self) -> None:
        """Save strains to storage."""
        await self.store.async_save(list(self.strains))

    async def add(self, strain: str) -> None:
        """Add a strain to the library."""
        clean_strain = strain.strip()
        if clean_strain:
            self.strains.add(clean_strain)
            await self.save()

    async def remove(self, strain: str) -> None:
        """Remove a strain from the library."""
        self.strains.discard(strain)
        await self.save()

    def get_all(self) -> list[str]:
        """Return a sorted list of all strains."""
        return sorted(self.strains)

    async def import_strains(
        self,
        strains: Iterable[str],
        replace: bool = False,
    ) -> int:
        """Import a list of strains, with an option to replace existing ones."""
        clean_strains = {s.strip() for s in strains if s.strip()}
        if replace:
            self.strains = clean_strains
        else:
            self.strains.update(clean_strains)
        await self.save()
        return len(self.strains)

    async def clear(self) -> int:
        """Clear all strains from the library."""
        count = len(self.strains)
        self.strains.clear()
        await self.save()
        return count
