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
from ..models import GrowspaceType
from ..utils import calculate_days_since, days_to_week

_LOGGER = logging.getLogger(__name__)

# Matches [ACTION]...[/ACTION] — non-greedy, allows multi-line content
_ACTION_RE = re.compile(r"\[ACTION\](.*?)\[/ACTION\]", re.DOTALL)

_VALID_IMAGE_DOMAINS = {"camera", "image"}

_RATE_LIMIT_MARKERS = ("429", "Too Many Requests", "RESOURCE_EXHAUSTED", "resource_exhausted")
_RATE_LIMIT_MESSAGE = "rate_limited"

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


def _is_rate_limited_result(result: Any) -> bool:
    """Return True if the conversation result carries a 429/rate-limit error."""
    if not (result and result.response):
        return False
    speech = (
        result.response.speech.get("plain", {}).get("speech", "")
        if result.response.speech
        else ""
    )
    err_code = getattr(result.response, "error_code", "") or ""
    return any(m in speech for m in _RATE_LIMIT_MARKERS) or any(
        m.lower() in err_code.lower() for m in _RATE_LIMIT_MARKERS
    )


def _is_rate_limited_error(err: BaseException) -> bool:
    """Return True if an exception message indicates a 429/rate-limit error."""
    msg = str(err)
    return any(m in msg for m in _RATE_LIMIT_MARKERS)


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


