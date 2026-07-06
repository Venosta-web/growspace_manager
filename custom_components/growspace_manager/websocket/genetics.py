"""Genetics and breeder management WebSocket handlers."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.strain_library import StrainLibrary
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from ._common import WSCommand

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


def websocket_get_genetics_data(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> Any:
    """Handle get genetics data command via WebSocket."""
    return coordinator.services.genetics.get_serialization_data()


async def websocket_update_breeder(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Handle updating breeder info across all strains."""
    strain_library: StrainLibrary = coordinator.services.config.strain_library
    count = await strain_library.update_breeder(
        original_name=msg["original_name"],
        new_name=msg["new_name"],
        logo=msg.get("logo"),
    )
    return {"updated": count}


async def websocket_delete_breeder(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Handle removing breeder association from all strains."""
    strain_library: StrainLibrary = coordinator.services.config.strain_library
    count = await strain_library.delete_breeder(
        breeder_name=msg["breeder_name"],
    )
    return {"deleted": count}


COMMANDS: list[WSCommand] = [
    WSCommand(
        WS_TYPE_GET_GENETICS_DATA,
        websocket_get_genetics_data,
        SCHEMA_WS_GET_GENETICS_DATA,
        sync=True,
    ),
    WSCommand(
        WS_TYPE_UPDATE_BREEDER,
        websocket_update_breeder,
        SCHEMA_WS_UPDATE_BREEDER,
        resolve="any",
    ),
    WSCommand(
        WS_TYPE_DELETE_BREEDER,
        websocket_delete_breeder,
        SCHEMA_WS_DELETE_BREEDER,
        resolve="any",
    ),
]
