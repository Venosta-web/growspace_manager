"""Subarea CRUD WebSocket handlers."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from ._common import WSCommand

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


async def websocket_get_subareas(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return all subareas for a growspace."""
    subareas = coordinator.services.growspaces.get_subareas(msg["growspace_id"])
    return [asdict(s) for s in subareas]


async def websocket_add_subarea(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Add a subarea to a growspace."""
    subarea = await coordinator.services.growspaces.add_subarea(
        msg["growspace_id"], msg["name"]
    )
    return asdict(subarea)


async def websocket_update_subarea(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Update a subarea's environment config."""
    subarea = await coordinator.services.growspaces.update_subarea(
        msg["growspace_id"], msg["subarea_id"], msg["environment_config"]
    )
    return asdict(subarea)


async def websocket_remove_subarea(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Remove a subarea from a growspace."""
    await coordinator.services.growspaces.remove_subarea(
        msg["growspace_id"], msg["subarea_id"]
    )
    return {"success": True}


COMMANDS: list[WSCommand] = [
    WSCommand(WS_TYPE_GET_SUBAREAS, websocket_get_subareas, SCHEMA_WS_GET_SUBAREAS),
    WSCommand(WS_TYPE_ADD_SUBAREA, websocket_add_subarea, SCHEMA_WS_ADD_SUBAREA),
    WSCommand(
        WS_TYPE_UPDATE_SUBAREA, websocket_update_subarea, SCHEMA_WS_UPDATE_SUBAREA
    ),
    WSCommand(
        WS_TYPE_REMOVE_SUBAREA, websocket_remove_subarea, SCHEMA_WS_REMOVE_SUBAREA
    ),
]