def _build_context_message(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    growspace_id: str,
    message: str,
) -> str:
    """Prepend growspace sensor readings and stage info to the user message."""
    growspace = coordinator.growspaces.get(growspace_id)
    if not growspace:
        return message

    env = growspace.environment_config

    # Collect sensor readings — first valid entity per type wins
    sensor_specs: list[tuple[str, list[str | None]]] = [
        ("Temperature", env.temperature_sensors or ([env.temperature_sensor] if env.temperature_sensor else [])),
        ("Humidity", env.humidity_sensors or ([env.humidity_sensor] if env.humidity_sensor else [])),
        ("VPD", env.vpd_sensors or ([env.vpd_sensor] if env.vpd_sensor else [])),
        ("CO2", [env.co2_sensor] if env.co2_sensor else []),
        ("Substrate temp", env.substrate_temperature_sensors),
        ("pH", env.ph_sensors),
        ("Feed EC", env.feed_ec_sensors),
        ("Runoff EC", env.runoff_ec_sensors),
    ]
    sensor_parts: list[str] = []
    for label, entity_ids in sensor_specs:
        for entity_id in entity_ids:
            if not entity_id:
                continue
            state = hass.states.get(entity_id)
            if state and state.state not in ("unavailable", "unknown"):
                unit = state.attributes.get("unit_of_measurement", "")
                sensor_parts.append(f"{label}={state.state}{unit}")
                break

    # Determine current growth stage from plants
    stage_line = ""
    if growspace.growspace_type in (GrowspaceType.DRY, GrowspaceType.CURE):
        stage_line = f"Stage: {growspace.growspace_type.value}"
    else:
        plants = coordinator.data_repository.get_growspace_plants(growspace_id)
        if plants:
            max_flower = max(
                (calculate_days_since(p.flower_start) for p in plants if p.flower_start),
                default=-1,
            )
            max_veg = max(
                (calculate_days_since(p.veg_start) for p in plants if p.veg_start),
                default=-1,
            )
            max_seedling = max(
                (calculate_days_since(p.seedling_start) for p in plants if p.seedling_start),
                default=-1,
            )
            max_clone = max(
                (calculate_days_since(p.clone_start) for p in plants if p.clone_start),
                default=-1,
            )
            if max_flower >= 0:
                stage_line = f"Stage: flower | Day {max_flower} | Week {days_to_week(max_flower)}"
            elif max_veg >= 0:
                stage_line = f"Stage: veg | Day {max_veg} | Week {days_to_week(max_veg)}"
            elif max_seedling >= 0:
                stage_line = f"Stage: seedling | Day {max_seedling} | Week {days_to_week(max_seedling)}"
            elif max_clone >= 0:
                stage_line = f"Stage: clone | Day {max_clone} | Week {days_to_week(max_clone)}"

    lines: list[str] = [f"[Growspace: {growspace.name} | Type: {growspace.growspace_type.value}]"]
    if stage_line:
        lines.append(stage_line)
    if sensor_parts:
        lines.append("Sensors: " + " | ".join(sensor_parts))
    lines.append("---")
    lines.append(message)
    return "\n".join(lines)


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
    coordinator = _get_coordinator(hass, connection)
    if agent_id is None and coordinator is not None:
        agent_id = coordinator.options.get("ai_settings", {}).get("assistant_id")
    image_entities: list[str] = msg.get("image_entities") or []

    if not _validate_image_entities(image_entities, connection, msg["id"]):
        return

    if coordinator is not None:
        message = _build_context_message(hass, coordinator, growspace_id, message)

    try:
        result = await _run_conversation(hass, message, agent_id, conversation_id=None)
    except ServiceValidationError as err:
        _LOGGER.error("Error in start_conversation: %s", err)
        if _is_rate_limited_error(err):
            connection.send_error(msg["id"], "rate_limited", _RATE_LIMIT_MESSAGE)
        else:
            connection.send_error(msg["id"], "ai_error", str(err))
        return
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Unexpected error in start_conversation: %s", err)
        if _is_rate_limited_error(err):
            connection.send_error(msg["id"], "rate_limited", _RATE_LIMIT_MESSAGE)
        else:
            connection.send_error(msg["id"], "ai_error", str(err))
        return

    if _is_rate_limited_result(result):
        _LOGGER.warning("AI rate limit reached in start_conversation")
        connection.send_error(msg["id"], "rate_limited", _RATE_LIMIT_MESSAGE)
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

    coordinator = _get_coordinator(hass, connection)
    agent_id: str | None = None
    if coordinator is not None:
        agent_id = coordinator.options.get("ai_settings", {}).get("assistant_id")
        message = _build_context_message(hass, coordinator, growspace_id, message)

    try:
        result = await _run_conversation(
            hass, message, agent_id=agent_id, conversation_id=conversation_id
        )
    except ServiceValidationError as err:
        _LOGGER.error("Error in send_message: %s", err)
        if _is_rate_limited_error(err):
            connection.send_error(msg["id"], "rate_limited", _RATE_LIMIT_MESSAGE)
        else:
            connection.send_error(msg["id"], "ai_error", str(err))
        return
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Unexpected error in send_message: %s", err)
        if _is_rate_limited_error(err):
            connection.send_error(msg["id"], "rate_limited", _RATE_LIMIT_MESSAGE)
        else:
            connection.send_error(msg["id"], "ai_error", str(err))
        return

    if _is_rate_limited_result(result):
        _LOGGER.warning("AI rate limit reached in send_message")
        connection.send_error(msg["id"], "rate_limited", _RATE_LIMIT_MESSAGE)
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

    alerts = coordinator.alert_monitor.get_alerts(
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
        vol.Optional("resolution_note"): str,
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
    - ``resolution_note`` *(optional)*: resolution notes to attach
    """
    coordinator = _get_coordinator(hass, connection)
    if coordinator is None:
        connection.send_error(
            msg["id"], "not_found", "Growspace Manager integration not loaded"
        )
        return

    alert_id: str = msg["alert_id"]
    notes: str | None = msg.get("resolution_note")
    resolved = await coordinator.alert_monitor.resolve_alert(alert_id, notes=notes)

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
        vol.Optional("growspace_id"): str,
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
    - ``growspace_id`` *(optional)*: growspace to fetch the briefing for
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


# ---------------------------------------------------------------------------
# get_ai_status
# ---------------------------------------------------------------------------

WS_TYPE_GET_AI_STATUS = f"{DOMAIN}/get_ai_status"
SCHEMA_WS_GET_AI_STATUS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {vol.Required("type"): WS_TYPE_GET_AI_STATUS}
)


async def websocket_get_ai_status(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the component-level AI enabled flag.

    Response: ``{ "ai_enabled": bool }``
    """
    coordinator = _get_coordinator(hass, connection)
    if coordinator is None:
        connection.send_error(
            msg["id"], "not_found", "Growspace Manager integration not loaded"
        )
        return

    ai_enabled: bool = coordinator.options.get("ai_settings", {}).get("ai_enabled", False)
    connection.send_result(msg["id"], {"ai_enabled": bool(ai_enabled)})


# ---------------------------------------------------------------------------
# get_ai_settings
# ---------------------------------------------------------------------------

WS_TYPE_GET_AI_SETTINGS = f"{DOMAIN}/get_ai_settings"
SCHEMA_WS_GET_AI_SETTINGS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {vol.Required("type"): WS_TYPE_GET_AI_SETTINGS}
)


