"""AI assistant WebSocket handlers for Growspace Manager.

Provides four commands:
- ``start_conversation``: begins a new AI conversation (conversation_id=None)
- ``send_message``: continues an existing conversation by conversation_id
- ``get_ai_alerts``: retrieves persistent AI alert records with optional filtering
- ``resolve_ai_alert``: marks an alert as resolved with optional notes

Both conversation commands optionally accept image entities (camera.* or
image.* domain only) to inject into the prompt for vision-capable agents.

Responses are scanned for ``[ACTION]...[/ACTION]`` blocks.  When found the
block is stripped from the display text and the JSON payload is parsed and
returned separately.  Parse failures are silenced — the full text (with the
raw block) is returned as-is.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import voluptuous as vol

from homeassistant.components import conversation, websocket_api
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from ..const import DOMAIN
from ..coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)

# Matches [ACTION]...[/ACTION] — non-greedy, allows multi-line content
_ACTION_RE = re.compile(r"\[ACTION\](.*?)\[/ACTION\]", re.DOTALL)

_VALID_IMAGE_DOMAINS = {"camera", "image"}

WS_TYPE_START_CONVERSATION = f"{DOMAIN}/start_conversation"
SCHEMA_WS_START_CONVERSATION = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_START_CONVERSATION,
        vol.Required("growspace_id"): str,
        vol.Required("message"): str,
        vol.Optional("agent_id"): str,
        vol.Optional("image_entities"): [str],
    }
)

WS_TYPE_SEND_MESSAGE = f"{DOMAIN}/send_message"
SCHEMA_WS_SEND_MESSAGE = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_SEND_MESSAGE,
        vol.Required("conversation_id"): str,
        vol.Required("growspace_id"): str,
        vol.Required("message"): str,
        vol.Optional("image_entities"): [str],
    }
)


def _validate_image_entities(
    image_entities: list[str],
    connection: websocket_api.ActiveConnection,
    msg_id: int,
) -> bool:
    """Validate that all image entity IDs belong to camera or image domains.

    Returns True if valid, False and sends an error to the connection if not.
    """
    for entity_id in image_entities:
        domain = entity_id.split(".", 1)[0]
        if domain not in _VALID_IMAGE_DOMAINS:
            connection.send_error(
                msg_id,
                "invalid_entity",
                f"Entity '{entity_id}' is not in the camera or image domain",
            )
            return False
    return True


def _extract_action(text: str) -> tuple[str, dict[str, Any] | None]:
    """Extract and parse an [ACTION]...[/ACTION] block from *text*.

    Returns ``(display_text, action_dict)``.  If no block is found, or if the
    JSON inside the block is malformed, ``action_dict`` is ``None`` and the
    original text is returned unchanged.
    """
    match = _ACTION_RE.search(text)
    if not match:
        return text, None

    raw_json = match.group(1).strip()
    try:
        action = json.loads(raw_json)
    except (json.JSONDecodeError, ValueError):
        # Malformed block — return the full text without modification
        return text, None

    # Strip the block (and any surrounding whitespace) from the display text
    display = _ACTION_RE.sub("", text).strip()
    return display, action


def _extract_speech(result: Any) -> str | None:
    """Pull the plain-speech string out of an async_converse result."""
    if (
        result
        and result.response
        and result.response.speech
        and result.response.speech.get("plain")
        and result.response.speech["plain"].get("speech")
    ):
        return str(result.response.speech["plain"]["speech"])
    return None


async def _run_conversation(
    hass: HomeAssistant,
    message: str,
    agent_id: str | None,
    conversation_id: str | None,
) -> Any:
    """Call conversation.async_converse and return the raw result."""
    return await conversation.async_converse(
        hass,
        text=message,
        conversation_id=conversation_id,
        context=Context(),
        agent_id=agent_id,
    )


async def websocket_start_conversation(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Handle the start_conversation WebSocket command.

    Begins a brand-new AI conversation (conversation_id=None) and returns
    the server-assigned conversation_id together with the response text.
    """
    growspace_id: str = msg["growspace_id"]
    message: str = msg["message"]
    agent_id: str | None = msg.get("agent_id")
    image_entities: list[str] = msg.get("image_entities") or []

    if not _validate_image_entities(image_entities, connection, msg["id"]):
        return

    try:
        result = await _run_conversation(hass, message, agent_id, conversation_id=None)
    except ServiceValidationError as err:
        _LOGGER.error("Error in start_conversation: %s", err)
        connection.send_error(msg["id"], "ai_error", str(err))
        return
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Unexpected error in start_conversation: %s", err)
        connection.send_error(msg["id"], "ai_error", str(err))
        return

    speech = _extract_speech(result)
    if speech is None:
        connection.send_error(
            msg["id"], "ai_error", "AI assistant returned an empty response"
        )
        return

    display_text, action = _extract_action(speech)
    ai_message: dict[str, Any] = {
        "role": "ai",
        "text": display_text,
        "timestamp": int(time.time() * 1000),
    }
    if action is not None:
        ai_message["suggestedAction"] = action

    connection.send_result(msg["id"], {
        "thread_id": result.conversation_id,
        "growspace_id": growspace_id,
        "messages": [ai_message],
    })


