"""Environment configuration handler for Growspace Manager."""

from __future__ import annotations

import ast
from dataclasses import asdict
import logging
from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import (
    CONF_CIRCULATION_FAN_ENTITIES,
    CONF_CIRCULATION_FAN_ENTITY,
    CONF_CO2_SENSOR,
    CONF_DEHUMIDIFIER_ENTITIES,
    CONF_DEHUMIDIFIER_ENTITY,
    CONF_EXHAUST_FAN_ENTITIES,
    CONF_HUMIDIFIER_ENTITIES,
    CONF_HUMIDIFIER_ENTITY,
    CONF_HUMIDITY_SENSOR,
    CONF_LIGHT_SENSOR,
    CONF_LIGHT_SENSORS,
    CONF_MOLD_THRESHOLD,
    CONF_SOIL_MOISTURE_SENSOR,
    CONF_STRESS_THRESHOLD,
    CONF_TEMP_SENSOR,
    CONF_VPD_SENSOR,
    DEFAULT_FLOWER_DAY_HOURS,
    DEFAULT_VEG_DAY_HOURS,
    DEHUMIDIFIER_STAGES,
)
from custom_components.growspace_manager.dehumidifier_coordinator import (
    DEFAULT_THRESHOLDS,
)
from custom_components.growspace_manager.models import EnvironmentConfig
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import selector

from . import BaseConfigHandler

_LOGGER = logging.getLogger(__name__)


