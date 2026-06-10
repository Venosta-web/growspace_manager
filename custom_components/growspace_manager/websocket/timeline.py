"""Timeline and notes WebSocket handlers."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import (
    ATTR_AMOUNT_ML,
    ATTR_EC,
    ATTR_GROWSPACE_ID,
    ATTR_IMAGES,
    ATTR_METADATA,
    ATTR_NOTES,
    ATTR_PH,
    ATTR_PLANT_ID,
    ATTR_TAGS,
    ATTR_TRANSITION_DATE,
    DOMAIN,
)
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from homeassistant.components import websocket_api
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.db_schema import Events
from homeassistant.components.recorder.util import session_scope
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

_LOGGER = logging.getLogger(__name__)

WS_TYPE_ADD_TIMELINE_NOTE = f"{DOMAIN}/add_timeline_note"
SCHEMA_WS_ADD_TIMELINE_NOTE = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_ADD_TIMELINE_NOTE,
        vol.Required(ATTR_PLANT_ID): str,
        vol.Required(ATTR_NOTES): str,
        vol.Optional(ATTR_TRANSITION_DATE): vol.Any(str, None),
        vol.Optional(ATTR_IMAGES): [str],
        vol.Optional(ATTR_TAGS): [str],
        vol.Optional(ATTR_PH): vol.Any(float, int),
        vol.Optional(ATTR_EC): vol.Any(float, int),
        vol.Optional(ATTR_AMOUNT_ML): vol.Any(float, int),
        vol.Optional(ATTR_METADATA): dict,
    }
)

WS_TYPE_ADD_GROWSPACE_NOTE = f"{DOMAIN}/add_growspace_note"
SCHEMA_WS_ADD_GROWSPACE_NOTE = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_ADD_GROWSPACE_NOTE,
        vol.Required(ATTR_GROWSPACE_ID): str,
        vol.Required(ATTR_NOTES): str,
        vol.Optional(ATTR_IMAGES): [str],
    }
)

WS_TYPE_REMOVE_TIMELINE_EVENT = f"{DOMAIN}/remove_timeline_event"
SCHEMA_WS_REMOVE_TIMELINE_EVENT = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_REMOVE_TIMELINE_EVENT,
        vol.Required("event_id"): int,
    }
)


async def websocket_add_timeline_note(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle add timeline note command via WebSocket."""
    try:
        coordinator = GrowspaceCoordinator.get_for_service_call(hass, msg)

        await coordinator.services.add_timeline_note(
            plant_id=msg[ATTR_PLANT_ID],
            notes=msg[ATTR_NOTES],
            timestamp=msg.get(ATTR_TRANSITION_DATE),
            images_base64=msg.get(ATTR_IMAGES),
            tags=msg.get(ATTR_TAGS),
            ph=msg.get(ATTR_PH),
            ec=msg.get(ATTR_EC),
            amount_ml=msg.get(ATTR_AMOUNT_ML),
            external_metadata=msg.get(ATTR_METADATA),
        )
        connection.send_result(msg["id"])
    except ServiceValidationError as err:
        connection.send_error(msg["id"], "invalid_args", str(err))
    except Exception as err:
        _LOGGER.exception("Error handling websocket_add_timeline_note")
        connection.send_error(msg["id"], "unknown_error", str(err))


async def websocket_add_growspace_note(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle add growspace note command via WebSocket."""
    try:
        coordinator = GrowspaceCoordinator.get_for_service_call(hass, msg)

        await coordinator.services.growspaces.add_growspace_note(
            hass=hass,
            growspace_id=msg[ATTR_GROWSPACE_ID],
            notes=msg[ATTR_NOTES],
            images_base64=msg.get(ATTR_IMAGES),
        )
        connection.send_result(msg["id"])
    except ServiceValidationError as err:
        connection.send_error(msg["id"], "invalid_args", str(err))
    except Exception as err:
        _LOGGER.exception("Error handling websocket_add_growspace_note")
        connection.send_error(msg["id"], "unknown_error", str(err))


async def websocket_remove_timeline_event(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle remove timeline event command via WebSocket."""
    event_id = msg["event_id"]
    try:
        recorder = get_instance(hass)

        def _delete_event() -> None:
            with session_scope(hass=hass) as session:
                session.query(Events).filter(Events.event_id == event_id).delete(
                    synchronize_session=False
                )

        await recorder.async_add_executor_job(_delete_event)
        connection.send_result(msg["id"])

    except Exception as err:
        _LOGGER.exception("Error handling websocket_remove_timeline_event")
        connection.send_error(msg["id"], "unknown_error", str(err))


COMMANDS: list[tuple[str, Any, Any, bool]] = [
    (
        WS_TYPE_ADD_TIMELINE_NOTE,
        websocket_add_timeline_note,
        SCHEMA_WS_ADD_TIMELINE_NOTE,
        False,
    ),
    (
        WS_TYPE_ADD_GROWSPACE_NOTE,
        websocket_add_growspace_note,
        SCHEMA_WS_ADD_GROWSPACE_NOTE,
        False,
    ),
    (
        WS_TYPE_REMOVE_TIMELINE_EVENT,
        websocket_remove_timeline_event,
        SCHEMA_WS_REMOVE_TIMELINE_EVENT,
        False,
    ),
]
