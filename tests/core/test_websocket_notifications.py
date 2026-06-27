"""Tests for the save_notification_settings WebSocket command."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.exceptions import ServiceValidationError


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
async def test_save_notification_settings_persists_timed_notifications(
    mock_connection: MagicMock,
) -> None:
    """A timed_notifications list in the message is persisted into options."""
    from custom_components.growspace_manager.websocket.notifications import (
        websocket_save_notification_settings,
    )

    coordinator = MagicMock()
    coordinator.config_entry.options = {"timed_notifications": [{"id": "old"}]}
    coordinator.async_commit = AsyncMock()

    timed = [
        {
            "id": "n1",
            "message": "Feed me",
            "trigger_type": "veg_start",
            "day": 3,
            "growspace_ids": ["gs1"],
        }
    ]

    mock_hass = MagicMock()
    with patch(
        "custom_components.growspace_manager.websocket.notifications._get_coordinator",
        return_value=coordinator,
    ):
        msg = {
            "id": 2,
            "type": "growspace_manager/save_notification_settings",
            "notification_settings": {},
            "ai_auto_alerts": True,
            "timed_notifications": timed,
        }
        await websocket_save_notification_settings(mock_hass, mock_connection, msg)

    saved_options = mock_hass.config_entries.async_update_entry.call_args[1]["options"]
    assert saved_options["timed_notifications"] == timed


@pytest.mark.asyncio
async def test_save_notification_settings_leaves_timed_notifications_untouched_when_absent(
    mock_connection: MagicMock,
) -> None:
    """Omitting timed_notifications preserves the existing stored list."""
    from custom_components.growspace_manager.websocket.notifications import (
        websocket_save_notification_settings,
    )

    coordinator = MagicMock()
    existing = [{"id": "keep"}]
    coordinator.config_entry.options = {"timed_notifications": existing}
    coordinator.async_commit = AsyncMock()

    mock_hass = MagicMock()
    with patch(
        "custom_components.growspace_manager.websocket.notifications._get_coordinator",
        return_value=coordinator,
    ):
        msg = {
            "id": 3,
            "type": "growspace_manager/save_notification_settings",
            "notification_settings": {},
            "ai_auto_alerts": True,
        }
        await websocket_save_notification_settings(mock_hass, mock_connection, msg)

    saved_options = mock_hass.config_entries.async_update_entry.call_args[1]["options"]
    assert saved_options["timed_notifications"] == existing


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


@pytest.mark.asyncio
async def test_get_coordinator_returns_coordinator_when_available(
    mock_connection: MagicMock,
) -> None:
    """_get_coordinator returns coordinator when get_for_service_call succeeds."""
    from custom_components.growspace_manager.websocket.notifications import (
        _get_coordinator,
    )

    coordinator = MagicMock()
    with patch(
        "custom_components.growspace_manager.websocket.notifications.GrowspaceCoordinator.get_for_service_call",
        return_value=coordinator,
    ):
        result = _get_coordinator(MagicMock(), mock_connection)

    assert result is coordinator


@pytest.mark.asyncio
async def test_get_coordinator_returns_none_on_service_validation_error(
    mock_connection: MagicMock,
) -> None:
    """_get_coordinator returns None when get_for_service_call raises ServiceValidationError."""
    from custom_components.growspace_manager.websocket.notifications import (
        _get_coordinator,
    )

    with patch(
        "custom_components.growspace_manager.websocket.notifications.GrowspaceCoordinator.get_for_service_call",
        side_effect=ServiceValidationError("not found"),
    ):
        result = _get_coordinator(MagicMock(), mock_connection)

    assert result is None


@pytest.mark.asyncio
async def test_get_coordinator_returns_none_on_unexpected_exception(
    mock_connection: MagicMock,
) -> None:
    """_get_coordinator returns None when get_for_service_call raises any exception."""
    from custom_components.growspace_manager.websocket.notifications import (
        _get_coordinator,
    )

    with patch(
        "custom_components.growspace_manager.websocket.notifications.GrowspaceCoordinator.get_for_service_call",
        side_effect=RuntimeError("unexpected"),
    ):
        result = _get_coordinator(MagicMock(), mock_connection)

    assert result is None
