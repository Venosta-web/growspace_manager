"""Tests for AI assistant WebSocket handlers (start_conversation, send_message)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError


def _make_converse_result(speech: str, conv_id: str = "conv-abc"):
    """Build a fake async_converse return value."""
    result = MagicMock()
    result.conversation_id = conv_id
    result.response.speech = {"plain": {"speech": speech}}
    return result


@pytest.fixture
def mock_connection():
    conn = MagicMock()
    conn.send_result = MagicMock()
    conn.send_error = MagicMock()
    return conn


# ---------------------------------------------------------------------------
# start_conversation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_conversation_returns_conversation_id(
    mock_connection: MagicMock,
) -> None:
    """start_conversation calls async_converse with conversation_id=None and
    returns the conversation_id from the result."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_start_conversation,
    )

    fake_result = _make_converse_result("Here is my advice.", conv_id="conv-123")

    with patch(
        "custom_components.growspace_manager.websocket.ai_assistant.conversation.async_converse",
        new=AsyncMock(return_value=fake_result),
    ) as mock_converse:
        msg = {
            "id": 1,
            "type": "growspace_manager/start_conversation",
            "growspace_id": "tent1",
            "message": "How are my plants?",
            "agent_id": "test_agent",
        }
        await websocket_start_conversation(MagicMock(), mock_connection, msg)

    mock_converse.assert_awaited_once()
    call_kwargs = mock_converse.call_args[1]
    assert call_kwargs.get("conversation_id") is None

    mock_connection.send_result.assert_called_once()
    result = mock_connection.send_result.call_args[0][1]
    assert result["thread_id"] == "conv-123"
    assert result["growspace_id"] == "tent1"
    assert len(result["messages"]) == 1
    assert result["messages"][0]["role"] == "ai"
    assert result["messages"][0]["text"] == "Here is my advice."


@pytest.mark.asyncio
async def test_start_conversation_extracts_action_block(
    mock_connection: MagicMock,
) -> None:
    """Responses containing [ACTION]...[/ACTION] have the JSON parsed out."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_start_conversation,
    )

    speech = 'All good. [ACTION]{"type": "water", "confidence": 0.9}[/ACTION]'
    fake_result = _make_converse_result(speech, conv_id="conv-xyz")

    with patch(
        "custom_components.growspace_manager.websocket.ai_assistant.conversation.async_converse",
        new=AsyncMock(return_value=fake_result),
    ):
        msg = {
            "id": 2,
            "type": "growspace_manager/start_conversation",
            "growspace_id": "tent1",
            "message": "What should I do?",
            "agent_id": "agent1",
        }
        await websocket_start_conversation(MagicMock(), mock_connection, msg)

    result = mock_connection.send_result.call_args[0][1]
    ai_msg = result["messages"][0]
    assert ai_msg["suggestedAction"] == {"type": "water", "confidence": 0.9}
    assert "[ACTION]" not in ai_msg["text"]


@pytest.mark.asyncio
async def test_start_conversation_malformed_action_block_is_plain_text(
    mock_connection: MagicMock,
) -> None:
    """A malformed [ACTION] block is silently ignored — no exception raised."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_start_conversation,
    )

    speech = "Here is advice. [ACTION]not valid json[/ACTION]"
    fake_result = _make_converse_result(speech)

    with patch(
        "custom_components.growspace_manager.websocket.ai_assistant.conversation.async_converse",
        new=AsyncMock(return_value=fake_result),
    ):
        msg = {
            "id": 3,
            "type": "growspace_manager/start_conversation",
            "growspace_id": "tent1",
            "message": "Any issues?",
            "agent_id": "agent1",
        }
        await websocket_start_conversation(MagicMock(), mock_connection, msg)

    result = mock_connection.send_result.call_args[0][1]
    ai_msg = result["messages"][0]
    assert "suggestedAction" not in ai_msg
    assert ai_msg["text"] is not None


