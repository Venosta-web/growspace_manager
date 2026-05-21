"""Core data retrieval WebSocket handlers."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from ..const import DOMAIN
from ..coordinator import GrowspaceCoordinator
from ..exceptions import GrowspaceError
from ..services.report import async_websocket_get_grow_report

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
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle get growspace data command."""
    growspace_id = msg.get("growspace_id")
    try:
        coordinator = GrowspaceCoordinator.get_for_service_call(hass, msg)
        data = coordinator.services.growspaces.get_growspace_data(growspace_id)
        connection.send_result(msg["id"], data)
    except ServiceValidationError:
        connection.send_error(
            msg["id"], "not_loaded", "Growspace Manager integration not loaded"
        )
    except (
        AttributeError,
        KeyError,
        ValueError,
        ServiceValidationError,
        GrowspaceError,
        Exception,
    ) as e:
        connection.send_error(msg["id"], "unknown_error", str(e))


COMMANDS: list[tuple[str, Any, Any, bool]] = [
    (WS_TYPE_GET_DATA, websocket_get_growspace_data, SCHEMA_WS_GET_DATA, False),
    (WS_TYPE_GET_GROW_REPORT, async_websocket_get_grow_report, SCHEMA_WS_GET_GROW_REPORT, False),
]
