"""Tests for AI assistant WebSocket handlers (start_conversation, send_message)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.exceptions import (
    CoordinatorNotReadyError,
    EntityNotFoundError,
    GrowspaceError,
    RateLimitedError,
)
from homeassistant.exceptions import ServiceValidationError


def _coord(**overrides):
    """A coordinator stub for the payload-returning handlers."""
    coord = MagicMock()
    coord.growspaces = {}
    coord.options = {"ai_settings": {}}
    for key, value in overrides.items():
        setattr(coord, key, value)
    return coord


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
    returns the conversation_id from the result.
    """
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_start_conversation,
    )

    fake_result = _make_converse_result("Here is my advice.", conv_id="conv-123")

    with patch(
        "homeassistant.components.conversation.async_converse",
        new=AsyncMock(return_value=fake_result),
    ) as mock_converse:
        msg = {
            "id": 1,
            "type": "growspace_manager/start_conversation",
            "growspace_id": "tent1",
            "message": "How are my plants?",
            "agent_id": "test_agent",
        }
        result = await websocket_start_conversation(MagicMock(), _coord(), msg)

    mock_converse.assert_awaited_once()
    call_kwargs = mock_converse.call_args[1]
    assert call_kwargs.get("conversation_id") is None

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
        "homeassistant.components.conversation.async_converse",
        new=AsyncMock(return_value=fake_result),
    ):
        msg = {
            "id": 2,
            "type": "growspace_manager/start_conversation",
            "growspace_id": "tent1",
            "message": "What should I do?",
            "agent_id": "agent1",
        }
        result = await websocket_start_conversation(MagicMock(), _coord(), msg)

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
        "homeassistant.components.conversation.async_converse",
        new=AsyncMock(return_value=fake_result),
    ):
        msg = {
            "id": 3,
            "type": "growspace_manager/start_conversation",
            "growspace_id": "tent1",
            "message": "Any issues?",
            "agent_id": "agent1",
        }
        result = await websocket_start_conversation(MagicMock(), _coord(), msg)

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
    with pytest.raises(ServiceValidationError):
        await websocket_start_conversation(MagicMock(), _coord(), msg)


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
        "homeassistant.components.conversation.async_converse",
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
        await websocket_start_conversation(hass, _coord(), msg)


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
        "homeassistant.components.conversation.async_converse",
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
        await websocket_start_conversation(hass, _coord(), msg)


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
        "homeassistant.components.conversation.async_converse",
        new=AsyncMock(return_value=fake_result),
    ) as mock_converse:
        msg = {
            "id": 7,
            "type": "growspace_manager/send_message",
            "conversation_id": "conv-existing",
            "growspace_id": "tent1",
            "message": "Tell me more",
        }
        result = await websocket_send_message(MagicMock(), _coord(), msg)

    call_kwargs = mock_converse.call_args[1]
    assert call_kwargs["conversation_id"] == "conv-existing"

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
        "homeassistant.components.conversation.async_converse",
        new=AsyncMock(return_value=fake_result),
    ):
        msg = {
            "id": 8,
            "type": "growspace_manager/send_message",
            "conversation_id": "conv-42",
            "growspace_id": "tent1",
            "message": "What should I adjust?",
        }
        result = await websocket_send_message(MagicMock(), _coord(), msg)

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
    with pytest.raises(ServiceValidationError):
        await websocket_send_message(MagicMock(), _coord(), msg)


