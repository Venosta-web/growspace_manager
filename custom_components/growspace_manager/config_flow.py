"""Configuration flow for the Growspace Manager integration.

This file manages the user interface for setting up and configuring the
Growspace Manager integration, including the initial setup (ConfigFlow) and
subsequent modifications (OptionsFlow). It provides a graphical user interface
for managing growspaces, plants, and environment sensor configurations.
"""

from __future__ import annotations

import ast
import logging
import uuid
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import conversation
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import selector

from .const import (
    AI_PERSONALITIES,
    CONF_AI_ENABLED,
    CONF_ASSISTANT_ID,
    CONF_NOTIFICATION_PERSONALITY,
    DEFAULT_NAME,
    DOMAIN,
)
from .models import Growspace, Plant

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
            await coordinator.async_set_updated_data(coordinator.data)
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
                    data_schema=self._get_add_growspace_schema(),
                    errors={"base": f"Error: {err}"},
                )

        _LOGGER.debug("Showing add_growspace form")
        return self.async_show_form(
            step_id="add_growspace",
            data_schema=self._get_add_growspace_schema(),
        )

    def _get_add_growspace_schema(self):
        """Build the voluptuous schema for the add growspace form.

        Returns:
            A voluptuous schema for the form.
        """
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
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self._get_main_menu_schema(),
        )

    async def async_step_configure_ai(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for configuring AI settings.

        Args:
            user_input: The user's input from the form, if any.

        Returns:
            A ConfigFlowResult.
        """
        if user_input is not None:
            new_options = self._config_entry.options.copy()
            new_options["ai_settings"] = user_input

            # Also update coordinator if needed, but options update triggers reload usually
            self.hass.config_entries.async_update_entry(
                self._config_entry, options=new_options
            )
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="configure_ai",
            data_schema=await self._get_ai_settings_schema(),
        )

    async def _get_ai_settings_schema(self) -> vol.Schema:
        """Build the schema for AI settings.

        Returns:
            A voluptuous schema for the form.
        """
        current_settings = self._config_entry.options.get("ai_settings", {})

        # Get available assistants
        assistants = []
        if "conversation" in self.hass.data:
            agent_manager = self.hass.data["conversation"]
            # Attempt to use the modern AgentManager method
            if hasattr(agent_manager, "async_get_agents"):
                assistants = await agent_manager.async_get_agents()

        if not assistants:
            # Fallback to default agent if no agents returned (or manager missing)
            try:
                # conversation.async_get_agent(hass) gets the default agent
                default_agent = await conversation.async_get_agent(self.hass)
                if default_agent:
                    assistants = [default_agent]
            except Exception:
                pass

        # Filter to ensure we have valid agent objects
        valid_assistants = [
            a for a in assistants
            if hasattr(a, "id") and hasattr(a, "name")
        ]

        assistant_options = [
            selector.SelectOptionDict(value=assistant.id, label=assistant.name)
            for assistant in valid_assistants
        ]

        schema = {
            vol.Required(
                CONF_AI_ENABLED, default=current_settings.get(CONF_AI_ENABLED, False)
            ): selector.BooleanSelector(),
        }

        if assistant_options:
             schema[vol.Optional(
                CONF_ASSISTANT_ID, default=current_settings.get(CONF_ASSISTANT_ID)
            )] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=assistant_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )

        schema[vol.Optional(
            CONF_NOTIFICATION_PERSONALITY,
            default=current_settings.get(CONF_NOTIFICATION_PERSONALITY, "Standard")
        )] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=AI_PERSONALITIES,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )

        return vol.Schema(schema)

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

                    self.hass.config_entries.async_update_entry(
                        self._config_entry, options=new_options
                    )
                    coordinator.options = new_options

                    return self.async_show_form(
                        step_id="manage_timed_notifications",
                        data_schema=self._get_timed_notification_schema(coordinator),
                    )

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

            # Update the config entry and the coordinator's in-memory options
            self.hass.config_entries.async_update_entry(
                self._config_entry, options=new_options
            )
            coordinator.options = new_options

            return self.async_show_form(
                step_id="manage_timed_notifications",
                data_schema=self._get_timed_notification_schema(coordinator),
            )

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

            # Update the config entry and the coordinator's in-memory options
            self.hass.config_entries.async_update_entry(
                self._config_entry, options=new_options
            )
            coordinator.options = new_options

            return self.async_show_form(
                step_id="manage_timed_notifications",
                data_schema=self._get_timed_notification_schema(coordinator),
            )

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

        return vol.Schema(
            {
                vol.Required(
                    "growspace_ids", default=notification.get("growspace_ids", [])
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=growspace_options,
                        multiple=True,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
                vol.Required(
                    "trigger_type", default=notification.get("trigger_type", "flower")
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value="flower", label="Flower Day"
                            ),
                            selector.SelectOptionDict(value="veg", label="Veg Day"),
                        ]
                    )
                ),
                vol.Required(
                    "day", default=notification.get("day", 1)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    "message", default=notification.get("message", "")
                ): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.TEXT,
                    )
                ),
            }
        )

    async def async_step_manage_growspaces(
        self, user_input: dict[str, Any] | None | None
    ) -> ConfigFlowResult:
        """Show the menu for managing growspaces (add, update, remove).

        Args:
            user_input: The user's input from the form, if any.

        Returns:
            A ConfigFlowResult directing to the appropriate action.
        """
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
                    await coordinator.async_remove_growspace(user_input["growspace_id"])
                except Exception as err:
                    _LOGGER.error("Error removing growspace: %s", err, exc_info=True)
                    return self.async_show_form(
                        step_id="manage_growspaces",
                        data_schema=self._get_growspace_management_schema(coordinator),
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
            data_schema=self._get_growspace_management_schema(coordinator),
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
            # FIX: Filter out None and empty string values BEFORE processing
            user_input = {
                k: v for k, v in user_input.items() if v is not None and v != ""
            }

            self._env_config_step1 = (
                growspace_options.copy()
            )  # Start with existing config
            self._env_config_step1.update(user_input)  # Update with new values

            if user_input.get("configure_advanced"):
                return await self.async_step_configure_advanced_bayesian()

            # Not configuring advanced, so we save and finish
            env_config = self._env_config_step1.copy()
            env_config.pop("configure_advanced", None)

            # Already filtered above, but keep this as a safety check
            env_config = {
                k: v for k, v in env_config.items() if v is not None and v != ""
            }

            growspace.environment_config = env_config
            await coordinator.async_save()
            await coordinator.async_refresh()

            # OPTIONAL: Sync to config_entry.options
            # but it's not necessary if you're storing in the growspace object
            new_options = self._current_options.copy()
            new_options[self._selected_growspace_id] = env_config
            self.hass.config_entries.async_update_entry(
                self._config_entry, options=new_options
            )
            coordinator.options = new_options

            _LOGGER.info(
                "Environment configuration saved for growspace %s: %s",
                growspace.name,
                env_config,
            )
            return self.async_create_entry(title="", data={})

        schema_dict = {}

        # Basic sensors - Use growspace_options for defaults
        for key, device_class in [
            ("temperature_sensor", "temperature"),
            ("humidity_sensor", "humidity"),
            ("vpd_sensor", "pressure"),
        ]:
            schema_dict[vol.Optional(key, default=growspace_options.get(key))] = (
                selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["sensor", "input_number"],
                        device_class=device_class,
                    )
                )
            )

        # Optional features with toggles
        for feature in ["light", "co2", "fan"]:
            # Use growspace_options for defaults
            enabled = growspace_options.get(
                f"configure_{feature}", bool(growspace_options.get(f"{feature}_sensor"))
            )
            schema_dict[vol.Optional(f"configure_{feature}", default=enabled)] = (
                selector.BooleanSelector()
            )
            if enabled:
                if feature == "light":
                    entity_key = "light_sensor"
                    domain = ["switch", "light", "input_boolean", "sensor"]
                    device_class = None
                elif feature == "fan":
                    entity_key = "circulation_fan"
                    domain = ["fan", "switch", "input_boolean"]
                    device_class = None
                else:  # co2
                    entity_key = f"{feature}_sensor"
                    domain = ["sensor", "input_number"]
                    device_class = ["carbon_dioxide"]

                entity_selector_config_args: dict[str, Any] = {}
                entity_selector_config_args["domain"] = domain
                if device_class is not None:
                    entity_selector_config_args["device_class"] = device_class

                schema_dict[
                    vol.Optional(entity_key, default=growspace_options.get(entity_key))
                ] = selector.EntitySelector(
                    selector.EntitySelectorConfig(**entity_selector_config_args)
                )
        # Thresholds
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

        return self.async_show_form(
            step_id="configure_environment",
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

            final_options = self._config_entry.options.copy()
            final_options[self._selected_growspace_id] = env_config
            self.hass.config_entries.async_update_entry(
                self._config_entry, options=final_options
            )

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

    async def async_step_add_growspace(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for adding a new growspace.

        Args:
            user_input: The user's input from the form, if any.

        Returns:
            A ConfigFlowResult.
        """
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
            try:
                _LOGGER.debug("Config flow received growspace data: %s", user_input)
                _LOGGER.debug("About to call coordinator.async_add_growspace")
                growspace = await coordinator.async_add_growspace(
                    name=user_input["name"],
                    rows=user_input["rows"],
                    plants_per_row=user_input["plants_per_row"],
                    notification_target=user_input.get("notification_target"),
                )
                _LOGGER.debug(
                    "Successfully added growspace: %s with ID: %s",
                    user_input["name"],
                    growspace.id,
                )
                return self.async_create_entry(title="", data={})
            except Exception as err:
                _LOGGER.exception("Error adding growspace: %s", err)
                return self.async_show_form(
                    step_id="add_growspace",
                    data_schema=self._get_add_growspace_schema(),
                    errors={"base": "add_failed"},
                )

        _LOGGER.debug(
            "Showing add_growspace form with schema fields: %s",
            list(self._get_add_growspace_schema().schema.keys()),
        )
        return self.async_show_form(
            step_id="add_growspace",
            data_schema=self._get_add_growspace_schema(),
        )

    async def async_step_update_growspace(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for updating an existing growspace.

        Args:
            user_input: The user's input from the form, if any.

        Returns:
            A ConfigFlowResult.
        """
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
                # Filter out empty values
                update_data = {k: v for k, v in user_input.items() if v}

                # Call coordinator's update method (you'll need to implement this)
                await coordinator.async_update_growspace(
                    self._selected_growspace_id, **update_data
                )

                _LOGGER.info(
                    "Successfully updated growspace: %s", self._selected_growspace_id
                )
                return self.async_create_entry(title="", data={})

            except Exception as err:
                _LOGGER.error("Error updating growspace: %s", err, exc_info=True)
                return self.async_show_form(
                    step_id="update_growspace",
                    data_schema=self._get_update_growspace_schema(growspace),
                    errors={"base": "update_failed"},
                )

        return self.async_show_form(
            step_id="update_growspace",
            data_schema=self._get_update_growspace_schema(growspace),
        )

    async def async_step_manage_plants(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the menu for managing plants (add, update, remove).

        Args:
            user_input: The user's input from the form, if any.

        Returns:
            A ConfigFlowResult directing to the appropriate action.
        """
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
                    await coordinator.async_remove_plant(user_input["plant_id"])
                except Exception:
                    return self.async_show_form(
                        step_id="manage_plants",
                        data_schema=self._get_plant_management_schema(coordinator),
                        errors={"base": "remove_failed"},
                    )
            if action == "back":
                return self.async_show_form(
                    step_id="init",
                    data_schema=self.add_suggested_values_to_schema(
                        coordinator, self._config_entry.options
                    ),
                )

        return self.async_show_form(
            step_id="manage_plants",
            data_schema=self._get_plant_management_schema(coordinator),
        )

    async def async_step_select_growspace_for_plant(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show a form to select a growspace before adding a new plant.

        Args:
            user_input: The user's input from the form, if any.

        Returns:
            A ConfigFlowResult.
        """
        try:
            coordinator = self.hass.data[DOMAIN][self._config_entry.entry_id][
                "coordinator"
            ]
            # Reload coordinator data from storage to ensure we have latest growspaces
            store = self.hass.data[DOMAIN][self._config_entry.entry_id]["store"]
            fresh_data = await store.async_load() or {}

            # Correctly deserialize data into objects
            coordinator.growspaces = {
                gid: Growspace.from_dict(g)
                for gid, g in fresh_data.get("growspaces", {}).items()
            }
            coordinator.plants = {
                pid: Plant.from_dict(p)
                for pid, p in fresh_data.get("plants", {}).items()
            }

            coordinator._notifications_sent = fresh_data.get("notifications_sent", {})
            # Update the data property
            coordinator.data = {
                "growspaces": coordinator.growspaces,
                "plants": coordinator.plants,
                "notifications_sent": coordinator._notifications_sent,
            }
        except KeyError:
            _LOGGER.error(
                "Coordinator not found - integration may not be properly set up"
            )
            return self.async_abort(reason="setup_error")

        _LOGGER.info(f"Config entry ID: {self._config_entry.entry_id}")
        _LOGGER.info(
            f"Available growspaces in coordinator: {list(coordinator.growspaces.keys())}"
        )

        # Get growspaces from device registry
        device_registry = dr.async_get(self.hass)
        devices = device_registry.devices.get_devices_for_config_entry_id(
            self._config_entry.entry_id
        )

        _LOGGER.info(f"Total devices for config entry: {len(devices)}")
        _LOGGER.info(
            f"All devices: {[(d.name, d.model, d.identifiers) for d in devices]}"
        )

        # Filter for growspace devices
        growspace_devices = [
            device
            for device in devices
            if device.model == "Growspace"
            and any(identifier[0] == DOMAIN for identifier in device.identifiers)
        ]

        _LOGGER.info(f"Found {len(growspace_devices)} growspace devices")
        for device in growspace_devices:
            _LOGGER.info(f"Growspace device: {device.name} - {device.identifiers}")

        if not growspace_devices:
            _LOGGER.warning("No growspace devices found in device registry")
            return self.async_show_form(
                step_id="select_growspace_for_plant",
                data_schema=vol.Schema({}),
                errors={
                    "base": "No growspaces available. Please create a growspace first."
                },
            )

        if user_input is not None:
            self._selected_growspace_id = user_input["growspace_id"]
            return await self.async_step_add_plant()

        return self.async_show_form(
            step_id="select_growspace_for_plant",
            data_schema=self._get_growspace_selection_schema_from_devices(
                growspace_devices, coordinator
            ),
        )

    async def async_step_add_plant(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for adding a new plant to a selected growspace.

        Args:
            user_input: The user's input from the form, if any.

        Returns:
            A ConfigFlowResult.
        """
        coordinator = self.hass.data[DOMAIN][self._config_entry.entry_id]["coordinator"]
        growspace = coordinator.growspaces.get(self._selected_growspace_id)

        if user_input is not None:
            try:
                await coordinator.async_add_plant(
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
                    data_schema=self._get_add_plant_schema(growspace, coordinator),
                    errors={"base": str(err)},
                )

        return self.async_show_form(
            step_id="add_plant",
            data_schema=self._get_add_plant_schema(growspace, coordinator),
        )

    async def async_step_update_plant(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for updating an existing plant.

        Args:
            user_input: The user's input from the form, if any.

        Returns:
            A ConfigFlowResult.
        """
        coordinator = self.hass.data[DOMAIN][self._config_entry.entry_id]["coordinator"]
        plant = coordinator.plants.get(self._selected_plant_id)

        if not plant:
            return self.async_abort(reason="plant_not_found")

        if user_input is not None:
            try:
                # Filter out empty values
                update_data = {k: v for k, v in user_input.items() if v}
                await coordinator.async_update_plant(
                    self._selected_plant_id, **update_data
                )
                return self.async_create_entry(title="", data={})
            except Exception as err:
                return self.async_show_form(
                    step_id="update_plant",
                    data_schema=self._get_update_plant_schema(plant, coordinator),
                    errors={"base": str(err)},
                )

        return self.async_show_form(
            step_id="update_plant",
            data_schema=self._get_update_plant_schema(plant, coordinator),
        )

    def _get_growspace_management_schema(self, coordinator) -> vol.Schema:
        """Build the schema for the growspace management menu.

        Args:
            coordinator: The data update coordinator.

        Returns:
            A voluptuous schema for the form.
        """
        growspace_options = [
            selector.SelectOptionDict(
                value=growspace_id,
                label=f"{growspace.name} ({len(coordinator.get_growspace_plants(growspace_id))} plants)",
            )
            for growspace_id, growspace in coordinator.growspaces.items()
        ]

        schema: dict[Any, Any] = {
            vol.Required("action"): selector.SelectSelector(
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
                            value="back", label="← Back to Main Menu"
                        ),
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        }

        if growspace_options:
            schema[vol.Optional("growspace_id")] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=growspace_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    custom_value=True,  # ✅ allow typing a new growspace
                )
            )
        else:
            # If no growspaces exist yet, allow text input only
            schema[vol.Optional("growspace_id")] = selector.TextSelector()

        return vol.Schema(schema)

    def _get_add_growspace_schema(self):
        """Build the schema for the add growspace form.

        Returns:
            A voluptuous schema for the form.
        """
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
            base[vol.Required("notification_target")] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=notification_options,
                    custom_value=False,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        else:
            # No notify services available, allow leaving it empty
            _LOGGER.info(
                "No notify services found – notification_target will be optional."
            )
            base[vol.Required("notification_target")] = selector.TextSelector()

        return vol.Schema(base)

    def _get_update_growspace_schema(self, growspace) -> vol.Schema:
        """Build the schema for the update growspace form.

        Args:
            growspace: The growspace object to pre-fill the form.

        Returns:
            A voluptuous schema for the form.
        """
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

        # Add "None" option to allow clearing notification target
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
            self.hass.config_entries.async_update_entry(
                self._config_entry, options=new_options
            )
            return self.async_create_entry(title="", data={})

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
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )

    def _get_plant_management_schema(self, coordinator) -> vol.Schema:
        """Build the schema for the plant management menu.

        Args:
            coordinator: The data update coordinator.

        Returns:
            A voluptuous schema for the form.
        """
        plant_options = []

        for plant_id, plant in coordinator.plants.items():
            # plant is now a Plant object
            growspace = coordinator.growspaces.get(plant.growspace_id)
            growspace_name = (
                getattr(growspace, "name", "Unknown") if growspace else "Unknown"
            )
            label = f"{plant.strain} - {growspace_name} ({plant.row},{plant.col})"
            plant_options.append(selector.SelectOptionDict(value=plant_id, label=label))

        schema = {
            vol.Required("action"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value="add", label="Add New Plant"),
                        selector.SelectOptionDict(value="update", label="Update Plant"),
                        selector.SelectOptionDict(value="remove", label="Remove Plant"),
                        selector.SelectOptionDict(
                            value="back", label="← Back to Main Menu"
                        ),
                    ]
                )
            )
        }

        if plant_options:
            schema[vol.Required("plant_id")] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=plant_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )

        return vol.Schema(schema)

    def _get_growspace_selection_schema_from_devices(
        self, growspace_devices, coordinator
    ) -> vol.Schema:
        """Build the schema for selecting a growspace from the device registry.

        Args:
            growspace_devices: A list of growspace device objects.
            coordinator: The data update coordinator.

        Returns:
            A voluptuous schema for the form.
        """
        growspace_options = []

        for device in growspace_devices:
            # Extract growspace_id from device identifiers
            growspace_id = None
            for identifier_set in device.identifiers:
                if identifier_set[0] == DOMAIN:
                    growspace_id = identifier_set[1]
                    break

            if growspace_id:
                growspace_obj = coordinator.growspaces.get(growspace_id)
                rows = getattr(growspace_obj, "rows", "?")
                plants_per_row = getattr(growspace_obj, "plants_per_row", "?")

                growspace_options.append(
                    selector.SelectOptionDict(
                        value=growspace_id,
                        label=f"{device.name} ({rows}x{plants_per_row})",
                    )
                )

        return vol.Schema(
            {
                vol.Required("growspace_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=growspace_options)
                ),
            }
        )

    def _get_add_plant_schema(self, growspace, coordinator=None) -> vol.Schema:
        """Build the schema for the add plant form.

        Args:
            growspace: The growspace object where the plant will be added.
            coordinator: The data update coordinator.

        Returns:
            A voluptuous schema for the form.
        """
        if not growspace:
            return vol.Schema({})

        rows = getattr(growspace, "rows", 10)
        plants_per_row = getattr(growspace, "plants_per_row", 10)

        # Get strain options for autocomplete
        strain_options = []
        if coordinator:
            strain_list = coordinator.get_strain_options()
            strain_options = [
                selector.SelectOptionDict(value=strain, label=strain)
                for strain in strain_list
            ]

        strain_selector = (
            selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=strain_options,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
            if strain_options
            else selector.TextSelector()
        )

        return vol.Schema(
            {
                vol.Required("strain"): strain_selector,
                vol.Optional("phenotype"): selector.TextSelector(),
                vol.Required("row", default=1): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=rows, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required("col", default=1): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=plants_per_row, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional("veg_start"): selector.DateSelector(),
                vol.Optional("flower_start"): selector.DateSelector(),
            }
        )

    def _get_update_plant_schema(self, plant, coordinator) -> vol.Schema:
        """Build the schema for the update plant form.

        Args:
            plant: The plant object to pre-fill the form.
            coordinator: The data update coordinator.

        Returns:
            A voluptuous schema for the form.
        """
        growspace = coordinator.growspaces.get(plant.growspace_id) if plant else None

        # Ensure rows and plants_per_row are integers
        rows = int(growspace.rows) if growspace else 10
        plants_per_row = int(growspace.plants_per_row) if growspace else 10

        # Get strain options for autocomplete
        strain_options = []
        strain_list = coordinator.get_strain_options()
        strain_options = [
            selector.SelectOptionDict(value=strain, label=strain)
            for strain in strain_list
        ]

        # Use autocomplete selector if we have strains, otherwise text input
        if strain_options:
            strain_selector = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=strain_options,
                    custom_value=True,  # Allow custom entries
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        else:
            strain_selector = selector.TextSelector()

        return vol.Schema(
            {
                vol.Optional(
                    "strain", default=plant.strain if plant else ""
                ): strain_selector,
                vol.Optional(
                    "phenotype", default=plant.phenotype if plant else ""
                ): selector.TextSelector(),
                vol.Optional("row", default=plant.row if plant else 1): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=rows, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional("col", default=plant.col if plant else 1): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=plants_per_row, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional("veg_start"): selector.DateSelector(),
                vol.Optional("flower_start"): selector.DateSelector(),
            }
        )

    async def async_step_manage_strain_library(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the menu for managing the strain library."""
        coordinator = self.hass.data[DOMAIN][self._config_entry.entry_id][
            "coordinator"
        ]

        if user_input is not None:
            action = user_input.get("action")
            if action == "add":
                return await self.async_step_add_strain()
            if action == "remove":
                strain_to_remove = user_input.get("strain_id")
                if strain_to_remove:
                    strain, phenotype = strain_to_remove.split("|")
                    await coordinator.strains.remove_strain_phenotype(strain, phenotype)
                    # Return to menu after action
                    return self.async_show_form(
                        step_id="manage_strain_library",
                        data_schema=self._get_strain_management_schema(coordinator),
                    )
            if action == "back":
                return self.async_show_form(
                    step_id="init",
                    data_schema=self.add_suggested_values_to_schema(
                        self._get_main_menu_schema(), self._config_entry.options
                    ),
                )

        return self.async_show_form(
            step_id="manage_strain_library",
            data_schema=self._get_strain_management_schema(coordinator),
        )

    async def async_step_add_strain(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for adding a new strain."""
        coordinator = self.hass.data[DOMAIN][self._config_entry.entry_id][
            "coordinator"
        ]

        if user_input is not None:
            try:
                await coordinator.strains.add_strain(
                    strain=user_input["strain"],
                    phenotype=user_input.get("phenotype"),
                    breeder=user_input.get("breeder"),
                    strain_type=user_input.get("type"),
                    lineage=user_input.get("lineage"),
                    sex=user_input.get("sex"),
                    flower_days_min=user_input.get("flower_days_min"),
                    flower_days_max=user_input.get("flower_days_max"),
                    description=user_input.get("description"),
                    sativa_percentage=user_input.get("sativa_percentage"),
                    indica_percentage=user_input.get("indica_percentage"),
                )
                return self.async_show_form(
                    step_id="manage_strain_library",
                    data_schema=self._get_strain_management_schema(coordinator),
                )
            except Exception as err:
                _LOGGER.error("Error adding strain: %s", err)
                return self.async_show_form(
                    step_id="add_strain",
                    data_schema=self._get_add_strain_schema(),
                    errors={"base": str(err)},
                )

        return self.async_show_form(
            step_id="add_strain",
            data_schema=self._get_add_strain_schema(),
        )

    def _get_strain_management_schema(self, coordinator) -> vol.Schema:
        """Build the schema for the strain management menu."""
        strain_options = []
        all_strains = coordinator.strains.get_all()

        for strain_name, data in all_strains.items():
            phenotypes = data.get("phenotypes", {})
            for pheno_name in phenotypes:
                label = f"{strain_name}"
                if pheno_name and pheno_name != "default":
                    label += f" ({pheno_name})"

                value = f"{strain_name}|{pheno_name}"
                strain_options.append(
                    selector.SelectOptionDict(value=value, label=label)
                )

        # Sort alphabetically
        strain_options.sort(key=lambda x: x["label"])

        schema = {
            vol.Required("action"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value="add", label="Add New Strain"),
                        selector.SelectOptionDict(value="remove", label="Remove Strain/Phenotype"),
                        selector.SelectOptionDict(value="back", label="← Back to Main Menu"),
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
                            selector.SelectOptionDict(value="Ruderalis", label="Ruderalis"),
                        ],
                        custom_value=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional("sex"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value="Feminized", label="Feminized"),
                            selector.SelectOptionDict(value="Regular", label="Regular"),
                            selector.SelectOptionDict(value="Autoflower", label="Autoflower"),
                        ],
                        custom_value=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional("lineage"): selector.TextSelector(),
                vol.Optional("sativa_percentage"): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=100, mode=selector.NumberSelectorMode.BOX, unit_of_measurement="%"
                    )
                ),
                vol.Optional("indica_percentage"): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=100, mode=selector.NumberSelectorMode.BOX, unit_of_measurement="%"
                    )
                ),
                vol.Optional("flower_days_min"): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Optional("flower_days_max"): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Optional("description"): selector.TextSelector(
                    selector.TextSelectorConfig(multiline=True)
                ),
            }
        )
