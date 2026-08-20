"""Nutrient and preset WebSocket handlers."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from ._common import WSCommand

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
        vol.Optional("brand", default=""): str,
        vol.Optional("stock_type", default="base"): vol.In(
            ["base", "bloom", "calmag", "root", "additive", "microbe"]
        ),
        vol.Optional("npk", default=""): str,
        vol.Optional("dose_ml_l", default=0.0): vol.All(
            vol.Any(float, int), vol.Range(min=0)
        ),
        vol.Optional("notes", default=""): str,
    }
)

WS_TYPE_REMOVE_NUTRIENT_STOCK = f"{DOMAIN}/remove_nutrient_stock"
SCHEMA_WS_REMOVE_NUTRIENT_STOCK = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_REMOVE_NUTRIENT_STOCK,
        vol.Required("nutrient_id"): str,
    }
)


def websocket_get_nutrient_presets(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> Any:
    """Handle get nutrient presets command via WebSocket."""
    return coordinator.services.config.get_nutrient_serialization_data()[
        "nutrient_presets"
    ]


def websocket_get_ipm_presets(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> Any:
    """Handle get IPM presets command via WebSocket."""
    return coordinator.services.config.get_nutrient_serialization_data()["ipm_presets"]


def websocket_get_ec_ramp_curves(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> Any:
    """Handle get EC ramp curves command via WebSocket."""
    return coordinator.services.config.get_nutrient_serialization_data().get(
        "ec_ramp_curves", []
    )


def websocket_get_nutrient_inventory(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Handle get nutrient inventory command."""
    inventory = coordinator.services.config.get_inventory()
    if inventory is not None:
        return asdict(inventory)
    return {"stocks": {}}


def websocket_update_nutrient_stock(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> None:
    """Handle update nutrient stock command."""
    current_ml = float(msg["current_ml"])
    initial_ml = float(msg["initial_ml"])
    if current_ml > initial_ml:
        raise ServiceValidationError("current_ml cannot exceed initial_ml")
    coordinator.services.config.update_stock(
        nutrient_id=msg["nutrient_id"],
        name=msg["name"],
        current_ml=current_ml,
        initial_ml=initial_ml,
        brand=msg["brand"],
        type=msg["stock_type"],
        npk=msg["npk"],
        dose_ml_l=float(msg["dose_ml_l"]),
        notes=msg["notes"],
    )
    coordinator.config_entry.async_create_background_task(
        hass, coordinator.async_commit(), "save_coordinator_data"
    )


def websocket_remove_nutrient_stock(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> None:
    """Handle remove nutrient stock command."""
    coordinator.services.config.remove_stock(msg["nutrient_id"])
    coordinator.config_entry.async_create_background_task(
        hass, coordinator.async_commit(), "save_coordinator_data"
    )


COMMANDS: list[WSCommand] = [
    WSCommand(
        WS_TYPE_GET_NUTRIENT_PRESETS,
        websocket_get_nutrient_presets,
        SCHEMA_WS_GET_NUTRIENT_PRESETS,
        sync=True,
    ),
    WSCommand(
        WS_TYPE_GET_IPM_PRESETS,
        websocket_get_ipm_presets,
        SCHEMA_WS_GET_IPM_PRESETS,
        sync=True,
    ),
    WSCommand(
        WS_TYPE_GET_EC_RAMP_CURVES,
        websocket_get_ec_ramp_curves,
        SCHEMA_WS_GET_EC_RAMP_CURVES,
        sync=True,
    ),
    WSCommand(
        WS_TYPE_GET_NUTRIENT_INVENTORY,
        websocket_get_nutrient_inventory,
        SCHEMA_WS_GET_NUTRIENT_INVENTORY,
        resolve="any",
        sync=True,
    ),
    WSCommand(
        WS_TYPE_UPDATE_NUTRIENT_STOCK,
        websocket_update_nutrient_stock,
        SCHEMA_WS_UPDATE_NUTRIENT_STOCK,
        resolve="any",
        sync=True,
    ),
    WSCommand(
        WS_TYPE_REMOVE_NUTRIENT_STOCK,
        websocket_remove_nutrient_stock,
        SCHEMA_WS_REMOVE_NUTRIENT_STOCK,
        resolve="any",
        sync=True,
    ),
]