@pytest.mark.asyncio
async def test_start_conversation_invalid_image_entity_domain(
    mock_connection: MagicMock,
) -> None:
    """Entities outside camera/image domains raise a validation error."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_start_conversation,
    )

    msg = {
        "id": 4,
        "type": "growspace_manager/start_conversation",
        "growspace_id": "tent1",
        "message": "Check this image",
        "agent_id": "agent1",
        "image_entities": ["sensor.temperature"],  # wrong domain
    }
    await websocket_start_conversation(MagicMock(), mock_connection, msg)

    mock_connection.send_error.assert_called_once()
    err_args = mock_connection.send_error.call_args[0]
    assert err_args[0] == 4
    assert err_args[1] == "invalid_entity"


@pytest.mark.asyncio
async def test_start_conversation_valid_camera_entity_accepted(
    mock_connection: MagicMock,
) -> None:
    """Entities in the camera domain are accepted without error."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_start_conversation,
    )

    fake_result = _make_converse_result("Looks healthy.")

    hass = MagicMock()
    cam_state = MagicMock()
    cam_state.attributes = {"entity_picture": "/api/camera_proxy/camera.tent"}
    hass.states.get = MagicMock(return_value=cam_state)

    with patch(
        "custom_components.growspace_manager.websocket.ai_assistant.conversation.async_converse",
        new=AsyncMock(return_value=fake_result),
    ):
        msg = {
            "id": 5,
            "type": "growspace_manager/start_conversation",
            "growspace_id": "tent1",
            "message": "How does this look?",
            "agent_id": "agent1",
            "image_entities": ["camera.tent_cam"],
        }
        await websocket_start_conversation(hass, mock_connection, msg)

    mock_connection.send_error.assert_not_called()
    mock_connection.send_result.assert_called_once()


@pytest.mark.asyncio
async def test_start_conversation_valid_image_entity_accepted(
    mock_connection: MagicMock,
) -> None:
    """Entities in the image domain are accepted without error."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_start_conversation,
    )

    fake_result = _make_converse_result("Looks fine.")

    hass = MagicMock()
    img_state = MagicMock()
    img_state.attributes = {}
    hass.states.get = MagicMock(return_value=img_state)

    with patch(
        "custom_components.growspace_manager.websocket.ai_assistant.conversation.async_converse",
        new=AsyncMock(return_value=fake_result),
    ):
        msg = {
            "id": 6,
            "type": "growspace_manager/start_conversation",
            "growspace_id": "tent1",
            "message": "Check growth",
            "agent_id": "agent1",
            "image_entities": ["image.plant_snapshot"],
        }
        await websocket_start_conversation(hass, mock_connection, msg)

    mock_connection.send_error.assert_not_called()
    mock_connection.send_result.assert_called_once()


# ---------------------------------------------------------------------------
# send_message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_message_passes_conversation_id(
    mock_connection: MagicMock,
) -> None:
    """send_message passes the existing conversation_id to async_converse."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_send_message,
    )

    fake_result = _make_converse_result("Follow-up answer.", conv_id="conv-existing")

    with patch(
        "custom_components.growspace_manager.websocket.ai_assistant.conversation.async_converse",
        new=AsyncMock(return_value=fake_result),
    ) as mock_converse:
        msg = {
            "id": 7,
            "type": "growspace_manager/send_message",
            "conversation_id": "conv-existing",
            "growspace_id": "tent1",
            "message": "Tell me more",
        }
        await websocket_send_message(MagicMock(), mock_connection, msg)

    call_kwargs = mock_converse.call_args[1]
    assert call_kwargs["conversation_id"] == "conv-existing"

    result = mock_connection.send_result.call_args[0][1]
    assert result["thread_id"] == "conv-existing"
    assert result["growspace_id"] == "tent1"
    assert len(result["messages"]) == 1
    assert result["messages"][0]["role"] == "ai"
    assert result["messages"][0]["text"] == "Follow-up answer."