class EnvironmentConfigHandler(BaseConfigHandler[dict[str, Any]]):
    """Handle environment configuration steps."""

    async def async_step_select_growspace_for_env(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show a form to select a growspace before configuring its environment."""
        if self.config_entry is None:
            return self.flow.async_abort(reason="setup_error")
        coordinator = self.config_entry.runtime_data
        if coordinator is None:
            return self.flow.async_abort(reason="setup_error")

        growspace_options = coordinator.get_sorted_growspace_options()

        if not growspace_options:
            return self.flow.async_abort(reason="no_growspaces")

        if user_input is not None:
            self.flow.selected_growspace_id = user_input["growspace_id"]
            return await self.async_step_configure_environment()

        schema: dict[Any, Any] = {
            vol.Required("growspace_id"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value=gs_id, label=name)
                        for gs_id, name in growspace_options
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        }
        return self.flow.async_show_form(
            step_id="select_growspace_for_env", data_schema=vol.Schema(schema)
        )

    async def async_step_configure_environment(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for configuring environment sensors for a growspace."""
        if self.config_entry is None:
            return self.flow.async_abort(reason="setup_error")
        coordinator = self.config_entry.runtime_data
        if coordinator is None:
            return self.flow.async_abort(reason="setup_error")
        growspace_id = self.flow.selected_growspace_id
        growspace = coordinator.growspaces.get(growspace_id)

        if not growspace:
            return self.flow.async_abort(reason="growspace_not_found")

        # Prepare defaults using dataclass
        if growspace.environment_config:
            growspace_options = asdict(growspace.environment_config)
        else:
            growspace_options = {}

        _LOGGER.debug(
            "Loading environment config for growspace %s: %s",
            growspace.name,
            growspace_options,
        )

        if user_input is not None:
            cleaned_input = self.clean_input(user_input)
            self.flow.env_config_step1 = self.merge_options(
                growspace_options, cleaned_input
            )

            # Already filtered by handler, do not filter again to preserve None values for clearing
            env_config = {
                k: v
                for k, v in self.flow.env_config_step1.items()
                if k not in ("configure_dehumidifier", "configure_advanced")
            }

            # Check for next steps
            if self.flow.env_config_step1.get(
                "configure_dehumidifier"
            ) and self.flow.env_config_step1.get("control_dehumidifier"):
                return await self.async_step_configure_dehumidifier()

            # If user unchecked configure_dehumidifier, clear any existing thresholds
            if not self.flow.env_config_step1.get("configure_dehumidifier"):
                env_config["dehumidifier_thresholds"] = {}

            if self.flow.env_config_step1.get("configure_advanced"):
                return await self.async_step_configure_advanced_bayesian()

            growspace.environment_config = EnvironmentConfig.from_dict(env_config)
            await coordinator.async_save()
            await coordinator.async_refresh()

            _LOGGER.info(
                "Environment configuration saved for growspace %s: %s",
                growspace.name,
                env_config,
            )
            return self.flow.async_create_entry(title="", data={})

        return self.flow.async_show_form(
            step_id="configure_environment",
            data_schema=self.get_environment_schema_step1(growspace_options),
            description_placeholders={"growspace_name": growspace.name},
        )

    async def async_step_configure_dehumidifier(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for configuring dehumidifier thresholds."""
        if self.config_entry is None:
            return self.flow.async_abort(reason="setup_error")
        coordinator = self.config_entry.runtime_data
        if coordinator is None:
            return self.flow.async_abort(reason="setup_error")
        growspace_id = self.flow.selected_growspace_id
        growspace = coordinator.growspaces.get(growspace_id)

        if not growspace:
            return self.flow.async_abort(reason="growspace_not_found")

        # Load existing thresholds or defaults
        current_thresholds = (
            growspace.environment_config.dehumidifier_thresholds
            if growspace.environment_config
            else {}
        )

        if user_input is not None:
            # Process input back into nested structure
            new_thresholds: dict[str, Any] = {}
            for stage in DEHUMIDIFIER_STAGES:
                new_thresholds[stage] = {}
                for cycle in ["day", "night"]:
                    new_thresholds[stage][cycle] = {
                        "on": user_input[f"{stage}_{cycle}_on"],
                        "off": user_input[f"{stage}_{cycle}_off"],
                    }

            # Update config
            env_config = self.flow.env_config_step1.copy()
            env_config["dehumidifier_thresholds"] = new_thresholds

            if env_config.get("configure_advanced"):
                # Update temporary config and move to next step
                self.flow.env_config_step1 = env_config
                return await self.async_step_configure_advanced_bayesian()

            # Save and finish
            env_config.pop("configure_advanced", None)
            growspace.environment_config = EnvironmentConfig.from_dict(env_config)
            await coordinator.async_save()
            await coordinator.async_refresh()
            return self.flow.async_create_entry(title="", data={})

        return self.flow.async_show_form(
            step_id="configure_dehumidifier",
            data_schema=self.get_dehumidifier_schema(current_thresholds),
            description_placeholders={"growspace_name": growspace.name},
        )

    async def async_step_configure_advanced_bayesian(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for advanced configuration of Bayesian probabilities."""
        if self.config_entry is None:
            return self.flow.async_abort(reason="setup_error")
        coordinator = self.config_entry.runtime_data
        if coordinator is None:
            return self.flow.async_abort(reason="setup_error")
        growspace_id = self.flow.selected_growspace_id
        growspace = coordinator.growspaces.get(growspace_id)

        if not growspace:
            return self.flow.async_abort(reason="growspace_not_found")

        if user_input is not None:
            env_config = self.flow.env_config_step1.copy()
            env_config.pop("configure_advanced", None)

            try:
                # Update env_config *after* all parsing is successful
                parsed_user_input = self.parse_advanced_bayesian_input(user_input)
                env_config.update(parsed_user_input)

            except (ValueError, SyntaxError, TypeError):
                _LOGGER.warning("Invalid tuple format submitted", exc_info=True)
                return self.flow.async_show_form(
                    step_id="configure_advanced_bayesian",
                    data_schema=self.get_advanced_bayesian_schema(
                        self.flow.env_config_step1
                    ),
                    errors={"base": "invalid_tuple_format"},
                    description_placeholders={"growspace_name": growspace.name},
                )

            growspace.environment_config = EnvironmentConfig.from_dict(env_config)
            await coordinator.async_save()
            await coordinator.async_refresh()

            _LOGGER.info(
                "Advanced Bayesian configuration saved for %s: %s",
                growspace.name,
                env_config,
            )
            return self.flow.async_create_entry(title="", data={})

        return self.flow.async_show_form(
            step_id="configure_advanced_bayesian",
            data_schema=self.get_advanced_bayesian_schema(self.flow.env_config_step1),
            description_placeholders={"growspace_name": growspace.name},
        )

    def get_environment_schema_step1(
        self, growspace_options: dict[str, Any]
    ) -> vol.Schema:
        """Build the schema for the first step of environment configuration."""
        schema_dict: dict[Any, Any] = {}

        self._add_basic_sensors_to_schema(schema_dict, growspace_options)
        self._add_lst_offset_to_schema(schema_dict, growspace_options)
        self._add_optional_features_to_schema(schema_dict, growspace_options)
        self._add_exhaust_humidifier_to_schema(schema_dict, growspace_options)
        self._add_dehumidifier_to_schema(schema_dict, growspace_options)

        return vol.Schema(schema_dict)

    def clean_input(self, user_input: dict[str, Any]) -> dict[str, Any]:
        """Override clean_input to explicitly allow clearing specific fields."""
        cleaned = super().clean_input(user_input)

        list_fields = [
            CONF_LIGHT_SENSORS,
            CONF_EXHAUST_FAN_ENTITIES,
            CONF_CIRCULATION_FAN_ENTITIES,
            CONF_HUMIDIFIER_ENTITIES,
            CONF_DEHUMIDIFIER_ENTITIES,
        ]

        # Explicitly check for specific optional sensors and preserve None/empty if present in user_input
        # This allows clearing them by overwriting existing values with None.
        optional_fields = [
            CONF_VPD_SENSOR,
            CONF_SOIL_MOISTURE_SENSOR,
            CONF_LIGHT_SENSOR,
            CONF_CO2_SENSOR,
        ]

        # Handle list fields first (sanitize list content)
        for field in list_fields:
            if field in user_input:
                val = user_input[field]
                if isinstance(val, list):
                    cleaned[field] = [v for v in val if v]
                elif val:
                    # Backward compat helper if somehow a string gets here (shouldn't with selector)
                    cleaned[field] = [val]
                else:
                    cleaned[field] = []

        # Handle simplified optional fields
        for field in optional_fields:
            if field in user_input and (
                user_input[field] is None or user_input[field] == ""
            ):
                cleaned[field] = None
            elif field not in user_input and field not in list_fields:
                # Only clear if it's not one of our new list fields (which handle themselves)
                # Actually, optional_fields contains CONF_LIGHT_SENSOR ("light_sensor")
                # We need to map old config flow keys (light_sensor) to new keys (light_sensors) if we change the keys in schema
                # The Models used separate keys.
                # Let's verify what keys we are using in the schema below.
                pass

        return cleaned

    def _add_basic_sensors_to_schema(
        self, schema_dict: dict[Any, Any], growspace_options: dict[str, Any]
    ) -> None:
        """Add basic sensors (temp, humidity, vpd) to the schema."""
        # Basic sensors
        for key, device_class in [
            (CONF_TEMP_SENSOR, "temperature"),
            (CONF_HUMIDITY_SENSOR, "humidity"),
        ]:
            # Use vol.Required if it's a new entry, strictly speaking the user prompt implies optionality *in general*,
            # but usually key sensors are required. The original code used vol.Optional(key, default=...).
            # I will keep them as is (Optional with default) which effectively makes them required if no default,
            # BUT the user asked for soil moisture specifically to be optional.
            # actually, standard flow in config flow with selectors: if you want it to be "optional to select",
            # you default to UNDEFINED or allow empty.
            # The original code: default=growspace_options.get(key)
            # If growspace_options has it, it pre-fills.
            # If not, it's None. vol.Optional(key, default=None) -> might show empty.
            # The requested change implies it shouldn't be forced or it should be clear it's optional.
            # Making it default to UNDEFINED if not present makes it "clean" optional.

            suggested_value = growspace_options.get(key)
            schema_dict[
                vol.Optional(key, description={"suggested_value": suggested_value})
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["sensor", "input_number"],
                    device_class=device_class,
                )
            )

        # Soil moisture sensor - optional
        suggested_moisture = growspace_options.get("soil_moisture_sensor")
        schema_dict[
            vol.Optional(
                "soil_moisture_sensor",
                description={"suggested_value": suggested_moisture},
            )
        ] = selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=["sensor", "input_number"],
                device_class="moisture",
            )
        )

        # VPD sensor - optional
        suggested_vpd = growspace_options.get(CONF_VPD_SENSOR)
        schema_dict[
            vol.Optional(
                CONF_VPD_SENSOR,
                description={"suggested_value": suggested_vpd},
            )
        ] = selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=["sensor", "input_number"],
                device_class="pressure",
            )
        )

    def _add_lst_offset_to_schema(
        self, schema_dict: dict[Any, Any], growspace_options: dict[str, Any]
    ) -> None:
        """Add LST offset to the schema if applicable."""
        has_temp = bool(growspace_options.get(CONF_TEMP_SENSOR))
        has_humidity = bool(growspace_options.get(CONF_HUMIDITY_SENSOR))
        has_vpd = bool(growspace_options.get(CONF_VPD_SENSOR))

        if has_temp and has_humidity and not has_vpd:
            schema_dict[
                vol.Optional(
                    "lst_offset",
                    default=growspace_options.get("lst_offset", -2.0),
                )
            ] = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=-10.0,
                    max=10.0,
                    step=0.5,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="°C",
                )
            )

    def _add_optional_features_to_schema(
        self, schema_dict: dict[Any, Any], growspace_options: dict[str, Any]
    ) -> None:
        """Add optional features (light, co2, fan) to the schema."""
        for feature in ["light", "co2", "fan"]:
            # Check if feature is already configured (different keys for different features)
            # Removed the configure_ feature checkboxes and their conditional logic
            self._add_feature_entity_selector(schema_dict, feature, growspace_options)

    def _add_feature_entity_selector(
        self,
        schema_dict: dict[Any, Any],
        feature: str,
        growspace_options: dict[str, Any],
    ) -> None:
        """Add the entity selector for a specific feature."""
        # Mapping for multi-device support
        if feature == "light":
            entity_key = CONF_LIGHT_SENSORS  # New Key
            domain = ["switch", "light", "input_boolean", "sensor"]
            device_class = None
            suggested_val = growspace_options.get(CONF_LIGHT_SENSORS) or (
                [growspace_options[CONF_LIGHT_SENSOR]]
                if growspace_options.get(CONF_LIGHT_SENSOR)
                else []
            )
        elif feature == "fan":
            entity_key = CONF_CIRCULATION_FAN_ENTITIES  # New Key
            domain = ["fan", "switch", "input_boolean", "sensor", "input_number"]
            device_class = None
            suggested_val = growspace_options.get(CONF_CIRCULATION_FAN_ENTITIES) or (
                [growspace_options[CONF_CIRCULATION_FAN_ENTITY]]
                if growspace_options.get(CONF_CIRCULATION_FAN_ENTITY)
                else []
            )
        else:  # co2 (remains singular for now based on model?)
            # Model check: co2_sensor is SINGLE. Only light/fans/humidifiers are lists.
            entity_key = CONF_CO2_SENSOR
            domain = ["sensor", "input_number"]
            device_class = ["carbon_dioxide"]
            suggested_val = growspace_options.get(entity_key)

        # Build selector config - only include device_class if specified
        # Enable multiple for array types
        # Enable multiple for array types
        is_multiple = entity_key in [CONF_LIGHT_SENSORS, CONF_CIRCULATION_FAN_ENTITIES]

        selector_config = selector.EntitySelectorConfig(
            domain=domain, multiple=is_multiple
        )
        if device_class:
            selector_config = selector.EntitySelectorConfig(
                domain=domain,
                device_class=device_class,
                multiple=is_multiple,
            )

        schema_dict[
            vol.Optional(
                entity_key,
                description={"suggested_value": suggested_val},
            )
        ] = selector.EntitySelector(selector_config)

    def _add_exhaust_humidifier_to_schema(
        self, schema_dict: dict[Any, Any], growspace_options: dict[str, Any]
    ) -> None:
        """Add exhaust and humidifier to the schema."""
        # Exhaust Entity (Merged: Fan/Switch/Sensor) -> Now List
        suggested_exhaust = growspace_options.get(CONF_EXHAUST_FAN_ENTITIES) or (
            [growspace_options.get("exhaust_fan_entity")]
            if growspace_options.get("exhaust_fan_entity")
            else []
        )

        schema_dict[
            vol.Optional(
                CONF_EXHAUST_FAN_ENTITIES,
                description={"suggested_value": suggested_exhaust},
            )
        ] = selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=[
                    "fan",
                    "switch",
                    "input_boolean",
                    "sensor",
                    "binary_sensor",
                    "input_number",
                ],
                multiple=True,
            )
        )

        # Humidifier Entity (Merged: Humidifier/Switch/Sensor) -> Now List
        suggested_humidifier = growspace_options.get(CONF_HUMIDIFIER_ENTITIES) or (
            [growspace_options.get(CONF_HUMIDIFIER_ENTITY)]
            if growspace_options.get(CONF_HUMIDIFIER_ENTITY)
            else []
        )

        schema_dict[
            vol.Optional(
                CONF_HUMIDIFIER_ENTITIES,
                description={"suggested_value": suggested_humidifier},
            )
        ] = selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=[
                    "humidifier",
                    "switch",
                    "input_boolean",
                    "sensor",
                    "binary_sensor",
                    "input_number",
                ],
                multiple=True,
            )
        )

    def _add_dehumidifier_to_schema(
        self, schema_dict: dict[Any, Any], growspace_options: dict[str, Any]
    ) -> None:
        """Add dehumidifier to the schema."""
        # Check for list or legacy str
        suggested_dehumidifier = growspace_options.get(CONF_DEHUMIDIFIER_ENTITIES) or (
            [growspace_options.get(CONF_DEHUMIDIFIER_ENTITY)]
            if growspace_options.get(CONF_DEHUMIDIFIER_ENTITY)
            else []
        )

        schema_dict[
            vol.Optional(
                CONF_DEHUMIDIFIER_ENTITIES,
                description={"suggested_value": suggested_dehumidifier},
            )
        ] = selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=[
                    "switch",
                    "humidifier",
                    "sensor",
                    "binary_sensor",
                    "input_boolean",
                ],
                multiple=True,
            )
        )
        schema_dict[
            vol.Optional(
                "control_dehumidifier",
                default=growspace_options.get("control_dehumidifier", False),
            )
        ] = selector.BooleanSelector()

        schema_dict[
            vol.Optional(
                "configure_dehumidifier",
                default=growspace_options.get(
                    "configure_dehumidifier",
                    bool(growspace_options.get("dehumidifier_thresholds")),
                ),
            )
        ] = selector.BooleanSelector()
        for key, default in [
            (CONF_STRESS_THRESHOLD, 0.70),
            (CONF_MOLD_THRESHOLD, 0.75),
        ]:
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

    def get_dehumidifier_schema(self, current_thresholds: dict[str, Any]) -> vol.Schema:
        """Generate schema for dehumidifier settings."""
        schema_dict = {}
        for stage in DEHUMIDIFIER_STAGES:
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

        return vol.Schema(schema_dict)

    def get_advanced_bayesian_schema(self, options: dict[str, Any]) -> vol.Schema:
        """Build the schema for the advanced Bayesian settings form."""
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

    def parse_advanced_bayesian_input(
        self, user_input: dict[str, Any]
    ) -> dict[str, Any]:
        """Parse user input for advanced Bayesian settings."""
        parsed_user_input = {}
        for key, value in user_input.items():
            if isinstance(value, str):
                # Check if it's a valid tuple string
                if not value.startswith("(") or not value.endswith(")"):
                    _LOGGER.warning("Invalid tuple format for %s: %s", key, value)
                    raise ValueError("Invalid tuple string format")

                parsed_value = ast.literal_eval(value)

                if not isinstance(parsed_value, tuple):
                    raise TypeError("Parsed value is not a tuple")

                parsed_user_input[key] = parsed_value
            else:
                parsed_user_input[key] = value
        return parsed_user_input