@pytest.mark.asyncio
async def test_send_message_empty_response_returns_error(
    mock_connection: MagicMock,
) -> None:
    """When async_converse returns None, an error is sent to the client."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_send_message,
    )

    with patch(
        "homeassistant.components.conversation.async_converse",
        new=AsyncMock(return_value=None),
    ):
        msg = {
            "id": 10,
            "type": "growspace_manager/send_message",
            "conversation_id": "conv-x",
            "growspace_id": "tent1",
            "message": "Hello",
        }
        with pytest.raises(GrowspaceError):
            await websocket_send_message(MagicMock(), _coord(), msg)


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
        "homeassistant.components.conversation.async_converse",
        new=AsyncMock(side_effect=ServiceValidationError("bad request")),
    ):
        msg = {
            "id": 11,
            "type": "growspace_manager/start_conversation",
            "growspace_id": "tent1",
            "message": "Hello",
        }
        with pytest.raises(GrowspaceError):
            await websocket_start_conversation(MagicMock(), _coord(), msg)


@pytest.mark.asyncio
async def test_start_conversation_generic_exception_returns_error(
    mock_connection: MagicMock,
) -> None:
    """An unexpected exception is caught and sent as a ws error."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_start_conversation,
    )

    with patch(
        "homeassistant.components.conversation.async_converse",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        msg = {
            "id": 12,
            "type": "growspace_manager/start_conversation",
            "growspace_id": "tent1",
            "message": "Hello",
        }
        with pytest.raises(GrowspaceError):
            await websocket_start_conversation(MagicMock(), _coord(), msg)


@pytest.mark.asyncio
async def test_start_conversation_empty_response_returns_error(
    mock_connection: MagicMock,
) -> None:
    """When async_converse returns no speech text, an ai_error is sent."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_start_conversation,
    )

    with patch(
        "homeassistant.components.conversation.async_converse",
        new=AsyncMock(return_value=None),
    ):
        msg = {
            "id": 13,
            "type": "growspace_manager/start_conversation",
            "growspace_id": "tent1",
            "message": "Hello",
        }
        with pytest.raises(GrowspaceError):
            await websocket_start_conversation(MagicMock(), _coord(), msg)


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
        "homeassistant.components.conversation.async_converse",
        new=AsyncMock(side_effect=ServiceValidationError("invalid")),
    ):
        msg = {
            "id": 14,
            "type": "growspace_manager/send_message",
            "conversation_id": "conv-err",
            "growspace_id": "tent1",
            "message": "Continue",
        }
        with pytest.raises(GrowspaceError):
            await websocket_send_message(MagicMock(), _coord(), msg)


@pytest.mark.asyncio
async def test_send_message_generic_exception_returns_error(
    mock_connection: MagicMock,
) -> None:
    """An unexpected exception in send_message is caught and returned as ws error."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_send_message,
    )

    with patch(
        "homeassistant.components.conversation.async_converse",
        new=AsyncMock(side_effect=ValueError("unexpected")),
    ):
        msg = {
            "id": 15,
            "type": "growspace_manager/send_message",
            "conversation_id": "conv-err",
            "growspace_id": "tent1",
            "message": "Continue",
        }
        with pytest.raises(GrowspaceError):
            await websocket_send_message(MagicMock(), _coord(), msg)


# ---------------------------------------------------------------------------
# _get_coordinator
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# websocket_get_ai_alerts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_ai_alerts_returns_filtered_alerts(
    mock_connection: MagicMock,
) -> None:
    """get_ai_alerts passes growspace_id and alert_type filters to the monitor."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_get_ai_alerts,
    )

    coordinator = MagicMock()
    coordinator.growspaces = {}
    coordinator.services.notifications.get_alerts.return_value = [
        {"id": "a1", "type": "stress"}
    ]

    if True:
        msg = {
            "id": 22,
            "type": "growspace_manager/get_ai_alerts",
            "growspace_id": "tent1",
            "alert_type": "stress",
        }
        result = await websocket_get_ai_alerts(MagicMock(), coordinator, msg)

    coordinator.services.notifications.get_alerts.assert_called_once_with(
        growspace_id="tent1", alert_type="stress"
    )
    assert result == [{"id": "a1", "type": "stress"}]


# ---------------------------------------------------------------------------
# websocket_resolve_ai_alert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_ai_alert_alert_not_found_sends_error(
    mock_connection: MagicMock,
) -> None:
    """resolve_ai_alert sends not_found when the alert_id does not exist."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_resolve_ai_alert,
    )

    coordinator = MagicMock()
    coordinator.growspaces = {}
    coordinator.services.notifications.resolve_alert = AsyncMock(return_value=False)

    if True:
        msg = {
            "id": 32,
            "type": "growspace_manager/resolve_ai_alert",
            "alert_id": "missing-id",
        }
        with pytest.raises(EntityNotFoundError):
            await websocket_resolve_ai_alert(MagicMock(), coordinator, msg)