@pytest.mark.asyncio
async def test_send_message_extracts_action_block(
    mock_connection: MagicMock,
) -> None:
    """send_message also parses [ACTION] blocks from the response."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_send_message,
    )

    speech = 'OK. [ACTION]{"type": "adjust_ph", "value": 6.2}[/ACTION]'
    fake_result = _make_converse_result(speech, conv_id="conv-42")

    with patch(
        "custom_components.growspace_manager.websocket.ai_assistant.conversation.async_converse",
        new=AsyncMock(return_value=fake_result),
    ):
        msg = {
            "id": 8,
            "type": "growspace_manager/send_message",
            "conversation_id": "conv-42",
            "growspace_id": "tent1",
            "message": "What should I adjust?",
        }
        await websocket_send_message(MagicMock(), mock_connection, msg)

    result = mock_connection.send_result.call_args[0][1]
    ai_msg = result["messages"][0]
    assert ai_msg["suggestedAction"] == {"type": "adjust_ph", "value": 6.2}
    assert "[ACTION]" not in ai_msg["text"]


@pytest.mark.asyncio
async def test_send_message_invalid_image_entity_domain(
    mock_connection: MagicMock,
) -> None:
    """send_message rejects image entities with invalid domains."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_send_message,
    )

    msg = {
        "id": 9,
        "type": "growspace_manager/send_message",
        "conversation_id": "conv-42",
        "growspace_id": "tent1",
        "message": "Check this",
        "image_entities": ["binary_sensor.door"],  # wrong domain
    }
    await websocket_send_message(MagicMock(), mock_connection, msg)

    mock_connection.send_error.assert_called_once()
    err_args = mock_connection.send_error.call_args[0]
    assert err_args[1] == "invalid_entity"


@pytest.mark.asyncio
async def test_send_message_empty_response_returns_error(
    mock_connection: MagicMock,
) -> None:
    """When async_converse returns None, an error is sent to the client."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_send_message,
    )

    with patch(
        "custom_components.growspace_manager.websocket.ai_assistant.conversation.async_converse",
        new=AsyncMock(return_value=None),
    ):
        msg = {
            "id": 10,
            "type": "growspace_manager/send_message",
            "conversation_id": "conv-x",
            "growspace_id": "tent1",
            "message": "Hello",
        }
        await websocket_send_message(MagicMock(), mock_connection, msg)

    mock_connection.send_error.assert_called_once()
    err_args = mock_connection.send_error.call_args[0]
    assert err_args[1] == "ai_error"


# ---------------------------------------------------------------------------
# start_conversation — error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_conversation_service_validation_error_returns_error(
    mock_connection: MagicMock,
) -> None:
    """ServiceValidationError during async_converse is caught and sent as ws error."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_start_conversation,
    )

    with patch(
        "custom_components.growspace_manager.websocket.ai_assistant.conversation.async_converse",
        new=AsyncMock(side_effect=ServiceValidationError("bad request")),
    ):
        msg = {
            "id": 11,
            "type": "growspace_manager/start_conversation",
            "growspace_id": "tent1",
            "message": "Hello",
        }
        await websocket_start_conversation(MagicMock(), mock_connection, msg)

    mock_connection.send_error.assert_called_once()
    assert mock_connection.send_error.call_args[0][1] == "ai_error"


