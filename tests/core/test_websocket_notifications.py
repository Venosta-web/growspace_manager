"""Tests for the save_notification_settings WebSocket command."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_connection() -> MagicMock:
    conn = MagicMock()
    conn.send_result = MagicMock()
    conn.send_error = MagicMock()
    return conn


@pytest.mark.asyncio
async def test_save_notification_settings_writes_settings_and_ai_auto_alerts(
    mock_connection: MagicMock,
) -> None:
    """save_notification_settings writes notification_settings and ai_auto_alerts atomically."""
    from custom_components.growspace_manager.websocket.notifications import (
        websocket_save_notification_settings,
    )

    coordinator = MagicMock()
    coordinator.config_entry.options = {
        "ai_settings": {"ai_enabled": True, "assistant_id": "agent.x"},
        "other": "kept",
    }
    coordinator.async_commit = AsyncMock()

    settings = {
        "critical_cooldown_minutes": 10,
        "warning_cooldown_minutes": 90,
        "recovery_cooldown_minutes": 5,
        "escalation_delay_minutes": 20,
        "min_stress_duration_seconds": 120,
        "warning_persistence_minutes": 15,
    }

    mock_hass = MagicMock()
    with patch(
        "custom_components.growspace_manager.websocket.notifications._get_coordinator",
        return_value=coordinator,
    ):
        msg = {
            "id": 1,
            "type": "growspace_manager/save_notification_settings",
            "notification_settings": settings,
            "ai_auto_alerts": False,
        }
        await websocket_save_notification_settings(mock_hass, mock_connection, msg)

    mock_hass.config_entries.async_update_entry.assert_called_once()
    saved_options = mock_hass.config_entries.async_update_entry.call_args[1]["options"]

    assert saved_options["notification_settings"] == settings
    assert saved_options["other"] == "kept"
    assert saved_options["ai_settings"]["ai_enabled"] is True
    assert saved_options["ai_settings"]["assistant_id"] == "agent.x"
    assert saved_options["ai_settings"]["ai_auto_alerts"] is False
    mock_connection.send_result.assert_called_once_with(1, {"success": True})


@pytest.mark.asyncio
async def test_save_notification_settings_sends_error_when_no_coordinator(
    mock_connection: MagicMock,
) -> None:
    """save_notification_settings sends not_found error when coordinator is absent."""
    from custom_components.growspace_manager.websocket.notifications import (
        websocket_save_notification_settings,
    )

    with patch(
        "custom_components.growspace_manager.websocket.notifications._get_coordinator",
        return_value=None,
    ):
        msg = {
            "id": 2,
            "type": "growspace_manager/save_notification_settings",
            "notification_settings": {},
            "ai_auto_alerts": True,
        }
        await websocket_save_notification_settings(MagicMock(), mock_connection, msg)

    mock_connection.send_error.assert_called_once()
    assert mock_connection.send_error.call_args[0][1] == "not_found"