@pytest.mark.asyncio
async def test_resolve_ai_alert_success(
    mock_connection: MagicMock,
) -> None:
    """resolve_ai_alert sends success result when alert is resolved."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_resolve_ai_alert,
    )

    coordinator = MagicMock()
    coordinator.growspaces = {}
    coordinator.services.notifications.resolve_alert = AsyncMock(return_value=True)

    if True:
        msg = {
            "id": 33,
            "type": "growspace_manager/resolve_ai_alert",
            "alert_id": "alert-xyz",
            "resolution_note": "All fixed",
        }
        result = await websocket_resolve_ai_alert(MagicMock(), coordinator, msg)

    coordinator.services.notifications.resolve_alert.assert_awaited_once_with(
        "alert-xyz", notes="All fixed"
    )
    assert result == {"success": True, "alert_id": "alert-xyz"}


# ---------------------------------------------------------------------------
# agent_id resolution — configured assistant used by default
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_message_uses_configured_agent_id(
    mock_connection: MagicMock,
) -> None:
    """send_message must route to the assistant configured in ai_settings, not None.

    This is the root cause of the bug: send_message was hardcoding agent_id=None,
    which always routed to the default HA local agent instead of the user-configured
    Google / Anthropic agent.
    """
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_send_message,
    )

    fake_result = _make_converse_result("VPD is 1.1 kPa.", conv_id="conv-existing")

    coordinator = MagicMock()
    coordinator.growspaces = {}
    coordinator.options = {
        "ai_settings": {"assistant_id": "conversation.google_ai_conversation"}
    }

    with (
        patch(
            "homeassistant.components.conversation.async_converse",
            new=AsyncMock(return_value=fake_result),
        ) as mock_converse,
    ):
        msg = {
            "id": 50,
            "type": "growspace_manager/send_message",
            "conversation_id": "conv-existing",
            "growspace_id": "tent1",
            "message": "What is the current VPD?",
        }
        await websocket_send_message(MagicMock(), coordinator, msg)

    call_kwargs = mock_converse.call_args[1]
    assert call_kwargs["agent_id"] == "conversation.google_ai_conversation"


@pytest.mark.asyncio
async def test_start_conversation_uses_configured_agent_when_no_agent_id_in_message(
    mock_connection: MagicMock,
) -> None:
    """start_conversation must fall back to ai_settings.assistant_id when no
    agent_id is supplied in the WebSocket message.

    The frontend does not pass agent_id in start_conversation; the backend must
    read it from the coordinator's ai_settings so the right LLM is used.
    """
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_start_conversation,
    )

    fake_result = _make_converse_result("Looking healthy!", conv_id="conv-new")

    coordinator = MagicMock()
    coordinator.growspaces = {}
    coordinator.options = {
        "ai_settings": {"assistant_id": "conversation.google_ai_conversation"}
    }

    with (
        patch(
            "homeassistant.components.conversation.async_converse",
            new=AsyncMock(return_value=fake_result),
        ) as mock_converse,
    ):
        msg = {
            "id": 51,
            "type": "growspace_manager/start_conversation",
            "growspace_id": "tent1",
            "message": "What is the current VPD?",
            # No agent_id in message — frontend never sends it
        }
        await websocket_start_conversation(MagicMock(), coordinator, msg)

    call_kwargs = mock_converse.call_args[1]
    assert call_kwargs["agent_id"] == "conversation.google_ai_conversation"


@pytest.mark.asyncio
async def test_start_conversation_explicit_agent_id_takes_precedence(
    mock_connection: MagicMock,
) -> None:
    """An explicit agent_id in the WS message overrides the configured assistant_id."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_start_conversation,
    )

    fake_result = _make_converse_result("Good to go.", conv_id="conv-explicit")

    coordinator = MagicMock()
    coordinator.growspaces = {}
    coordinator.options = {
        "ai_settings": {"assistant_id": "conversation.google_ai_conversation"}
    }

    with (
        patch(
            "homeassistant.components.conversation.async_converse",
            new=AsyncMock(return_value=fake_result),
        ) as mock_converse,
    ):
        msg = {
            "id": 52,
            "type": "growspace_manager/start_conversation",
            "growspace_id": "tent1",
            "message": "Hello",
            "agent_id": "conversation.override_agent",
        }
        await websocket_start_conversation(MagicMock(), coordinator, msg)

    call_kwargs = mock_converse.call_args[1]
    assert call_kwargs["agent_id"] == "conversation.override_agent"


