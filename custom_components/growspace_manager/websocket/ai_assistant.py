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

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.exceptions import (
    CoordinatorNotReadyError,
    EntityNotFoundError,
    GrowspaceError,
    RateLimitedError,
)
from custom_components.growspace_manager.models import GrowspaceType
from custom_components.growspace_manager.utils import (
    calculate_days_since,
    days_to_week,
    strip_markdown_fence,
)
from homeassistant.components import conversation, websocket_api
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from ._common import WSCommand

_LOGGER = logging.getLogger(__name__)

# Matches [ACTION]...[/ACTION] — non-greedy, allows multi-line content
_ACTION_RE = re.compile(r"\[ACTION\](.*?)\[/ACTION\]", re.DOTALL)

_VALID_IMAGE_DOMAINS = {"camera", "image"}

_RATE_LIMIT_MARKERS = (
    "429",
    "Too Many Requests",
    "RESOURCE_EXHAUSTED",
    "resource_exhausted",
)
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


def _validate_image_entities(image_entities: list[str]) -> None:
    """Validate that all image entity IDs belong to camera or image domains."""
    for entity_id in image_entities:
        domain = entity_id.split(".", 1)[0]
        if domain not in _VALID_IMAGE_DOMAINS:
            raise ServiceValidationError(
                f"Entity '{entity_id}' is not in the camera or image domain"
            )


def _extract_action(text: str) -> tuple[str, dict[str, Any] | None]:
    """Extract and parse an [ACTION]...[/ACTION] block from *text*.

    Returns ``(display_text, action_dict)``.  If no block is found, or if the
    JSON inside the block is malformed, ``action_dict`` is ``None`` and the
    original text is returned unchanged.
    """
    match = _ACTION_RE.search(text)
    if not match:
        return text, None
    raw_json = strip_markdown_fence(match.group(1).strip())
    try:
        action = json.loads(raw_json)
    except json.JSONDecodeError, ValueError:
        # Malformed block — return the full text without modification
        return text, None
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
        (
            "Temperature",
            env.temperature_sensors
            or ([env.temperature_sensor] if env.temperature_sensor else []),
        ),
        (
            "Humidity",
            env.humidity_sensors
            or ([env.humidity_sensor] if env.humidity_sensor else []),
        ),
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
        plants = coordinator.services.growspaces.get_growspace_plants(growspace_id)
        if plants:
            max_flower = max(
                (
                    calculate_days_since(p.flower_start)
                    for p in plants
                    if p.flower_start
                ),
                default=-1,
            )
            max_veg = max(
                (calculate_days_since(p.veg_start) for p in plants if p.veg_start),
                default=-1,
            )
            max_seedling = max(
                (
                    calculate_days_since(p.seedling_start)
                    for p in plants
                    if p.seedling_start
                ),
                default=-1,
            )
            max_clone = max(
                (calculate_days_since(p.clone_start) for p in plants if p.clone_start),
                default=-1,
            )
            if max_flower >= 0:
                stage_line = f"Stage: flower | Day {max_flower} | Week {days_to_week(max_flower)}"
            elif max_veg >= 0:
                stage_line = (
                    f"Stage: veg | Day {max_veg} | Week {days_to_week(max_veg)}"
                )
            elif max_seedling >= 0:
                stage_line = f"Stage: seedling | Day {max_seedling} | Week {days_to_week(max_seedling)}"
            elif max_clone >= 0:
                stage_line = (
                    f"Stage: clone | Day {max_clone} | Week {days_to_week(max_clone)}"
                )

    lines: list[str] = [
        f"[Growspace: {growspace.name} | Type: {growspace.growspace_type.value}]"
    ]
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


async def _converse_or_raise(
    hass: HomeAssistant,
    message: str,
    agent_id: str | None,
    conversation_id: str | None,
) -> tuple[str, str]:
    """Run a conversation turn, raising typed errors for the lifecycle map.

    Returns ``(speech, conversation_id)``.
    """
    try:
        result = await _run_conversation(hass, message, agent_id, conversation_id)
    except Exception as err:
        _LOGGER.error("AI conversation failed: %s", err)
        if _is_rate_limited_error(err):
            raise RateLimitedError(_RATE_LIMIT_MESSAGE) from err
        raise GrowspaceError(str(err)) from err

    if _is_rate_limited_result(result):
        _LOGGER.warning("AI rate limit reached")
        raise RateLimitedError(_RATE_LIMIT_MESSAGE)

    speech = _extract_speech(result)
    if speech is None:
        raise GrowspaceError("AI assistant returned an empty response")
    return speech, result.conversation_id


