"""Lineage tree WebSocket handlers."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.exceptions import (
    CoordinatorNotReadyError,
    PlantNotFoundError,
)
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from ._common import WSCommand

_LOGGER = logging.getLogger(__name__)

WS_TYPE_GET_LINEAGE_TREE = f"{DOMAIN}/get_lineage_tree"
SCHEMA_WS_GET_LINEAGE_TREE = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_LINEAGE_TREE,
        vol.Required("plant_id"): str,
    }
)

WS_TYPE_GET_STRAIN_LINEAGE_TREE = f"{DOMAIN}/get_strain_lineage_tree"
SCHEMA_WS_GET_STRAIN_LINEAGE_TREE = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_STRAIN_LINEAGE_TREE,
        vol.Required("strain_name"): str,
    }
)

WS_TYPE_UPDATE_STRAIN_LINEAGE_TREE = f"{DOMAIN}/update_strain_lineage_tree"
SCHEMA_WS_UPDATE_STRAIN_LINEAGE_TREE = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_UPDATE_STRAIN_LINEAGE_TREE,
        vol.Required("strain_name"): str,
        vol.Required("parents"): [
            {
                vol.Required("name"): str,
                vol.Required("source"): vol.In(["library", "manual"]),
                vol.Optional("phenotype"): str,
            }
        ],
    }
)

WS_TYPE_IMPORT_STRAIN_LINEAGE_TREE = f"{DOMAIN}/import_strain_lineage_tree"
SCHEMA_WS_IMPORT_STRAIN_LINEAGE_TREE = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_IMPORT_STRAIN_LINEAGE_TREE,
        vol.Required("strain_name"): str,
        vol.Required("tree"): dict,
    }
)


async def websocket_get_lineage_tree(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Handle get lineage tree command."""
    plant_id = msg["plant_id"]
    if plant_id not in coordinator.plants:
        raise PlantNotFoundError(f"Plant {plant_id} not found")

    tree = coordinator.services.genetics.get_lineage_tree(plant_id)

    if not tree.get("parents") and (
        strain_library := coordinator.services.config.strain_library
    ):
        plant = coordinator.plants.get(plant_id)
        strain_name = plant.genetics.strain_name if plant else None
        if strain_name:
            strain_tree = strain_library.get_strain_lineage_tree(strain_name)
            if strain_tree.get("parents"):
                tree["parents"] = strain_tree["parents"]

    return tree


async def websocket_get_strain_lineage_tree(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Handle get_strain_lineage_tree command."""
    strain_library = coordinator.services.config.strain_library
    if strain_library is None:
        raise CoordinatorNotReadyError("Strain library not initialized")
    return strain_library.get_strain_lineage_tree(msg["strain_name"])


async def websocket_update_strain_lineage_tree(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Handle update_strain_lineage_tree command."""
    strain_library = coordinator.services.config.strain_library
    if strain_library is None:
        raise CoordinatorNotReadyError("Strain library not initialized")
    flat_lineage = await strain_library.update_strain_lineage_tree(
        msg["strain_name"], msg["parents"]
    )
    return {"lineage": flat_lineage}


async def websocket_import_strain_lineage_tree(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Import a full seedfinder lineage tree, creating ancestor stubs as needed."""
    strain_library = coordinator.services.config.strain_library
    if strain_library is None:
        raise CoordinatorNotReadyError("Strain library not initialized")
    await strain_library.async_import_seedfinder_lineage_tree(
        msg["strain_name"], msg["tree"], scraper=coordinator.seedfinder_scraper
    )
    return {"ok": True}


COMMANDS: list[WSCommand] = [
    WSCommand(
        WS_TYPE_GET_LINEAGE_TREE, websocket_get_lineage_tree, SCHEMA_WS_GET_LINEAGE_TREE
    ),
    WSCommand(
        WS_TYPE_GET_STRAIN_LINEAGE_TREE,
        websocket_get_strain_lineage_tree,
        SCHEMA_WS_GET_STRAIN_LINEAGE_TREE,
        resolve="any",
    ),
    WSCommand(
        WS_TYPE_UPDATE_STRAIN_LINEAGE_TREE,
        websocket_update_strain_lineage_tree,
        SCHEMA_WS_UPDATE_STRAIN_LINEAGE_TREE,
        resolve="any",
    ),
    WSCommand(
        WS_TYPE_IMPORT_STRAIN_LINEAGE_TREE,
        websocket_import_strain_lineage_tree,
        SCHEMA_WS_IMPORT_STRAIN_LINEAGE_TREE,
        resolve="any",
    ),
]