# ---------------------------------------------------------------------------
# websocket_get_briefing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_briefing_no_scheduler_sends_error(
    mock_connection: MagicMock,
) -> None:
    """get_briefing sends not_found when coordinator has no briefing_scheduler."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_get_briefing,
    )

    coordinator = MagicMock(spec=[])  # no briefing_scheduler attribute

    if True:
        msg = {
            "id": 41,
            "type": "growspace_manager/get_briefing",
            "force_refresh": False,
        }
        with pytest.raises(CoordinatorNotReadyError):
            await websocket_get_briefing(MagicMock(), coordinator, msg)


@pytest.mark.asyncio
async def test_get_briefing_returns_briefing_data(
    mock_connection: MagicMock,
) -> None:
    """get_briefing returns briefing from scheduler, respecting force_refresh flag."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_get_briefing,
    )

    briefing_data = {
        "summary": "Everything looks healthy",
        "generated_at": "2026-05-27",
    }
    scheduler = MagicMock()
    scheduler.async_get_briefing = AsyncMock(return_value=briefing_data)
    coordinator = MagicMock()
    coordinator.growspaces = {}
    coordinator.briefing_scheduler = scheduler

    if True:
        msg = {
            "id": 42,
            "type": "growspace_manager/get_briefing",
            "force_refresh": True,
        }
        result = await websocket_get_briefing(MagicMock(), coordinator, msg)

    scheduler.async_get_briefing.assert_awaited_once_with(force_refresh=True)
    assert result == briefing_data


