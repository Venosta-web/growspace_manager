"""Irrigation analytics WebSocket handler."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import (
    DOMAIN,
    IrrigationRecipeKind,
    SteeringMode,
)
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.crop_steering_history import (
    CropSteeringHistoryAnalyzer,
)
from custom_components.growspace_manager.exceptions import GrowspaceNotFoundError
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from ._common import WSCommand

WS_TYPE_GET_IRRIGATION_ANALYTICS = f"{DOMAIN}/irrigation_analytics"
SCHEMA_WS_GET_IRRIGATION_ANALYTICS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_IRRIGATION_ANALYTICS,
        vol.Required("growspace_id"): str,
    }
)

WS_TYPE_GET_TANK_WATER_HISTORY = f"{DOMAIN}/get_tank_water_history"
SCHEMA_WS_GET_TANK_WATER_HISTORY = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_TANK_WATER_HISTORY,
        vol.Required("growspace_id"): str,
        vol.Required("range"): vol.In(["1h", "6h", "24h", "7d"]),
    }
)

WS_TYPE_GET_CROP_STEERING_HISTORY = f"{DOMAIN}/get_crop_steering_history"
SCHEMA_WS_GET_CROP_STEERING_HISTORY = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_CROP_STEERING_HISTORY,
        vol.Required("growspace_id"): str,
    }
)

WS_TYPE_APPLY_STEERING_MODE = f"{DOMAIN}/apply_steering_mode"
SCHEMA_WS_APPLY_STEERING_MODE = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_APPLY_STEERING_MODE,
        vol.Required("growspace_id"): str,
        vol.Required("steering_mode"): vol.In([m.value for m in SteeringMode]),
    }
)

WS_TYPE_GET_IRRIGATION_RECIPES = f"{DOMAIN}/get_irrigation_recipes"
SCHEMA_WS_GET_IRRIGATION_RECIPES = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_IRRIGATION_RECIPES,
    }
)

WS_TYPE_SAVE_IRRIGATION_RECIPE = f"{DOMAIN}/save_irrigation_recipe"
SCHEMA_WS_SAVE_IRRIGATION_RECIPE = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_SAVE_IRRIGATION_RECIPE,
        vol.Required("growspace_id"): str,
        vol.Required("name"): str,
        vol.Required("kind"): vol.In([k.value for k in IrrigationRecipeKind]),
        vol.Optional("recipe_id"): str,
    }
)

WS_TYPE_REMOVE_IRRIGATION_RECIPE = f"{DOMAIN}/remove_irrigation_recipe"
SCHEMA_WS_REMOVE_IRRIGATION_RECIPE = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_REMOVE_IRRIGATION_RECIPE,
        vol.Required("recipe_id"): str,
    }
)

_RANGE_CONFIG: dict[str, tuple[str, int]] = {
    "1h": ("24h", 4),
    "6h": ("24h", 24),
    "24h": ("24h", 96),
    "7d": ("7d", 168),
}


async def websocket_get_irrigation_analytics(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Return water consumption aggregated by growth stage for a growspace."""
    growspace_id: str = msg["growspace_id"]
    trackers = coordinator.services.growspaces.get_all_trackers_for_growspace(
        growspace_id
    )

    combined: dict[str, float] = {}
    for tracker in trackers.values():
        for stage, liters in tracker.get_stage_aggregates().items():
            combined[stage] = combined.get(stage, 0.0) + liters

    return {"growspace_id": growspace_id, "stage_aggregates": combined}


