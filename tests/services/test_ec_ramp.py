"""Tests for the EC ramp curve service handlers."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.const import (
    ATTR_CURVE_ID,
    ATTR_NAME,
    ATTR_POINTS,
    ATTR_STAGE,
)
from custom_components.growspace_manager.services.ec_ramp import (
    handle_remove_ec_ramp_curve,
    handle_save_ec_ramp_curve,
)


@pytest.fixture
def coordinator():
    """Mock coordinator with EC ramp async methods."""
    mock = MagicMock()
    mock.services.config.save_ec_ramp_curve = AsyncMock()
    mock.services.config.remove_ec_ramp_curve = AsyncMock()
    return mock


@pytest.mark.asyncio
async def test_handle_save_ec_ramp_curve_with_curve_id(coordinator) -> None:
    """Test saving an EC ramp curve when an existing curve_id is provided."""
    call = MagicMock()
    call.data = {
        ATTR_NAME: "Veg Ramp",
        ATTR_STAGE: "vegetative",
        ATTR_POINTS: [{"day": 1, "ec": 1.0}, {"day": 7, "ec": 1.8}],
        ATTR_CURVE_ID: "curve-abc-123",
    }

    await handle_save_ec_ramp_curve(MagicMock(), coordinator, call)

    coordinator.services.config.save_ec_ramp_curve.assert_awaited_once_with(
        name="Veg Ramp",
        stage="vegetative",
        points=[{"day": 1, "ec": 1.0}, {"day": 7, "ec": 1.8}],
        curve_id="curve-abc-123",
    )


@pytest.mark.asyncio
async def test_handle_save_ec_ramp_curve_without_curve_id(coordinator) -> None:
    """Test saving an EC ramp curve when no curve_id is provided (new curve)."""
    data = {
        ATTR_NAME: "Flower Ramp",
        ATTR_STAGE: "flowering",
        ATTR_POINTS: [{"day": 1, "ec": 1.5}, {"day": 14, "ec": 2.2}],
    }
    call = MagicMock()
    call.data = data

    await handle_save_ec_ramp_curve(MagicMock(), coordinator, call)

    coordinator.services.config.save_ec_ramp_curve.assert_awaited_once_with(
        name="Flower Ramp",
        stage="flowering",
        points=[{"day": 1, "ec": 1.5}, {"day": 14, "ec": 2.2}],
        curve_id=None,
    )


@pytest.mark.asyncio
async def test_handle_remove_ec_ramp_curve(coordinator) -> None:
    """Test removing an EC ramp curve by curve_id."""
    data = {
        ATTR_CURVE_ID: "curve-xyz-456",
    }
    call = MagicMock()
    call.data = data

    await handle_remove_ec_ramp_curve(MagicMock(), coordinator, call)

    coordinator.services.config.remove_ec_ramp_curve.assert_awaited_once_with(
        growspace_id=None,
        curve_id="curve-xyz-456",
    )