# ---------------------------------------------------------------------------
# save_ai_settings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_ai_settings_persists_full_dict(
    mock_connection: MagicMock,
) -> None:
    """save_ai_settings writes the full ai_settings dict to the config entry."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_save_ai_settings,
    )

    coordinator = MagicMock()
    coordinator.growspaces = {}
    coordinator.config_entry.options = {"other": "kept"}
    coordinator.async_commit = AsyncMock()

    payload = {
        "ai_enabled": True,
        "assistant_id": "conversation.claude",
        "notification_personality": "Scientific",
        "ai_auto_alerts": False,
        "max_response_length": 300,
        "vision_explainer_sees_image": False,
        "ai_task_entity_id": "ai_task.my_task",
        "briefing_interval_minutes": 60,
        "briefing_trigger_entities": ["sensor.vpd"],
    }

    mock_hass = MagicMock()
    if True:
        msg = {"id": 7, "type": "growspace_manager/save_ai_settings", **payload}
        result = await websocket_save_ai_settings(mock_hass, coordinator, msg)

    mock_hass.config_entries.async_update_entry.assert_called_once()
    saved_options = mock_hass.config_entries.async_update_entry.call_args[1]["options"]
    assert saved_options["other"] == "kept"
    assert saved_options["ai_settings"] == payload
    assert result == {"success": True}


# ---------------------------------------------------------------------------
# _build_context_message
# ---------------------------------------------------------------------------


def _make_coordinator_with_growspace(
    growspace_name: str = "Tent 1",
    growspace_type: str = "flower",
    vpd_sensor: str | None = "sensor.vpd",
    temperature_sensor: str | None = "sensor.temp",
    plants: list | None = None,
) -> MagicMock:
    from custom_components.growspace_manager.models import (
        EnvironmentConfig,
        GrowspaceType,
    )

    env = EnvironmentConfig(
        vpd_sensor=vpd_sensor,
        temperature_sensor=temperature_sensor,
    )
    growspace = MagicMock()
    growspace.name = growspace_name
    growspace.growspace_type = GrowspaceType(growspace_type)
    growspace.environment_config = env

    coordinator = MagicMock()
    coordinator.growspaces = {}
    coordinator.growspaces = {"tent1": growspace}
    coordinator.services.growspaces.get_growspace_plants.return_value = plants or []
    return coordinator


def _make_hass_with_states(states: dict[str, tuple[str, str]]) -> MagicMock:
    """Return a hass mock where states[entity_id] = (state_value, unit)."""
    hass = MagicMock()

    def get_state(entity_id: str):
        if entity_id not in states:
            return None
        value, unit = states[entity_id]
        state = MagicMock()
        state.state = value
        state.attributes = {"unit_of_measurement": unit}
        return state

    hass.states.get.side_effect = get_state
    return hass


def test_build_context_message_includes_growspace_name_and_sensors() -> None:
    from custom_components.growspace_manager.websocket.ai_assistant import (
        _build_context_message,
    )

    coordinator = _make_coordinator_with_growspace(
        vpd_sensor="sensor.vpd",
        temperature_sensor="sensor.temp",
    )
    hass = _make_hass_with_states(
        {
            "sensor.vpd": ("1.20", "kPa"),
            "sensor.temp": ("24.5", "°C"),
        }
    )

    result = _build_context_message(hass, coordinator, "tent1", "What is the VPD?")

    assert "[Growspace: Tent 1 | Type: flower]" in result
    assert "VPD=1.20kPa" in result
    assert "Temperature=24.5°C" in result
    assert "What is the VPD?" in result


def test_build_context_message_skips_unavailable_sensors() -> None:
    from custom_components.growspace_manager.websocket.ai_assistant import (
        _build_context_message,
    )

    coordinator = _make_coordinator_with_growspace(
        vpd_sensor="sensor.vpd",
        temperature_sensor="sensor.temp",
    )
    hass = _make_hass_with_states(
        {
            "sensor.vpd": ("unavailable", "kPa"),
            "sensor.temp": ("24.5", "°C"),
        }
    )

    result = _build_context_message(hass, coordinator, "tent1", "Hello")

    assert "VPD" not in result
    assert "Temperature=24.5°C" in result


def test_build_context_message_includes_flower_stage_from_plants() -> None:
    from custom_components.growspace_manager.websocket.ai_assistant import (
        _build_context_message,
    )

    plant = MagicMock()
    plant.flower_start = "2026-04-28"
    plant.veg_start = None
    plant.seedling_start = None
    plant.clone_start = None

    coordinator = _make_coordinator_with_growspace(plants=[plant])
    hass = _make_hass_with_states({})

    result = _build_context_message(hass, coordinator, "tent1", "Optimize me")

    assert "Stage: flower" in result
    assert "Day " in result
    assert "Week " in result


def test_build_context_message_returns_plain_message_when_growspace_missing() -> None:
    from custom_components.growspace_manager.websocket.ai_assistant import (
        _build_context_message,
    )

    coordinator = MagicMock()
    coordinator.growspaces = {}
    coordinator.growspaces = {}
    hass = MagicMock()

    result = _build_context_message(hass, coordinator, "unknown", "Hello")

    assert result == "Hello"


def test_build_context_message_dry_growspace_shows_stage_type() -> None:
    from custom_components.growspace_manager.websocket.ai_assistant import (
        _build_context_message,
    )

    coordinator = _make_coordinator_with_growspace(
        growspace_type="dry",
        vpd_sensor=None,
        temperature_sensor=None,
    )
    hass = _make_hass_with_states({})

    result = _build_context_message(hass, coordinator, "tent1", "How is the dry?")

    assert "Stage: dry" in result
    assert "How is the dry?" in result


@pytest.mark.asyncio
async def test_start_conversation_injects_context_when_coordinator_available(
    mock_connection: MagicMock,
) -> None:
    """start_conversation enriches the message with growspace context before sending to the AI."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_start_conversation,
    )

    fake_result = _make_converse_result("Here is my advice.", conv_id="conv-ctx")
    coordinator = _make_coordinator_with_growspace()
    hass = _make_hass_with_states({"sensor.vpd": ("1.10", "kPa")})

    with (
        patch(
            "homeassistant.components.conversation.async_converse",
            new=AsyncMock(return_value=fake_result),
        ) as mock_converse,
    ):
        msg = {
            "id": 1,
            "type": "growspace_manager/start_conversation",
            "growspace_id": "tent1",
            "message": "What is the VPD?",
            "agent_id": "test_agent",
        }
        await websocket_start_conversation(hass, coordinator, msg)

    call_kwargs = mock_converse.call_args[1]
    assert "[Growspace: Tent 1" in call_kwargs["text"]
    assert "What is the VPD?" in call_kwargs["text"]


