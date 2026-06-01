"""Lineage tree WebSocket handlers."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.exceptions import GrowspaceError
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

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
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle get lineage tree command."""
    plant_id = msg["plant_id"]
    try:
        coordinator = GrowspaceCoordinator.get_for_service_call(hass, msg)
    except ServiceValidationError as err:
        connection.send_error(msg["id"], "invalid_args", str(err))
        return
    except Exception as e:  # noqa: BLE001
        connection.send_error(msg["id"], "unknown_error", str(e))
        return

    if plant_id not in coordinator.plants:
        connection.send_error(msg["id"], "invalid_args", f"Plant {plant_id} not found")
        return

    try:
        tree = coordinator.services.genetics.get_lineage_tree(plant_id)

        if not tree.get("parents") and (strain_library := coordinator.services.config.strain_library):
            plant = coordinator.plants.get(plant_id)
            strain_name = plant.genetics.strain_name if plant else None
            if strain_name:
                strain_tree = strain_library.get_strain_lineage_tree(strain_name)
                if strain_tree.get("parents"):
                    tree["parents"] = strain_tree["parents"]

        connection.send_result(msg["id"], tree)
    except (
        AttributeError,
        KeyError,
        ValueError,
        ServiceValidationError,
        GrowspaceError,
        Exception,  # noqa: BLE001
    ) as e:
        connection.send_error(msg["id"], "unknown_error", str(e))


async def websocket_get_strain_lineage_tree(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle get_strain_lineage_tree command."""
    strain_name = msg["strain_name"]
    try:
        coordinator = GrowspaceCoordinator.get_any(hass)
        strain_library = coordinator.services.config.strain_library
        tree = strain_library.get_strain_lineage_tree(strain_name)
        connection.send_result(msg["id"], tree)
    except ServiceValidationError:
        connection.send_error(msg["id"], "not_loaded", "Strain library not loaded")
    except Exception as e:  # noqa: BLE001
        connection.send_error(msg["id"], "unknown_error", str(e))


async def websocket_update_strain_lineage_tree(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle update_strain_lineage_tree command."""
    strain_name = msg["strain_name"]
    parents = msg["parents"]
    try:
        coordinator = GrowspaceCoordinator.get_any(hass)
        strain_library = coordinator.services.config.strain_library
        flat_lineage = await strain_library.update_strain_lineage_tree(
            strain_name, parents
        )
        connection.send_result(msg["id"], {"lineage": flat_lineage})
    except ServiceValidationError:
        connection.send_error(msg["id"], "not_loaded", "Strain library not loaded")
    except Exception as e:  # noqa: BLE001
        connection.send_error(msg["id"], "unknown_error", str(e))


async def websocket_import_strain_lineage_tree(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Import a full seedfinder lineage tree, creating ancestor stubs as needed."""
    strain_name = msg["strain_name"]
    tree = msg["tree"]
    try:
        coordinator = GrowspaceCoordinator.get_any(hass)
        strain_library = coordinator.services.config.strain_library
        await strain_library.async_import_seedfinder_lineage_tree(
            strain_name, tree, scraper=coordinator.seedfinder_scraper
        )
        connection.send_result(msg["id"], {"ok": True})
    except ServiceValidationError:
        connection.send_error(msg["id"], "not_loaded", "Strain library not loaded")
    except Exception as e:  # noqa: BLE001
        connection.send_error(msg["id"], "unknown_error", str(e))


COMMANDS: list[tuple[str, Any, Any, bool]] = [
    (WS_TYPE_GET_LINEAGE_TREE, websocket_get_lineage_tree, SCHEMA_WS_GET_LINEAGE_TREE, False),
    (WS_TYPE_GET_STRAIN_LINEAGE_TREE, websocket_get_strain_lineage_tree, SCHEMA_WS_GET_STRAIN_LINEAGE_TREE, False),
    (WS_TYPE_UPDATE_STRAIN_LINEAGE_TREE, websocket_update_strain_lineage_tree, SCHEMA_WS_UPDATE_STRAIN_LINEAGE_TREE, False),
    (WS_TYPE_IMPORT_STRAIN_LINEAGE_TREE, websocket_import_strain_lineage_tree, SCHEMA_WS_IMPORT_STRAIN_LINEAGE_TREE, False),
]
