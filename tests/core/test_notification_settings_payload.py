"""Tests for notification_settings / timed_notifications in build_data_property."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from homeassistant.core import HomeAssistant
from tests.common import MockConfigEntry  # noqa: TID251


def create_coordinator(hass: HomeAssistant, options: dict[str, Any]) -> GrowspaceCoordinator:
    """Build a real coordinator with the given config-entry options."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=options)
    entry.add_to_hass(hass)
    entry.async_create_background_task = MagicMock()
    return GrowspaceCoordinator.build(hass, entry, data={}, options=options)


@pytest.mark.asyncio
async def test_build_data_property_includes_notification_settings(
    hass: HomeAssistant,
) -> None:
    """build_data_property exposes notification_settings from config entry options."""
    settings = {"critical_cooldown_minutes": 15, "warning_cooldown_minutes": 60}
    coordinator = create_coordinator(hass, options={"notification_settings": settings})

    result = coordinator.view_model_builder.build_data_property()

    assert result["notification_settings"] == settings


@pytest.mark.asyncio
async def test_build_data_property_notification_settings_defaults_to_empty_dict(
    hass: HomeAssistant,
) -> None:
    """build_data_property returns {} for notification_settings when absent from options."""
    coordinator = create_coordinator(hass, options={})

    result = coordinator.view_model_builder.build_data_property()

    assert result["notification_settings"] == {}


@pytest.mark.asyncio
async def test_build_data_property_includes_timed_notifications(
    hass: HomeAssistant,
) -> None:
    """build_data_property exposes timed_notifications from config entry options."""
    timed = [
        {
            "id": "abc",
            "message": "Flip lights",
            "trigger_type": "flower",
            "day": 1,
            "growspace_ids": [],
        }
    ]
    coordinator = create_coordinator(hass, options={"timed_notifications": timed})

    result = coordinator.view_model_builder.build_data_property()

    assert result["timed_notifications"] == timed
