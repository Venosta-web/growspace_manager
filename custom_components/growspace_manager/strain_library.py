from homeassistant.helpers.storage import Store
from collections.abc import Iterable


class StrainLibrary:
    def __init__(self, hass, storage_version: int, storage_key: str) -> None:
        self.hass = hass
        self.store = Store(hass, storage_version, storage_key)
        self.strains: set[str] = set()

    async def load(self) -> None:
        data = await self.store.async_load() or []
        self.strains = set(data)

    async def save(self) -> None:
        await self.store.async_save(list(self.strains))

    async def add(self, strain: str) -> None:
        clean_strain = strain.strip()
        if clean_strain:
            self.strains.add(clean_strain)
            await self.save()

    async def remove(self, strain: str) -> None:
        self.strains.discard(strain)
        await self.save()

    def get_all(self) -> list[str]:
        return sorted(self.strains)

    async def import_strains(
        self, strains: Iterable[str], replace: bool = False
    ) -> int:
        clean_strains = {s.strip() for s in strains if s.strip()}
        if replace:
            self.strains = clean_strains
        else:
            self.strains.update(clean_strains)
        await self.save()
        return len(self.strains)

    async def clear(self) -> int:
        count = len(self.strains)
        self.strains.clear()
        await self.save()
        return count
