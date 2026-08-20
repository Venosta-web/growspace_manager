from unittest.mock import AsyncMock, MagicMock

import pytest
import voluptuous as vol

from custom_components.growspace_manager.const import (
    ATTR_GROWSPACE_ID,
    ATTR_ITEMS,
    ATTR_MIN_DAYS_IN_STAGE,
    ATTR_NAME,
    ATTR_NOTES,
    ATTR_PLANT_IDS,
    ATTR_PRESET_ID,
    ATTR_STAGE,
    ATTR_TYPE,
)
from custom_components.growspace_manager.schemas import APPLY_IPM_SCHEMA
from custom_components.growspace_manager.services.config_facade import ConfigFacade


@pytest.mark.asyncio
async def test_handle_save_ipm_preset() -> None:
    """Test handle_save_ipm_preset service handler."""
    coordinator = MagicMock()
    coordinator.services.config.save_ipm_preset = AsyncMock()

    data = {
        ATTR_NAME: "Soap Spray",
        ATTR_TYPE: "foliar",
        ATTR_ITEMS: [{"name": "Soap", "dose_amount": 10, "dose_unit": "ml"}],
        ATTR_PRESET_ID: "preset_123",
        ATTR_STAGE: "veg",
        ATTR_MIN_DAYS_IN_STAGE: 7,
    }
    call = MagicMock()
    call.data = data

    facade = ConfigFacade(coordinator)
    facade.save_ipm_preset = coordinator.services.config.save_ipm_preset
    await facade.save_ipm_preset_from_call(None, call)

    coordinator.services.config.save_ipm_preset.assert_awaited_once_with(
        name="Soap Spray",
        preset_type="foliar",
        items=[{"name": "Soap", "dose_amount": 10, "dose_unit": "ml"}],
        stage="veg",
        min_days_in_stage=7,
        preset_id="preset_123",
    )


@pytest.mark.asyncio
async def test_handle_remove_ipm_preset() -> None:
    """Test handle_remove_ipm_preset service handler."""
    coordinator = MagicMock()
    coordinator.services.config.remove_ipm_preset = AsyncMock()

    data = {ATTR_PRESET_ID: "preset_123"}
    call = MagicMock()
    call.data = data

    facade = ConfigFacade(coordinator)
    facade.remove_ipm_preset = coordinator.services.config.remove_ipm_preset
    await facade.remove_ipm_preset_from_call(None, call)

    coordinator.services.config.remove_ipm_preset.assert_awaited_once_with("preset_123")


@pytest.mark.asyncio
async def test_handle_apply_ipm() -> None:
    """Test handle_apply_ipm service handler."""
    coordinator = MagicMock()
    coordinator.services.plants.apply_ipm = AsyncMock()

    data = {
        ATTR_PRESET_ID: "preset_123",
        ATTR_GROWSPACE_ID: "gs1",
        ATTR_PLANT_IDS: ["p1", "p2"],
        ATTR_NOTES: "Heavily infested",
    }
    call = MagicMock()
    call.data = data

    await ConfigFacade(coordinator).apply_ipm_from_call(None, call)

    coordinator.services.plants.apply_ipm.assert_awaited_once_with(
        preset_id="preset_123",
        growspace_id="gs1",
        plant_ids=["p1", "p2"],
        notes="Heavily infested",
    )


def test_apply_ipm_schema_accepts_plant_ids_key() -> None:
    """Schema must accept 'plant_ids' (plural) — the key sent by the frontend card."""
    data = {
        "preset_id": "preset_123",
        "plant_ids": ["p1", "p2"],
    }
    validated = APPLY_IPM_SCHEMA(data)
    assert validated["plant_ids"] == ["p1", "p2"]


def test_apply_ipm_schema_rejects_unknown_key() -> None:
    """Schema must still reject completely unknown keys."""
    with pytest.raises(vol.Invalid):
        APPLY_IPM_SCHEMA({"preset_id": "preset_123", "unknown_key": "value"})