async def websocket_start_conversation(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Handle the start_conversation WebSocket command.

    Begins a brand-new AI conversation (conversation_id=None) and returns
    the server-assigned conversation_id together with the response text.
    """
    growspace_id: str = msg["growspace_id"]
    message: str = msg["message"]
    agent_id: str | None = msg.get("agent_id")
    if agent_id is None:
        agent_id = coordinator.options.get("ai_settings", {}).get("assistant_id")

    _validate_image_entities(msg.get("image_entities") or [])
    message = _build_context_message(hass, coordinator, growspace_id, message)

    speech, thread_id = await _converse_or_raise(
        hass, message, agent_id, conversation_id=None
    )

    display_text, action = _extract_action(speech)
    ai_message: dict[str, Any] = {
        "role": "ai",
        "text": display_text,
        "timestamp": int(time.time() * 1000),
    }
    if action is not None:
        ai_message["suggestedAction"] = action

    return {
        "thread_id": thread_id,
        "growspace_id": growspace_id,
        "messages": [ai_message],
    }


async def websocket_send_message(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Handle the send_message WebSocket command.

    Continues an existing AI conversation identified by *conversation_id*.
    """
    conversation_id: str = msg["conversation_id"]
    growspace_id: str = msg["growspace_id"]
    message: str = msg["message"]

    _validate_image_entities(msg.get("image_entities") or [])

    agent_id = coordinator.options.get("ai_settings", {}).get("assistant_id")
    message = _build_context_message(hass, coordinator, growspace_id, message)

    speech, _ = await _converse_or_raise(
        hass, message, agent_id=agent_id, conversation_id=conversation_id
    )

    display_text, action = _extract_action(speech)
    ai_message: dict[str, Any] = {
        "role": "ai",
        "text": display_text,
        "timestamp": int(time.time() * 1000),
    }
    if action is not None:
        ai_message["suggestedAction"] = action

    return {
        "thread_id": conversation_id,
        "growspace_id": growspace_id,
        "messages": [ai_message],
    }


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
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> Any:
    """Return AI alert records, optionally filtered by growspace or type.

    WebSocket message fields:
    - ``growspace_id`` *(optional)*: filter to a specific growspace
    - ``alert_type`` *(optional)*: ``"stress"`` or ``"mold"``
    """
    return coordinator.services.notifications.get_alerts(
        growspace_id=msg.get("growspace_id"),
        alert_type=msg.get("alert_type"),
    )


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
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> Any:
    """Mark an AI alert as resolved.

    WebSocket message fields:
    - ``alert_id`` *(required)*: UUID of the alert to resolve
    - ``resolution_note`` *(optional)*: resolution notes to attach
    """
    alert_id: str = msg["alert_id"]
    notes: str | None = msg.get("resolution_note")
    resolved = await coordinator.services.notifications.resolve_alert(
        alert_id, notes=notes
    )

    if not resolved:
        raise EntityNotFoundError(f"Alert '{alert_id}' not found")

    return {"success": True, "alert_id": alert_id}


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
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> Any:
    """Return the latest AI briefing, optionally regenerating it.

    WebSocket message fields:
    - ``growspace_id`` *(optional)*: growspace to fetch the briefing for
    - ``force_refresh`` *(optional, default False)*: when ``True`` bypass the
      cache and generate a fresh briefing immediately.
    """
    briefing_scheduler = getattr(coordinator, "briefing_scheduler", None)
    if briefing_scheduler is None:
        raise CoordinatorNotReadyError("Briefing scheduler not available")

    force_refresh: bool = msg.get("force_refresh", False)
    return await briefing_scheduler.async_get_briefing(force_refresh=force_refresh)


# ---------------------------------------------------------------------------
# get_ai_status
# ---------------------------------------------------------------------------

WS_TYPE_GET_AI_STATUS = f"{DOMAIN}/get_ai_status"
SCHEMA_WS_GET_AI_STATUS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {vol.Required("type"): WS_TYPE_GET_AI_STATUS}
)


async def websocket_get_ai_status(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> Any:
    """Return the component-level AI enabled flag.

    Response: ``{ "ai_enabled": bool }``
    """
    ai_enabled: bool = coordinator.options.get("ai_settings", {}).get(
        "ai_enabled", False
    )
    return {"ai_enabled": bool(ai_enabled)}


# ---------------------------------------------------------------------------
# get_ai_settings
# ---------------------------------------------------------------------------

WS_TYPE_GET_AI_SETTINGS = f"{DOMAIN}/get_ai_settings"
SCHEMA_WS_GET_AI_SETTINGS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {vol.Required("type"): WS_TYPE_GET_AI_SETTINGS}
)


