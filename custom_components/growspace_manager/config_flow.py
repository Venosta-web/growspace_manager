"""Configuration flow for the Growspace Manager integration.

This file manages the user interface for setting up and configuring the
Growspace Manager integration, including the initial setup (ConfigFlow) and
subsequent modifications (OptionsFlow). It provides a graphical user interface
for managing growspaces, plants, and environment sensor configurations.
"""

from __future__ import annotations

import logging
from typing import Any, override

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector
import homeassistant.helpers.config_validation as cv

from .config_handlers import (
    AIConfigHandler,
    EnvironmentConfigHandler,
    GrowspaceConfigHandler,
    IrrigationConfigHandler,
    NotificationConfigHandler,
    PlantConfigHandler,
    StrainConfigHandler,
)
from .const import DEFAULT_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)

# Translation strings for the options flow
STEP_INIT = {
    "manage_growspaces": "Manage Growspaces",
    "manage_plants": "Manage Plants",
}

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Optional("name", default=DEFAULT_NAME): cv.string,
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial configuration flow for Growspace Manager.

    This class is responsible for the initial setup of the integration when the
    user adds it from the Home Assistant UI.
    """

    VERSION = 1
    MINOR_VERSION = 1
    integration_name = "Growspace Manager"

    @override  # type: ignore[misc]
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the first step of the configuration flow.

        This step prompts the user for a name for the integration instance.

        Args:
            user_input: The user's input from the form, if any.

        Returns:
            A ConfigFlowResult indicating the next step or completion.
        """
        try:
            _LOGGER.debug("async_step_user called with input: %s", user_input)

            if user_input is not None:
                name = user_input.get("name", DEFAULT_NAME)
                _LOGGER.debug(
                    "Processing user input, storing integration name: %s",
                    name,
                )
                return self.async_create_entry(
                    title=name,
                    data={"name": name},
                )

            _LOGGER.debug("Showing initial user form")
            return self.async_show_form(
                step_id="user",
                data_schema=STEP_USER_DATA_SCHEMA,
            )

        except Exception as err:
            _LOGGER.exception("Error in async_step_user")
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {vol.Optional("name", default=DEFAULT_NAME): cv.string}
                ),
                errors={"base": f"Error: {err}"},
            )

    async def async_step_add_growspace(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle adding a growspace during the initial setup.

        This is an optional step that allows the user to create their first
        growspace immediately after adding the integration.

        Args:
            user_input: The user's input from the form, if any.

        Returns:
            A ConfigFlowResult indicating the next step or completion.
        """
        if user_input is not None:
            try:
                _LOGGER.debug("ConfigFlow received growspace data: %s", user_input)

                pending_growspace = {
                    "name": user_input["name"],
                    "rows": user_input["rows"],
                    "plants_per_row": user_input["plants_per_row"],
                    "notification_target": user_input.get("notification_target"),
                }

                entry = self.async_create_entry(
                    title=getattr(self, "_integration_name", DEFAULT_NAME),
                    data={
                        "name": getattr(self, "_integration_name", DEFAULT_NAME),
                        "pending_growspace": pending_growspace,
                    },
                )
            except Exception as err:
                _LOGGER.exception("Error in async_step_add_growspace")
                return self.async_show_form(
                    step_id="add_growspace",
                    data_schema=GrowspaceConfigHandler(
                        self.hass, None
                    ).get_add_growspace_schema(),
                    errors={"base": f"Error: {err}"},
                )

            _LOGGER.debug("Stored pending growspace data in config entry")
            return entry

        _LOGGER.debug("Showing add_growspace form")
        return self.async_show_form(
            step_id="add_growspace",
            data_schema=GrowspaceConfigHandler(
                self.hass, None
            ).get_add_growspace_schema(),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlowHandler:
        """Get the options flow for this handler.

        Args:
            config_entry: The configuration entry.

        Returns:
            An instance of the OptionsFlowHandler.
        """
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(OptionsFlow):
    """Handles the options flow for Growspace Manager.

    This class provides the UI for managing the integration's settings after
    it has been installed, including adding/updating/removing growspaces and
    plants, and configuring environmental monitoring.
    """

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize the options flow handler.

        Args:
            config_entry: The configuration entry.
        """
        super().__init__()
        self.handler = config_entry.entry_id
        self.current_options: dict[str, Any] = config_entry.options.copy()
        self._growspace_handler: GrowspaceConfigHandler | None = None
        self._plant_handler: PlantConfigHandler | None = None
        self._ai_handler: AIConfigHandler | None = None
        self.selected_notification_id: str | None = None
        self.selected_growspace_id: str | None = None
        self.env_config_step1: dict[str, Any] | None = None
        self.selected_plant_id: str | None = None
        self.selected_strain_id: str | None = None
        self._env_handler: EnvironmentConfigHandler | None = None
        self._irrigation_handler: IrrigationConfigHandler | None = None
        self._notify_handler: NotificationConfigHandler | None = None
        self._strain_handler: StrainConfigHandler | None = None

    @property
    def growspace_handler(self) -> GrowspaceConfigHandler:
        """Get the growspace config handler."""
        if self._growspace_handler is None:
            self._growspace_handler = GrowspaceConfigHandler(self)
        return self._growspace_handler

    @property
    def plant_handler(self) -> PlantConfigHandler:
        """Get the plant config handler."""
        if self._plant_handler is None:
            self._plant_handler = PlantConfigHandler(self)
        return self._plant_handler

    @property
    def ai_handler(self) -> AIConfigHandler:
        """Get the AI config handler."""
        if self._ai_handler is None:
            self._ai_handler = AIConfigHandler(self)
        return self._ai_handler

    @property
    def env_handler(self) -> EnvironmentConfigHandler:
        """Get the environment config handler."""
        if self._env_handler is None:
            self._env_handler = EnvironmentConfigHandler(self)
        return self._env_handler

    @property
    def irrigation_handler(self) -> IrrigationConfigHandler:
        """Get the irrigation config handler."""
        if self._irrigation_handler is None:
            self._irrigation_handler = IrrigationConfigHandler(self)
        return self._irrigation_handler

    @property
    def notify_handler(self) -> NotificationConfigHandler:
        """Get the notification config handler."""
        if self._notify_handler is None:
            self._notify_handler = NotificationConfigHandler(self)
        return self._notify_handler

    @property
    def strain_handler(self) -> StrainConfigHandler:
        """Get the strain config handler."""
        if self._strain_handler is None:
            self._strain_handler = StrainConfigHandler(self)
        return self._strain_handler

    @override  # type: ignore[misc]
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the main options menu.

        Args:
            user_input: The user's selection from the menu, if any.

        Returns:
            A ConfigFlowResult directing to the next step.
        """
        if user_input is not None:
            action = user_input.get("action")
            if action == "manage_growspaces":
                return await self.growspace_handler.async_step_manage_growspaces()
            if action == "manage_plants":
                return await self.plant_handler.async_step_manage_plants()
            if action == "configure_environment":
                return await self.async_step_select_growspace_for_env()
            if action == "configure_ai":
                return await self.ai_handler.async_step_configure_ai()
            if action == "manage_timed_notifications":
                return await self.notify_handler.async_step_manage_timed_notifications()
            if action == "manage_strain_library":
                return await self.strain_handler.async_step_manage_strain_library()
            if action == "configure_irrigation":
                return await self.async_step_select_growspace_for_irrigation()
            if action == "configure_global":
                return await self.async_step_configure_global()
            if action == "configure_general":
                return await self.async_step_configure_general()

            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.get_main_menu_schema(),
        )

    async def async_step_configure_ai(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delegate AI configuration to the AI handler."""
        return await self.ai_handler.async_step_configure_ai(user_input)

    async def async_step_manage_timed_notifications(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delegate notification management to the notification handler."""
        return await self.notify_handler.async_step_manage_timed_notifications(
            user_input
        )

    async def async_step_add_timed_notification(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delegate notification addition to the notification handler."""
        return await self.notify_handler.async_step_add_timed_notification(user_input)

    async def async_step_edit_timed_notification(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delegate notification editing to the notification handler."""
        return await self.notify_handler.async_step_edit_timed_notification(user_input)

    async def async_step_delete_timed_notification(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delegate notification deletion to the notification handler."""
        return await self.notify_handler.async_step_delete_timed_notification(
            user_input
        )

    async def async_step_manage_growspaces(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delegate growspace management to the handler."""
        return await self.growspace_handler.async_step_manage_growspaces(user_input)

    async def async_step_add_growspace(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delegate growspace addition to the handler."""
        return await self.growspace_handler.async_step_add_growspace(user_input)

    async def async_step_update_growspace(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delegate growspace update to the handler."""
        return await self.growspace_handler.async_step_update_growspace(user_input)

    async def async_step_confirm_remove_growspace(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delegate growspace removal confirmation to the handler."""
        return await self.growspace_handler.async_step_confirm_remove_growspace(
            user_input
        )

    async def async_step_configure_general(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle general integration settings."""
        if user_input is not None:
            self.current_options.update(user_input)
            return self.async_create_entry(title="", data=self.current_options)

        return self.async_show_form(
            step_id="configure_general",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "show_sidebar",
                        default=self.current_options.get("show_sidebar", True),
                    ): cv.boolean,
                }
            ),
        )

    async def async_step_select_growspace_for_env(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delegate growspace selection for environment to the handler."""
        return await self.env_handler.async_step_select_growspace_for_env(user_input)

    async def async_step_select_growspace_for_irrigation(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delegate growspace selection for irrigation to the handler."""
        return await self.irrigation_handler.async_step_select_growspace_for_irrigation(
            user_input
        )

    async def async_step_configure_environment(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delegate environment configuration to the handler."""
        return await self.env_handler.async_step_configure_environment(user_input)

    async def async_step_configure_dehumidifier(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delegate dehumidifier configuration to the handler."""
        return await self.env_handler.async_step_configure_dehumidifier(user_input)

    async def async_step_configure_advanced_bayesian(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delegate advanced Bayesian configuration to the handler."""
        return await self.env_handler.async_step_configure_advanced_bayesian(user_input)

    async def async_step_configure_sensor_placement(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delegate sensor placement configuration to the handler."""
        return await self.env_handler.async_step_configure_sensor_placement(user_input)

    async def async_step_manage_plants(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delegate plant management to the handler."""
        return await self.plant_handler.async_step_manage_plants(user_input)

    async def async_step_select_growspace_for_plant(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delegate growspace selection for plant to the handler."""
        return await self.plant_handler.async_step_select_growspace_for_plant(
            user_input
        )

    async def async_step_add_plant(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delegate plant addition to the handler."""
        return await self.plant_handler.async_step_add_plant(user_input)

    async def async_step_update_plant(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delegate plant update to the handler."""
        return await self.plant_handler.async_step_update_plant(user_input)

    async def async_step_configure_irrigation(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delegate irrigation configuration to the handler."""
        return await self.irrigation_handler.async_step_configure_irrigation(user_input)

    async def async_step_irrigation_overview(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delegate irrigation overview to the handler."""
        return await self.irrigation_handler.async_step_irrigation_overview(user_input)

    async def async_step_manage_strain_library(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delegate strain library management to the handler."""
        return await self.strain_handler.async_step_manage_strain_library(user_input)

    async def async_step_add_strain(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delegate strain addition to the handler."""
        return await self.strain_handler.async_step_add_strain(user_input)

    async def async_step_edit_strain(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delegate strain editing to the handler."""
        return await self.strain_handler.async_step_edit_strain(user_input)

    async def async_step_import_strain_library(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delegate strain library import to the handler."""
        return await self.strain_handler.async_step_import_strain_library(user_input)

    async def async_step_export_strain_library(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delegate strain library export to the handler."""
        return await self.strain_handler.async_step_export_strain_library(user_input)

    async def async_step_manage_breeder_blacklist(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delegate breeder blacklist management to the handler."""
        return await self.strain_handler.async_step_manage_breeder_blacklist(user_input)

    async def async_step_configure_global(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for configuring global sensors (outside weather, lung room)."""
        if user_input is not None:
            new_options = self.config_entry.options.copy()
            new_options["global_settings"] = user_input
            return self.async_create_entry(title="", data=new_options)

        global_settings = self.config_entry.options.get("global_settings", {})
        schema_dict = {
            vol.Optional(
                "weather_entity", default=global_settings.get("weather_entity")
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="weather")),
            vol.Optional(
                "lung_room_temp_sensor",
                default=global_settings.get("lung_room_temp_sensor"),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["sensor", "input_number"], device_class="temperature"
                )
            ),
            vol.Optional(
                "lung_room_humidity_sensor",
                default=global_settings.get("lung_room_humidity_sensor"),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["sensor", "input_number"], device_class="humidity"
                )
            ),
        }

        return self.async_show_form(
            step_id="configure_global", data_schema=vol.Schema(schema_dict)
        )

    def get_main_menu_schema(self) -> vol.Schema:
        """Build the schema for the main options menu."""
        return vol.Schema(
            {
                vol.Required("action"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value="manage_growspaces", label="Manage Growspaces"
                            ),
                            selector.SelectOptionDict(
                                value="manage_plants", label="Manage Plants"
                            ),
                            selector.SelectOptionDict(
                                value="configure_environment",
                                label="Configure Growspace Environment",
                            ),
                            selector.SelectOptionDict(
                                value="configure_global",
                                label="Configure Global Sensors",
                            ),
                            selector.SelectOptionDict(
                                value="configure_ai",
                                label="Configure AI Assistant",
                            ),
                            selector.SelectOptionDict(
                                value="manage_timed_notifications",
                                label="Timed Notifications",
                            ),
                            selector.SelectOptionDict(
                                value="configure_irrigation",
                                label="Configure Irrigation",
                            ),
                            selector.SelectOptionDict(
                                value="manage_strain_library",
                                label="Manage Strain Library",
                            ),
                            selector.SelectOptionDict(
                                value="configure_general",
                                label="General Settings",
                            ),
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                        translation_key="menu_options",
                    )
                )
            }
        )
