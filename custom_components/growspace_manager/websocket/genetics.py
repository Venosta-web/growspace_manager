"""Genetics and breeder management WebSocket handlers."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError

from ..const import DOMAIN
from ..coordinator import GrowspaceCoordinator
from ..strain_library import StrainLibrary

_LOGGER = logging.getLogger(__name__)

WS_TYPE_GET_GENETICS_DATA = f"{DOMAIN}/get_genetics_data"
SCHEMA_WS_GET_GENETICS_DATA = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_GENETICS_DATA,
    }
)

WS_TYPE_UPDATE_BREEDER = f"{DOMAIN}/update_breeder"
SCHEMA_WS_UPDATE_BREEDER = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_UPDATE_BREEDER,
        vol.Required("original_name"): str,
        vol.Required("new_name"): str,
        vol.Optional("logo"): str,
    }
)

WS_TYPE_DELETE_BREEDER = f"{DOMAIN}/delete_breeder"
SCHEMA_WS_DELETE_BREEDER = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_DELETE_BREEDER,
        vol.Required("breeder_name"): str,
    }
)


@callback
def websocket_get_genetics_data(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Handle get genetics data command via WebSocket."""
    try:
        coordinator: GrowspaceCoordinator = GrowspaceCoordinator.get_for_service_call(
            hass, msg
        )
        connection.send_result(
            msg["id"],
            coordinator.genetics_manager.get_serialization_data(),
        )
    except Exception as err:
        _LOGGER.exception("Error handling websocket_get_genetics_data")
        connection.send_error(msg["id"], "unknown_error", str(err))


async def websocket_update_breeder(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Handle updating breeder info across all strains."""
    try:
        coordinator = GrowspaceCoordinator.get_any(hass)
        strain_library: StrainLibrary = coordinator.services.config.strain_library
        count = await strain_library.update_breeder(
            original_name=msg["original_name"],
            new_name=msg["new_name"],
            logo=msg.get("logo"),
        )
        connection.send_result(msg["id"], {"updated": count})
    except ServiceValidationError:
        connection.send_error(
            msg["id"], "not_loaded", "Growspace Manager strain library not loaded"
        )
    except Exception as err:
        _LOGGER.exception("Error handling websocket_update_breeder")
        connection.send_error(msg["id"], "unknown_error", str(err))


async def websocket_delete_breeder(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Handle removing breeder association from all strains."""
    try:
        coordinator = GrowspaceCoordinator.get_any(hass)
        strain_library: StrainLibrary = coordinator.services.config.strain_library

        count = await strain_library.delete_breeder(
            breeder_name=msg["breeder_name"],
        )
        connection.send_result(msg["id"], {"deleted": count})
    except ServiceValidationError:
        connection.send_error(
            msg["id"], "not_loaded", "Growspace Manager strain library not loaded"
        )
    except Exception as err:
        _LOGGER.exception("Error handling websocket_delete_breeder")
        connection.send_error(msg["id"], "unknown_error", str(err))


COMMANDS: list[tuple[str, Any, Any, bool]] = [
    (WS_TYPE_GET_GENETICS_DATA, websocket_get_genetics_data, SCHEMA_WS_GET_GENETICS_DATA, True),
    (WS_TYPE_UPDATE_BREEDER, websocket_update_breeder, SCHEMA_WS_UPDATE_BREEDER, False),
    (WS_TYPE_DELETE_BREEDER, websocket_delete_breeder, SCHEMA_WS_DELETE_BREEDER, False),
]