@pytest.mark.asyncio
async def test_start_conversation_generic_exception_returns_error(
    mock_connection: MagicMock,
) -> None:
    """An unexpected exception is caught and sent as a ws error."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_start_conversation,
    )

    with patch(
        "custom_components.growspace_manager.websocket.ai_assistant.conversation.async_converse",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        msg = {
            "id": 12,
            "type": "growspace_manager/start_conversation",
            "growspace_id": "tent1",
            "message": "Hello",
        }
        await websocket_start_conversation(MagicMock(), mock_connection, msg)

    mock_connection.send_error.assert_called_once()
    assert mock_connection.send_error.call_args[0][1] == "ai_error"


@pytest.mark.asyncio
async def test_start_conversation_empty_response_returns_error(
    mock_connection: MagicMock,
) -> None:
    """When async_converse returns no speech text, an ai_error is sent."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_start_conversation,
    )

    with patch(
        "custom_components.growspace_manager.websocket.ai_assistant.conversation.async_converse",
        new=AsyncMock(return_value=None),
    ):
        msg = {
            "id": 13,
            "type": "growspace_manager/start_conversation",
            "growspace_id": "tent1",
            "message": "Hello",
        }
        await websocket_start_conversation(MagicMock(), mock_connection, msg)

    mock_connection.send_error.assert_called_once()
    assert mock_connection.send_error.call_args[0][1] == "ai_error"


# ---------------------------------------------------------------------------
# send_message — error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_message_service_validation_error_returns_error(
    mock_connection: MagicMock,
) -> None:
    """ServiceValidationError during send_message is caught and returned as ws error."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_send_message,
    )

    with patch(
        "custom_components.growspace_manager.websocket.ai_assistant.conversation.async_converse",
        new=AsyncMock(side_effect=ServiceValidationError("invalid")),
    ):
        msg = {
            "id": 14,
            "type": "growspace_manager/send_message",
            "conversation_id": "conv-err",
            "growspace_id": "tent1",
            "message": "Continue",
        }
        await websocket_send_message(MagicMock(), mock_connection, msg)

    mock_connection.send_error.assert_called_once()
    assert mock_connection.send_error.call_args[0][1] == "ai_error"


@pytest.mark.asyncio
async def test_send_message_generic_exception_returns_error(
    mock_connection: MagicMock,
) -> None:
    """An unexpected exception in send_message is caught and returned as ws error."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_send_message,
    )

    with patch(
        "custom_components.growspace_manager.websocket.ai_assistant.conversation.async_converse",
        new=AsyncMock(side_effect=ValueError("unexpected")),
    ):
        msg = {
            "id": 15,
            "type": "growspace_manager/send_message",
            "conversation_id": "conv-err",
            "growspace_id": "tent1",
            "message": "Continue",
        }
        await websocket_send_message(MagicMock(), mock_connection, msg)

    mock_connection.send_error.assert_called_once()
    assert mock_connection.send_error.call_args[0][1] == "ai_error"


# ---------------------------------------------------------------------------
# _get_coordinator
# ---------------------------------------------------------------------------


def test_get_coordinator_returns_none_on_exception() -> None:
    """_get_coordinator swallows any exception and returns None."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        _get_coordinator,
    )

    with patch(
        "custom_components.growspace_manager.websocket.ai_assistant.GrowspaceCoordinator.get_for_service_call",
        side_effect=ServiceValidationError("not loaded"),
    ):
        result = _get_coordinator(MagicMock(), MagicMock())

    assert result is None


def test_get_coordinator_returns_none_on_generic_exception() -> None:
    """_get_coordinator also swallows generic exceptions and returns None."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        _get_coordinator,
    )

    with patch(
        "custom_components.growspace_manager.websocket.ai_assistant.GrowspaceCoordinator.get_for_service_call",
        side_effect=RuntimeError("crash"),
    ):
        result = _get_coordinator(MagicMock(), MagicMock())

    assert result is None