@pytest.mark.asyncio
async def test_send_message_injects_context_when_coordinator_available(
    mock_connection: MagicMock,
) -> None:
    """send_message enriches the message with growspace context before forwarding."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_send_message,
    )

    fake_result = _make_converse_result("Updated advice.", conv_id="conv-456")
    coordinator = _make_coordinator_with_growspace()
    hass = _make_hass_with_states({"sensor.temp": ("22.0", "°C")})

    with (
        patch(
            "homeassistant.components.conversation.async_converse",
            new=AsyncMock(return_value=fake_result),
        ) as mock_converse,
    ):
        msg = {
            "id": 2,
            "type": "growspace_manager/send_message",
            "conversation_id": "conv-456",
            "growspace_id": "tent1",
            "message": "How can I optimize?",
        }
        await websocket_send_message(hass, coordinator, msg)

    call_kwargs = mock_converse.call_args[1]
    assert "[Growspace: Tent 1" in call_kwargs["text"]
    assert "How can I optimize?" in call_kwargs["text"]


def test_build_context_message_skips_empty_entity_ids() -> None:
    """_build_context_message ignores None or empty string entity IDs in specs."""
    from custom_components.growspace_manager.models import EnvironmentConfig
    from custom_components.growspace_manager.websocket.ai_assistant import (
        _build_context_message,
    )

    coordinator = _make_coordinator_with_growspace(
        vpd_sensor=None,
        temperature_sensor=None,
    )
    # Inject None/empty values into EnvironmentConfig lists to trigger continue
    env = EnvironmentConfig(
        temperature_sensors=[None, ""],
        humidity_sensors=["", None],
    )
    coordinator.growspaces["tent1"].environment_config = env
    hass = _make_hass_with_states({})

    result = _build_context_message(hass, coordinator, "tent1", "Hello")
    assert "Sensors" not in result


def test_build_context_message_veg_stage_from_plants() -> None:
    """_build_context_message formats the stage correctly when plants are in veg stage."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        _build_context_message,
    )

    plant = MagicMock()
    plant.flower_start = None
    plant.veg_start = "2026-05-01"
    plant.seedling_start = None
    plant.clone_start = None

    coordinator = _make_coordinator_with_growspace(plants=[plant])
    hass = _make_hass_with_states({})

    result = _build_context_message(hass, coordinator, "tent1", "Optimize")
    assert "Stage: veg" in result


def test_build_context_message_seedling_stage_from_plants() -> None:
    """_build_context_message formats the stage correctly when plants are in seedling stage."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        _build_context_message,
    )

    plant = MagicMock()
    plant.flower_start = None
    plant.veg_start = None
    plant.seedling_start = "2026-05-15"
    plant.clone_start = None

    coordinator = _make_coordinator_with_growspace(plants=[plant])
    hass = _make_hass_with_states({})

    result = _build_context_message(hass, coordinator, "tent1", "Optimize")
    assert "Stage: seedling" in result


def test_build_context_message_clone_stage_from_plants() -> None:
    """_build_context_message formats the stage correctly when plants are in clone stage."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        _build_context_message,
    )

    plant = MagicMock()
    plant.flower_start = None
    plant.veg_start = None
    plant.seedling_start = None
    plant.clone_start = "2026-05-20"

    coordinator = _make_coordinator_with_growspace(plants=[plant])
    hass = _make_hass_with_states({})

    result = _build_context_message(hass, coordinator, "tent1", "Optimize")
    assert "Stage: clone" in result


