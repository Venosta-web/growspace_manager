"""Irrigation Zone editing through the shared WS Command Lifecycle."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.schemas import ZONE_EDIT_SCHEMAS
from custom_components.growspace_manager.services.zone_management import (
    async_edit_zones,
)
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from ._common import WSCommand


async def websocket_edit_zone(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Commit a zone edit and return authoritative membership and revision."""
    values = {
        key: value
        for key, value in msg.items()
        if key not in {"id", "type", "growspace_id", "expected_layout_revision"}
    }
    operation = (
        msg["type"]
        .split("/")[-1]
        .removesuffix("_irrigation_zone")
        .removesuffix("_irrigation_zones")
    )
    return await async_edit_zones(
        coordinator,
        msg["growspace_id"],
        msg["expected_layout_revision"],
        operation,
        values,
    )


COMMANDS = tuple(
    WSCommand(
        f"{DOMAIN}/{name}",
        websocket_edit_zone,
        websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
            {**schema.schema, vol.Required("type"): f"{DOMAIN}/{name}"}
        ),
    )
    for name, schema in ZONE_EDIT_SCHEMAS.items()
)
