"""Major-version protection for the Plant snapshot and movement outbox."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from custom_components.growspace_manager.const import STORAGE_KEY_PLANTS
from custom_components.growspace_manager.storage_manager import (
    PlantActivityStore,
    _copy_plant_store_before_migration,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store, UnsupportedStorageVersionError


def test_pre_migration_copy_keeps_the_exact_document(tmp_path: Path) -> None:
    """The rollback copy is created once and never overwritten."""
    path = tmp_path / STORAGE_KEY_PLANTS
    original = b'{"version":1,"data":{"plants":{}}}\n'
    path.write_bytes(original)
    _copy_plant_store_before_migration(str(path), 1)
    assert Path(f"{path}.v1").read_bytes() == original
    path.write_bytes(b"new content")
    _copy_plant_store_before_migration(str(path), 1)
    assert Path(f"{path}.v1").read_bytes() == original


@pytest.mark.asyncio
async def test_v1_plant_document_migrates_and_refuses_old_reader(
    hass: HomeAssistant, hass_storage: dict
) -> None:
    """An older build cannot erase activity facts after migration."""
    document = {"plants": {"plant-1": {"growspace_id": "tent"}}}
    hass_storage[STORAGE_KEY_PLANTS] = {
        "version": 1,
        "minor_version": 1,
        "key": STORAGE_KEY_PLANTS,
        "data": document,
    }
    with patch(
        "custom_components.growspace_manager.storage_manager._copy_plant_store_before_migration"
    ) as copy:
        new = PlantActivityStore(hass, 2, STORAGE_KEY_PLANTS)
        assert await new.async_load() == {**document, "activity_facts": []}
    copy.assert_called_once_with(new.path, 1)
    assert hass_storage[STORAGE_KEY_PLANTS]["version"] == 2

    await new.async_save({**document, "activity_facts": [{"id": "pending"}]})
    with pytest.raises(UnsupportedStorageVersionError):
        await Store(hass, 1, STORAGE_KEY_PLANTS).async_load()


@pytest.mark.asyncio
async def test_plant_migration_refuses_when_backup_fails(
    hass: HomeAssistant, hass_storage: dict
) -> None:
    """A failed copy leaves the old version available to retry."""
    hass_storage[STORAGE_KEY_PLANTS] = {
        "version": 1,
        "minor_version": 1,
        "key": STORAGE_KEY_PLANTS,
        "data": {"plants": {}},
    }
    with patch(
        "custom_components.growspace_manager.storage_manager._copy_plant_store_before_migration",
        side_effect=OSError("disk full"),
    ):
        with pytest.raises(OSError, match="disk full"):
            await PlantActivityStore(hass, 2, STORAGE_KEY_PLANTS).async_load()
    assert hass_storage[STORAGE_KEY_PLANTS]["version"] == 1