# ---------------------------------------------------------------------------
# websocket_get_ai_alerts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_ai_alerts_coordinator_not_loaded(
    mock_connection: MagicMock,
) -> None:
    """get_ai_alerts sends not_found when coordinator is unavailable."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_get_ai_alerts,
    )

    with patch(
        "custom_components.growspace_manager.websocket.ai_assistant._get_coordinator",
        return_value=None,
    ):
        msg = {"id": 20, "type": "growspace_manager/get_ai_alerts"}
        await websocket_get_ai_alerts(MagicMock(), mock_connection, msg)

    mock_connection.send_error.assert_called_once()
    assert mock_connection.send_error.call_args[0][1] == "not_found"


@pytest.mark.asyncio
async def test_get_ai_alerts_no_alert_monitor_returns_empty(
    mock_connection: MagicMock,
) -> None:
    """get_ai_alerts returns empty list when coordinator has no alert_monitor."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_get_ai_alerts,
    )

    coordinator = MagicMock(spec=[])  # no alert_monitor attribute

    with patch(
        "custom_components.growspace_manager.websocket.ai_assistant._get_coordinator",
        return_value=coordinator,
    ):
        msg = {"id": 21, "type": "growspace_manager/get_ai_alerts"}
        await websocket_get_ai_alerts(MagicMock(), mock_connection, msg)

    mock_connection.send_result.assert_called_once_with(21, [])


@pytest.mark.asyncio
async def test_get_ai_alerts_returns_filtered_alerts(
    mock_connection: MagicMock,
) -> None:
    """get_ai_alerts passes growspace_id and alert_type filters to the monitor."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_get_ai_alerts,
    )

    alert_monitor = MagicMock()
    alert_monitor.get_alerts.return_value = [{"id": "a1", "type": "stress"}]
    coordinator = MagicMock()
    coordinator.alert_monitor = alert_monitor

    with patch(
        "custom_components.growspace_manager.websocket.ai_assistant._get_coordinator",
        return_value=coordinator,
    ):
        msg = {
            "id": 22,
            "type": "growspace_manager/get_ai_alerts",
            "growspace_id": "tent1",
            "alert_type": "stress",
        }
        await websocket_get_ai_alerts(MagicMock(), mock_connection, msg)

    alert_monitor.get_alerts.assert_called_once_with(
        growspace_id="tent1", alert_type="stress"
    )
    result = mock_connection.send_result.call_args[0][1]
    assert result == [{"id": "a1", "type": "stress"}]


# ---------------------------------------------------------------------------
# websocket_resolve_ai_alert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_ai_alert_coordinator_not_loaded(
    mock_connection: MagicMock,
) -> None:
    """resolve_ai_alert sends not_found when coordinator is unavailable."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_resolve_ai_alert,
    )

    with patch(
        "custom_components.growspace_manager.websocket.ai_assistant._get_coordinator",
        return_value=None,
    ):
        msg = {
            "id": 30,
            "type": "growspace_manager/resolve_ai_alert",
            "alert_id": "abc",
        }
        await websocket_resolve_ai_alert(MagicMock(), mock_connection, msg)

    mock_connection.send_error.assert_called_once()
    assert mock_connection.send_error.call_args[0][1] == "not_found"


@pytest.mark.asyncio
async def test_resolve_ai_alert_no_alert_monitor_sends_error(
    mock_connection: MagicMock,
) -> None:
    """resolve_ai_alert sends not_found when coordinator has no alert_monitor."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_resolve_ai_alert,
    )

    coordinator = MagicMock(spec=[])  # no alert_monitor attribute

    with patch(
        "custom_components.growspace_manager.websocket.ai_assistant._get_coordinator",
        return_value=coordinator,
    ):
        msg = {
            "id": 31,
            "type": "growspace_manager/resolve_ai_alert",
            "alert_id": "abc",
        }
        await websocket_resolve_ai_alert(MagicMock(), mock_connection, msg)

    mock_connection.send_error.assert_called_once()
    assert mock_connection.send_error.call_args[0][1] == "not_found"


@pytest.mark.asyncio
async def test_resolve_ai_alert_alert_not_found_sends_error(
    mock_connection: MagicMock,
) -> None:
    """resolve_ai_alert sends not_found when the alert_id does not exist."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_resolve_ai_alert,
    )

    alert_monitor = MagicMock()
    alert_monitor.resolve_alert = AsyncMock(return_value=False)
    coordinator = MagicMock()
    coordinator.alert_monitor = alert_monitor

    with patch(
        "custom_components.growspace_manager.websocket.ai_assistant._get_coordinator",
        return_value=coordinator,
    ):
        msg = {
            "id": 32,
            "type": "growspace_manager/resolve_ai_alert",
            "alert_id": "missing-id",
        }
        await websocket_resolve_ai_alert(MagicMock(), mock_connection, msg)

    mock_connection.send_error.assert_called_once()
    assert mock_connection.send_error.call_args[0][1] == "not_found"


