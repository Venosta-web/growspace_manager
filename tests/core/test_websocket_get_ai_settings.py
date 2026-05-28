"""Tests for the get_ai_settings WebSocket handler."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.const import DOMAIN


@pytest.fixture
def mock_connection():
    conn = MagicMock()
    conn.send_result = MagicMock()
    conn.send_error = MagicMock()
    return conn


def _make_coordinator(ai_settings: dict) -> MagicMock:
    coord = MagicMock()
    coord.options = {"ai_settings": ai_settings}
    return coord


# ---------------------------------------------------------------------------
# get_ai_settings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_ai_settings_returns_full_settings_dict(
    mock_connection: MagicMock,
) -> None:
    """get_ai_settings returns the full ai_settings dict from config entry options."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_get_ai_settings,
    )

    settings = {
        "ai_enabled": True,
        "assistant_id": "conversation.claude",
        "notification_personality": "Scientific",
        "ai_auto_alerts": True,
        "max_response_length": 300,
        "vision_checkup_enabled": False,
        "ai_task_entity_id": "todo.grow_tasks",
        "briefing_interval_minutes": 60,
        "briefing_trigger_entities": ["sensor.vpd", "sensor.temp"],
    }
    coordinator = _make_coordinator(settings)
    msg = {"id": 1, "type": f"{DOMAIN}/get_ai_settings"}

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.growspace_manager.websocket.ai_assistant._get_coordinator",
            lambda h, c: coordinator,
        )
        await websocket_get_ai_settings(MagicMock(), mock_connection, msg)

    mock_connection.send_result.assert_called_once()
    result = mock_connection.send_result.call_args[0][1]
    assert result == settings


@pytest.mark.asyncio
async def test_get_ai_settings_returns_empty_dict_when_no_ai_settings(
    mock_connection: MagicMock,
) -> None:
    """get_ai_settings returns {} when ai_settings key is absent."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_get_ai_settings,
    )

    coordinator = MagicMock()
    coordinator.options = {}
    msg = {"id": 2, "type": f"{DOMAIN}/get_ai_settings"}

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.growspace_manager.websocket.ai_assistant._get_coordinator",
            lambda h, c: coordinator,
        )
        await websocket_get_ai_settings(MagicMock(), mock_connection, msg)

    result = mock_connection.send_result.call_args[0][1]
    assert result == {}


@pytest.mark.asyncio
async def test_get_ai_settings_sends_error_when_coordinator_missing(
    mock_connection: MagicMock,
) -> None:
    """get_ai_settings sends a not_found error when the coordinator is not loaded."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_get_ai_settings,
    )

    msg = {"id": 3, "type": f"{DOMAIN}/get_ai_settings"}

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.growspace_manager.websocket.ai_assistant._get_coordinator",
            lambda h, c: None,
        )
        await websocket_get_ai_settings(MagicMock(), mock_connection, msg)

    mock_connection.send_error.assert_called_once()
    error_code = mock_connection.send_error.call_args[0][1]
    assert error_code == "not_found"
