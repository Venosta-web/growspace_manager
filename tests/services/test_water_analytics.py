"""Tests for the water analytics service handlers."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.const import ATTR_GROWSPACE_ID
from custom_components.growspace_manager.services.water_analytics import (
    handle_reset_water_tracking,
)


@pytest.fixture
def coordinator():
    """Mock coordinator with water analytics methods."""
    mock = MagicMock()
    mock.services.growspaces.reset_water_tracking = AsyncMock()
    return mock


@pytest.mark.asyncio
async def test_handle_reset_water_tracking(coordinator) -> None:
    """Test resetting water tracking counters for a growspace."""
    call = MagicMock()
    call.data = {
        ATTR_GROWSPACE_ID: "tent1",
    }

    await handle_reset_water_tracking(MagicMock(), coordinator, call)

    coordinator.services.growspaces.reset_water_tracking.assert_awaited_once_with(
        growspace_id="tent1",
    )
