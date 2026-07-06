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

from ._common import WSCommand

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
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> None:
    """Handle add timeline note command via WebSocket."""
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


async def websocket_add_growspace_note(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> None:
    """Handle add growspace note command via WebSocket."""
    await coordinator.services.growspaces.add_growspace_note(
        hass=hass,
        growspace_id=msg[ATTR_GROWSPACE_ID],
        notes=msg[ATTR_NOTES],
        images_base64=msg.get(ATTR_IMAGES),
    )


async def websocket_remove_timeline_event(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> None:
    """Handle remove timeline event command via WebSocket."""
    event_id = msg["event_id"]
    recorder = get_instance(hass)

    def _delete_event() -> None:
        with session_scope(hass=hass) as session:
            session.query(Events).filter(Events.event_id == event_id).delete(
                synchronize_session=False
            )

    await recorder.async_add_executor_job(_delete_event)


COMMANDS: list[WSCommand] = [
    WSCommand(
        WS_TYPE_ADD_TIMELINE_NOTE,
        websocket_add_timeline_note,
        SCHEMA_WS_ADD_TIMELINE_NOTE,
    ),
    WSCommand(
        WS_TYPE_ADD_GROWSPACE_NOTE,
        websocket_add_growspace_note,
        SCHEMA_WS_ADD_GROWSPACE_NOTE,
    ),
    WSCommand(
        WS_TYPE_REMOVE_TIMELINE_EVENT,
        websocket_remove_timeline_event,
        SCHEMA_WS_REMOVE_TIMELINE_EVENT,
        resolve="any",
    ),
]
