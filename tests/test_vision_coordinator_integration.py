"""Tests for VisionCheckupScheduler integration with coordinator."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.vision_checkup_scheduler import (
    VisionCheckupScheduler,
)
from homeassistant.core import HomeAssistant


def test_coordinator_has_vision_scheduler(hass: HomeAssistant) -> None:
    """Test that coordinator has vision_scheduler attribute of correct type."""
    from tests.common import MockConfigEntry

    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    entry.async_create_background_task = MagicMock()

    strain_library = MagicMock()
    coordinator = GrowspaceCoordinator.build(
        hass,
        entry,
        data={},
        strain_library=strain_library,
    )

    assert hasattr(coordinator, "vision_scheduler")
    assert isinstance(coordinator.vision_scheduler, VisionCheckupScheduler)
