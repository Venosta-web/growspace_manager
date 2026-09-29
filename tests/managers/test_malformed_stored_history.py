"""Malformed stored Stage History survives loading and a lifecycle repair."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.const import STORAGE_KEY_PLANTS
from custom_components.growspace_manager.domain.current_stage import (
    resolve_current_stage,
)
from custom_components.growspace_manager.domain.plant_lifecycle import RepairWarningCode
from custom_components.growspace_manager.domain.plant_lifecycle_adapter import (
    plant_lifecycle_from_plant,
)
from custom_components.growspace_manager.storage_manager import StorageManager
from homeassistant.core import HomeAssistant


@pytest.mark.parametrize(
    ("history", "warning"),
    [
        (
            [{"stage": None, "start": "2025-08-01", "end": None}],
            RepairWarningCode.UNKNOWN_STAGE,
        ),
        (
            [{"stage": "veg", "start": None, "end": None}],
            RepairWarningCode.INVALID_DATE,
        ),
        ([{"stage": "veg", "start": 123, "end": None}], RepairWarningCode.INVALID_DATE),
        ([{"start": "2025-08-01", "end": None}], RepairWarningCode.UNKNOWN_STAGE),
        ([{"stage": "veg", "end": None}], RepairWarningCode.INVALID_DATE),
        (["broken"], RepairWarningCode.MALFORMED_ITEM),
        ([42], RepairWarningCode.MALFORMED_ITEM),
        ([None], RepairWarningCode.MALFORMED_ITEM),
        ([["veg", "2025-08-01"]], RepairWarningCode.MALFORMED_ITEM),
    ],
)
async def test_stored_history_survives_load_save_and_date_repair(
    hass: HomeAssistant,
    hass_storage: dict,
    repository,
    manager_factory,
    history: list[object],
    warning: RepairWarningCode,
) -> None:
    """A stored Plant stays visible and an ordinary date edit repairs it."""
    nutrient = MagicMock()
    nutrient.get_serialization_data.return_value = {}
    storage = StorageManager(hass, repository, nutrient)
    raw = {
        "plant_id": "damaged",
        "growspace_id": "main",
        "stage": "veg",
        "veg_start": "2025-08-01",
        "stage_history": deepcopy(history),
    }
    await storage.plants_store.async_save({"plants": {"damaged": raw}})

    await storage.async_load()
    plant = repository.require_plant("damaged")
    assert plant.stage_history == history
    assert resolve_current_stage(plant, observed_on=date(2025, 8, 20)) == "unknown"
    lifecycle = plant_lifecycle_from_plant(plant, observed_on=date(2025, 8, 20))
    assert warning in {item.code for item in lifecycle.warnings}

    await storage.async_force_save()
    assert (
        hass_storage[STORAGE_KEY_PLANTS]["data"]["plants"]["damaged"]["stage_history"]
        == history
    )

    manager = manager_factory(AsyncMock(side_effect=storage.async_force_save))
    await manager.update_plant("damaged", veg_start="2025-08-10")
    saved = hass_storage[STORAGE_KEY_PLANTS]["data"]["plants"]["damaged"]
    assert saved["stage_history"] == [
        {"stage": "veg", "start": "2025-08-10T00:00:00+00:00", "end": None}
    ]

    await storage.async_load()
    repaired = repository.require_plant("damaged")
    assert repaired.stage_history == saved["stage_history"]
    assert resolve_current_stage(repaired, observed_on=date(2025, 8, 20)) == "veg"


async def test_well_formed_stored_history_round_trips(
    hass: HomeAssistant, repository
) -> None:
    """The untrusted field preserves ordinary history too."""
    nutrient = MagicMock()
    nutrient.get_serialization_data.return_value = {}
    storage = StorageManager(hass, repository, nutrient)
    history = [{"stage": "veg", "start": "2025-08-01", "end": None}]
    await storage.plants_store.async_save(
        {
            "plants": {
                "healthy": {
                    "plant_id": "healthy",
                    "growspace_id": "main",
                    "stage": "veg",
                    "stage_history": history,
                }
            }
        }
    )

    await storage.async_load()
    plant = repository.require_plant("healthy")
    assert plant.stage_history == history
    assert resolve_current_stage(plant, observed_on=date(2025, 8, 20)) == "veg"
