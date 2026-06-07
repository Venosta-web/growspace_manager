"""Irrigation analytics WebSocket handler."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.crop_steering_history import (
    CropSteeringHistoryAnalyzer,
)
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

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

_RANGE_CONFIG: dict[str, tuple[str, int]] = {
    "1h": ("24h", 4),
    "6h": ("24h", 24),
    "24h": ("24h", 96),
    "7d": ("7d", 168),
}


async def websocket_get_irrigation_analytics(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return water consumption aggregated by growth stage for a growspace."""
    try:
        coordinator = GrowspaceCoordinator.get_for_service_call(hass, msg)
        growspace_id: str = msg["growspace_id"]
        trackers = coordinator.services.growspaces.get_all_trackers_for_growspace(growspace_id)

        combined: dict[str, float] = {}
        for tracker in trackers.values():
            for stage, liters in tracker.get_stage_aggregates().items():
                combined[stage] = combined.get(stage, 0.0) + liters

        connection.send_result(
            msg["id"],
            {"growspace_id": growspace_id, "stage_aggregates": combined},
        )
    except Exception as e:  # noqa: BLE001
        connection.send_error(msg["id"], "unknown_error", str(e))


async def websocket_get_tank_water_history(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return pre-bucketed water consumption for qualifying tanks of a growspace."""
    try:
        coordinator = GrowspaceCoordinator.get_for_service_call(hass, msg)
        growspace_id: str = msg["growspace_id"]
        range_key: str = msg["range"]

        growspace = coordinator.growspaces.get(growspace_id)
        if growspace is None:
            connection.send_result(msg["id"], {"growspace_id": growspace_id, "range": range_key, "buckets": []})
            return

        env = growspace.environment_config
        if env.irrigation_flow_sensors or env.drain_volume_sensors:
            connection.send_result(msg["id"], {"growspace_id": growspace_id, "range": range_key, "buckets": []})
            return

        trackers = coordinator.services.growspaces.get_all_trackers_for_growspace(growspace_id)
        history_key, bucket_count = _RANGE_CONFIG[range_key]

        raw_histories: list[list[dict[str, Any]]] = []
        for tracker in trackers.values():
            if history_key == "7d":
                raw_histories.append(tracker.get_history_7d()[-bucket_count:])
            else:
                raw_histories.append(tracker.get_history_24h()[-bucket_count:])

        if not raw_histories:
            connection.send_result(msg["id"], {"growspace_id": growspace_id, "range": range_key, "buckets": []})
            return

        buckets: list[dict[str, Any]] = []
        for i, slot in enumerate(raw_histories[0]):
            total = sum(h[i]["liters_consumed"] for h in raw_histories)
            buckets.append({"timestamp": slot["bucket_start"], "liters": round(total, 4)})

        connection.send_result(msg["id"], {"growspace_id": growspace_id, "range": range_key, "buckets": buckets})
    except Exception as e:  # noqa: BLE001
        connection.send_error(msg["id"], "unknown_error", str(e))


async def websocket_get_crop_steering_history(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return bucketed crop steering sensor history for a growspace."""
    try:
        coordinator = GrowspaceCoordinator.get_for_service_call(hass, msg)
        growspace_id: str = msg["growspace_id"]

        growspace = coordinator.growspaces.get(growspace_id)
        if growspace is None:
            connection.send_error(
                msg["id"], "not_found", f"Growspace {growspace_id} not found"
            )
            return

        analyzer = CropSteeringHistoryAnalyzer(hass)
        history = await analyzer.async_get_history(growspace)

        connection.send_result(msg["id"], {"growspace_id": growspace_id, **history})
    except Exception as e:  # noqa: BLE001
        connection.send_error(msg["id"], "unknown_error", str(e))


COMMANDS: list[tuple[str, Any, Any, bool]] = [
    (
        WS_TYPE_GET_IRRIGATION_ANALYTICS,
        websocket_get_irrigation_analytics,
        SCHEMA_WS_GET_IRRIGATION_ANALYTICS,
        False,
    ),
    (
        WS_TYPE_GET_TANK_WATER_HISTORY,
        websocket_get_tank_water_history,
        SCHEMA_WS_GET_TANK_WATER_HISTORY,
        False,
    ),
    (
        WS_TYPE_GET_CROP_STEERING_HISTORY,
        websocket_get_crop_steering_history,
        SCHEMA_WS_GET_CROP_STEERING_HISTORY,
        False,
    ),
]