@pytest.mark.asyncio
async def test_start_conversation_rate_limited_service_validation_error(
    mock_connection: MagicMock,
) -> None:
    """ServiceValidationError with a rate limit message is caught and mapped to rate_limited error."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_start_conversation,
    )

    with patch(
        "homeassistant.components.conversation.async_converse",
        new=AsyncMock(side_effect=ServiceValidationError("Rate limit exceeded: 429")),
    ):
        msg = {
            "id": 20,
            "type": "growspace_manager/start_conversation",
            "growspace_id": "tent1",
            "message": "Hello",
        }
        with pytest.raises(RateLimitedError):
            await websocket_start_conversation(MagicMock(), _coord(), msg)


@pytest.mark.asyncio
async def test_start_conversation_rate_limited_generic_exception(
    mock_connection: MagicMock,
) -> None:
    """A generic Exception containing rate limit indications is mapped to rate_limited error."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_start_conversation,
    )

    with patch(
        "homeassistant.components.conversation.async_converse",
        new=AsyncMock(side_effect=RuntimeError("Error 429 - Too Many Requests")),
    ):
        msg = {
            "id": 21,
            "type": "growspace_manager/start_conversation",
            "growspace_id": "tent1",
            "message": "Hello",
        }
        with pytest.raises(RateLimitedError):
            await websocket_start_conversation(MagicMock(), _coord(), msg)


@pytest.mark.asyncio
async def test_start_conversation_rate_limited_result(
    mock_connection: MagicMock,
) -> None:
    """When async_converse result contains a rate limited indicator, it is sent as rate_limited."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_start_conversation,
    )

    fake_result = MagicMock()
    fake_result.conversation_id = "conv-123"
    fake_result.response = MagicMock()
    fake_result.response.speech = {
        "plain": {"speech": "Error: Too Many Requests (429)"}
    }
    fake_result.response.error_code = "RESOURCE_EXHAUSTED"

    with patch(
        "homeassistant.components.conversation.async_converse",
        new=AsyncMock(return_value=fake_result),
    ):
        msg = {
            "id": 22,
            "type": "growspace_manager/start_conversation",
            "growspace_id": "tent1",
            "message": "Hello",
        }
        with pytest.raises(RateLimitedError):
            await websocket_start_conversation(MagicMock(), _coord(), msg)


@pytest.mark.asyncio
async def test_send_message_rate_limited_service_validation_error(
    mock_connection: MagicMock,
) -> None:
    """ServiceValidationError with rate limit info in send_message is caught and mapped to rate_limited error."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_send_message,
    )

    with patch(
        "homeassistant.components.conversation.async_converse",
        new=AsyncMock(side_effect=ServiceValidationError("API call rejected (429)")),
    ):
        msg = {
            "id": 23,
            "type": "growspace_manager/send_message",
            "conversation_id": "conv-123",
            "growspace_id": "tent1",
            "message": "Hello",
        }
        with pytest.raises(RateLimitedError):
            await websocket_send_message(MagicMock(), _coord(), msg)


