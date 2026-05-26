"""Irrigation analytics WebSocket handler."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from ..const import DOMAIN
from ..coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)

WS_TYPE_GET_IRRIGATION_ANALYTICS = f"{DOMAIN}/irrigation_analytics"
SCHEMA_WS_GET_IRRIGATION_ANALYTICS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_IRRIGATION_ANALYTICS,
        vol.Required("growspace_id"): str,
    }
)


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
    except Exception as e:
        connection.send_error(msg["id"], "unknown_error", str(e))


COMMANDS: list[tuple[str, Any, Any, bool]] = [
    (
        WS_TYPE_GET_IRRIGATION_ANALYTICS,
        websocket_get_irrigation_analytics,
        SCHEMA_WS_GET_IRRIGATION_ANALYTICS,
        False,
    ),
]
