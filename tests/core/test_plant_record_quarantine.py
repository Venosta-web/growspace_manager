"""A rejected Plant survives the first save after startup (#805)."""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.const import DOMAIN, STORAGE_KEY_PLANTS
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.data_access.growspace_repository import (
    GrowspaceRepository,
)
from custom_components.growspace_manager.models import Plant
from custom_components.growspace_manager.plant_record_loader import ISSUE_PREFIX
from custom_components.growspace_manager.storage_manager import StorageManager
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from tests.common import MockConfigEntry


@pytest.fixture
def storage(hass: HomeAssistant) -> StorageManager:
    """Use the real repository and HA stores, with unrelated managers stubbed."""
    nutrient = MagicMock()
    nutrient.get_serialization_data.return_value = {}
    return StorageManager(hass, GrowspaceRepository(), nutrient)


async def test_segmented_load_save_keeps_bad_plant_and_repairs_on_recovery(
    hass: HomeAssistant,
    hass_storage: dict,
    storage: StorageManager,
) -> None:
    """A bad neighbor is quarantined verbatim, then retried on the next load."""
    good = Plant(plant_id="good", growspace_id="tent", row=1, col=1).to_dict()
    bad = {
        "plant_id": "bad",
        "growspace_id": "tent",
        "row": "2.0",
        "strain": "Old strain",
        "genetics": 5,
    }
    original_bad = deepcopy(bad)
    await storage.plants_store.async_save({"plants": {"good": good, "bad": bad}})

    await storage.async_load()
    assert bad == original_bad
    assert {plant.plant_id for plant in storage.repository.get_all_plants()} == {"good"}
    assert storage.quarantined_plants == {"bad": bad}
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"{ISSUE_PREFIX}bad")
    assert issue is not None
    assert issue.translation_placeholders["plant_id"] == "bad"
    assert issue.translation_placeholders["reason"]

    await storage.async_force_save()
    saved = hass_storage[STORAGE_KEY_PLANTS]["data"]
    assert saved["quarantined_plants"]["bad"] == original_bad
    assert saved["plants"]["good"]["plant_id"] == "good"

    await storage.plants_store.async_save(
        {
            "plants": {"good": good},
            "quarantined_plants": {
                "bad": Plant(plant_id="bad", growspace_id="tent").to_dict()
            },
        }
    )
    await storage.async_load()
    assert storage.quarantined_plants == {}
    assert {plant.plant_id for plant in storage.repository.get_all_plants()} == {
        "good",
        "bad",
    }
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"{ISSUE_PREFIX}bad") is None


async def test_initial_coordinator_loader_shares_quarantine_with_storage(
    hass: HomeAssistant,
) -> None:
    """The coordinator's injected-data path uses the same loader and save state."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    bad = {"plant_id": "bad", "growspace_id": "tent", "genetics": 5}
    coordinator = GrowspaceCoordinator.build(
        hass,
        entry,
        data={
            "plants": {
                "good": Plant(plant_id="good", growspace_id="tent"),
                "bad": bad,
                "wrong_type": "unreadable",
            }
        },
    )

    assert set(coordinator.plants) == {"good"}
    assert coordinator.storage_manager._get_plants_data()["quarantined_plants"] == {
        "bad": bad,
        "wrong_type": "unreadable",
    }
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"{ISSUE_PREFIX}wrong_type")
