"""The growspace store's major version 2, and its Pre-Migration Copy (ADR-0063)."""

from __future__ import annotations

import copy
from typing import Any
from unittest.mock import patch

import pytest

from custom_components.growspace_manager.const import (
    STORAGE_KEY_CONFIG,
    STORAGE_VERSION_CONFIG,
)
from custom_components.growspace_manager.storage_manager import GrowspaceConfigStore
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store, UnsupportedStorageVersionError

COPY_KEY = f"{STORAGE_KEY_CONFIG}.v1"


def _v1_document() -> dict[str, Any]:
    return {
        "growspaces": {
            "tent": {
                "id": "tent",
                "name": "Tent",
                "rows": 1,
                "plants_per_row": 2,
                "irrigation_config": {"pump_flow_rate_ml_per_sec": 9.0},
                "irrigation_strategy": {"enabled": True, "lights_on_time": "05:00:00"},
                "environment_config": {"soil_moisture_sensor": "sensor.vwc"},
            },
            "broken": "not a growspace",
        },
        "notifications_enabled": {"tent": True},
    }


def _seed(hass_storage: dict, data: dict[str, Any], minor: int = 1) -> None:
    hass_storage[STORAGE_KEY_CONFIG] = {
        "version": 1,
        "minor_version": minor,
        "key": STORAGE_KEY_CONFIG,
        "data": data,
    }


async def test_v1_document_migrates_and_keeps_the_copy(
    hass: HomeAssistant, hass_storage: dict
) -> None:
    """Every growspace moves into its zone; the old document is kept as it was."""
    original = _v1_document()
    _seed(hass_storage, copy.deepcopy(original), minor=3)

    store = GrowspaceConfigStore(hass, STORAGE_VERSION_CONFIG, STORAGE_KEY_CONFIG)
    loaded = await store.async_load()

    assert loaded is not None
    tent = loaded["growspaces"]["tent"]
    assert tent["irrigation_zones"][0]["pump_flow_rate_ml_per_sec"] == 9.0
    assert tent["irrigation_zones"][0]["soil_moisture_sensor"] == "sensor.vwc"
    assert tent["light_cycle"] == {"lights_on_time": "05:00:00"}
    assert "irrigation_strategy" not in tent
    # Non-growspace entries pass through for the loader to report.
    assert loaded["growspaces"]["broken"] == "not a growspace"
    assert loaded["notifications_enabled"] == {"tent": True}
    assert hass_storage[STORAGE_KEY_CONFIG]["version"] == 2

    kept = hass_storage[COPY_KEY]
    assert kept["version"] == 1
    assert kept["minor_version"] == 3
    assert kept["data"] == original


async def test_copy_is_written_once_and_never_updated(
    hass: HomeAssistant, hass_storage: dict
) -> None:
    """A second v1 document meets the first copy and leaves it alone."""
    first = {"growspaces": {}, "marker": "first"}
    hass_storage[COPY_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": COPY_KEY,
        "data": first,
    }
    _seed(hass_storage, {"growspaces": {}, "marker": "second"})

    await GrowspaceConfigStore(
        hass, STORAGE_VERSION_CONFIG, STORAGE_KEY_CONFIG
    ).async_load()

    assert hass_storage[COPY_KEY]["data"] == first


async def test_an_older_build_refuses_the_migrated_store(
    hass: HomeAssistant, hass_storage: dict
) -> None:
    """Version 1 readers fail setup rather than drop the zones and save over them."""
    _seed(hass_storage, _v1_document())
    store = GrowspaceConfigStore(hass, STORAGE_VERSION_CONFIG, STORAGE_KEY_CONFIG)
    await store.async_load()

    with pytest.raises(UnsupportedStorageVersionError):
        await Store(hass, 1, STORAGE_KEY_CONFIG).async_load()


async def test_a_newer_minor_version_is_read_as_it_is(
    hass: HomeAssistant, hass_storage: dict
) -> None:
    """Only a major bump migrates; a minor one is passed through unchanged."""
    data = {"growspaces": {}, "future": True}
    hass_storage[STORAGE_KEY_CONFIG] = {
        "version": 2,
        "minor_version": 9,
        "key": STORAGE_KEY_CONFIG,
        "data": data,
    }

    loaded = await GrowspaceConfigStore(
        hass, STORAGE_VERSION_CONFIG, STORAGE_KEY_CONFIG
    ).async_load()

    assert loaded == data
    assert COPY_KEY not in hass_storage


async def test_an_unknown_old_version_is_refused(
    hass: HomeAssistant, hass_storage: dict
) -> None:
    """A format this build never wrote is not guessed into version 2."""
    store = GrowspaceConfigStore(hass, STORAGE_VERSION_CONFIG, STORAGE_KEY_CONFIG)
    with pytest.raises(ValueError, match="Unsupported config store version: 0"):
        await store._async_migrate_func(0, 1, {})


async def test_a_failed_copy_leaves_the_old_document_in_place(
    hass: HomeAssistant, hass_storage: dict
) -> None:
    """Without the copy there is no migration, so the next start tries again."""
    _seed(hass_storage, _v1_document())

    with (
        patch.object(Store, "async_save", side_effect=OSError("disk full")),
        pytest.raises(OSError, match="disk full"),
    ):
        await GrowspaceConfigStore(
            hass, STORAGE_VERSION_CONFIG, STORAGE_KEY_CONFIG
        ).async_load()

    assert hass_storage[STORAGE_KEY_CONFIG]["version"] == 1
    assert COPY_KEY not in hass_storage


async def test_metering_is_an_additive_v2_minor_migration(hass, hass_storage, caplog):
    """Drop unverified declarations once, without another major-version copy."""
    from custom_components.growspace_manager.const import STORAGE_MINOR_VERSION_CONFIG

    data = {
        "growspaces": {
            "tent": {
                "environment_config": {"irrigation_flow_sensors": ["sensor.old"]},
                "irrigation_zones": [{"id": "default"}],
            }
        }
    }
    hass_storage[STORAGE_KEY_CONFIG] = {
        "version": 2,
        "minor_version": 1,
        "key": STORAGE_KEY_CONFIG,
        "data": data,
    }
    store = GrowspaceConfigStore(
        hass, 2, STORAGE_KEY_CONFIG, minor_version=STORAGE_MINOR_VERSION_CONFIG
    )
    loaded = await store.async_load()
    assert loaded["growspaces"]["tent"]["environment_config"] == {"flow_meters": []}
    assert loaded["growspaces"]["tent"]["irrigation_zones"] == [{"id": "default"}]
    assert hass_storage[STORAGE_KEY_CONFIG]["version"] == 2
    assert hass_storage[STORAGE_KEY_CONFIG]["minor_version"] == 2
    assert COPY_KEY not in hass_storage
    assert "sensor.old" in caplog.text
    caplog.clear()
    assert (
        await GrowspaceConfigStore(
            hass, 2, STORAGE_KEY_CONFIG, minor_version=STORAGE_MINOR_VERSION_CONFIG
        ).async_load()
        == loaded
    )
    assert "Retired irrigation_flow_sensors" not in caplog.text
