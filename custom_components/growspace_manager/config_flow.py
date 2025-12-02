"""Configuration flow for the Growspace Manager integration.

This file manages the user interface for setting up and configuring the
Growspace Manager integration, including the initial setup (ConfigFlow) and
subsequent modifications (OptionsFlow). It provides a graphical user interface
for managing growspaces, plants, and environment sensor configurations.
"""

from __future__ import annotations

import ast
import json
import logging
import uuid
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .config_handlers.ai_config_handler import AIConfigHandler
from .config_handlers.growspace_config_handler import GrowspaceConfigHandler
from .config_handlers.plant_config_handler import PlantConfigHandler
from .const import (
    CONF_AI_ENABLED,
    CONF_ASSISTANT_ID,
    DEFAULT_FLOWER_DAY_HOURS,
    DEFAULT_NAME,
    DEFAULT_VEG_DAY_HOURS,
    DOMAIN,
)
from .dehumidifier_coordinator import DEFAULT_THRESHOLDS

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


async def ensure_default_growspaces(coordinator):
    """Ensure that the default special growspaces (dry, cure, etc.) exist.

    This function is called during setup to create the logical growspaces
    used for specific stages of cultivation if they haven't been created yet.

    Args:
        coordinator: The Growspace Manager data update coordinator.
    """
    try:
        # Create special growspaces with their canonical IDs
        default_growspaces = [
            ("dry", "dry", 3, 3),
            ("cure", "cure", 3, 3),
            ("mother", "mother", 3, 3),
            ("clone", "clone", 5, 5),
            ("veg", "veg", 5, 5),
        ]

        created_count = 0
        for growspace_id, name, rows, plants_per_row in default_growspaces:
            # Use the coordinator's method to ensure special growspaces
            canonical_id = coordinator._ensure_special_growspace(
                growspace_id, name, rows, plants_per_row
            )
            if canonical_id not in coordinator.growspaces:
                created_count += 1

        if created_count > 0:
            # Save the updated data
            await coordinator.async_save()
            # Notify listeners of the changes
            coordinator.async_set_updated_data(coordinator.data)
            _LOGGER.info("Created %s default growspaces", created_count)
        else:
            _LOGGER.info("All default growspaces already exist")

    except (ValueError, KeyError, AttributeError) as err:
        _LOGGER.error("Error creating default growspaces: %s", err)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial configuration flow for Growspace Manager.

    This class is responsible for the initial setup of the integration when the
    user adds it from the Home Assistant UI.
    """

    VERSION = 1
    MINOR_VERSION = 1
    integration_name = "Growspace Manager"

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
            _LOGGER.exception("Error in async_step_user: %s", err)
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

                entry = self.async_create_entry(
                    title=getattr(self, "_integration_name", DEFAULT_NAME),
                    data={"name": getattr(self, "_integration_name", DEFAULT_NAME)},
                )

                self.hass.data.setdefault(DOMAIN, {})
                self.hass.data[DOMAIN]["pending_growspace"] = {
                    "name": user_input["name"],
                    "rows": user_input["rows"],
                    "plants_per_row": user_input["plants_per_row"],
                    "notification_target": user_input.get("notification_target"),
                }

                _LOGGER.debug(
                    "Stored pending growspace data: %s",
                    self.hass.data[DOMAIN]["pending_growspace"],
                )
                return entry

            except Exception as err:
                _LOGGER.exception("Error in async_step_add_growspace: %s", err)
                return self.async_show_form(
                    step_id="add_growspace",
                    data_schema=GrowspaceConfigHandler(
                        self.hass, None
                    ).get_add_growspace_schema(),
                    errors={"base": f"Error: {err}"},
                )

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
        self._config_entry = config_entry
        self._current_options: dict[str, Any] = self._config_entry.options.copy()
        self._growspace_handler = None
        self._plant_handler = None
        self._ai_handler = None

    @property
    def growspace_handler(self) -> GrowspaceConfigHandler:
        """Get the growspace config handler."""
        if self._growspace_handler is None:
            self._growspace_handler = GrowspaceConfigHandler(
                self.hass, self._config_entry
            )
        return self._growspace_handler

    @property
    def plant_handler(self) -> PlantConfigHandler:
        """Get the plant config handler."""
        if self._plant_handler is None:
            self._plant_handler = PlantConfigHandler(self.hass, self._config_entry)
        return self._plant_handler

    @property
    def ai_handler(self) -> AIConfigHandler:
        """Get the AI config handler."""
        if self._ai_handler is None:
            self._ai_handler = AIConfigHandler(self.hass, self._config_entry)
        return self._ai_handler

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
                return await self.async_step_manage_growspaces(user_input)
            if action == "manage_plants":
                return await self.async_step_manage_plants()
            if action == "configure_environment":
                return await self.async_step_select_growspace_for_env()
            if action == "configure_global":
                return await self.async_step_configure_global()
            if action == "configure_ai":
                return await self.async_step_configure_ai()
            if action == "manage_timed_notifications":
                return await self.async_step_manage_timed_notifications()
            if action == "manage_strain_library":
                return await self.async_step_manage_strain_library()
            if action == "configure_irrigation":
                return await self.async_step_select_growspace_for_irrigation()
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self._get_main_menu_schema(),
        )

    async def async_step_configure_ai(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for configuring AI settings."""
        errors = {}

        if user_input is not None:
            # Validate that if AI is enabled, an assistant is selected
            if user_input.get(CONF_AI_ENABLED) and not user_input.get(
                CONF_ASSISTANT_ID
            ):
                errors["base"] = "assistant_required"
            else:
                coordinator = self.hass.data[DOMAIN][self._config_entry.entry_id][
                    "coordinator"
                ]
                await self.ai_handler.save_ai_settings(coordinator, user_input)

                # Inform user about the changes
                return self.async_create_entry(
                    title="",
                    data=self._config_entry.options,
                    description="AI settings have been updated. "
                    + (
                        "AI features are now enabled. "
                        if user_input.get(CONF_AI_ENABLED)
                        else "AI features are disabled. "
                    )
                    + f"Assistant: {user_input.get(CONF_ASSISTANT_ID, 'None')}",
                )

        return self.async_show_form(
            step_id="configure_ai",
            data_schema=await self.ai_handler.get_ai_settings_schema(),
            errors=errors,
            description_placeholders={
                "info": "Configure AI-powered features for grow advice and notifications. "
                "You need a conversation/LLM integration (like Google Gemini, OpenAI, etc.) "
                "configured in Home Assistant for this to work."
            },
        )

    async def async_step_manage_timed_notifications(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the menu for managing timed notifications.

        Args:
            user_input: The user's input from the form, if any.

        Returns:
            A ConfigFlowResult directing to the appropriate action (add/edit/delete).
        """
        coordinator = self.hass.data[DOMAIN][self._config_entry.entry_id]["coordinator"]

        if user_input is not None:
            action = user_input.get("action")

            if action == "add":
                return await self.async_step_add_timed_notification()
            elif action == "edit":
                notification_id = user_input.get("notification_id")
                if notification_id:
                    self._selected_notification_id = notification_id
                    return await self.async_step_edit_timed_notification()
            elif action == "delete":
                notification_id = user_input.get("notification_id")
                if notification_id:
                    new_options = self._config_entry.options.copy()
                    notifications = new_options.get("timed_notifications", [])
                    notifications = [
                        n for n in notifications if n.get("id") != notification_id
                    ]
                    new_options["timed_notifications"] = notifications

                    # Update coordinator's in-memory options
                    coordinator.options = new_options

                    return self.async_create_entry(title="", data=new_options)

        return self.async_show_form(
            step_id="manage_timed_notifications",
            data_schema=self._get_timed_notification_schema(coordinator),
        )

    def _get_timed_notification_schema(self, coordinator) -> vol.Schema:
        """Build the schema for the timed notification management menu.

        Args:
            coordinator: The data update coordinator.

        Returns:
            A voluptuous schema for the form.
        """
        notifications = self._config_entry.options.get("timed_notifications", [])

        notification_options = [
            selector.SelectOptionDict(
                value=n["id"],
                label=f"{n['message']} ({n['trigger_type']} day {n['day']})",
            )
            for n in notifications
        ]

        schema = {
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

    async def async_step_add_timed_notification(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for adding a new timed notification.

        Args:
            user_input: The user's input from the form, if any.

        Returns:
            A ConfigFlowResult.
        """
        coordinator = self.hass.data[DOMAIN][self._config_entry.entry_id]["coordinator"]

        if user_input is not None:
            new_options = self._config_entry.options.copy()
            notifications = new_options.get("timed_notifications", [])

            # Add a unique ID to the new notification
            new_notification = user_input.copy()
            new_notification["id"] = str(uuid.uuid4())
            notifications.append(new_notification)
            new_options["timed_notifications"] = notifications

            # Update the coordinator's in-memory options
            coordinator.options = new_options

            return self.async_create_entry(title="", data=new_options)

        return self.async_show_form(
            step_id="add_timed_notification",
            data_schema=self._get_add_edit_timed_notification_schema(coordinator),
        )

    async def async_step_edit_timed_notification(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for editing an existing timed notification.

        Args:
            user_input: The user's input from the form, if any.

        Returns:
            A ConfigFlowResult.
        """
        coordinator = self.hass.data[DOMAIN][self._config_entry.entry_id]["coordinator"]
        notification_id = self._selected_notification_id
        notifications = self._config_entry.options.get("timed_notifications", [])
        notification = next(
            (n for n in notifications if n.get("id") == notification_id), None
        )

        if user_input is not None:
            new_options = self._config_entry.options.copy()
            notifications = new_options.get("timed_notifications", [])

            # Find and update the existing notification
            for i, n in enumerate(notifications):
                if n.get("id") == notification_id:
                    updated_notification = user_input.copy()
                    updated_notification["id"] = notification_id  # Preserve the ID
                    notifications[i] = updated_notification
                    break

            new_options["timed_notifications"] = notifications

            # Update the coordinator's in-memory options
            coordinator.options = new_options

            return self.async_create_entry(title="", data=new_options)

        return self.async_show_form(
            step_id="edit_timed_notification",
            data_schema=self._get_add_edit_timed_notification_schema(
                coordinator, notification
            ),
        )

    def _get_add_edit_timed_notification_schema(
        self, coordinator, notification=None
    ) -> vol.Schema:
        """Build the schema for the add/edit timed notification form.

        Args:
            coordinator: The data update coordinator.
            notification: The notification object to pre-fill the form, if editing.

        Returns:
            A voluptuous schema for the form.
        """
        if notification is None:
            notification = {}

        growspace_options = [
            selector.SelectOptionDict(value=gs_id, label=gs.name)
            for gs_id, gs in coordinator.growspaces.items()
        ]

        schema = {
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

    async def async_step_manage_growspaces(
        self, user_input: dict[str, Any] | None | None
    ) -> ConfigFlowResult:
        """Show the menu for managing growspaces (add, update, remove)."""
        try:
            coordinator = self.hass.data[DOMAIN][self._config_entry.entry_id][
                "coordinator"
            ]
        except KeyError:
            _LOGGER.error(
                "Coordinator not found - integration may not be properly set up"
            )
            return self.async_abort(reason="setup_error")

        if user_input is not None:
            action = user_input.get("action")

            if action == "add":
                return await self.async_step_add_growspace()
            elif action == "update" and user_input.get("growspace_id"):
                self._selected_growspace_id = user_input["growspace_id"]
                return await self.async_step_update_growspace()
            elif action == "remove" and user_input.get("growspace_id"):
                try:
                    await self.growspace_handler.async_remove_growspace(
                        user_input["growspace_id"]
                    )
                except Exception as err:
                    _LOGGER.exception("Error removing growspace: %s", err)
                    return self.async_show_form(
                        step_id="manage_growspaces",
                        data_schema=self.growspace_handler.get_growspace_management_schema(
                            coordinator
                        ),
                        errors={"base": "remove_failed"},
                    )
            elif action == "back":
                return self.async_show_form(
                    step_id="init",
                    data_schema=self.add_suggested_values_to_schema(
                        self._get_main_menu_schema(), self._config_entry.options
                    ),
                )

        return self.async_show_form(
            step_id="manage_growspaces",
            data_schema=self.growspace_handler.get_growspace_management_schema(
                coordinator
            ),
        )

    async def async_step_add_growspace(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for adding a new growspace."""
        try:
            # Check if coordinator exists
            self.hass.data[DOMAIN][self._config_entry.entry_id]["coordinator"]
        except KeyError:
            return self.async_abort(reason="setup_error")

        if user_input is not None:
            try:
                await self.growspace_handler.async_add_growspace(user_input)
                return self.async_create_entry(title="", data={})
            except Exception as err:
                _LOGGER.exception("Error adding growspace: %s", err)
                return self.async_show_form(
                    step_id="add_growspace",
                    data_schema=self.growspace_handler.get_add_growspace_schema(),
                    errors={"base": "add_failed"},
                )

        return self.async_show_form(
            step_id="add_growspace",
            data_schema=self.growspace_handler.get_add_growspace_schema(),
        )

    async def async_step_update_growspace(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for updating an existing growspace."""
        try:
            coordinator = self.hass.data[DOMAIN][self._config_entry.entry_id][
                "coordinator"
            ]
        except KeyError:
            _LOGGER.error(
                "Coordinator not found - integration may not be properly set up"
            )
            return self.async_abort(reason="setup_error")

        growspace = coordinator.growspaces.get(self._selected_growspace_id)

        if not growspace:
            _LOGGER.error("Growspace not found: %s", self._selected_growspace_id)
            return self.async_abort(reason="growspace_not_found")

        if user_input is not None:
            try:
                await self.growspace_handler.async_update_growspace(
                    self._selected_growspace_id, user_input
                )
                return self.async_create_entry(title="", data={})

            except Exception as err:
                _LOGGER.exception("Error updating growspace: %s", err)
                return self.async_show_form(
                    step_id="update_growspace",
                    data_schema=self.growspace_handler.get_update_growspace_schema(
                        growspace
                    ),
                    errors={"base": "update_failed"},
                )

        return self.async_show_form(
            step_id="update_growspace",
            data_schema=self.growspace_handler.get_update_growspace_schema(growspace),
        )

    async def async_step_select_growspace_for_env(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show a form to select a growspace before configuring its environment.

        Args:
            user_input: The user's input from the form, if any.

        Returns:
            A ConfigFlowResult.
        """
        coordinator = self.hass.data[DOMAIN][self._config_entry.entry_id]["coordinator"]
        growspace_options = coordinator.get_sorted_growspace_options()

        if not growspace_options:
            return self.async_abort(reason="no_growspaces")

        if user_input is not None:
            self._selected_growspace_id = user_input["growspace_id"]
            return await self.async_step_configure_environment()

        schema = vol.Schema(
            {
                vol.Required("growspace_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": gs_id, "label": name}
                            for gs_id, name in growspace_options
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="select_growspace_for_env", data_schema=schema
        )

    async def async_step_configure_environment(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for configuring environment sensors for a growspace.

        Args:
            user_input: The user's input from the form, if any.

        Returns:
            A ConfigFlowResult.
        """
        coordinator = self.hass.data[DOMAIN][self._config_entry.entry_id]["coordinator"]
        growspace = coordinator.growspaces.get(self._selected_growspace_id)

        if not growspace:
            return self.async_abort(reason="growspace_not_found")

        growspace_options = growspace.environment_config or {}

        _LOGGER.debug(
            "Loading environment config for growspace %s: %s",
            growspace.name,
            growspace_options,
        )

        if user_input is not None:
            self._env_config_step1 = self._process_environment_input(
                user_input, growspace_options
            )

            # Already filtered above, but keep this as a safety check
            env_config = {
                k: v
                for k, v in self._env_config_step1.items()
                if v is not None and v != ""
            }

            # Check for next steps
            if self._env_config_step1.get(
                "configure_dehumidifier"
            ) and self._env_config_step1.get("control_dehumidifier"):
                return await self.async_step_configure_dehumidifier()

            if self._env_config_step1.get("configure_advanced"):
                return await self.async_step_configure_advanced_bayesian()

            growspace.environment_config = env_config
            await coordinator.async_save()
            await coordinator.async_refresh()

            _LOGGER.info(
                "Environment configuration saved for growspace %s: %s",
                growspace.name,
                env_config,
            )
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="configure_environment",
            data_schema=self._get_environment_schema_step1(growspace_options),
            description_placeholders={"growspace_name": growspace.name},
        )

    async def async_step_configure_dehumidifier(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for configuring dehumidifier thresholds.

        Args:
            user_input: The user's input from the form, if any.

        Returns:
            A ConfigFlowResult.
        """
        coordinator = self.hass.data[DOMAIN][self._config_entry.entry_id]["coordinator"]
        growspace = coordinator.growspaces.get(self._selected_growspace_id)

        if not growspace:
            return self.async_abort(reason="growspace_not_found")

        # Load existing thresholds or defaults
        current_thresholds = (
            growspace.environment_config.get("dehumidifier_thresholds") or {}
        )

        if user_input is not None:
            # Process input back into nested structure
            new_thresholds = {}
            for stage in ["veg", "early_flower", "mid_flower", "late_flower"]:
                new_thresholds[stage] = {}
                for cycle in ["day", "night"]:
                    new_thresholds[stage][cycle] = {
                        "on": user_input[f"{stage}_{cycle}_on"],
                        "off": user_input[f"{stage}_{cycle}_off"],
                    }

            # Update config
            env_config = self._env_config_step1.copy()
            env_config["dehumidifier_thresholds"] = new_thresholds

            if env_config.get("configure_advanced"):
                # Update temporary config and move to next step
                self._env_config_step1 = env_config
                return await self.async_step_configure_advanced_bayesian()

            # Save and finish
            env_config.pop("configure_advanced", None)
            growspace.environment_config = env_config
            await coordinator.async_save()
            await coordinator.async_refresh()
            return self.async_create_entry(title="", data={})

        schema_dict = {}
        for stage in ["veg", "early_flower", "mid_flower", "late_flower"]:
            for cycle in ["day", "night"]:
                defaults = current_thresholds.get(stage, {}).get(
                    cycle, DEFAULT_THRESHOLDS[stage][cycle]
                )

                # ON Threshold
                schema_dict[
                    vol.Required(f"{stage}_{cycle}_on", default=defaults["on"])
                ] = selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.1,
                        max=3.0,
                        step=0.01,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="kPa",
                    )
                )

                # OFF Threshold
                schema_dict[
                    vol.Required(f"{stage}_{cycle}_off", default=defaults["off"])
                ] = selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.1,
                        max=3.0,
                        step=0.01,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="kPa",
                    )
                )

        return self.async_show_form(
            step_id="configure_dehumidifier",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={"growspace_name": growspace.name},
        )

    async def async_step_configure_advanced_bayesian(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for advanced configuration of Bayesian probabilities.

        Args:
            user_input: The user's input from the form, if any.

        Returns:
            A ConfigFlowResult.
        """
        coordinator = self.hass.data[DOMAIN][self._config_entry.entry_id]["coordinator"]
        growspace = coordinator.growspaces.get(self._selected_growspace_id)

        # Add this check early
        if not growspace:
            return self.async_abort(reason="growspace_not_found")

        if user_input is not None:
            env_config = self._env_config_step1.copy()
            env_config.pop("configure_advanced", None)

            try:
                parsed_user_input = {}
                for key, value in user_input.items():
                    if isinstance(value, str):
                        # Check if it's a valid tuple string
                        if not value.startswith("(") or not value.endswith(")"):
                            _LOGGER.warning(
                                "Invalid tuple format for %s: %s", key, value
                            )
                            raise ValueError("Invalid tuple string format")

                        parsed_value = ast.literal_eval(value)

                        if not isinstance(parsed_value, tuple):
                            raise TypeError("Parsed value is not a tuple")

                        parsed_user_input[key] = parsed_value
                    else:
                        parsed_user_input[key] = value

                # Update env_config *after* all parsing is successful
                env_config.update(parsed_user_input)

            except (ValueError, SyntaxError, TypeError):
                _LOGGER.warning("Invalid tuple format submitted", exc_info=True)
                return self.async_show_form(
                    step_id="configure_advanced_bayesian",
                    data_schema=self._get_advanced_bayesian_schema(
                        self._env_config_step1
                    ),
                    errors={"base": "invalid_tuple_format"},
                    description_placeholders={"growspace_name": growspace.name},
                )

            growspace.environment_config = env_config
            await coordinator.async_save()
            await coordinator.async_refresh()

            _LOGGER.info(
                "Advanced Bayesian configuration saved for %s: %s",
                growspace.name,
                env_config,
            )
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="configure_advanced_bayesian",
            data_schema=self._get_advanced_bayesian_schema(self._env_config_step1),
            description_placeholders={"growspace_name": growspace.name},
        )

    def _get_advanced_bayesian_schema(self, options: dict) -> vol.Schema:
        """Build the schema for the advanced Bayesian settings form.

        Args:
            options: The current options to use as default values.

        Returns:
            A voluptuous schema for the form.
        """
        defaults = {
            "prob_temp_extreme_heat": (0.98, 0.05),
            "prob_temp_high_heat": (0.85, 0.15),
            "prob_temp_warm": (0.65, 0.30),
            "prob_temp_extreme_cold": (0.95, 0.08),
            "prob_temp_cold": (0.80, 0.20),
            "prob_humidity_too_dry": (0.85, 0.20),
            "prob_humidity_high_veg_early": (0.80, 0.20),
            "prob_humidity_high_veg_late": (0.85, 0.15),
            "prob_humidity_too_humid_flower": (0.95, 0.10),
            "prob_humidity_high_flower": (0.75, 0.25),
            "prob_vpd_stress_veg_early": (0.85, 0.15),
            "prob_vpd_mild_stress_veg_early": (0.60, 0.30),
            "prob_vpd_stress_veg_late": (0.80, 0.18),
            "prob_vpd_mild_stress_veg_late": (0.55, 0.35),
            "prob_vpd_stress_flower_early": (0.85, 0.15),
            "prob_vpd_mild_stress_flower_early": (0.60, 0.30),
            "prob_vpd_stress_flower_late": (0.90, 0.12),
            "prob_vpd_mild_stress_flower_late": (0.65, 0.28),
            "prob_night_temp_high": (0.80, 0.20),
            "prob_mold_temp_danger_zone": (0.85, 0.30),
            "prob_mold_humidity_high_night": (0.99, 0.10),
            "prob_mold_vpd_low_night": (0.95, 0.20),
            "prob_mold_lights_off": (0.75, 0.30),
            "prob_mold_humidity_high_day": (0.95, 0.20),
            "prob_mold_vpd_low_day": (0.90, 0.25),
            "prob_mold_fan_off": (0.80, 0.15),
        }
        schema_dict = {
            vol.Optional(
                key, default=str(options.get(key, default))
            ): selector.TextSelector()
            for key, default in defaults.items()
        }
        return vol.Schema(schema_dict)

    async def async_step_configure_global(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for configuring global sensors (outside weather, lung room).

        Args:
            user_input: The user's input from the form, if any.

        Returns:
            A ConfigFlowResult.
        """
        if user_input is not None:
            # Save the global settings into the main config_entry's options
            new_options = self._config_entry.options.copy()
            new_options["global_settings"] = user_input
            return self.async_create_entry(title="", data=new_options)

        # Get current global settings to prepopulate the form
        global_settings = self._config_entry.options.get("global_settings", {})

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

    def _get_main_menu_schema(self) -> vol.Schema:
        """Build the schema for the main options menu.

        Returns:
            A voluptuous schema for the form.
        """
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
                                value="manage_strain_library",
                                label="Manage Strain Library",
                            ),
                            selector.SelectOptionDict(
                                value="configure_irrigation",
                                label="Configure Irrigation",
                            ),
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )

    async def async_step_select_growspace_for_irrigation(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show a form to select a growspace before configuring its irrigation."""
        try:
            coordinator = self.hass.data[DOMAIN][self._config_entry.entry_id][
                "coordinator"
            ]
        except KeyError:
            _LOGGER.error("Coordinator not found for irrigation config flow.")
            return self.async_abort(reason="setup_error")
        growspace_options = coordinator.get_sorted_growspace_options()

        if not growspace_options:
            _LOGGER.error(
                "IRRIGATION FLOW ABORT: No growspaces available to configure."
            )
            return self.async_abort(reason="no_growspaces")

        _LOGGER.debug(
            "IRRIGATION FLOW: Found %d growspaces: %s",
            len(growspace_options),
            growspace_options,
        )
        if user_input is not None:
            self._selected_growspace_id = user_input["growspace_id"]
            return await self.async_step_configure_irrigation()

        schema = vol.Schema(
            {
                vol.Required("growspace_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": gs_id, "label": name}
                            for gs_id, name in growspace_options
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="select_growspace_for_irrigation", data_schema=schema
        )

    async def async_step_configure_irrigation(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the irrigation configuration menu for a selected growspace."""
        coordinator = self.hass.data[DOMAIN][self._config_entry.entry_id]["coordinator"]
        growspace = coordinator.growspaces.get(self._selected_growspace_id)

        if not growspace:
            return self.async_abort(reason="growspace_not_found")

        # [MODIFIED]: Route directly to the unified overview step
        return await self.async_step_irrigation_overview()

    async def async_step_irrigation_overview(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the unified irrigation management screen for the Lovelace card."""
        coordinator = self.hass.data[DOMAIN][self._config_entry.entry_id]["coordinator"]
        growspace = coordinator.growspaces.get(self._selected_growspace_id)

        if not growspace:
            return self.async_abort(reason="growspace_not_found")

        # Load ALL current irrigation options for the growspace from the Growspace object
        irrigation_options = growspace.irrigation_config

        # --- START OF FIX: Ensure EntitySelector receives None instead of "" ---
        irrigation_pump_default = irrigation_options.get("irrigation_pump_entity")
        if not irrigation_pump_default:
            irrigation_pump_default = None

        drain_pump_default = irrigation_options.get("drain_pump_entity")
        if not drain_pump_default:
            drain_pump_default = None
        # --- END OF FIX ---

        if user_input is not None:
            # 1. Update the Growspace object directly

            # CRITICAL FIX: Only update the R/W fields (pump entities and durations)
            # Filter out the read-only fields that were passed for display purposes
            updated_settings = {
                k: v
                for k, v in user_input.items()
                if k
                not in [
                    "current_irrigation_times",
                    "current_drain_times",
                    "growspace_id_read_only",
                ]
            }

            # Explicitly handle pump entities to allow clearing them (setting to None)
            # If they are missing from user_input (e.g. cleared in UI), set them to None
            if "irrigation_pump_entity" not in updated_settings:
                updated_settings["irrigation_pump_entity"] = None
            if "drain_pump_entity" not in updated_settings:
                updated_settings["drain_pump_entity"] = None

            # Update the config in the growspace object
            growspace.irrigation_config.update(updated_settings)

            # Save via coordinator
            await coordinator.async_save()

            # Notify listeners (including IrrigationCoordinator)
            coordinator.async_set_updated_data(coordinator.data)

            # This triggers async_update_listener in __init__.py, reloading the IrrigationCoordinator
            return self.async_create_entry(
                title="",
                data=self._current_options,  # No changes to ConfigEntry options
                description="Irrigation settings have been updated.",
            )

        # 2. Define schema to pass ALL data to the Lovelace component
        schema = vol.Schema(
            {
                # R/W Fields: Pump Settings (User edits and submits these)
                vol.Optional(
                    "irrigation_pump_entity",
                    default=irrigation_pump_default,
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch")
                ),
                vol.Optional(
                    "drain_pump_entity",
                    default=drain_pump_default,
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch")
                ),
                vol.Optional(
                    "irrigation_duration",
                    default=irrigation_options.get("irrigation_duration", 30),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    "drain_duration",
                    default=irrigation_options.get("drain_duration", 30),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                # Read-only Fields: Schedules and ID (Passed to frontend for visual use/service calls)
                # Must be stringified to pass complex objects through schema inputs
                vol.Optional(
                    "current_irrigation_times",
                    default=json.dumps(irrigation_options.get("irrigation_times", [])),
                ): selector.TextSelector(),
                vol.Optional(
                    "current_drain_times",
                    default=json.dumps(irrigation_options.get("drain_times", [])),
                ): selector.TextSelector(),
                vol.Optional(
                    "growspace_id_read_only", default=self._selected_growspace_id
                ): selector.TextSelector(),
            }
        )

        return self.async_show_form(
            step_id="irrigation_overview",
            data_schema=schema,
            description_placeholders={"growspace_name": growspace.name},
        )

    async def async_step_manage_plants(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the menu for managing plants (add, update, remove)."""
        coordinator = self.hass.data[DOMAIN][self._config_entry.entry_id]["coordinator"]

        if user_input is not None:
            action = user_input.get("action")

            if action == "add":
                return await self.async_step_select_growspace_for_plant()
            if action == "update" and user_input.get("plant_id"):
                self._selected_plant_id = user_input["plant_id"]
                return await self.async_step_update_plant()
            if action == "remove" and user_input.get("plant_id"):
                try:
                    # We need to get the growspace_id for the plant to remove it
                    # This is a bit tricky as the plant ID is unique globally but we need the growspace ID
                    # Ideally the coordinator should handle this lookup or we iterate
                    plant = coordinator.plants.get(user_input["plant_id"])
                    if plant:
                        await self.plant_handler.async_destroy_plant(
                            plant.growspace_id, plant.id
                        )
                except Exception:
                    return self.async_show_form(
                        step_id="manage_plants",
                        data_schema=self.plant_handler.get_plant_management_schema(
                            coordinator
                        ),
                        errors={"base": "remove_failed"},
                    )
            if action == "back":
                return self.async_show_form(
                    step_id="init",
                    data_schema=self._get_main_menu_schema(),
                )

        return self.async_show_form(
            step_id="manage_plants",
            data_schema=self.plant_handler.get_plant_management_schema(coordinator),
        )

    async def async_step_select_growspace_for_plant(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show a form to select a growspace before adding a new plant."""
        coordinator = self.hass.data[DOMAIN][self._config_entry.entry_id]["coordinator"]

        if user_input is not None:
            self._selected_growspace_id = user_input["growspace_id"]
            return await self.async_step_add_plant()

        # Reuse the growspace selection schema from GrowspaceConfigHandler if possible
        # But here we need it for a specific purpose.
        # For simplicity, let's use a simple schema here as it's just a selection step
        growspace_options = coordinator.get_sorted_growspace_options()
        if not growspace_options:
            return self.async_abort(reason="no_growspaces")

        schema = vol.Schema(
            {
                vol.Required("growspace_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": gid, "label": name}
                            for gid, name in growspace_options
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )

        return self.async_show_form(
            step_id="select_growspace_for_plant",
            data_schema=schema,
        )

    async def async_step_add_plant(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for adding a new plant to a selected growspace."""
        try:
            coordinator = self.hass.data[DOMAIN][self._config_entry.entry_id][
                "coordinator"
            ]
        except KeyError:
            return self.async_abort(reason="setup_error")

        growspace = coordinator.growspaces.get(self._selected_growspace_id)

        if user_input is not None:
            try:
                await self.plant_handler.async_add_plant(
                    growspace_id=self._selected_growspace_id,
                    strain=user_input["strain"],
                    row=user_input["row"],
                    col=user_input["col"],
                    phenotype=user_input.get("phenotype"),
                    veg_start=user_input.get("veg_start"),
                    flower_start=user_input.get("flower_start"),
                )
                return self.async_create_entry(title="", data={})
            except Exception as err:
                return self.async_show_form(
                    step_id="add_plant",
                    data_schema=self.plant_handler.get_add_plant_schema(
                        growspace, coordinator
                    ),
                    errors={"base": str(err)},
                )

        return self.async_show_form(
            step_id="add_plant",
            data_schema=self.plant_handler.get_add_plant_schema(growspace, coordinator),
        )

    async def async_step_update_plant(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for updating an existing plant."""
        coordinator = self.hass.data[DOMAIN][self._config_entry.entry_id]["coordinator"]
        plant = coordinator.plants.get(self._selected_plant_id)

        if not plant:
            return self.async_abort(reason="plant_not_found")

        if user_input is not None:
            try:
                # Filter out empty values
                update_data = {k: v for k, v in user_input.items() if v}
                await self.plant_handler.async_update_plant(
                    self._selected_plant_id, **update_data
                )
                return self.async_create_entry(title="", data={})
            except Exception as err:
                return self.async_show_form(
                    step_id="update_plant",
                    data_schema=self.plant_handler.get_update_plant_schema(
                        plant, coordinator
                    ),
                    errors={"base": str(err)},
                )

        return self.async_show_form(
            step_id="update_plant",
            data_schema=self.plant_handler.get_update_plant_schema(plant, coordinator),
        )

    async def async_step_manage_strain_library(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the menu for managing the strain library."""
        coordinator = self.hass.data[DOMAIN][self._config_entry.entry_id]["coordinator"]

        if user_input is not None:
            action = user_input.get("action")
            if action == "add_strain":
                return await self.async_step_add_strain()
            if action == "edit_strain":
                self._selected_strain_id = user_input.get("strain_id")
                return await self.async_step_edit_strain()
            if action == "delete_strain":
                await coordinator.strain_library.async_delete_strain(
                    user_input.get("strain_id")
                )
                return self.async_show_form(
                    step_id="manage_strain_library",
                    data_schema=self._get_strain_library_menu_schema(coordinator),
                )
            if action == "import":
                return await self.async_step_import_strain_library()
            if action == "export":
                return await self.async_step_export_strain_library()
            if action == "back":
                return self.async_show_form(
                    step_id="init",
                    data_schema=self._get_main_menu_schema(),
                )

        return self.async_show_form(
            step_id="manage_strain_library",
            data_schema=self._get_strain_library_menu_schema(coordinator),
        )

    def _get_strain_library_menu_schema(self, coordinator) -> vol.Schema:
        """Build the schema for the strain library menu."""
        strains = coordinator.strain_library.get_all_strains()
        strain_options = [
            selector.SelectOptionDict(value=s.id, label=s.name) for s in strains
        ]

        schema = {
            vol.Required("action"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(
                            value="add_strain", label="Add New Strain"
                        ),
                        selector.SelectOptionDict(
                            value="edit_strain", label="Edit Strain"
                        ),
                        selector.SelectOptionDict(
                            value="delete_strain", label="Delete Strain"
                        ),
                        selector.SelectOptionDict(
                            value="import", label="Import Library"
                        ),
                        selector.SelectOptionDict(
                            value="export", label="Export Library"
                        ),
                        selector.SelectOptionDict(
                            value="back", label="Back to Main Menu"
                        ),
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        }

        if strain_options:
            schema[vol.Optional("strain_id")] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=strain_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )

        return vol.Schema(schema)

    async def async_step_add_strain(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for adding a new strain."""
        coordinator = self.hass.data[DOMAIN][self._config_entry.entry_id]["coordinator"]

        if user_input is not None:
            await coordinator.strain_library.async_add_strain(
                name=user_input["strain"],
                breeder=user_input.get("breeder"),
                strain_type=user_input.get("type"),
                sex=user_input.get("sex"),
                description=user_input.get("description"),
                flowering_days=user_input.get("flower_days_max"),  # Simplified mapping
            )
            return await self.async_step_manage_strain_library()

        return self.async_show_form(
            step_id="add_strain",
            data_schema=self._get_add_strain_schema(),
        )

    async def async_step_edit_strain(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for editing a strain."""

        if user_input is not None:
            # Update logic here
            # For now, just return to menu as this is a placeholder restoration
            return await self.async_step_manage_strain_library()

        return self.async_show_form(
            step_id="edit_strain",
            data_schema=self._get_add_strain_schema(),  # Reuse add schema for now
        )

    def _get_add_strain_schema(self) -> vol.Schema:
        """Build the schema for adding a new strain."""
        return vol.Schema(
            {
                vol.Required("strain"): selector.TextSelector(),
                vol.Optional("phenotype"): selector.TextSelector(),
                vol.Optional("breeder"): selector.TextSelector(),
                vol.Optional("type"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value="Sativa", label="Sativa"),
                            selector.SelectOptionDict(value="Indica", label="Indica"),
                            selector.SelectOptionDict(value="Hybrid", label="Hybrid"),
                            selector.SelectOptionDict(
                                value="Ruderalis", label="Ruderalis"
                            ),
                        ],
                        custom_value=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional("sex"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value="Feminized", label="Feminized"
                            ),
                            selector.SelectOptionDict(value="Regular", label="Regular"),
                            selector.SelectOptionDict(
                                value="Autoflower", label="Autoflower"
                            ),
                        ],
                        custom_value=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional("lineage"): selector.TextSelector(),
                vol.Optional("sativa_percentage"): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=100,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="%",
                    )
                ),
                vol.Optional("indica_percentage"): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=100,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="%",
                    )
                ),
                vol.Optional("flower_days_min"): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional("flower_days_max"): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional("description"): selector.TextSelector(
                    selector.TextSelectorConfig(multiline=True)
                ),
            }
        )

    async def async_step_import_strain_library(self, user_input=None):
        """Import strain library from ZIP."""
        errors = {}
        if user_input is not None:
            try:
                coordinator = self.hass.data[DOMAIN][self._config_entry.entry_id][
                    "coordinator"
                ]
                file_path = user_input["file_path"]

                # Use default image directory if not specified
                # In a real scenario, we might want to let the user choose or use a fixed path
                target_dir = self.hass.config.path("www/growspace_images")

                await coordinator.import_export_manager.import_library(
                    file_path, target_dir
                )

                # Reload strains to reflect changes
                await coordinator.strains.async_load()

                return await self.async_step_manage_strain_library()
            except FileNotFoundError:
                errors["base"] = "file_not_found"
            except ValueError:
                errors["base"] = "invalid_zip"
            except Exception as e:
                _LOGGER.error("Import failed: %s", e)
                errors["base"] = "import_failed"

        return self.async_show_form(
            step_id="import_strain_library",
            data_schema=vol.Schema(
                {
                    vol.Required("file_path"): selector.TextSelector(),
                }
            ),
            errors=errors,
            description_placeholders={
                "default_path": "/config/strain_library_export.zip"
            },
        )

    async def async_step_export_strain_library(self, user_input=None):
        """Export strain library to ZIP."""
        if user_input is not None:
            return await self.async_step_manage_strain_library()

        coordinator = self.hass.data[DOMAIN][self._config_entry.entry_id]["coordinator"]

        # Default export location
        export_dir = self.hass.config.path("exports")

        try:
            zip_path = await coordinator.import_export_manager.export_library(
                coordinator.strains.get_all(), export_dir
            )
            return self.async_show_form(
                step_id="export_strain_library",
                description_placeholders={"path": zip_path},
                last_step=True,
            )
        except Exception as e:
            _LOGGER.error("Export failed: %s", e)
            return self.async_abort(reason="export_failed")

    def _process_environment_input(
        self, user_input: dict[str, Any], growspace_options: dict[str, Any]
    ) -> dict[str, Any]:
        """Process user input and merge with existing options."""
        user_input = {k: v for k, v in user_input.items() if v is not None and v != ""}

        env_config = growspace_options.copy()
        env_config.update(user_input)

        # Clear disabled features
        if not env_config.get("configure_light"):
            env_config["light_sensor"] = None
        if not env_config.get("configure_fan"):
            env_config["circulation_fan"] = None
        if not env_config.get("configure_co2"):
            env_config["co2_sensor"] = None
        if not env_config.get("configure_exhaust"):
            env_config["exhaust_sensor"] = None
        if not env_config.get("configure_humidifier"):
            env_config["humidifier_sensor"] = None

        return env_config

    def _get_environment_schema_step1(
        self, growspace_options: dict[str, Any]
    ) -> vol.Schema:
        """Build the schema for the first step of environment configuration."""
        schema_dict = {}

        self._add_basic_sensors_to_schema(schema_dict, growspace_options)
        self._add_lst_offset_to_schema(schema_dict, growspace_options)
        self._add_optional_features_to_schema(schema_dict, growspace_options)
        self._add_exhaust_humidifier_to_schema(schema_dict, growspace_options)
        self._add_dehumidifier_to_schema(schema_dict, growspace_options)

        return vol.Schema(schema_dict)

    def _add_basic_sensors_to_schema(
        self, schema_dict: dict, growspace_options: dict[str, Any]
    ) -> None:
        """Add basic sensors (temp, humidity, vpd) to the schema."""
        # Basic sensors
        for key, device_class in [
            ("temperature_sensor", "temperature"),
            ("humidity_sensor", "humidity"),
        ]:
            schema_dict[vol.Optional(key, default=growspace_options.get(key))] = (
                selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["sensor", "input_number"],
                        device_class=device_class,
                    )
                )
            )

        # VPD sensor - optional
        schema_dict[
            vol.Optional(
                "vpd_sensor",
                default=growspace_options.get("vpd_sensor") or vol.UNDEFINED,
            )
        ] = selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=["sensor", "input_number"],
                device_class="pressure",
            )
        )

    def _add_lst_offset_to_schema(
        self, schema_dict: dict, growspace_options: dict[str, Any]
    ) -> None:
        """Add LST offset to the schema if applicable."""
        has_temp = bool(growspace_options.get("temperature_sensor"))
        has_humidity = bool(growspace_options.get("humidity_sensor"))
        has_vpd = bool(growspace_options.get("vpd_sensor"))

        if has_temp and has_humidity and not has_vpd:
            schema_dict[
                vol.Optional(
                    "lst_offset",
                    default=growspace_options.get("lst_offset", -2.0),
                )
            ] = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=-5.0,
                    max=5.0,
                    step=0.5,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="°C",
                )
            )

    def _add_optional_features_to_schema(
        self, schema_dict: dict, growspace_options: dict[str, Any]
    ) -> None:
        """Add optional features (light, co2, fan) to the schema."""
        for feature in ["light", "co2", "fan"]:
            enabled = growspace_options.get(
                f"configure_{feature}",
                bool(growspace_options.get(f"{feature}_sensor")),
            )
            schema_dict[vol.Optional(f"configure_{feature}", default=enabled)] = (
                selector.BooleanSelector()
            )
            if enabled:
                self._add_feature_entity_selector(
                    schema_dict, feature, growspace_options
                )

    def _add_feature_entity_selector(
        self, schema_dict: dict, feature: str, growspace_options: dict[str, Any]
    ) -> None:
        """Add the entity selector for a specific feature."""
        if feature == "light":
            entity_key = "light_sensor"
            domain = ["switch", "light", "input_boolean", "sensor"]
            device_class = None
        elif feature == "fan":
            entity_key = "circulation_fan"
            domain = [
                "fan",
                "switch",
                "input_boolean",
                "sensor",
                "input_number",
            ]
            device_class = None
        else:  # co2
            entity_key = f"{feature}_sensor"
            domain = ["sensor", "input_number"]
            device_class = ["carbon_dioxide"]

        entity_selector_config_args: dict[str, Any] = {"domain": domain}
        if device_class is not None:
            entity_selector_config_args["device_class"] = device_class

        schema_dict[
            vol.Optional(
                entity_key,
                default=growspace_options.get(entity_key) or vol.UNDEFINED,
            )
        ] = selector.EntitySelector(
            selector.EntitySelectorConfig(**entity_selector_config_args)
        )

    def _add_exhaust_humidifier_to_schema(
        self, schema_dict: dict, growspace_options: dict[str, Any]
    ) -> None:
        """Add exhaust and humidifier to the schema."""
        for feature in ["exhaust", "humidifier"]:
            enabled = growspace_options.get(
                f"configure_{feature}",
                bool(growspace_options.get(f"{feature}_sensor")),
            )
            schema_dict[vol.Optional(f"configure_{feature}", default=enabled)] = (
                selector.BooleanSelector()
            )
            if enabled:
                schema_dict[
                    vol.Optional(
                        f"{feature}_sensor",
                        default=growspace_options.get(f"{feature}_sensor")
                        or vol.UNDEFINED,
                    )
                ] = selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["sensor", "input_number"],
                        device_class="power_factor",
                    )
                )

    def _add_dehumidifier_to_schema(
        self, schema_dict: dict, growspace_options: dict[str, Any]
    ) -> None:
        """Add dehumidifier to the schema."""
        configure_dehumidifier = growspace_options.get(
            "configure_dehumidifier", bool(growspace_options.get("dehumidifier_entity"))
        )
        schema_dict[
            vol.Optional("configure_dehumidifier", default=configure_dehumidifier)
        ] = selector.BooleanSelector()

        if configure_dehumidifier:
            schema_dict[
                vol.Optional(
                    "dehumidifier_entity",
                    default=growspace_options.get("dehumidifier_entity")
                    or vol.UNDEFINED,
                )
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["switch", "humidifier", "sensor", "binary_sensor"]
                )
            )
            schema_dict[
                vol.Optional(
                    "control_dehumidifier",
                    default=growspace_options.get("control_dehumidifier", False),
                )
            ] = selector.BooleanSelector()
        for key, default in [("stress_threshold", 0.70), ("mold_threshold", 0.75)]:
            schema_dict[
                vol.Optional(key, default=growspace_options.get(key, default))
            ] = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.5,
                    max=0.95,
                    step=0.05,
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            )

        # Photoperiod Configuration
        schema_dict[
            vol.Optional(
                "veg_day_hours",
                default=growspace_options.get("veg_day_hours", DEFAULT_VEG_DAY_HOURS),
            )
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1, max=24, step=1, mode=selector.NumberSelectorMode.BOX
            )
        )

        for stage in ["flower_early", "flower_mid", "flower_late"]:
            schema_dict[
                vol.Optional(
                    f"{stage}_day_hours",
                    default=growspace_options.get(
                        f"{stage}_day_hours", DEFAULT_FLOWER_DAY_HOURS
                    ),
                )
            ] = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=24, step=1, mode=selector.NumberSelectorMode.BOX
                )
            )

        # Thresholds
        schema_dict[
            vol.Optional(
                "minimum_source_air_temperature",
                default=growspace_options.get("minimum_source_air_temperature", 18),
            )
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=10, max=25, step=1, mode=selector.NumberSelectorMode.SLIDER
            )
        )

        # Trend analysis settings (fallback)
        for trend_type, default_threshold in [("vpd", 1.2), ("temp", 26.0)]:
            schema_dict[
                vol.Optional(
                    f"trend_{trend_type}_threshold",
                    default=growspace_options.get(
                        f"trend_{trend_type}_threshold", default_threshold
                    ),
                )
            ] = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.1, max=50.0, step=0.1, mode=selector.NumberSelectorMode.BOX
                )
            )

            schema_dict[
                vol.Optional(
                    f"{trend_type}_trend_duration",
                    default=growspace_options.get(f"{trend_type}_trend_duration", 30),
                )
            ] = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=5,
                    max=120,
                    step=5,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="minutes",
                )
            )
            if trend_type == "temp":
                schema_dict[
                    vol.Optional(
                        f"{trend_type}_trend_threshold",
                        default=growspace_options.get(
                            f"{trend_type}_trend_threshold", default_threshold
                        ),
                    )
                ] = selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=20,
                        max=35,
                        step=0.5,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="°C",
                    )
                )
            schema_dict[
                vol.Optional(
                    f"{trend_type}_trend_sensitivity",
                    default=growspace_options.get(
                        f"{trend_type}_trend_sensitivity", 0.5
                    ),
                )
            ] = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.1, max=1.0, step=0.1, mode=selector.NumberSelectorMode.SLIDER
                )
            )

        # Advanced settings toggle
        schema_dict[vol.Optional("configure_advanced", default=False)] = (
            selector.BooleanSelector()
        )

        return vol.Schema(schema_dict)
