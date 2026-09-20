"""Label Template capability discovery."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.labels.capability import published_capability
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from ._common import WSCommand

WS_TYPE_GET_LABEL_TEMPLATE_CAPABILITY = f"{DOMAIN}/get_label_template_capability"
SCHEMA_WS_GET_LABEL_TEMPLATE_CAPABILITY = (
    websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
        {vol.Required("type"): WS_TYPE_GET_LABEL_TEMPLATE_CAPABILITY}
    )
)


def websocket_get_label_template_capability(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Return the one complete envelope; never a partial capability."""
    del hass, coordinator, msg
    capability = published_capability()
    if capability is None:
        raise HomeAssistantError("The Label Template capability is unavailable")
    return capability.as_dict()


COMMANDS: list[WSCommand] = [
    WSCommand(
        WS_TYPE_GET_LABEL_TEMPLATE_CAPABILITY,
        websocket_get_label_template_capability,
        SCHEMA_WS_GET_LABEL_TEMPLATE_CAPABILITY,
        resolve="any",
        sync=True,
    )
]
