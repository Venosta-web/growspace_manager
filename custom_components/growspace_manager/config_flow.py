"""Enhanced config flow for Growspace Manager integration with plant management GUI."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import (
    ConfigFlowResult,
    OptionsFlow,
    ConfigEntry,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers import selector
from homeassistant.helpers import device_registry as dr


from .const import DOMAIN, DEFAULT_NAME

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


async def ensure_default_growspaces(hass: HomeAssistant, coordinator):
    """Ensure default growspaces (dry, cure, mother, clone, veg) exist."""
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
            canonical_id = coordinator.ensure_special_growspace(
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

    except Exception as err:
        _LOGGER.error("Error creating default growspaces: %s")


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Growspace Manager."""

    VERSION = 1
    MINOR_VERSION = 1
    integration_name = "Growspace Manager"

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        try:
            _LOGGER.info("DEBUG - async_step_user called with input: %s", user_input)

            if user_input is not None:
                name = user_input.get("name", DEFAULT_NAME)
                _LOGGER.info(
                    "DEBUG - Processing user input, storing integration name: %s",
                    name,
                )
                return self.async_create_entry(
                    title=name,
                    data={"name": name},
                )

            _LOGGER.info("DEBUG - Showing initial user form")
            return self.async_show_form(
                step_id="user",
                data_schema=STEP_USER_DATA_SCHEMA,
            )

        except Exception:
            _LOGGER.exception(
                "Error in async_step_user: %s ,{type(err).__name__}: {err}"
            )
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {vol.Optional("name", default=DEFAULT_NAME): cv.string}
                ),
                errors={"base": "Error: %s ,{str(err)}"},
            )

    async def async_step_add_growspace(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a growspace during initial setup."""
        if user_input is not None:
            try:
                _LOGGER.info(
                    "DEBUG - ConfigFlow received growspace data: %s", user_input
                )

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

                _LOGGER.info(
                    "DEBUG - Stored pending growspace data: %s %s ,{self.hass.data[DOMAIN],['pending_growspace']}"
                )
                return entry

            except Exception:
                _LOGGER.exception("Error in async_step_user: %s", self)
                return self.async_show_form(
                    step_id="add_growspace",
                    data_schema=self._get_add_growspace_schema(),
                )

        _LOGGER.info("DEBUG - Showing add_growspace form")
        return self.async_show_form(
            step_id="add_growspace",
            data_schema=self._get_add_growspace_schema(),
        )

    def _get_add_growspace_schema(self):
        """Dynamic schema for adding a growspace during config flow."""
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
        """Create the options flow."""
        return OptionsFlowHandler()


class OptionsFlowHandler(OptionsFlow):
    """Growspace Manager options flow."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Initial options menu."""
        if user_input is not None:
            action = user_input.get("action")
            if action == "manage_growspaces":
                return await self.async_step_manage_growspaces(user_input)
            if action == "manage_plants":
                return await self.async_step_manage_plants()
            if action == "configure_environment":
                return await self.async_step_select_growspace_for_env()
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self._get_main_menu_schema(),
        )

    async def async_step_manage_growspaces(
        self, user_input: Optional[dict[str, Any]] | None
    ) -> ConfigFlowResult:
        """Manage growspaces."""
        try:
            coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id][
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
                        self._get_main_menu_schema(), self.config_entry.options
                    ),
                )

        return self.async_show_form(
            step_id="manage_growspaces",
            data_schema=self._get_growspace_management_schema(coordinator),
        )

    async def async_step_select_growspace_for_env(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user select which growspace to configure."""
        coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]["coordinator"]
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
        """Handle the configuration of environment sensors."""
        coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]["coordinator"]
        growspace = coordinator.growspaces.get(self._selected_growspace_id)

        if not growspace:
            return self.async_abort(reason="growspace_not_found")

        options = self.config_entry.options.get(self._selected_growspace_id, {})

        if user_input is not None:
            self._env_config_step1 = options.copy()
            self._env_config_step1.update(user_input)

            if user_input.get("configure_advanced"):
                return await self.async_step_configure_advanced_bayesian()

            # Not configuring advanced, so we save and finish
            env_config = self._env_config_step1
            env_config.pop("configure_advanced", None)  # Remove flow control key

            growspace.environment_config = env_config
            await coordinator.async_save()
            await coordinator.async_refresh()

            final_options = self.config_entry.options.copy()
            final_options[self._selected_growspace_id] = env_config
            _LOGGER.info(
                "Environment configuration saved for growspace %s: %s",
                growspace.name,
                env_config,
            )
            return self.async_create_entry(title="", data=final_options)

        schema_dict = {}

        # Basic sensors
        for key, device_class in [
            ("temperature_sensor", "temperature"),
            ("humidity_sensor", "humidity"),
            ("vpd_sensor", None),
        ]:
            schema_dict[vol.Required(key, default=options.get(key))] = (
                selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["sensor", "input_number"], device_class=device_class
                    )
                )
            )

        # Light sensor
        schema_dict[vol.Optional("light_sensor", default=options.get("light_sensor"))] = (
            selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["switch", "light", "input_boolean", "sensor"]
                )
            )
        )

        # Optional features with toggles
        for feature in ["co2", "fan"]:
            enabled = options.get(
                f"configure_{feature}", bool(options.get(f"{feature}_sensor"))
            )
            schema_dict[vol.Optional(f"configure_{feature}", default=enabled)] = (
                selector.BooleanSelector()
            )
            if enabled:
                entity_key = (
                    "circulation_fan" if feature == "fan" else f"{feature}_sensor"
                )
                domain = (
                    ["fan", "switch", "input_boolean"]
                    if feature == "fan"
                    else ["sensor", "input_number"]
                )
                device_class = "carbon_dioxide" if feature == "co2" else None
                schema_dict[
                    vol.Optional(entity_key, default=options.get(entity_key))
                ] = selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=domain, device_class=device_class)
                )

        # Thresholds
        for key, default in [("stress_threshold", 0.70), ("mold_threshold", 0.75)]:
            schema_dict[
                vol.Optional(key, default=options.get(key, default))
            ] = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.5, max=0.95, step=0.05, mode=selector.NumberSelectorMode.SLIDER
                )
            )

        # Trend analysis settings (fallback)
        for trend_type, default_threshold in [("vpd", 1.2), ("temp", 26.0)]:
            schema_dict[
                vol.Optional(
                    f"{trend_type}_trend_duration",
                    default=options.get(f"{trend_type}_trend_duration", 30),
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
                        default=options.get(f"{trend_type}_trend_threshold", default_threshold),
                    )
                ] = selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=20, max=35, step=0.5, mode=selector.NumberSelectorMode.BOX, unit_of_measurement="°C"
                    )
                )
            schema_dict[
                vol.Optional(
                    f"{trend_type}_trend_sensitivity",
                    default=options.get(f"{trend_type}_trend_sensitivity", 0.5),
                )
            ] = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.1, max=1.0, step=0.1, mode=selector.NumberSelectorMode.SLIDER
                )
            )

        # Advanced settings toggle
        schema_dict[
            vol.Optional("configure_advanced", default=False)
        ] = selector.BooleanSelector()

        return self.async_show_form(
            step_id="configure_environment",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={"growspace_name": growspace.name},
        )

    async def async_step_configure_advanced_bayesian(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle advanced configuration of Bayesian probabilities."""
        coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]["coordinator"]
        growspace = coordinator.growspaces.get(self._selected_growspace_id)

        if user_input is not None:
            import ast

            env_config = self._env_config_step1.copy()
            env_config.pop("configure_advanced", None)

            try:
                for key, value in user_input.items():
                    if isinstance(value, str) and value.startswith("("):
                        env_config[key] = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                return self.async_show_form(
                    step_id="configure_advanced_bayesian",
                    data_schema=self._get_advanced_bayesian_schema(
                        self._env_config_step1
                    ),
                    errors={"base": "invalid_tuple_format"},
                )

            growspace.environment_config = env_config
            await coordinator.async_save()
            await coordinator.async_refresh()

            final_options = self.config_entry.options.copy()
            final_options[self._selected_growspace_id] = env_config

            _LOGGER.info(
                "Advanced Bayesian configuration saved for %s: %s",
                growspace.name,
                env_config,
            )
            return self.async_create_entry(title="", data=final_options)

        return self.async_show_form(
            step_id="configure_advanced_bayesian",
            data_schema=self._get_advanced_bayesian_schema(self._env_config_step1),
            description_placeholders={"growspace_name": growspace.name},
        )

    def _get_advanced_bayesian_schema(self, options: dict) -> vol.Schema:
        """Build the schema for advanced Bayesian settings."""
        defaults = {
            "prob_temp_extreme_heat": (0.98, 0.05),
            "prob_temp_high_heat": (0.85, 0.15),
            "prob_temp_warm": (0.65, 0.30),
            "prob_temp_warm_late_flower": (0.70, 0.30),
            "prob_temp_extreme_cold": (0.95, 0.08),
            "prob_temp_cold": (0.80, 0.20),
            "prob_humidity_too_dry": (0.85, 0.20),
            "prob_humidity_high_veg_early": (0.80, 0.20),
            "prob_humidity_high_veg_late": (0.85, 0.15),
            "prob_humidity_stress_flower_early": (0.85, 0.15),
            "prob_humidity_stress_flower_late": (0.90, 0.10),
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
        """Add a new growspace."""
        try:
            coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id][
                "coordinator"
            ]
        except KeyError:
            _LOGGER.error(
                "Coordinator not found - integration may not be properly set up"
            )
            return self.async_abort(reason="setup_error")

        if user_input is not None:
            try:
                _LOGGER.info(
                    "DEBUG - Config flow received growspace data: %s, {user_input}"
                )
                _LOGGER.info(
                    "DEBUG - About to call %s, coordinator.async_add_growspace"
                )
                growspace_id = await coordinator.async_add_growspace(
                    name=user_input["name"],
                    rows=user_input["rows"],
                    plants_per_row=user_input["plants_per_row"],
                    notification_target=user_input.get("notification_target"),
                )
                _LOGGER.info(
                    "DEBUG - Successfully added growspace: %s %s,{user_input['name']} with ID: {growspace_id}"
                )
                return self.async_create_entry(title="", data={})
            except Exception:
                _LOGGER.exception("Error adding growspace: %s", Exception)
                return self.async_show_form(
                    step_id="add_growspace",
                    data_schema=self._get_add_growspace_schema(),
                    errors={"base": "add_failed"},
                )

        _LOGGER.info(
            "DEBUG - Showing add_growspace form with schema fields: %s ,{list(self._get_add_growspace_schema().schema.keys())}"
        )
        return self.async_show_form(
            step_id="add_growspace",
            data_schema=self._get_add_growspace_schema(),
        )

    async def async_step_update_growspace(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Update an existing growspace."""
        try:
            coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id][
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
        """Manage plants."""
        coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]["coordinator"]

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
                        errors={"base": str(Exception)},
                    )
            if action == "back":
                return self.async_show_form(
                    step_id="init",
                    data_schema=self.add_suggested_values_to_schema(
                        coordinator, self.config_entry.options
                    ),
                )

        return self.async_show_form(
            step_id="manage_plants",
            data_schema=self._get_plant_management_schema(coordinator),
        )

    async def async_step_select_growspace_for_plant(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select growspace for new plant."""
        try:
            coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id][
                "coordinator"
            ]
            # Reload coordinator data from storage to ensure we have latest growspaces
            store = self.hass.data[DOMAIN][self.config_entry.entry_id]["store"]
            fresh_data = await store.async_load() or {}
            coordinator.growspaces = fresh_data.get("growspaces", {})
            coordinator.plants = fresh_data.get("plants", {})
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

        _LOGGER.info(f"Config entry ID: {self.config_entry.entry_id}")
        _LOGGER.info(
            f"Available growspaces in coordinator: {list(coordinator.growspaces.keys())}"
        )

        # Get growspaces from device registry
        device_registry = dr.async_get(self.hass)
        devices = device_registry.devices.get_devices_for_config_entry_id(
            self.config_entry.entry_id
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
        """Add a new plant."""
        coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]["coordinator"]
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
        """Update an existing plant."""
        coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]["coordinator"]
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
        """Get schema for growspace management using object attributes."""
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
        """Dynamic schema for adding a growspace during options flow."""
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
        """Get schema for updating a growspace."""
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

    def _get_main_menu_schema(self) -> vol.Schema:
        """Get schema for main menu."""
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
                                label="Configure Environment Sensors",
                            ),
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )

    def _get_plant_management_schema(self, coordinator) -> vol.Schema:
        """Get schema for plant management using object attributes."""
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
        """Get schema for selecting a growspace from device registry using object attributes."""
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
        """Get schema for adding a plant with object-based Growspace."""
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
        """Get schema for updating a plant."""

        growspace = coordinator.growspaces.get(plant.growspace_id)

        # Ensure rows and plants_per_row are integers
        rows = int(growspace.get("rows", 10))
        plants_per_row = int(growspace.get("plants_per_row", 10))

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
                    "strain", default=plant.get("strain", "")
                ): strain_selector,
                vol.Optional(
                    "phenotype", default=plant.get("phenotype", "")
                ): selector.TextSelector(),
                vol.Optional(
                    "row", default=plant.get("row", 1)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=rows, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    "col", default=plant.get("col", 1)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=plants_per_row, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional("veg_start"): selector.DateSelector(),
                vol.Optional("flower_start"): selector.DateSelector(),
            }
        )