async def websocket_get_tank_water_history(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Return pre-bucketed water consumption for qualifying tanks of a growspace."""
    growspace_id: str = msg["growspace_id"]
    range_key: str = msg["range"]
    empty = {"growspace_id": growspace_id, "range": range_key, "buckets": []}

    growspace = coordinator.growspaces.get(growspace_id)
    if growspace is None:
        return empty

    env = growspace.environment_config
    if env.irrigation_flow_sensors or env.drain_volume_sensors:
        return empty

    trackers = coordinator.services.growspaces.get_all_trackers_for_growspace(
        growspace_id
    )
    history_key, bucket_count = _RANGE_CONFIG[range_key]

    raw_histories: list[list[dict[str, Any]]] = []
    for tracker in trackers.values():
        if history_key == "7d":
            raw_histories.append(tracker.get_history_7d()[-bucket_count:])
        else:
            raw_histories.append(tracker.get_history_24h()[-bucket_count:])

    if not raw_histories:
        return empty

    buckets: list[dict[str, Any]] = []
    for i, slot in enumerate(raw_histories[0]):
        total = sum(h[i]["liters_consumed"] for h in raw_histories)
        buckets.append({"timestamp": slot["bucket_start"], "liters": round(total, 4)})

    return {"growspace_id": growspace_id, "range": range_key, "buckets": buckets}


async def websocket_get_crop_steering_history(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Return bucketed crop steering sensor history for a growspace."""
    growspace_id: str = msg["growspace_id"]

    growspace = coordinator.growspaces.get(growspace_id)
    if growspace is None:
        raise GrowspaceNotFoundError(f"Growspace {growspace_id} not found")

    analyzer = CropSteeringHistoryAnalyzer(hass)
    history = await analyzer.async_get_history(growspace)

    return {"growspace_id": growspace_id, **history}


async def websocket_apply_steering_mode(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Stamp a Steering Mode's preset values into the strategy (ADR-0012)."""
    growspace_id: str = msg["growspace_id"]
    mode = SteeringMode(msg["steering_mode"])

    await coordinator.services.growspaces.apply_steering_mode(growspace_id, mode)

    return {"growspace_id": growspace_id, "declared_steering_mode": mode.value}


def websocket_get_irrigation_recipes(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Return the global Irrigation Recipe library.

    Global, so it resolves through any coordinator and never takes a
    growspace: a recipe saved from one tent is listed from every other.
    """
    return coordinator.services.config.get_irrigation_recipes()


async def websocket_save_irrigation_recipe(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Save a growspace's current irrigation settings as a named recipe."""
    recipe = await coordinator.services.config.save_irrigation_recipe(
        growspace_id=msg["growspace_id"],
        name=msg["name"],
        kind=IrrigationRecipeKind(msg["kind"]),
        recipe_id=msg.get("recipe_id"),
    )
    return recipe.to_dict()


async def websocket_remove_irrigation_recipe(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> None:
    """Remove a recipe from the global Irrigation Recipe library."""
    await coordinator.services.config.remove_irrigation_recipe(msg["recipe_id"])


COMMANDS: list[WSCommand] = [
    WSCommand(
        WS_TYPE_GET_IRRIGATION_ANALYTICS,
        websocket_get_irrigation_analytics,
        SCHEMA_WS_GET_IRRIGATION_ANALYTICS,
    ),
    WSCommand(
        WS_TYPE_GET_TANK_WATER_HISTORY,
        websocket_get_tank_water_history,
        SCHEMA_WS_GET_TANK_WATER_HISTORY,
    ),
    WSCommand(
        WS_TYPE_GET_CROP_STEERING_HISTORY,
        websocket_get_crop_steering_history,
        SCHEMA_WS_GET_CROP_STEERING_HISTORY,
    ),
    WSCommand(
        WS_TYPE_APPLY_STEERING_MODE,
        websocket_apply_steering_mode,
        SCHEMA_WS_APPLY_STEERING_MODE,
    ),
    WSCommand(
        WS_TYPE_GET_IRRIGATION_RECIPES,
        websocket_get_irrigation_recipes,
        SCHEMA_WS_GET_IRRIGATION_RECIPES,
        resolve="any",
        sync=True,
    ),
    WSCommand(
        WS_TYPE_SAVE_IRRIGATION_RECIPE,
        websocket_save_irrigation_recipe,
        SCHEMA_WS_SAVE_IRRIGATION_RECIPE,
    ),
    WSCommand(
        WS_TYPE_REMOVE_IRRIGATION_RECIPE,
        websocket_remove_irrigation_recipe,
        SCHEMA_WS_REMOVE_IRRIGATION_RECIPE,
        resolve="any",
    ),
]
