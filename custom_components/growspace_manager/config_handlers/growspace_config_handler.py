"""Growspace Configuration Handler for Growspace Manager."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from custom_components.growspace_manager.models import Growspace

import voluptuous as vol

from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import selector

from . import AbortFlow, BaseConfigHandler

_LOGGER = logging.getLogger(__name__)


class GrowspaceConfigHandler(BaseConfigHandler[dict[str, Any]]):
    """Handler for Growspace configuration steps."""

    def get_growspace_management_schema(
        self, coordinator: GrowspaceCoordinator
    ) -> vol.Schema:
        """Build the schema for the growspace management menu."""
        growspace_options = coordinator.growspace_service.get_sorted_growspace_options()

        schema: dict[Any, Any] = {
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
                        selector.SelectOptionDict(value=gs_id, label=name)
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
            vol.Required("length", default=120): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="cm",
                )
            ),
            vol.Required("width", default=120): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="cm",
                )
            ),
            vol.Required("height", default=200): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="cm",
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

    async def async_step_manage_growspaces(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle growspace management step."""
        try:
            coordinator = self.get_coordinator()
        except AbortFlow as e:
            return self.flow.async_abort(reason=e.reason)

        if user_input is not None:
            action = user_input.get("action")

            if action == "add":
                return await self.async_step_add_growspace()
            if action == "update":
                self.flow.selected_growspace_id = user_input.get("growspace_id")
                if not self.flow.selected_growspace_id:
                    return self.flow.async_show_form(
                        step_id="manage_growspaces",
                        data_schema=self.get_growspace_management_schema(coordinator),
                        errors={"base": "select_growspace"},
                    )
                return await self.async_step_update_growspace()
            if action == "remove":
                self.flow.selected_growspace_id = user_input.get("growspace_id")
                if not self.flow.selected_growspace_id:
                    return self.flow.async_show_form(
                        step_id="manage_growspaces",
                        data_schema=self.get_growspace_management_schema(coordinator),
                        errors={"base": "select_growspace"},
                    )
                return await self.async_step_confirm_remove_growspace()
            if action == "back":
                return await self.flow.async_step_init()

        return self.flow.async_show_form(
            step_id="manage_growspaces",
            data_schema=self.get_growspace_management_schema(coordinator),
        )

    async def async_step_add_growspace(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for adding a new growspace."""
        try:
            self.get_coordinator()
        except AbortFlow as e:
            return self.flow.async_abort(reason=e.reason)

        if user_input is not None:
            try:
                await self.async_add_growspace(user_input)
                return self.flow.async_create_entry(title="", data=self.config_entry.options)
            except Exception:
                _LOGGER.exception("Error adding growspace")
                return self.flow.async_show_form(
                    step_id="add_growspace",
                    data_schema=self.get_add_growspace_schema(),
                    errors={"base": "add_failed"},
                )

        return self.flow.async_show_form(
            step_id="add_growspace",
            data_schema=self.get_add_growspace_schema(),
        )

    async def async_add_growspace(self, user_input: dict[str, Any]) -> None:
        """Add a new growspace."""
        if self.config_entry is None:
            raise ValueError("Coordinator not found")
        coordinator = self.config_entry.runtime_data
        if coordinator is None:
            raise ValueError("Coordinator not found")

        # Use coordinator to add growspace
        await coordinator.async_add_growspace(
            name=user_input["name"],
            rows=user_input["rows"],
            plants_per_row=user_input["plants_per_row"],
            notification_target=user_input.get("notification_target"),
            dimensions={
                "length": user_input["length"],
                "width": user_input["width"],
                "height": user_input["height"],
                "unit": "cm",
            },
        )

    async def async_step_confirm_remove_growspace(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm removal of a growspace."""
        try:
            coordinator = self.get_coordinator()
        except AbortFlow as e:
            return self.flow.async_abort(reason=e.reason)
        growspace_id = self.flow.selected_growspace_id
        growspace = coordinator.growspaces.get(growspace_id)

        if not growspace:
            return self.flow.async_abort(reason="growspace_not_found")

        if user_input is not None:
            try:
                await self.async_remove_growspace(growspace_id)
                return self.flow.async_create_entry(title="", data=self.config_entry.options)
            except Exception:
                _LOGGER.exception("Error removing growspace")
                return self.flow.async_show_form(
                    step_id="confirm_remove_growspace",
                    errors={"base": "remove_failed"},
                    description_placeholders={"growspace_name": growspace.name},
                )

        return self.flow.async_show_form(
            step_id="confirm_remove_growspace",
            description_placeholders={"growspace_name": growspace.name},
        )

    def get_update_growspace_schema(self, growspace: Growspace) -> vol.Schema:
        """Build the schema for the update growspace form."""
        if not growspace:
            return vol.Schema({})

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

        # Add "None" option if we found any mobile apps
        if notification_options:
            notification_options.insert(
                0, selector.SelectOptionDict(value="", label="None (No notifications)")
            )

        current_notification = getattr(growspace, "notification_target", None) or ""

        base = {
            vol.Optional(
                "name", default=getattr(growspace, "name", "")
            ): selector.TextSelector(),
            vol.Optional(
                "rows", default=getattr(growspace, "rows", 4)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=20, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Optional(
                "plants_per_row", default=getattr(growspace, "plants_per_row", 4)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=20, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Optional(
                "length",
                default=growspace.dimensions.get("length", 120)
                if growspace.dimensions
                else 120,
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="cm",
                )
            ),
            vol.Optional(
                "width",
                default=growspace.dimensions.get("width", 120)
                if growspace.dimensions
                else 120,
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="cm",
                )
            ),
            vol.Optional(
                "height",
                default=growspace.dimensions.get("height", 200)
                if growspace.dimensions
                else 200,
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="cm",
                )
            ),
        }

        if notification_options:
            base[vol.Optional("notification_target", default=current_notification)] = (
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=notification_options,
                        custom_value=False,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            )
        else:
            base[vol.Optional("notification_target", default=current_notification)] = (
                selector.TextSelector()
            )

        return vol.Schema(base)

    async def async_remove_growspace(self, growspace_id: str) -> None:
        """Remove a growspace."""
        if self.config_entry is None:
            raise ValueError("Coordinator not found")
        coordinator = self.config_entry.runtime_data
        if coordinator is None:
            raise ValueError("Coordinator not found")
        await coordinator.async_remove_growspace(growspace_id)

    async def async_update_growspace(
        self, growspace_id: str, user_input: dict[str, Any]
    ) -> None:
        """Update an existing growspace."""
        if self.config_entry is None:
            raise ValueError("Coordinator not found")
        coordinator = self.config_entry.runtime_data
        if coordinator is None:
            raise ValueError("Coordinator not found")

        # Filter out empty values
        update_data = {k: v for k, v in user_input.items() if v}

        # Handle dimensions update if present
        if "length" in user_input and "width" in user_input and "height" in user_input:
            dimensions = {
                "length": user_input.pop("length"),
                "width": user_input.pop("width"),
                "height": user_input.pop("height"),
                "unit": "cm",
            }
            update_data["dimensions"] = dimensions

        await coordinator.async_update_growspace(growspace_id, **update_data)

    async def async_step_update_growspace(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for updating an existing growspace."""
        try:
            coordinator = self.get_coordinator()
        except AbortFlow as e:
            return self.flow.async_abort(reason=e.reason)
        growspace_id = self.flow.selected_growspace_id
        growspace = coordinator.growspaces.get(growspace_id)

        if not growspace:
            return self.flow.async_abort(reason="growspace_not_found")

        if user_input is not None:
            try:
                await self.async_update_growspace(growspace_id, user_input)
                return self.flow.async_create_entry(title="", data=self.config_entry.options)
            except Exception:
                _LOGGER.exception("Error updating growspace")
                return self.flow.async_show_form(
                    step_id="update_growspace",
                    data_schema=self.get_update_growspace_schema(growspace),
                    errors={"base": "update_failed"},
                    description_placeholders={"growspace_name": growspace.name},
                )

        return self.flow.async_show_form(
            step_id="update_growspace",
            data_schema=self.get_update_growspace_schema(growspace),
            description_placeholders={"growspace_name": growspace.name},
        )
