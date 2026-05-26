"""Nutrient and preset WebSocket handlers."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError

from ..const import DOMAIN
from ..coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)

WS_TYPE_GET_NUTRIENT_PRESETS = f"{DOMAIN}/get_nutrient_presets"
SCHEMA_WS_GET_NUTRIENT_PRESETS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_NUTRIENT_PRESETS,
    }
)

WS_TYPE_GET_IPM_PRESETS = f"{DOMAIN}/get_ipm_presets"
SCHEMA_WS_GET_IPM_PRESETS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_IPM_PRESETS,
    }
)

WS_TYPE_GET_EC_RAMP_CURVES = f"{DOMAIN}/get_ec_ramp_curves"
SCHEMA_WS_GET_EC_RAMP_CURVES = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_EC_RAMP_CURVES,
    }
)

WS_TYPE_GET_NUTRIENT_INVENTORY = f"{DOMAIN}/get_nutrient_inventory"
SCHEMA_WS_GET_NUTRIENT_INVENTORY = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_NUTRIENT_INVENTORY,
    }
)

WS_TYPE_UPDATE_NUTRIENT_STOCK = f"{DOMAIN}/update_nutrient_stock"
SCHEMA_WS_UPDATE_NUTRIENT_STOCK = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_UPDATE_NUTRIENT_STOCK,
        vol.Required("nutrient_id"): str,
        vol.Required("name"): str,
        vol.Required("current_ml"): vol.All(vol.Any(float, int), vol.Range(min=0)),
        vol.Required("initial_ml"): vol.All(vol.Any(float, int), vol.Range(min=1)),
    }
)

WS_TYPE_REMOVE_NUTRIENT_STOCK = f"{DOMAIN}/remove_nutrient_stock"
SCHEMA_WS_REMOVE_NUTRIENT_STOCK = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_REMOVE_NUTRIENT_STOCK,
        vol.Required("nutrient_id"): str,
    }
)


@callback
def websocket_get_nutrient_presets(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle get nutrient presets command via WebSocket."""
    try:
        coordinator: GrowspaceCoordinator = GrowspaceCoordinator.get_for_service_call(
            hass, msg
        )
        data = coordinator.nutrient_manager.get_serialization_data()
        connection.send_result(msg["id"], data["nutrient_presets"])
    except ServiceValidationError:
        connection.send_error(
            msg["id"], "not_loaded", "Growspace Manager integration not loaded"
        )
    except Exception as err:
        _LOGGER.exception("Error handling websocket_get_nutrient_presets")
        connection.send_error(msg["id"], "unknown_error", str(err))


