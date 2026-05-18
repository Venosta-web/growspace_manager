"""Tests for the drain EC service handlers."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.const import (
    ATTR_DRAIN_EC,
    ATTR_DRAIN_VOLUME_ML,
    ATTR_FEED_EC,
    ATTR_FEED_VOLUME_ML,
    ATTR_GROWSPACE_ID,
    ATTR_MAX_EC_DELTA,
    ATTR_TARGET_RUNOFF_PERCENT,
)
from custom_components.growspace_manager.services.drain_ec import (
    handle_configure_drain_monitoring,
    handle_log_drain_reading,
)


@pytest.fixture
def coordinator():
    """Mock coordinator with drain-related async methods."""
    mock = MagicMock()
    mock.services = MagicMock()
    mock.services.log_drain_reading = AsyncMock()
    mock.services.configure_drain_monitoring = AsyncMock()
    return mock


@pytest.mark.asyncio
async def test_handle_log_drain_reading_all_fields(coordinator) -> None:
    """Test logging a drain EC reading with all optional fields provided."""
    call = MagicMock()
    call.data = {
        ATTR_GROWSPACE_ID: "tent1",
        ATTR_FEED_EC: 2.0,
        ATTR_DRAIN_EC: 2.4,
        ATTR_DRAIN_VOLUME_ML: 150.0,
        ATTR_FEED_VOLUME_ML: 500.0,
    }

    await handle_log_drain_reading(MagicMock(), coordinator, call)

    coordinator.services.log_drain_reading.assert_awaited_once_with(
        growspace_id="tent1",
        feed_ec=2.0,
        drain_ec=2.4,
        drain_volume_ml=150.0,
        feed_volume_ml=500.0,
    )


@pytest.mark.asyncio
async def test_handle_log_drain_reading_no_volumes(coordinator) -> None:
    """Test logging a drain reading without optional volume fields."""
    call = MagicMock()
    call.data = {
        ATTR_GROWSPACE_ID: "tent2",
        ATTR_FEED_EC: 1.8,
        ATTR_DRAIN_EC: 2.1,
    }

    await handle_log_drain_reading(MagicMock(), coordinator, call)

    coordinator.services.log_drain_reading.assert_awaited_once_with(
        growspace_id="tent2",
        feed_ec=1.8,
        drain_ec=2.1,
        drain_volume_ml=None,
        feed_volume_ml=None,
    )


@pytest.mark.asyncio
async def test_handle_configure_drain_monitoring_all_fields(coordinator) -> None:
    """Test configuring drain monitoring with all optional settings."""
    call = MagicMock()
    call.data = {
        ATTR_GROWSPACE_ID: "tent1",
        "enabled": True,
        ATTR_MAX_EC_DELTA: 0.5,
        ATTR_TARGET_RUNOFF_PERCENT: 20.0,
    }

    await handle_configure_drain_monitoring(MagicMock(), coordinator, call)

    coordinator.services.configure_drain_monitoring.assert_awaited_once_with(
        growspace_id="tent1",
        enabled=True,
        max_ec_delta=0.5,
        target_runoff_percent=20.0,
    )


@pytest.mark.asyncio
async def test_handle_configure_drain_monitoring_no_optional_fields(
    coordinator,
) -> None:
    """Test configuring drain monitoring with only the required growspace_id."""
    call = MagicMock()
    call.data = {ATTR_GROWSPACE_ID: "tent3"}

    await handle_configure_drain_monitoring(MagicMock(), coordinator, call)

    coordinator.services.configure_drain_monitoring.assert_awaited_once_with(
        growspace_id="tent3",
        enabled=None,
        max_ec_delta=None,
        target_runoff_percent=None,
    )
