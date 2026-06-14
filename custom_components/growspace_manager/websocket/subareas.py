"""Subarea CRUD WebSocket handlers."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from ._common import WSErrorMap, handle_ws_errors

_ERROR_MAP: WSErrorMap = (
    (ServiceValidationError, "invalid_args", False, None),
    (Exception, "unknown_error", False, None),
)

WS_TYPE_GET_SUBAREAS = f"{DOMAIN}/get_subareas"
SCHEMA_WS_GET_SUBAREAS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {vol.Required("type"): WS_TYPE_GET_SUBAREAS, vol.Required("growspace_id"): str}
)

WS_TYPE_ADD_SUBAREA = f"{DOMAIN}/add_subarea"
SCHEMA_WS_ADD_SUBAREA = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_ADD_SUBAREA,
        vol.Required("growspace_id"): str,
        vol.Required("name"): str,
    }
)

WS_TYPE_UPDATE_SUBAREA = f"{DOMAIN}/update_subarea"
SCHEMA_WS_UPDATE_SUBAREA = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_UPDATE_SUBAREA,
        vol.Required("growspace_id"): str,
        vol.Required("subarea_id"): str,
        vol.Required("environment_config"): dict,
    }
)

WS_TYPE_REMOVE_SUBAREA = f"{DOMAIN}/remove_subarea"
SCHEMA_WS_REMOVE_SUBAREA = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_REMOVE_SUBAREA,
        vol.Required("growspace_id"): str,
        vol.Required("subarea_id"): str,
    }
)


@handle_ws_errors(_ERROR_MAP)
async def websocket_get_subareas(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return all subareas for a growspace."""
    coordinator = GrowspaceCoordinator.get_for_service_call(hass, msg)
    subareas = coordinator.services.growspaces.get_subareas(msg["growspace_id"])
    connection.send_result(msg["id"], [asdict(s) for s in subareas])


@handle_ws_errors(_ERROR_MAP)
async def websocket_add_subarea(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Add a subarea to a growspace."""
    coordinator = GrowspaceCoordinator.get_for_service_call(hass, msg)
    subarea = await coordinator.services.growspaces.add_subarea(msg["growspace_id"], msg["name"])
    connection.send_result(msg["id"], asdict(subarea))


@handle_ws_errors(_ERROR_MAP)
async def websocket_update_subarea(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Update a subarea's environment config."""
    coordinator = GrowspaceCoordinator.get_for_service_call(hass, msg)
    subarea = await coordinator.services.growspaces.update_subarea(
        msg["growspace_id"], msg["subarea_id"], msg["environment_config"]
    )
    connection.send_result(msg["id"], asdict(subarea))


@handle_ws_errors(_ERROR_MAP)
async def websocket_remove_subarea(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Remove a subarea from a growspace."""
    coordinator = GrowspaceCoordinator.get_for_service_call(hass, msg)
    await coordinator.services.growspaces.remove_subarea(msg["growspace_id"], msg["subarea_id"])
    connection.send_result(msg["id"], {"success": True})


COMMANDS: list[tuple[str, Any, Any, bool]] = [
    (WS_TYPE_GET_SUBAREAS, websocket_get_subareas, SCHEMA_WS_GET_SUBAREAS, False),
    (WS_TYPE_ADD_SUBAREA, websocket_add_subarea, SCHEMA_WS_ADD_SUBAREA, False),
    (WS_TYPE_UPDATE_SUBAREA, websocket_update_subarea, SCHEMA_WS_UPDATE_SUBAREA, False),
    (WS_TYPE_REMOVE_SUBAREA, websocket_remove_subarea, SCHEMA_WS_REMOVE_SUBAREA, False),
]
