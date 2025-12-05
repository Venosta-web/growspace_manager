"""Notification configuration handler for Growspace Manager."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector

_LOGGER = logging.getLogger(__name__)


class NotificationConfigHandler:
    """Handle notification configuration steps."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the handler."""
        self.hass = hass
        self.config_entry = config_entry

    def get_timed_notification_schema(self, notifications: list[dict]) -> vol.Schema:
        """Build the schema for the timed notification management menu."""
        notification_options = [
            selector.SelectOptionDict(
                value=n["id"],
                label=f"{n['message']} ({n['trigger_type']} day {n['day']})",
            )
            for n in notifications
        ]

        schema: dict[Any, Any] = {
            vol.Required("action", default="add"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(
                            value="add", label="Add Notification"
                        ),
                        selector.SelectOptionDict(
                            value="edit", label="Edit Notification"
                        ),
                        selector.SelectOptionDict(
                            value="delete", label="Delete Notification"
                        ),
                    ]
                )
            ),
        }

        if notification_options:
            schema[vol.Required("notification_id")] = selector.SelectSelector(
                selector.SelectSelectorConfig(options=notification_options)
            )

        return vol.Schema(schema)

    def get_add_edit_schema(
        self, coordinator, notification: dict[str, Any] | None = None
    ) -> vol.Schema:
        """Build the schema for the add/edit timed notification form."""
        if notification is None:
            notification = {}

        growspace_options = [
            selector.SelectOptionDict(value=gs_id, label=gs.name)
            for gs_id, gs in coordinator.growspaces.items()
        ]

        schema: dict[Any, Any] = {
            vol.Required(
                "message", default=notification.get("message", "")
            ): selector.TextSelector(),
            vol.Required(
                "trigger_type",
                default=notification.get("trigger_type", "days_since_flip"),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(
                            value="days_since_flip", label="Days Since Flip"
                        ),
                        selector.SelectOptionDict(
                            value="days_since_germination",
                            label="Days Since Germination",
                        ),
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                "day", default=notification.get("day", 1)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, mode=selector.NumberSelectorMode.BOX
                )
            ),
        }

        if growspace_options:
            schema[
                vol.Optional("growspace_id", default=notification.get("growspace_id"))
            ] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=growspace_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )

        return vol.Schema(schema)