@pytest.mark.asyncio
async def test_send_message_rate_limited_generic_exception(
    mock_connection: MagicMock,
) -> None:
    """Generic exception with rate limit info in send_message is mapped to rate_limited error."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_send_message,
    )

    with patch(
        "homeassistant.components.conversation.async_converse",
        new=AsyncMock(side_effect=ValueError("429 Too Many Requests")),
    ):
        msg = {
            "id": 24,
            "type": "growspace_manager/send_message",
            "conversation_id": "conv-123",
            "growspace_id": "tent1",
            "message": "Hello",
        }
        with pytest.raises(RateLimitedError):
            await websocket_send_message(MagicMock(), _coord(), msg)


@pytest.mark.asyncio
async def test_send_message_rate_limited_result(
    mock_connection: MagicMock,
) -> None:
    """When send_message result contains a rate limited indicator, it is sent as rate_limited."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_send_message,
    )

    fake_result = MagicMock()
    fake_result.conversation_id = "conv-123"
    fake_result.response = MagicMock()
    fake_result.response.speech = {"plain": {"speech": "Something went wrong."}}
    fake_result.response.error_code = "RESOURCE_EXHAUSTED"

    with patch(
        "homeassistant.components.conversation.async_converse",
        new=AsyncMock(return_value=fake_result),
    ):
        msg = {
            "id": 25,
            "type": "growspace_manager/send_message",
            "conversation_id": "conv-123",
            "growspace_id": "tent1",
            "message": "Hello",
        }
        with pytest.raises(RateLimitedError):
            await websocket_send_message(MagicMock(), _coord(), msg)


@pytest.mark.asyncio
async def test_save_ai_agent_success(
    mock_connection: MagicMock,
) -> None:
    """save_ai_agent updates the config entry options and enables AI assistant settings."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_save_ai_agent,
    )

    # Mock config entry and options
    config_entry = MagicMock()
    config_entry.options = {
        "ai_settings": {"assistant_id": "old-agent", "ai_enabled": False}
    }

    coordinator = MagicMock()
    coordinator.growspaces = {}
    coordinator.config_entry = config_entry
    coordinator.options = config_entry.options
    coordinator.async_commit = AsyncMock()

    hass = MagicMock()
    hass.config_entries.async_update_entry = MagicMock()

    if True:
        msg = {
            "id": 31,
            "type": "growspace_manager/save_ai_agent",
            "agent_id": "new-agent-abc",
        }
        result = await websocket_save_ai_agent(hass, coordinator, msg)

    # Verify options update
    expected_options = {
        "ai_settings": {
            "assistant_id": "new-agent-abc",
            "ai_enabled": True,
        }
    }
    assert coordinator.options == expected_options
    hass.config_entries.async_update_entry.assert_called_once_with(
        config_entry, options=expected_options
    )
    coordinator.async_commit.assert_called_once()
    assert result == {"success": True, "agent_id": "new-agent-abc"}


@pytest.mark.asyncio
async def test_save_ai_agent_without_options_attribute(
    mock_connection: MagicMock,
) -> None:
    """save_ai_agent handles a coordinator that has no options attribute."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_save_ai_agent,
    )

    config_entry = MagicMock()
    config_entry.options = {
        "ai_settings": {"assistant_id": "old-agent", "ai_enabled": False}
    }

    coordinator = MagicMock()
    coordinator.growspaces = {}
    coordinator.config_entry = config_entry
    del coordinator.options
    coordinator.async_commit = AsyncMock()

    hass = MagicMock()
    hass.config_entries.async_update_entry = MagicMock()

    if True:
        msg = {
            "id": 32,
            "type": "growspace_manager/save_ai_agent",
            "agent_id": "new-agent-abc",
        }
        await websocket_save_ai_agent(hass, coordinator, msg)

    assert not hasattr(coordinator, "options")
    hass.config_entries.async_update_entry.assert_called_once()


@pytest.mark.asyncio
async def test_save_ai_settings_without_options_attribute(
    mock_connection: MagicMock,
) -> None:
    """save_ai_settings handles a coordinator that has no options attribute."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_save_ai_settings,
    )

    config_entry = MagicMock()
    config_entry.options = {"other": "kept"}

    coordinator = MagicMock()
    coordinator.growspaces = {}
    coordinator.config_entry = config_entry
    del coordinator.options
    coordinator.async_commit = AsyncMock()

    mock_hass = MagicMock()
    if True:
        msg = {
            "id": 33,
            "type": "growspace_manager/save_ai_settings",
            "ai_enabled": True,
        }
        result = await websocket_save_ai_settings(mock_hass, coordinator, msg)

    assert not hasattr(coordinator, "options")
    mock_hass.config_entries.async_update_entry.assert_called_once()
    assert result == {"success": True}
