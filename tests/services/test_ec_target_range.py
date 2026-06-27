"""Tests for the set_ec_target_range service handler."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.const import ATTR_GROWSPACE_ID, ATTR_STAGE
from custom_components.growspace_manager.services.irrigation import (
    handle_set_ec_target_range,
)


@pytest.fixture
def coordinator() -> MagicMock:
    """Mock coordinator with ec target range async method."""
    mock = MagicMock()
    mock.services.growspaces.set_ec_target_range = AsyncMock()
    return mock


@pytest.mark.asyncio
async def test_handle_set_ec_target_range_new_stage(coordinator: MagicMock) -> None:
    """Test setting an EC target range for a stage that doesn't exist yet."""
    call = MagicMock()
    call.data = {
        ATTR_GROWSPACE_ID: "tent1",
        ATTR_STAGE: "veg",
        "feed_ec_min": 1.2,
        "feed_ec_max": 1.8,
    }

    await handle_set_ec_target_range(MagicMock(), coordinator, call)

    coordinator.services.growspaces.set_ec_target_range.assert_awaited_once_with(
        growspace_id="tent1",
        stage="veg",
        feed_ec_min=1.2,
        feed_ec_max=1.8,
    )


@pytest.mark.asyncio
async def test_handle_set_ec_target_range_update_existing_stage(
    coordinator: MagicMock,
) -> None:
    """Test that calling set_ec_target_range again on the same stage updates it."""
    call = MagicMock()
    call.data = {
        ATTR_GROWSPACE_ID: "tent1",
        ATTR_STAGE: "flower",
        "feed_ec_min": 2.0,
        "feed_ec_max": 2.6,
    }

    await handle_set_ec_target_range(MagicMock(), coordinator, call)

    coordinator.services.growspaces.set_ec_target_range.assert_awaited_once_with(
        growspace_id="tent1",
        stage="flower",
        feed_ec_min=2.0,
        feed_ec_max=2.6,
    )