async def websocket_get_ai_settings(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> Any:
    """Return the full ai_settings dict from the config entry options.

    Response: the ``ai_settings`` dict, or ``{}`` when not yet configured.
    """
    ai_settings: dict[str, Any] = coordinator.options.get("ai_settings", {})
    return dict(ai_settings)


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
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> Any:
    """Persist a conversation agent selection and enable AI features.

    WebSocket message fields:
    - ``agent_id`` *(required)*: entity ID of the conversation agent to activate.

    Sets ``ai_settings.assistant_id`` and ``ai_settings.ai_enabled = True`` in
    the config entry options so the change survives restarts.
    """
    agent_id: str = msg["agent_id"]
    new_options = coordinator.config_entry.options.copy()
    ai_settings: dict[str, Any] = dict(new_options.get("ai_settings", {}))
    ai_settings["assistant_id"] = agent_id
    ai_settings["ai_enabled"] = True
    new_options["ai_settings"] = ai_settings

    if hasattr(coordinator, "options"):
        coordinator.options = new_options

    hass.config_entries.async_update_entry(
        coordinator.config_entry, options=new_options
    )
    await coordinator.async_commit()

    return {"success": True, "agent_id": agent_id}


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
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> Any:
    """Persist all user-facing AI settings from the Growmaster Settings Panel.

    Accepts the nine user-facing ``ai_settings`` fields (all except
    ``vision_debug_enabled``) and writes them atomically to the config entry.
    """
    new_options = coordinator.config_entry.options.copy()
    existing_settings = dict(new_options.get("ai_settings", {}))
    ai_settings: dict[str, Any] = {
        **existing_settings,
        **{k: msg[k] for k in _AI_SETTINGS_KEYS if k in msg},
    }
    new_options["ai_settings"] = ai_settings

    if hasattr(coordinator, "options"):
        coordinator.options = new_options

    hass.config_entries.async_update_entry(
        coordinator.config_entry, options=new_options
    )
    await coordinator.async_commit()

    return {"success": True}


# ---------------------------------------------------------------------------
# get_conversation_threads
# ---------------------------------------------------------------------------

WS_TYPE_GET_CONVERSATION_THREADS = f"{DOMAIN}/get_conversation_threads"
SCHEMA_WS_GET_CONVERSATION_THREADS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_CONVERSATION_THREADS,
        vol.Required("growspace_id"): str,
    }
)


async def websocket_get_conversation_threads(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> Any:
    """Return persisted conversation threads for a growspace.

    WebSocket message fields:
    - ``growspace_id`` *(required)*: the growspace to fetch threads for.

    Response: list of thread objects (may be empty).
    """
    return coordinator.conversation_store.get_threads(msg["growspace_id"])


# ---------------------------------------------------------------------------
# save_conversation_threads
# ---------------------------------------------------------------------------

WS_TYPE_SAVE_CONVERSATION_THREADS = f"{DOMAIN}/save_conversation_threads"
SCHEMA_WS_SAVE_CONVERSATION_THREADS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_SAVE_CONVERSATION_THREADS,
        vol.Required("growspace_id"): str,
        vol.Required("threads"): list,
    }
)


async def websocket_save_conversation_threads(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> Any:
    """Persist the frontend-managed conversation thread list for a growspace.

    The frontend enforces MAX_PINNED_THREADS / MAX_RECENT_THREADS eviction
    before calling this command. The backend stores whatever it receives.

    WebSocket message fields:
    - ``growspace_id`` *(required)*: growspace these threads belong to.
    - ``threads`` *(required)*: full replacement list of thread objects.

    Response: ``{ "success": True }``
    """
    await coordinator.conversation_store.save_threads(
        msg["growspace_id"], msg["threads"]
    )
    return {"success": True}


COMMANDS: list[WSCommand] = [
    WSCommand(
        WS_TYPE_START_CONVERSATION,
        websocket_start_conversation,
        SCHEMA_WS_START_CONVERSATION,
        resolve="any",
    ),
    WSCommand(
        WS_TYPE_SEND_MESSAGE,
        websocket_send_message,
        SCHEMA_WS_SEND_MESSAGE,
        resolve="any",
    ),
    WSCommand(
        WS_TYPE_GET_AI_ALERTS,
        websocket_get_ai_alerts,
        SCHEMA_WS_GET_AI_ALERTS,
        resolve="any",
    ),
    WSCommand(
        WS_TYPE_RESOLVE_AI_ALERT,
        websocket_resolve_ai_alert,
        SCHEMA_WS_RESOLVE_AI_ALERT,
        resolve="any",
    ),
    WSCommand(
        WS_TYPE_GET_BRIEFING,
        websocket_get_briefing,
        SCHEMA_WS_GET_BRIEFING,
        resolve="any",
    ),
    WSCommand(
        WS_TYPE_GET_AI_STATUS,
        websocket_get_ai_status,
        SCHEMA_WS_GET_AI_STATUS,
        resolve="any",
    ),
    WSCommand(
        WS_TYPE_GET_AI_SETTINGS,
        websocket_get_ai_settings,
        SCHEMA_WS_GET_AI_SETTINGS,
        resolve="any",
    ),
    WSCommand(
        WS_TYPE_SAVE_AI_AGENT,
        websocket_save_ai_agent,
        SCHEMA_WS_SAVE_AI_AGENT,
        resolve="any",
    ),
    WSCommand(
        WS_TYPE_SAVE_AI_SETTINGS,
        websocket_save_ai_settings,
        SCHEMA_WS_SAVE_AI_SETTINGS,
        resolve="any",
    ),
    WSCommand(
        WS_TYPE_GET_CONVERSATION_THREADS,
        websocket_get_conversation_threads,
        SCHEMA_WS_GET_CONVERSATION_THREADS,
        resolve="any",
    ),
    WSCommand(
        WS_TYPE_SAVE_CONVERSATION_THREADS,
        websocket_save_conversation_threads,
        SCHEMA_WS_SAVE_CONVERSATION_THREADS,
        resolve="any",
    ),
]
