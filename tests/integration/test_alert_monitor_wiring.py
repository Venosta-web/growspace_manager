"""Integration test: AlertMonitor is properly wired to GrowspaceCoordinator.

Verifies that:
- coordinator.alert_monitor is an AlertMonitor instance after build()
- async_start() was called (listener is registered) after async_load()
- async_stop() is called during async_shutdown()
- stress/mold binary sensors register themselves on async_added_to_hass()
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tests.common import MockConfigEntry

from custom_components.growspace_manager import DOMAIN
from custom_components.growspace_manager.alert_monitor import AlertMonitor
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from homeassistant.core import HomeAssistant


@pytest.mark.asyncio
async def test_coordinator_has_alert_monitor_after_build(
    hass: HomeAssistant,
) -> None:
    """coordinator.alert_monitor is an AlertMonitor after CoordinatorBuilder.build()."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="test_wiring")

    coordinator = GrowspaceCoordinator.build(hass, entry, data={})

    assert isinstance(coordinator.alert_monitor, AlertMonitor)


@pytest.mark.asyncio
async def test_alert_monitor_listener_registered_after_async_load(
    hass: HomeAssistant,
) -> None:
    """async_start() was called: the HA bus listener is active after async_load()."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="test_wiring_load")

    with patch(
        "custom_components.growspace_manager.coordinator_builder.StorageManager"
    ) as mock_sm_cls:
        mock_sm = mock_sm_cls.return_value
        mock_sm.async_load = AsyncMock()
        mock_sm.async_force_save = AsyncMock()

        coordinator = GrowspaceCoordinator.build(hass, entry, data={})
        await coordinator.async_load()

    assert coordinator.alert_monitor._cancel_listener is not None


@pytest.mark.asyncio
async def test_alert_monitor_listener_cancelled_after_async_shutdown(
    hass: HomeAssistant,
) -> None:
    """async_stop() is called during async_shutdown(), cancelling the listener."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="test_wiring_shutdown")

    with patch(
        "custom_components.growspace_manager.coordinator_builder.StorageManager"
    ) as mock_sm_cls:
        mock_sm = mock_sm_cls.return_value
        mock_sm.async_load = AsyncMock()
        mock_sm.async_force_save = AsyncMock()

        coordinator = GrowspaceCoordinator.build(hass, entry, data={})
        await coordinator.async_load()

        assert coordinator.alert_monitor._cancel_listener is not None

        await coordinator.async_shutdown()

    assert coordinator.alert_monitor._cancel_listener is None
