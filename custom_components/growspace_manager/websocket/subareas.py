"""Subarea CRUD WebSocket handlers."""

from __future__ import annotations

from dataclasses import asdict
import logging
from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

_LOGGER = logging.getLogger(__name__)

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
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return all subareas for a growspace."""
    try:
        coordinator = GrowspaceCoordinator.get_for_service_call(hass, msg)
        subareas = coordinator.services.growspaces.get_subareas(msg["growspace_id"])
        connection.send_result(msg["id"], [asdict(s) for s in subareas])
    except ServiceValidationError as err:
        connection.send_error(msg["id"], "invalid_args", str(err))
    except Exception as e:  # noqa: BLE001
        connection.send_error(msg["id"], "unknown_error", str(e))


async def websocket_add_subarea(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Add a subarea to a growspace."""
    try:
        coordinator = GrowspaceCoordinator.get_for_service_call(hass, msg)
        subarea = await coordinator.services.growspaces.add_subarea(msg["growspace_id"], msg["name"])
        connection.send_result(msg["id"], asdict(subarea))
    except ServiceValidationError as err:
        connection.send_error(msg["id"], "invalid_args", str(err))
    except Exception as e:  # noqa: BLE001
        connection.send_error(msg["id"], "unknown_error", str(e))


async def websocket_update_subarea(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Update a subarea's environment config."""
    try:
        coordinator = GrowspaceCoordinator.get_for_service_call(hass, msg)
        subarea = await coordinator.services.growspaces.update_subarea(
            msg["growspace_id"], msg["subarea_id"], msg["environment_config"]
        )
        connection.send_result(msg["id"], asdict(subarea))
    except ServiceValidationError as err:
        connection.send_error(msg["id"], "invalid_args", str(err))
    except Exception as e:  # noqa: BLE001
        connection.send_error(msg["id"], "unknown_error", str(e))


async def websocket_remove_subarea(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Remove a subarea from a growspace."""
    try:
        coordinator = GrowspaceCoordinator.get_for_service_call(hass, msg)
        await coordinator.services.growspaces.remove_subarea(msg["growspace_id"], msg["subarea_id"])
        connection.send_result(msg["id"], {"success": True})
    except ServiceValidationError as err:
        connection.send_error(msg["id"], "invalid_args", str(err))
    except Exception as e:  # noqa: BLE001
        connection.send_error(msg["id"], "unknown_error", str(e))


COMMANDS: list[tuple[str, Any, Any, bool]] = [
    (WS_TYPE_GET_SUBAREAS, websocket_get_subareas, SCHEMA_WS_GET_SUBAREAS, False),
    (WS_TYPE_ADD_SUBAREA, websocket_add_subarea, SCHEMA_WS_ADD_SUBAREA, False),
    (WS_TYPE_UPDATE_SUBAREA, websocket_update_subarea, SCHEMA_WS_UPDATE_SUBAREA, False),
    (WS_TYPE_REMOVE_SUBAREA, websocket_remove_subarea, SCHEMA_WS_REMOVE_SUBAREA, False),
]
