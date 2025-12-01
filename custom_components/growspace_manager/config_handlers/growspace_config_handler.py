"""Growspace Configuration Handler for Growspace Manager."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.helpers import selector

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class GrowspaceConfigHandler:
    """Handler for Growspace configuration steps."""

    def __init__(self, hass, config_entry):
        """Initialize the Growspace config handler."""
        self.hass = hass
        self.config_entry = config_entry

    def get_growspace_management_schema(self, coordinator) -> vol.Schema:
        """Build the schema for the growspace management menu."""
        growspace_options = coordinator.get_sorted_growspace_options()

        schema = {
            vol.Required("action", default="add"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value="add", label="Add Growspace"),
                        selector.SelectOptionDict(
                            value="update", label="Update Growspace"
                        ),
                        selector.SelectOptionDict(
                            value="remove", label="Remove Growspace"
                        ),
                        selector.SelectOptionDict(
                            value="back", label="Back to Main Menu"
                        ),
                    ]
                )
            ),
        }

        if growspace_options:
            schema[vol.Optional("growspace_id")] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": gs_id, "label": name}
                        for gs_id, name in growspace_options
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )

        return vol.Schema(schema)

    def get_add_growspace_schema(self) -> vol.Schema:
        """Build the voluptuous schema for the add growspace form."""
        base = {
            vol.Required("name"): selector.TextSelector(),
            vol.Required("rows", default=4): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=20, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Required("plants_per_row", default=4): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=20, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Optional("notification_target"): selector.TextSelector(),
        }

        # Get available notify services
        services = self.hass.services.async_services().get("notify", {})
        notification_options = [
            selector.SelectOptionDict(
                value=service,
                label=service.replace("mobile_app_", "").replace("_", " ").title(),
            )
            for service in services
            if service.startswith("mobile_app_")
        ]

        if notification_options:
            base[vol.Optional("notification_target")] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=notification_options,
                    custom_value=False,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        else:
            base[vol.Optional("notification_target")] = selector.TextSelector()

        return vol.Schema(base)

    async def async_add_growspace(self, user_input: dict[str, Any]) -> None:
        """Add a new growspace."""
        coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]["coordinator"]
        
        # Use coordinator to add growspace
        coordinator.async_add_growspace(
            name=user_input["name"],
            rows=user_input["rows"],
            plants_per_row=user_input["plants_per_row"],
            notification_target=user_input.get("notification_target"),
        )
        
        # Save changes
        await coordinator.async_save()

    async def async_remove_growspace(self, growspace_id: str) -> None:
        """Remove a growspace."""
        coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]["coordinator"]
        await coordinator.async_remove_growspace(growspace_id)
