"""Notification configuration handler for Growspace Manager."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

import voluptuous as vol

from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import selector

from ..notifications.timed import (
    TIMED_NOTIFICATION_TRIGGER_OPTIONS,
    normalize_timed_notification_trigger,
)
from . import AbortFlow, BaseConfigHandler

_LOGGER = logging.getLogger(__name__)


class NotificationConfigHandler(BaseConfigHandler[dict[str, Any]]):
    """Handle notification configuration steps."""

    async def async_step_manage_timed_notifications(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle timed notification management step."""
        try:
            coordinator = self.get_coordinator()
        except AbortFlow as e:
            return self.flow.async_abort(reason=e.reason)

        notifications = coordinator.services.notifications.get_timed_notifications()

        if user_input is not None:
            action = user_input.get("action")
            notification_id = user_input.get("notification_id")

            if action == "add":
                return await self.async_step_add_timed_notification()
            if action == "edit" and notification_id:
                self.flow.selected_notification_id = notification_id
                return await self.async_step_edit_timed_notification()
            if action == "delete" and notification_id:
                self.flow.selected_notification_id = notification_id
                return await self.async_step_delete_timed_notification()
            if action == "back":
                return await self.flow.async_step_init()

        return self.flow.async_show_form(
            step_id="manage_timed_notifications",
            data_schema=self.get_timed_notification_schema(notifications),
        )

    async def async_step_add_timed_notification(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for adding a new timed notification."""
        if self.config_entry is None:
            return self.flow.async_abort(reason="setup_error")
        coordinator = self.config_entry.runtime_data

        if user_input is not None:
            await coordinator.services.notifications.async_add_timed_notification(
                user_input["message"],
                user_input["trigger_type"],
                user_input["day"],
                user_input.get("growspace_ids"),
            )
            return self.flow.async_create_entry(
                title="", data=self.config_entry.options
            )

        return self.flow.async_show_form(
            step_id="add_timed_notification",
            data_schema=self.get_add_edit_schema(coordinator),
        )

    async def async_step_edit_timed_notification(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for editing a timed notification."""
        if self.config_entry is None:
            return self.flow.async_abort(reason="setup_error")
        coordinator = self.config_entry.runtime_data
        notification_id = self.flow.selected_notification_id
        notification = next(
            (
                n
                for n in coordinator.services.notifications.get_timed_notifications()
                if n["id"] == notification_id
            ),
            None,
        )

        if not notification:
            return self.flow.async_abort(reason="notification_not_found")

        if user_input is not None:
            await coordinator.services.notifications.async_update_timed_notification(
                notification_id,
                user_input["message"],
                user_input["trigger_type"],
                user_input["day"],
                user_input.get("growspace_ids"),
            )
            return self.flow.async_create_entry(
                title="", data=self.config_entry.options
            )

        return self.flow.async_show_form(
            step_id="edit_timed_notification",
            data_schema=self.get_add_edit_schema(coordinator, notification),
        )

    async def async_step_delete_timed_notification(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm deletion of a timed notification."""
        if self.config_entry is None:
            return self.flow.async_abort(reason="setup_error")
        coordinator = self.config_entry.runtime_data
        notification_id = self.flow.selected_notification_id

        if user_input is not None:
            await coordinator.services.notifications.async_remove_timed_notification(
                notification_id
            )
            return self.flow.async_create_entry(title="", data={})

        return self.flow.async_show_form(
            step_id="delete_timed_notification",
            description_placeholders={"notification_id": notification_id},
        )

    def get_timed_notification_schema(
        self, notifications: list[dict[str, Any]]
    ) -> vol.Schema:
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
        self,
        coordinator: GrowspaceCoordinator,
        notification: dict[str, Any] | None = None,
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
                default=normalize_timed_notification_trigger(
                    notification.get("trigger_type", "flower")
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value=value, label=label)
                        for value, label in TIMED_NOTIFICATION_TRIGGER_OPTIONS
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
                vol.Optional(
                    "growspace_ids", default=notification.get("growspace_ids", [])
                )
            ] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=growspace_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    multiple=True,
                )
            )

        return vol.Schema(schema)