async def websocket_get_ai_settings(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the full ai_settings dict from the config entry options.

    Response: the ``ai_settings`` dict, or ``{}`` when not yet configured.
    """
    coordinator = _get_coordinator(hass, connection)
    if coordinator is None:
        connection.send_error(
            msg["id"], "not_found", "Growspace Manager integration not loaded"
        )
        return

    ai_settings: dict[str, Any] = coordinator.options.get("ai_settings", {})
    connection.send_result(msg["id"], dict(ai_settings))


# ---------------------------------------------------------------------------
# save_ai_agent
# ---------------------------------------------------------------------------

WS_TYPE_SAVE_AI_AGENT = f"{DOMAIN}/save_ai_agent"
SCHEMA_WS_SAVE_AI_AGENT = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_SAVE_AI_AGENT,
        vol.Required("agent_id"): str,
    }
)


async def websocket_save_ai_agent(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Persist a conversation agent selection and enable AI features.

    WebSocket message fields:
    - ``agent_id`` *(required)*: entity ID of the conversation agent to activate.

    Sets ``ai_settings.assistant_id`` and ``ai_settings.ai_enabled = True`` in
    the config entry options so the change survives restarts.
    """
    coordinator = _get_coordinator(hass, connection)
    if coordinator is None:
        connection.send_error(
            msg["id"], "not_found", "Growspace Manager integration not loaded"
        )
        return

    agent_id: str = msg["agent_id"]
    new_options = coordinator.config_entry.options.copy()
    ai_settings: dict[str, Any] = dict(new_options.get("ai_settings", {}))
    ai_settings["assistant_id"] = agent_id
    ai_settings["ai_enabled"] = True
    new_options["ai_settings"] = ai_settings

    if hasattr(coordinator, "options"):
        coordinator.options = new_options

    hass.config_entries.async_update_entry(coordinator.config_entry, options=new_options)
    await coordinator.async_commit()

    connection.send_result(msg["id"], {"success": True, "agent_id": agent_id})


# ---------------------------------------------------------------------------
# save_ai_settings
# ---------------------------------------------------------------------------

_AI_SETTINGS_KEYS = (
    "ai_enabled",
    "assistant_id",
    "notification_personality",
    "ai_auto_alerts",
    "max_response_length",
    "vision_checkup_enabled",
    "ai_task_entity_id",
    "briefing_interval_minutes",
    "briefing_trigger_entities",
)

WS_TYPE_SAVE_AI_SETTINGS = f"{DOMAIN}/save_ai_settings"
SCHEMA_WS_SAVE_AI_SETTINGS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_SAVE_AI_SETTINGS,
        vol.Optional("ai_enabled"): bool,
        vol.Optional("assistant_id"): vol.Any(str, None),
        vol.Optional("notification_personality"): str,
        vol.Optional("ai_auto_alerts"): bool,
        vol.Optional("max_response_length"): int,
        vol.Optional("vision_checkup_enabled"): bool,
        vol.Optional("ai_task_entity_id"): vol.Any(str, None),
        vol.Optional("briefing_interval_minutes"): int,
        vol.Optional("briefing_trigger_entities"): list,
    }
)


async def websocket_save_ai_settings(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Persist all user-facing AI settings from the Growmaster Settings Panel.

    Accepts the nine user-facing ``ai_settings`` fields (all except
    ``vision_debug_enabled``) and writes them atomically to the config entry.
    """
    coordinator = _get_coordinator(hass, connection)
    if coordinator is None:
        connection.send_error(
            msg["id"], "not_found", "Growspace Manager integration not loaded"
        )
        return

    new_options = coordinator.config_entry.options.copy()
    ai_settings: dict[str, Any] = {k: msg[k] for k in _AI_SETTINGS_KEYS if k in msg}
    new_options["ai_settings"] = ai_settings

    if hasattr(coordinator, "options"):
        coordinator.options = new_options

    hass.config_entries.async_update_entry(coordinator.config_entry, options=new_options)
    await coordinator.async_commit()

    connection.send_result(msg["id"], {"success": True})


COMMANDS: list[tuple[str, Any, Any, bool]] = [
    (WS_TYPE_START_CONVERSATION, websocket_start_conversation, SCHEMA_WS_START_CONVERSATION, False),
    (WS_TYPE_SEND_MESSAGE, websocket_send_message, SCHEMA_WS_SEND_MESSAGE, False),
    (WS_TYPE_GET_AI_ALERTS, websocket_get_ai_alerts, SCHEMA_WS_GET_AI_ALERTS, False),
    (WS_TYPE_RESOLVE_AI_ALERT, websocket_resolve_ai_alert, SCHEMA_WS_RESOLVE_AI_ALERT, False),
    (WS_TYPE_GET_BRIEFING, websocket_get_briefing, SCHEMA_WS_GET_BRIEFING, False),
    (WS_TYPE_GET_AI_STATUS, websocket_get_ai_status, SCHEMA_WS_GET_AI_STATUS, False),
    (WS_TYPE_GET_AI_SETTINGS, websocket_get_ai_settings, SCHEMA_WS_GET_AI_SETTINGS, False),
    (WS_TYPE_SAVE_AI_AGENT, websocket_save_ai_agent, SCHEMA_WS_SAVE_AI_AGENT, False),
    (WS_TYPE_SAVE_AI_SETTINGS, websocket_save_ai_settings, SCHEMA_WS_SAVE_AI_SETTINGS, False),
]
