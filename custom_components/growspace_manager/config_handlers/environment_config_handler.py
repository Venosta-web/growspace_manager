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
    CONF_IRRIGATION_TANK_SENSORS,
    CONF_IRRIGATION_TANK_WARNING_LEVEL,
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

from . import AbortFlow, BaseConfigHandler

_LOGGER = logging.getLogger(__name__)


class EnvironmentConfigHandler(BaseConfigHandler[dict[str, Any]]):
    """Handle environment configuration steps."""

    async def async_step_select_growspace_for_env(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show a form to select a growspace before configuring its environment."""
        try:
            coordinator = self.get_coordinator()
        except AbortFlow as e:
            return self.flow.async_abort(reason=e.reason)

        growspace_options = coordinator.growspace_service.get_sorted_growspace_options()

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
        try:
            coordinator = self.get_coordinator()
        except AbortFlow as e:
            return self.flow.async_abort(reason=e.reason)
        growspace_id = self.flow.selected_growspace_id
        growspace = coordinator.growspaces.get(growspace_id)

        if not growspace:
            return self.flow.async_abort(reason="growspace_not_found")

        # Prepare defaults using dataclass
        if growspace.environment_config:
            growspace_options = asdict(growspace.environment_config)

            # Convert irrigation_tanks from list of dicts back to list of sensor entities for the form
            if growspace_options.get("irrigation_tanks"):
                tank_sensors = [
                    tank["sensor_entity"]
                    for tank in growspace_options["irrigation_tanks"]
                ]
                # Get warning level from first tank (they all share the same warning level in the form)
                warning_level = growspace_options["irrigation_tanks"][0].get(
                    "warning_level", 30.0
                )
                growspace_options[CONF_IRRIGATION_TANK_SENSORS] = tank_sensors
                growspace_options[CONF_IRRIGATION_TANK_WARNING_LEVEL] = warning_level
                # Remove the irrigation_tanks as it's not a form field
                growspace_options.pop("irrigation_tanks", None)
        else:
            growspace_options = {}

        _LOGGER.debug(
            "Loading environment config for growspace %s: %s",
            growspace.name,
            growspace_options,
        )

        if user_input is not None:
            env_config = self._clean_and_merge_input(user_input, growspace_options)
            env_config = self._process_irrigation_tanks(env_config)
            self.flow.env_config_step1 = env_config
            return await self._determine_next_step(user_input)

        return self.flow.async_show_form(
            step_id="configure_environment",
            data_schema=self.get_environment_schema_step1(growspace_options),
            description_placeholders={"growspace_name": growspace.name},
        )

    def _clean_and_merge_input(
        self, user_input: dict[str, Any], growspace_options: dict[str, Any]
    ) -> dict[str, Any]:
        """Clean user input and merge with existing options."""
        cleaned_input = self.clean_input(user_input)
        merged = self.merge_options(growspace_options, cleaned_input)

        # Filter out config flow control fields
        env_config = {
            k: v
            for k, v in merged.items()
            if k not in ("configure_dehumidifier", "configure_advanced")
        }

        # Preserve sensor_groups if present in input
        if "sensor_groups" in cleaned_input:
            env_config["sensor_groups"] = cleaned_input["sensor_groups"]

        # Clear dehumidifier thresholds if unchecked
        if not merged.get("configure_dehumidifier"):
            env_config["dehumidifier_thresholds"] = {}

        return env_config

    def _process_irrigation_tanks(self, env_config: dict[str, Any]) -> dict[str, Any]:
        """Convert irrigation tank sensors to IrrigationTank instances."""
        tank_sensors = env_config.get(CONF_IRRIGATION_TANK_SENSORS, [])
        warning_level = env_config.get(CONF_IRRIGATION_TANK_WARNING_LEVEL, 30.0)

        if tank_sensors:
            irrigation_tanks = []
            for i, sensor_entity in enumerate(tank_sensors, start=1):
                # Extract friendly name from sensor if available
                state_obj = self.hass.states.get(sensor_entity)
                tank_name = (
                    state_obj.attributes.get("friendly_name", f"Tank {i}")
                    if state_obj
                    else f"Tank {i}"
                )
                irrigation_tanks.append(
                    {
                        "sensor_entity": sensor_entity,
                        "name": tank_name,
                        "warning_level": warning_level,
                    }
                )
            env_config["irrigation_tanks"] = irrigation_tanks
        else:
            env_config["irrigation_tanks"] = []

        # Remove temporary config flow fields
        env_config.pop(CONF_IRRIGATION_TANK_SENSORS, None)
        env_config.pop(CONF_IRRIGATION_TANK_WARNING_LEVEL, None)

        return env_config

    async def _determine_next_step(
        self, user_input: dict[str, Any]
    ) -> ConfigFlowResult:
        """Determine which configuration step to show next."""
        cleaned_input = self.clean_input(user_input)
        merged = self.merge_options({}, cleaned_input)

        # Check if dehumidifier configuration is requested
        if merged.get("configure_dehumidifier") and merged.get("control_dehumidifier"):
            return await self.async_step_configure_dehumidifier()

        # Check if advanced Bayesian configuration is requested
        if merged.get("configure_advanced") or cleaned_input.get("configure_advanced"):
            return await self.async_step_configure_advanced_bayesian()

        # Default to sensor placement
        return await self.async_step_configure_sensor_placement()

    async def async_step_configure_dehumidifier(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for configuring dehumidifier thresholds."""
        try:
            coordinator = self.get_coordinator()
        except AbortFlow as e:
            return self.flow.async_abort(reason=e.reason)
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
            self.flow.env_config_step1 = env_config
            return await self.async_step_configure_sensor_placement()

        return self.flow.async_show_form(
            step_id="configure_dehumidifier",
            data_schema=self.get_dehumidifier_schema(current_thresholds),
            description_placeholders={"growspace_name": growspace.name},
        )

    async def async_step_configure_advanced_bayesian(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for advanced configuration of Bayesian probabilities."""
        try:
            coordinator = self.get_coordinator()
        except AbortFlow as e:
            return self.flow.async_abort(reason=e.reason)
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

                # Merge into bayesian_options nested dict
                bayesian_opts = env_config.get("bayesian_options", {})
                if not isinstance(bayesian_opts, dict):
                    bayesian_opts = {}
                else:
                    bayesian_opts = bayesian_opts.copy()

                bayesian_opts.update(parsed_user_input)
                env_config["bayesian_options"] = bayesian_opts

                # Cleanup root level keys to avoid duplicates
                for key in parsed_user_input:
                    env_config.pop(key, None)

                self.flow.env_config_step1 = env_config

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

            return await self.async_step_configure_sensor_placement()

        return self.flow.async_show_form(
            step_id="configure_advanced_bayesian",
            data_schema=self.get_advanced_bayesian_schema(self.flow.env_config_step1),
            description_placeholders={"growspace_name": growspace.name},
        )

    async def async_step_configure_sensor_placement(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure 3D coordinates for sensors."""
        try:
            coordinator = self.get_coordinator()
        except AbortFlow as e:
            return self.flow.async_abort(reason=e.reason)
        growspace_id = self.flow.selected_growspace_id
        growspace = coordinator.growspaces.get(growspace_id)

        if not growspace:
            return self.flow.async_abort(reason="growspace_not_found")

        env_config = self.flow.env_config_step1

        # Collect sensors that need coordinate configuration
        sensors_to_configure, sensors_allowed_outside = self._collect_sensors_to_configure(
            env_config, growspace
        )

        if not sensors_to_configure:
            # No sensors to place, save and exit
            return await self._async_save_and_finish(growspace, env_config)

        if user_input is not None:
            sensor_coordinates = {}
            for sensor in sensors_to_configure:
                x = user_input.get(f"coord_{sensor}_x")
                y = user_input.get(f"coord_{sensor}_y")
                z = user_input.get(f"coord_{sensor}_z")
                if x is not None and y is not None and z is not None:
                    sensor_coordinates[sensor] = {"x": x, "y": y, "z": z}

            env_config["sensor_coordinates"] = sensor_coordinates
            return await self._async_save_and_finish(growspace, env_config)

        # Build schema for sensor coordinates
        schema_dict = self._build_sensor_coordinate_schema(
            sensors_to_configure, sensors_allowed_outside, growspace
        )

        return self.flow.async_show_form(
            step_id="configure_sensor_placement",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={"growspace_name": growspace.name},
        )

    def _collect_sensors_to_configure(
        self, env_config: dict[str, Any], growspace: Any
    ) -> tuple[list[str], set[str]]:
        """Identify all configured sensors and those allowed to be outside."""
        sensors_to_configure = []
        sensors_allowed_outside = set()

        # Collect sensors from environment config
        for key in [
            "temperature_sensors",
            "humidity_sensors",
            "vpd_sensors",
            "light_sensors",
            "co2_sensor",
            "soil_moisture_sensor",
            "circulation_fan_entities",
            "circulation_fan_entity",
            "exhaust_fan_entities",
            "exhaust_entity",
            "exhaust_fan_entity",
            "humidifier_entities",
            "humidifier_entity",
            "dehumidifier_entities",
            "dehumidifier_entity",
        ]:
            val = env_config.get(key)
            if not val:
                continue
            entities = val if isinstance(val, list) else [val]
            entities = [e for e in entities if isinstance(e, str)]
            if not entities:
                continue

            sensors_to_configure.extend(entities)

            # Check if this key belongs to allowed outside types
            if any(k in key for k in ["humidifier", "dehumidifier", "tank", "pump"]):
                sensors_allowed_outside.update(entities)

        # Add irrigation tanks
        if "irrigation_tanks" in env_config:
            for tank in env_config["irrigation_tanks"]:
                sensor = tank.get("sensor_entity")
                if isinstance(sensor, str):
                    sensors_to_configure.append(sensor)
                    sensors_allowed_outside.add(sensor)

        # Add irrigation pumps
        if growspace.irrigation_config:
            if isinstance(growspace.irrigation_config.irrigation_pump_entity, str):
                pump = growspace.irrigation_config.irrigation_pump_entity
                sensors_to_configure.append(pump)
                sensors_allowed_outside.add(pump)
            if isinstance(growspace.irrigation_config.drain_pump_entity, str):
                pump = growspace.irrigation_config.drain_pump_entity
                sensors_to_configure.append(pump)
                sensors_allowed_outside.add(pump)

        # Remove duplicates and sort
        sensors_to_configure = sorted(set(sensors_to_configure), key=str)

        return sensors_to_configure, sensors_allowed_outside

    def _build_sensor_coordinate_schema(
        self,
        sensors_to_configure: list[str],
        sensors_allowed_outside: set[str],
        growspace: Any,
    ) -> dict[Any, Any]:
        """Build schema for sensor coordinate configuration."""
        schema_dict = {}
        dimensions = growspace.dimensions or {}

        def get_dimension(key: str, default: float) -> float:
            val = dimensions.get(key, default)
            return float(val) if isinstance(val, (int, float)) else default

        max_width = get_dimension("width", 120.0)
        max_depth = get_dimension("length", 120.0)  # depth is length
        max_height = get_dimension("height", 200.0)
        unit = dimensions.get("unit", "cm")
        if not isinstance(unit, str):
            unit = "cm"

        existing_coords = (
            growspace.environment_config.sensor_coordinates
            if growspace.environment_config
            else {}
        )

        for sensor in sensors_to_configure:
            defaults = existing_coords.get(sensor, {"x": 0.0, "y": 0.0, "z": 0.0})
            is_outside_allowed = sensor in sensors_allowed_outside

            # X coordinate
            schema_dict[
                vol.Required(f"coord_{sensor}_x", default=defaults.get("x", 0.0))
            ] = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=-100 if is_outside_allowed else 0,
                    max=max_width + 100 if is_outside_allowed else max_width,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement=unit,
                )
            )
            # Y coordinate
            schema_dict[
                vol.Required(f"coord_{sensor}_y", default=defaults.get("y", 0.0))
            ] = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=-100 if is_outside_allowed else 0,
                    max=max_depth + 100 if is_outside_allowed else max_depth,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement=unit,
                )
            )
            # Z coordinate
            schema_dict[
                vol.Required(f"coord_{sensor}_z", default=defaults.get("z", 0.0))
            ] = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=-50 if is_outside_allowed else 0,
                    max=max_height + 50 if is_outside_allowed else max_height,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement=unit,
                )
            )

        return schema_dict

    async def _async_save_and_finish(self, growspace, env_config):
        """Helper to save config and finish flow."""
        coordinator = self.config_entry.runtime_data

        # Clean up temporary keys strictly
        env_config.pop("configure_advanced", None)
        env_config.pop("configure_dehumidifier", None)

        growspace.environment_config = EnvironmentConfig.from_dict_custom(env_config)
        await coordinator.async_save()
        await coordinator.async_refresh()

        _LOGGER.info(
            "Environment configuration saved for growspace %s: %s",
            growspace.name,
            env_config,
        )
        return self.flow.async_create_entry(title="", data={})

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

            suggested_value = growspace_options.get(f"{key}s", []) or (
                [growspace_options.get(key)] if growspace_options.get(key) else []
            )

            # Use the pluaral form key for the schema
            schema_dict[
                vol.Optional(
                    f"{key}s", description={"suggested_value": suggested_value}
                )
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["sensor", "input_number"],
                    device_class=device_class,
                    multiple=True,
                )
            )

        # Soil moisture sensor - optional
        suggested_moisture = growspace_options.get(CONF_SOIL_MOISTURE_SENSOR)
        schema_dict[
            vol.Optional(
                CONF_SOIL_MOISTURE_SENSOR,
                description={"suggested_value": suggested_moisture},
            )
        ] = selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=["sensor", "input_number"],
                device_class="moisture",
            )
        )

        # VPD sensor - optional
        suggested_vpd = growspace_options.get(f"{CONF_VPD_SENSOR}s", []) or (
            [growspace_options.get(CONF_VPD_SENSOR)]
            if growspace_options.get(CONF_VPD_SENSOR)
            else []
        )
        schema_dict[
            vol.Optional(
                f"{CONF_VPD_SENSOR}s",
                description={"suggested_value": suggested_vpd},
            )
        ] = selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=["sensor", "input_number"],
                device_class="pressure",
                multiple=True,
            )
        )

        # Irrigation tank sensors - optional (multiple sensors for tank level monitoring)
        suggested_tanks = growspace_options.get(CONF_IRRIGATION_TANK_SENSORS, [])
        schema_dict[
            vol.Optional(
                CONF_IRRIGATION_TANK_SENSORS,
                description={"suggested_value": suggested_tanks},
            )
        ] = selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=["sensor", "input_number"],
                multiple=True,
            )
        )

        # Irrigation tank warning level - optional
        schema_dict[
            vol.Optional(
                CONF_IRRIGATION_TANK_WARNING_LEVEL,
                default=growspace_options.get(CONF_IRRIGATION_TANK_WARNING_LEVEL, 30.0),
            )
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=5.0,
                max=50.0,
                step=5.0,
                mode=selector.NumberSelectorMode.SLIDER,
                unit_of_measurement="%",
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
