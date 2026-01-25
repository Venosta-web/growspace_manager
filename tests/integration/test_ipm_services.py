from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.const import (
    ATTR_GROWSPACE_ID,
    ATTR_ITEMS,
    ATTR_MIN_DAYS_IN_STAGE,
    ATTR_NAME,
    ATTR_NOTES,
    ATTR_PLANT_ID,
    ATTR_PRESET_ID,
    ATTR_STAGE,
    ATTR_TYPE,
)
from custom_components.growspace_manager.services.ipm import (
    handle_apply_ipm,
    handle_remove_ipm_preset,
    handle_save_ipm_preset,
)


@pytest.mark.asyncio
async def test_handle_save_ipm_preset() -> None:
    """Test handle_save_ipm_preset service handler."""
    coordinator = AsyncMock()
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

    await handle_save_ipm_preset(None, coordinator, call)

    coordinator.async_save_ipm_preset.assert_awaited_once_with(
        name="Soap Spray",
        type="foliar",
        items=[{"name": "Soap", "dose_amount": 10, "dose_unit": "ml"}],
        stage="veg",
        min_days_in_stage=7,
        preset_id="preset_123",
    )


@pytest.mark.asyncio
async def test_handle_remove_ipm_preset() -> None:
    """Test handle_remove_ipm_preset service handler."""
    coordinator = AsyncMock()
    data = {ATTR_PRESET_ID: "preset_123"}
    call = MagicMock()
    call.data = data

    await handle_remove_ipm_preset(None, coordinator, call)

    coordinator.async_remove_ipm_preset.assert_awaited_once_with("preset_123")


@pytest.mark.asyncio
async def test_handle_apply_ipm() -> None:
    """Test handle_apply_ipm service handler."""
    coordinator = AsyncMock()
    data = {
        ATTR_PRESET_ID: "preset_123",
        ATTR_GROWSPACE_ID: "gs1",
        ATTR_PLANT_ID: ["p1", "p2"],
        ATTR_NOTES: "Heavily infested",
    }
    call = MagicMock()
    call.data = data

    await handle_apply_ipm(None, coordinator, call)

    coordinator.async_apply_ipm.assert_awaited_once_with(
        preset_id="preset_123",
        growspace_id="gs1",
        plant_ids=["p1", "p2"],
        notes="Heavily infested",
    )
