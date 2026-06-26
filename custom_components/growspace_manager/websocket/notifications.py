"""WebSocket handlers for notification settings."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

_LOGGER = logging.getLogger(__name__)


def _get_coordinator(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
) -> GrowspaceCoordinator | None:
    try:
        return GrowspaceCoordinator.get_for_service_call(hass, {})
    except (ServiceValidationError, Exception):  # noqa: BLE001
        return None


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
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Persist notification timing settings and ai_auto_alerts atomically."""
    coordinator = _get_coordinator(hass, connection)
    if coordinator is None:
        connection.send_error(
            msg["id"], "not_found", "Growspace Manager integration not loaded"
        )
        return

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

    hass.config_entries.async_update_entry(coordinator.config_entry, options=new_options)
    await coordinator.async_commit()

    connection.send_result(msg["id"], {"success": True})


COMMANDS: list[tuple[str, Any, Any, bool]] = [
    (
        WS_TYPE_SAVE_NOTIFICATION_SETTINGS,
        websocket_save_notification_settings,
        SCHEMA_WS_SAVE_NOTIFICATION_SETTINGS,
        False,
    ),
]
