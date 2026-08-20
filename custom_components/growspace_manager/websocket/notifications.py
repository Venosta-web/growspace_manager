"""WebSocket handlers for notification settings."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from ._common import WSCommand

_LOGGER = logging.getLogger(__name__)

WS_TYPE_SAVE_NOTIFICATION_SETTINGS = f"{DOMAIN}/save_notification_settings"
SCHEMA_WS_SAVE_NOTIFICATION_SETTINGS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_SAVE_NOTIFICATION_SETTINGS,
        vol.Required("notification_settings"): dict,
        vol.Required("ai_auto_alerts"): bool,
        vol.Optional("timed_notifications"): list,
    }
)


async def websocket_save_notification_settings(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Persist notification timing settings and ai_auto_alerts atomically."""
    new_options = coordinator.config_entry.options.copy()
    new_options["notification_settings"] = msg["notification_settings"]

    ai_settings: dict[str, Any] = dict(new_options.get("ai_settings", {}))
    ai_settings["ai_auto_alerts"] = msg["ai_auto_alerts"]
    new_options["ai_settings"] = ai_settings

    # Timed notifications are optional: persist them only when the card sends the
    # list, otherwise leave the stored list untouched.
    if "timed_notifications" in msg:
        new_options["timed_notifications"] = msg["timed_notifications"]

    if hasattr(coordinator, "options"):
        coordinator.options = new_options

    hass.config_entries.async_update_entry(
        coordinator.config_entry, options=new_options
    )
    await coordinator.async_commit()

    return {"success": True}


COMMANDS: list[WSCommand] = [
    WSCommand(
        WS_TYPE_SAVE_NOTIFICATION_SETTINGS,
        websocket_save_notification_settings,
        SCHEMA_WS_SAVE_NOTIFICATION_SETTINGS,
        resolve="any",
    ),
]
