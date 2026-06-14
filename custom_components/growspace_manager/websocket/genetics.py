"""Genetics and breeder management WebSocket handlers."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.strain_library import StrainLibrary
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError

from ._common import WSErrorMap, handle_ws_errors, handle_ws_errors_sync

_GET_ERROR_MAP: WSErrorMap = ((Exception, "unknown_error", True, None),)

_BREEDER_ERROR_MAP: WSErrorMap = (
    (ServiceValidationError, "not_loaded", False, "Growspace Manager strain library not loaded"),
    (Exception, "unknown_error", True, None),
)

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
@handle_ws_errors_sync(_GET_ERROR_MAP)
def websocket_get_genetics_data(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Handle get genetics data command via WebSocket."""
    coordinator: GrowspaceCoordinator = GrowspaceCoordinator.get_for_service_call(hass, msg)
    connection.send_result(
        msg["id"],
        coordinator.services.genetics.get_serialization_data(),
    )


@handle_ws_errors(_BREEDER_ERROR_MAP)
async def websocket_update_breeder(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Handle updating breeder info across all strains."""
    coordinator = GrowspaceCoordinator.get_any(hass)
    strain_library: StrainLibrary = coordinator.services.config.strain_library
    count = await strain_library.update_breeder(
        original_name=msg["original_name"],
        new_name=msg["new_name"],
        logo=msg.get("logo"),
    )
    connection.send_result(msg["id"], {"updated": count})


@handle_ws_errors(_BREEDER_ERROR_MAP)
async def websocket_delete_breeder(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Handle removing breeder association from all strains."""
    coordinator = GrowspaceCoordinator.get_any(hass)
    strain_library: StrainLibrary = coordinator.services.config.strain_library
    count = await strain_library.delete_breeder(
        breeder_name=msg["breeder_name"],
    )
    connection.send_result(msg["id"], {"deleted": count})


COMMANDS: list[tuple[str, Any, Any, bool]] = [
    (WS_TYPE_GET_GENETICS_DATA, websocket_get_genetics_data, SCHEMA_WS_GET_GENETICS_DATA, True),
    (WS_TYPE_UPDATE_BREEDER, websocket_update_breeder, SCHEMA_WS_UPDATE_BREEDER, False),
    (WS_TYPE_DELETE_BREEDER, websocket_delete_breeder, SCHEMA_WS_DELETE_BREEDER, False),
]
