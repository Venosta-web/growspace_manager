"""Core data retrieval WebSocket handlers."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.services.report import (
    async_websocket_get_grow_report,
)
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from ._common import WSCommand

_LOGGER = logging.getLogger(__name__)

WS_TYPE_GET_DATA = f"{DOMAIN}/get_data"
SCHEMA_WS_GET_DATA = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_DATA,
        vol.Optional("growspace_id"): str,
    }
)

WS_TYPE_GET_GROW_REPORT = f"{DOMAIN}/get_grow_report"
SCHEMA_WS_GET_GROW_REPORT = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_GROW_REPORT,
        vol.Optional("growspace_id"): str,
        vol.Optional("plant_id"): str,
        vol.Optional("include_history", default=True): bool,
    }
)


async def websocket_get_growspace_data(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> Any:
    """Handle get growspace data command."""
    return coordinator.services.growspaces.get_growspace_data(msg.get("growspace_id"))


COMMANDS: list[WSCommand] = [
    WSCommand(WS_TYPE_GET_DATA, websocket_get_growspace_data, SCHEMA_WS_GET_DATA),
    WSCommand(
        WS_TYPE_GET_GROW_REPORT,
        async_websocket_get_grow_report,
        SCHEMA_WS_GET_GROW_REPORT,
    ),
]