@callback
def websocket_get_ipm_presets(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle get IPM presets command via WebSocket."""
    try:
        coordinator: GrowspaceCoordinator = GrowspaceCoordinator.get_for_service_call(
            hass, msg
        )
        data = coordinator.nutrient_manager.get_serialization_data()
        connection.send_result(msg["id"], data["ipm_presets"])
    except ServiceValidationError:
        connection.send_error(
            msg["id"], "not_loaded", "Growspace Manager integration not loaded"
        )
    except Exception as err:
        _LOGGER.exception("Error handling websocket_get_ipm_presets")
        connection.send_error(msg["id"], "unknown_error", str(err))


@callback
def websocket_get_ec_ramp_curves(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle get EC ramp curves command via WebSocket."""
    try:
        coordinator: GrowspaceCoordinator = GrowspaceCoordinator.get_for_service_call(
            hass, msg
        )
        data = coordinator.nutrient_manager.get_serialization_data()
        connection.send_result(msg["id"], data.get("ec_ramp_curves", []))
    except ServiceValidationError:
        connection.send_error(
            msg["id"], "not_loaded", "Growspace Manager integration not loaded"
        )
    except Exception as err:
        _LOGGER.exception("Error handling websocket_get_ec_ramp_curves")
        connection.send_error(msg["id"], "unknown_error", str(err))


@callback
def websocket_get_nutrient_inventory(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle get nutrient inventory command."""
    try:
        coordinator: GrowspaceCoordinator = GrowspaceCoordinator.get_any(hass)
        if coordinator.nutrient_inventory_service:
            inventory = coordinator.nutrient_inventory_service.get_inventory()
            connection.send_result(msg["id"], asdict(inventory))
        else:
            connection.send_result(msg["id"], {"stocks": {}})
    except ServiceValidationError:
        connection.send_error(
            msg["id"], "not_loaded", "Growspace Manager integration not loaded"
        )
    except Exception as err:
        _LOGGER.exception("Error handling websocket_get_nutrient_inventory")
        connection.send_error(msg["id"], "unknown_error", str(err))


@callback
def websocket_update_nutrient_stock(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle update nutrient stock command."""
    try:
        coordinator: GrowspaceCoordinator = GrowspaceCoordinator.get_any(hass)
        if coordinator.nutrient_inventory_service:
            current_ml = float(msg["current_ml"])
            initial_ml = float(msg["initial_ml"])
            if current_ml > initial_ml:
                connection.send_error(
                    msg["id"],
                    "invalid_input",
                    "current_ml cannot exceed initial_ml",
                )
                return
            coordinator.nutrient_inventory_service.update_stock(
                nutrient_id=msg["nutrient_id"],
                name=msg["name"],
                current_ml=current_ml,
                initial_ml=initial_ml,
            )
            coordinator.config_entry.async_create_background_task(
                hass, coordinator.async_commit(), "save_coordinator_data"
            )
            connection.send_result(msg["id"])
        else:
            connection.send_error(msg["id"], "not_initialized", "Service not ready")
    except ServiceValidationError:
        connection.send_error(
            msg["id"], "not_loaded", "Growspace Manager integration not loaded"
        )
    except Exception as err:
        _LOGGER.exception("Error handling websocket_update_nutrient_stock")
        connection.send_error(msg["id"], "unknown_error", str(err))


@callback
def websocket_remove_nutrient_stock(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle remove nutrient stock command."""
    try:
        coordinator: GrowspaceCoordinator = GrowspaceCoordinator.get_any(hass)
        if coordinator.nutrient_inventory_service:
            coordinator.nutrient_inventory_service.remove_stock(msg["nutrient_id"])
            coordinator.config_entry.async_create_background_task(
                hass, coordinator.async_commit(), "save_coordinator_data"
            )
            connection.send_result(msg["id"])
        else:
            connection.send_error(msg["id"], "not_initialized", "Service not ready")
    except ServiceValidationError:
        connection.send_error(
            msg["id"], "not_loaded", "Growspace Manager integration not loaded"
        )
    except Exception as err:
        _LOGGER.exception("Error handling websocket_remove_nutrient_stock")
        connection.send_error(msg["id"], "unknown_error", str(err))


COMMANDS: list[tuple[str, Any, Any, bool]] = [
    (WS_TYPE_GET_NUTRIENT_PRESETS, websocket_get_nutrient_presets, SCHEMA_WS_GET_NUTRIENT_PRESETS, True),
    (WS_TYPE_GET_IPM_PRESETS, websocket_get_ipm_presets, SCHEMA_WS_GET_IPM_PRESETS, True),
    (WS_TYPE_GET_EC_RAMP_CURVES, websocket_get_ec_ramp_curves, SCHEMA_WS_GET_EC_RAMP_CURVES, True),
    (WS_TYPE_GET_NUTRIENT_INVENTORY, websocket_get_nutrient_inventory, SCHEMA_WS_GET_NUTRIENT_INVENTORY, True),
    (WS_TYPE_UPDATE_NUTRIENT_STOCK, websocket_update_nutrient_stock, SCHEMA_WS_UPDATE_NUTRIENT_STOCK, True),
    (WS_TYPE_REMOVE_NUTRIENT_STOCK, websocket_remove_nutrient_stock, SCHEMA_WS_REMOVE_NUTRIENT_STOCK, True),
]
