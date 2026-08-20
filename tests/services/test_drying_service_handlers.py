"""Tests for drying service handlers — verify args passed to coordinator."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.const import (
    ATTR_DATE,
    ATTR_MOISTURE_PERCENT,
    ATTR_PLANT_ID,
    ATTR_VISUAL_TAG,
    ATTR_WEIGHT_GRAMS,
)
from custom_components.growspace_manager.services.drying import (
    handle_log_drying_weight,
    handle_log_moisture_reading,
    handle_set_visual_tag,
)


@pytest.fixture
def coordinator() -> MagicMock:
    """Mock coordinator with drying async methods."""
    mock = MagicMock()
    mock.services = MagicMock()
    mock.services.plants.log_drying_weight = AsyncMock()
    mock.services.plants.log_moisture_reading = AsyncMock()
    mock.services.plants.set_visual_tag = AsyncMock()
    return mock


@pytest.mark.asyncio
async def test_handle_log_drying_weight_all_fields(coordinator: MagicMock) -> None:
    """Passes plant_id, weight_grams, and date to coordinator."""
    call = MagicMock()
    call.data = {
        ATTR_PLANT_ID: "p1",
        ATTR_WEIGHT_GRAMS: 320.5,
        ATTR_DATE: "2026-05-16",
    }
    await handle_log_drying_weight(MagicMock(), coordinator, call)
    coordinator.services.plants.log_drying_weight.assert_awaited_once_with(
        plant_id="p1",
        weight_grams=320.5,
        date="2026-05-16",
    )


@pytest.mark.asyncio
async def test_handle_log_drying_weight_no_date(coordinator: MagicMock) -> None:
    """Date is optional — passes None when omitted."""
    call = MagicMock()
    call.data = {ATTR_PLANT_ID: "p1", ATTR_WEIGHT_GRAMS: 300.0}
    await handle_log_drying_weight(MagicMock(), coordinator, call)
    coordinator.services.plants.log_drying_weight.assert_awaited_once_with(
        plant_id="p1",
        weight_grams=300.0,
        date=None,
    )


@pytest.mark.asyncio
async def test_handle_log_moisture_reading_all_fields(coordinator: MagicMock) -> None:
    """Passes plant_id, moisture_percent, and date to coordinator."""
    call = MagicMock()
    call.data = {
        ATTR_PLANT_ID: "p2",
        ATTR_MOISTURE_PERCENT: 13.5,
        ATTR_DATE: "2026-05-16",
    }
    await handle_log_moisture_reading(MagicMock(), coordinator, call)
    coordinator.services.plants.log_moisture_reading.assert_awaited_once_with(
        plant_id="p2",
        moisture_percent=13.5,
        date="2026-05-16",
    )


@pytest.mark.asyncio
async def test_handle_log_moisture_reading_no_date(coordinator: MagicMock) -> None:
    """Date is optional for moisture readings."""
    call = MagicMock()
    call.data = {ATTR_PLANT_ID: "p2", ATTR_MOISTURE_PERCENT: 11.0}
    await handle_log_moisture_reading(MagicMock(), coordinator, call)
    coordinator.services.plants.log_moisture_reading.assert_awaited_once_with(
        plant_id="p2",
        moisture_percent=11.0,
        date=None,
    )


@pytest.mark.asyncio
async def test_handle_set_visual_tag(coordinator: MagicMock) -> None:
    """Passes plant_id and visual_tag to coordinator."""
    call = MagicMock()
    call.data = {ATTR_PLANT_ID: "p3", ATTR_VISUAL_TAG: "Blue Sticker"}
    await handle_set_visual_tag(MagicMock(), coordinator, call)
    coordinator.services.plants.set_visual_tag.assert_awaited_once_with(
        plant_id="p3",
        visual_tag="Blue Sticker",
    )


@pytest.mark.asyncio
async def test_handle_set_visual_tag_none_clears_tag(coordinator: MagicMock) -> None:
    """Passing None as visual_tag clears the tag."""
    call = MagicMock()
    call.data = {ATTR_PLANT_ID: "p3", ATTR_VISUAL_TAG: None}
    await handle_set_visual_tag(MagicMock(), coordinator, call)
    coordinator.services.plants.set_visual_tag.assert_awaited_once_with(
        plant_id="p3",
        visual_tag=None,
    )
