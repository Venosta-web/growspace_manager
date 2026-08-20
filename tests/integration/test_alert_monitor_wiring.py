"""Integration test: AlertMonitor is properly wired to GrowspaceCoordinator.

Verifies that:
- coordinator.alert_monitor is an AlertMonitor instance after build()
"""

from __future__ import annotations

import pytest

from custom_components.growspace_manager import DOMAIN
from custom_components.growspace_manager.alert_monitor import AlertMonitor
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from homeassistant.core import HomeAssistant
from tests.common import MockConfigEntry


@pytest.mark.asyncio
async def test_coordinator_has_alert_monitor_after_build(
    hass: HomeAssistant,
) -> None:
    """coordinator.alert_monitor is an AlertMonitor after CoordinatorBuilder.build()."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="test_wiring")

    coordinator = GrowspaceCoordinator.build(hass, entry, data={})

    assert isinstance(coordinator.alert_monitor, AlertMonitor)
