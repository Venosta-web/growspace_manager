"""Tests for AI assistant WebSocket handlers (start_conversation, send_message)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.core import HomeAssistant


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
            "message": "How are my plants?",
            "agent_id": "test_agent",
        }
        await websocket_start_conversation(MagicMock(), mock_connection, msg)

    mock_converse.assert_awaited_once()
    call_kwargs = mock_converse.call_args[1]
    assert call_kwargs.get("conversation_id") is None

    mock_connection.send_result.assert_called_once()
    result = mock_connection.send_result.call_args[0][1]
    assert result["conversation_id"] == "conv-123"
    assert result["response"] == "Here is my advice."


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
            "message": "What should I do?",
            "agent_id": "agent1",
        }
        await websocket_start_conversation(MagicMock(), mock_connection, msg)

    result = mock_connection.send_result.call_args[0][1]
    assert result["action"] == {"type": "water", "confidence": 0.9}
    # Display text should not include the action block
    assert "[ACTION]" not in result["response"]


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
            "message": "Any issues?",
            "agent_id": "agent1",
        }
        await websocket_start_conversation(MagicMock(), mock_connection, msg)

    result = mock_connection.send_result.call_args[0][1]
    assert "action" not in result
    assert result["response"] is not None  # some text returned


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
            "message": "Tell me more",
        }
        await websocket_send_message(MagicMock(), mock_connection, msg)

    call_kwargs = mock_converse.call_args[1]
    assert call_kwargs["conversation_id"] == "conv-existing"

    result = mock_connection.send_result.call_args[0][1]
    assert result["conversation_id"] == "conv-existing"
    assert result["response"] == "Follow-up answer."


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
            "message": "What should I adjust?",
        }
        await websocket_send_message(MagicMock(), mock_connection, msg)

    result = mock_connection.send_result.call_args[0][1]
    assert result["action"] == {"type": "adjust_ph", "value": 6.2}
    assert "[ACTION]" not in result["response"]


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
            "message": "Hello",
        }
        await websocket_send_message(MagicMock(), mock_connection, msg)

    mock_connection.send_error.assert_called_once()
    err_args = mock_connection.send_error.call_args[0]
    assert err_args[1] == "ai_error"