@pytest.mark.asyncio
async def test_resolve_ai_alert_success(
    mock_connection: MagicMock,
) -> None:
    """resolve_ai_alert sends success result when alert is resolved."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_resolve_ai_alert,
    )

    alert_monitor = MagicMock()
    alert_monitor.resolve_alert = AsyncMock(return_value=True)
    coordinator = MagicMock()
    coordinator.alert_monitor = alert_monitor

    with patch(
        "custom_components.growspace_manager.websocket.ai_assistant._get_coordinator",
        return_value=coordinator,
    ):
        msg = {
            "id": 33,
            "type": "growspace_manager/resolve_ai_alert",
            "alert_id": "alert-xyz",
            "resolution_note": "All fixed",
        }
        await websocket_resolve_ai_alert(MagicMock(), mock_connection, msg)

    alert_monitor.resolve_alert.assert_awaited_once_with("alert-xyz", notes="All fixed")
    result = mock_connection.send_result.call_args[0][1]
    assert result == {"success": True, "alert_id": "alert-xyz"}


# ---------------------------------------------------------------------------
# websocket_get_briefing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_briefing_coordinator_not_loaded(
    mock_connection: MagicMock,
) -> None:
    """get_briefing sends not_found when coordinator is unavailable."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_get_briefing,
    )

    with patch(
        "custom_components.growspace_manager.websocket.ai_assistant._get_coordinator",
        return_value=None,
    ):
        msg = {"id": 40, "type": "growspace_manager/get_briefing", "force_refresh": False}
        await websocket_get_briefing(MagicMock(), mock_connection, msg)

    mock_connection.send_error.assert_called_once()
    assert mock_connection.send_error.call_args[0][1] == "not_found"


@pytest.mark.asyncio
async def test_get_briefing_no_scheduler_sends_error(
    mock_connection: MagicMock,
) -> None:
    """get_briefing sends not_found when coordinator has no briefing_scheduler."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_get_briefing,
    )

    coordinator = MagicMock(spec=[])  # no briefing_scheduler attribute

    with patch(
        "custom_components.growspace_manager.websocket.ai_assistant._get_coordinator",
        return_value=coordinator,
    ):
        msg = {"id": 41, "type": "growspace_manager/get_briefing", "force_refresh": False}
        await websocket_get_briefing(MagicMock(), mock_connection, msg)

    mock_connection.send_error.assert_called_once()
    assert mock_connection.send_error.call_args[0][1] == "not_found"


@pytest.mark.asyncio
async def test_get_briefing_returns_briefing_data(
    mock_connection: MagicMock,
) -> None:
    """get_briefing returns briefing from scheduler, respecting force_refresh flag."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_get_briefing,
    )

    briefing_data = {"summary": "Everything looks healthy", "generated_at": "2026-05-27"}
    scheduler = MagicMock()
    scheduler.async_get_briefing = AsyncMock(return_value=briefing_data)
    coordinator = MagicMock()
    coordinator.briefing_scheduler = scheduler

    with patch(
        "custom_components.growspace_manager.websocket.ai_assistant._get_coordinator",
        return_value=coordinator,
    ):
        msg = {"id": 42, "type": "growspace_manager/get_briefing", "force_refresh": True}
        await websocket_get_briefing(MagicMock(), mock_connection, msg)

    scheduler.async_get_briefing.assert_awaited_once_with(force_refresh=True)
    result = mock_connection.send_result.call_args[0][1]
    assert result == briefing_data