async def websocket_send_message(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Handle the send_message WebSocket command.

    Continues an existing AI conversation identified by *conversation_id*.
    """
    conversation_id: str = msg["conversation_id"]
    growspace_id: str = msg["growspace_id"]
    message: str = msg["message"]
    image_entities: list[str] = msg.get("image_entities") or []

    if not _validate_image_entities(image_entities, connection, msg["id"]):
        return

    try:
        result = await _run_conversation(
            hass, message, agent_id=None, conversation_id=conversation_id
        )
    except ServiceValidationError as err:
        _LOGGER.error("Error in send_message: %s", err)
        connection.send_error(msg["id"], "ai_error", str(err))
        return
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Unexpected error in send_message: %s", err)
        connection.send_error(msg["id"], "ai_error", str(err))
        return

    speech = _extract_speech(result)
    if speech is None:
        connection.send_error(
            msg["id"], "ai_error", "AI assistant returned an empty response"
        )
        return

    display_text, action = _extract_action(speech)
    ai_message: dict[str, Any] = {
        "role": "ai",
        "text": display_text,
        "timestamp": int(time.time() * 1000),
    }
    if action is not None:
        ai_message["suggestedAction"] = action

    connection.send_result(msg["id"], {
        "thread_id": conversation_id,
        "growspace_id": growspace_id,
        "messages": [ai_message],
    })


def _get_coordinator(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
) -> GrowspaceCoordinator | None:
    """Return the first loaded GrowspaceCoordinator, or *None*.

    Returns ``None`` (rather than raising) so callers can send a typed
    WebSocket error response.
    """
    try:
        return GrowspaceCoordinator.get_for_service_call(hass, {})
    except (ServiceValidationError, Exception):  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# get_ai_alerts
# ---------------------------------------------------------------------------

WS_TYPE_GET_AI_ALERTS = f"{DOMAIN}/get_ai_alerts"
SCHEMA_WS_GET_AI_ALERTS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_AI_ALERTS,
        vol.Optional("growspace_id"): str,
        vol.Optional("alert_type"): vol.In(["stress", "mold"]),
    }
)


async def websocket_get_ai_alerts(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return AI alert records, optionally filtered by growspace or type.

    WebSocket message fields:
    - ``growspace_id`` *(optional)*: filter to a specific growspace
    - ``alert_type`` *(optional)*: ``"stress"`` or ``"mold"``
    """
    coordinator = _get_coordinator(hass, connection)
    if coordinator is None:
        connection.send_error(
            msg["id"], "not_found", "Growspace Manager integration not loaded"
        )
        return

    alert_monitor = getattr(coordinator, "alert_monitor", None)
    if alert_monitor is None:
        connection.send_result(msg["id"], [])
        return

    alerts = alert_monitor.get_alerts(
        growspace_id=msg.get("growspace_id"),
        alert_type=msg.get("alert_type"),
    )
    connection.send_result(msg["id"], alerts)


# ---------------------------------------------------------------------------
# resolve_ai_alert
# ---------------------------------------------------------------------------

WS_TYPE_RESOLVE_AI_ALERT = f"{DOMAIN}/resolve_ai_alert"
SCHEMA_WS_RESOLVE_AI_ALERT = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_RESOLVE_AI_ALERT,
        vol.Required("alert_id"): str,
        vol.Optional("notes"): str,
    }
)


async def websocket_resolve_ai_alert(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Mark an AI alert as resolved.

    WebSocket message fields:
    - ``alert_id`` *(required)*: UUID of the alert to resolve
    - ``notes`` *(optional)*: resolution notes to attach
    """
    coordinator = _get_coordinator(hass, connection)
    if coordinator is None:
        connection.send_error(
            msg["id"], "not_found", "Growspace Manager integration not loaded"
        )
        return

    alert_monitor = getattr(coordinator, "alert_monitor", None)
    if alert_monitor is None:
        connection.send_error(
            msg["id"], "not_found", "Alert monitor not available"
        )
        return

    alert_id: str = msg["alert_id"]
    notes: str | None = msg.get("notes")
    resolved = await alert_monitor.resolve_alert(alert_id, notes=notes)

    if not resolved:
        connection.send_error(
            msg["id"], "not_found", f"Alert '{alert_id}' not found"
        )
        return

    connection.send_result(msg["id"], {"success": True, "alert_id": alert_id})


# ---------------------------------------------------------------------------
# get_briefing
# ---------------------------------------------------------------------------

WS_TYPE_GET_BRIEFING = f"{DOMAIN}/get_briefing"
SCHEMA_WS_GET_BRIEFING = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_BRIEFING,
        vol.Optional("force_refresh", default=False): bool,
    }
)


async def websocket_get_briefing(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the latest AI briefing, optionally regenerating it.

    WebSocket message fields:
    - ``force_refresh`` *(optional, default False)*: when ``True`` bypass the
      cache and generate a fresh briefing immediately.
    """
    coordinator = _get_coordinator(hass, connection)
    if coordinator is None:
        connection.send_error(
            msg["id"], "not_found", "Growspace Manager integration not loaded"
        )
        return

    briefing_scheduler = getattr(coordinator, "briefing_scheduler", None)
    if briefing_scheduler is None:
        connection.send_error(
            msg["id"], "not_found", "Briefing scheduler not available"
        )
        return

    force_refresh: bool = msg.get("force_refresh", False)
    briefing = await briefing_scheduler.async_get_briefing(force_refresh=force_refresh)
    connection.send_result(msg["id"], briefing)


COMMANDS: list[tuple[str, Any, Any, bool]] = [
    (WS_TYPE_START_CONVERSATION, websocket_start_conversation, SCHEMA_WS_START_CONVERSATION, False),
    (WS_TYPE_SEND_MESSAGE, websocket_send_message, SCHEMA_WS_SEND_MESSAGE, False),
    (WS_TYPE_GET_AI_ALERTS, websocket_get_ai_alerts, SCHEMA_WS_GET_AI_ALERTS, False),
    (WS_TYPE_RESOLVE_AI_ALERT, websocket_resolve_ai_alert, SCHEMA_WS_RESOLVE_AI_ALERT, False),
    (WS_TYPE_GET_BRIEFING, websocket_get_briefing, SCHEMA_WS_GET_BRIEFING, False),
]
