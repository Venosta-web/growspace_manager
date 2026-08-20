"""Bayesian advanced and sensor placement configuration handler for Growspace Manager."""

from __future__ import annotations

import ast
import logging
from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import (
    CONF_BULK_EC_SENSORS,
    CONF_CAMERA_ENTITIES,
    CONF_DRAIN_VOLUME_SENSORS,
    CONF_ENERGY_SENSORS,
    CONF_FEED_EC_SENSORS,
    CONF_IRRIGATION_FLOW_SENSORS,
    CONF_PH_SENSORS,
    CONF_PORE_EC_SENSORS,
    CONF_POWER_SENSORS,
    CONF_PROB_HUMIDITY_HIGH_FLOWER,
    CONF_PROB_HUMIDITY_HIGH_VEG_EARLY,
    CONF_PROB_HUMIDITY_HIGH_VEG_LATE,
    CONF_PROB_HUMIDITY_TOO_DRY,
    CONF_PROB_HUMIDITY_TOO_HUMID_FLOWER,
    CONF_PROB_MOLD_FAN_OFF,
    CONF_PROB_MOLD_HUMIDITY_HIGH_DAY,
    CONF_PROB_MOLD_HUMIDITY_HIGH_NIGHT,
    CONF_PROB_MOLD_LIGHTS_OFF,
    CONF_PROB_MOLD_TEMP_DANGER_ZONE,
    CONF_PROB_MOLD_VPD_LOW_DAY,
    CONF_PROB_MOLD_VPD_LOW_NIGHT,
    CONF_PROB_NIGHT_TEMP_HIGH,
    CONF_PROB_TEMP_COLD,
    CONF_PROB_TEMP_EXTREME_COLD,
    CONF_PROB_TEMP_EXTREME_HEAT,
    CONF_PROB_TEMP_HIGH_HEAT,
    CONF_PROB_TEMP_WARM,
    CONF_PROB_VPD_MILD_STRESS_FLOWER_EARLY,
    CONF_PROB_VPD_MILD_STRESS_FLOWER_LATE,
    CONF_PROB_VPD_MILD_STRESS_VEG_EARLY,
    CONF_PROB_VPD_MILD_STRESS_VEG_LATE,
    CONF_PROB_VPD_STRESS_FLOWER_EARLY,
    CONF_PROB_VPD_STRESS_FLOWER_LATE,
    CONF_PROB_VPD_STRESS_VEG_EARLY,
    CONF_PROB_VPD_STRESS_VEG_LATE,
    CONF_RUNOFF_EC_SENSORS,
)
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import selector

from . import AbortFlow, BaseConfigHandler

_LOGGER = logging.getLogger(__name__)


class BayesianAdvancedHandler(BaseConfigHandler[dict[str, Any]]):
    """Handle advanced Bayesian configuration and sensor placement steps."""

    async def async_step_configure_advanced_bayesian(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for advanced configuration of Bayesian probabilities."""
        try:
            coordinator = self.get_coordinator()
        except AbortFlow as e:
            return self.flow.async_abort(reason=e.reason)
        growspace_id = self.flow.selected_growspace_id
        if growspace_id is None:
            return self.flow.async_abort(reason="growspace_not_found")
        growspace = coordinator.services.growspaces.get_growspace(growspace_id)

        if not growspace:
            return self.flow.async_abort(reason="growspace_not_found")

        if user_input is not None:
            env_config = dict(self.flow.env_config_step1 or {})
            env_config.pop("configure_advanced", None)

            try:
                parsed_user_input = self.parse_advanced_bayesian_input(user_input)

                bayesian_opts = env_config.get("bayesian_options", {})
                if not isinstance(bayesian_opts, dict):
                    bayesian_opts = {}
                else:
                    bayesian_opts = bayesian_opts.copy()

                bayesian_opts.update(parsed_user_input)
                env_config["bayesian_options"] = bayesian_opts

                for key in parsed_user_input:
                    env_config.pop(key, None)

                self.flow.env_config_step1 = env_config

            except ValueError, SyntaxError, TypeError:
                _LOGGER.warning("Invalid tuple format submitted", exc_info=True)
                return self.flow.async_show_form(
                    step_id="configure_advanced_bayesian",
                    data_schema=self.get_advanced_bayesian_schema(
                        self.flow.env_config_step1 or {}
                    ),
                    errors={"base": "invalid_tuple_format"},
                    description_placeholders={"growspace_name": growspace.name},
                )

            return await self.flow.async_step_configure_sensor_placement()

        return self.flow.async_show_form(
            step_id="configure_advanced_bayesian",
            data_schema=self.get_advanced_bayesian_schema(
                self.flow.env_config_step1 or {}
            ),
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
        if growspace_id is None:
            return self.flow.async_abort(reason="growspace_not_found")
        growspace = coordinator.services.growspaces.get_growspace(growspace_id)

        if not growspace:
            return self.flow.async_abort(reason="growspace_not_found")

        env_config = self.flow.env_config_step1
        if env_config is None:
            return self.flow.async_abort(reason="setup_error")

        sensors_to_configure, sensors_allowed_outside = (
            self._collect_sensors_to_configure(env_config, growspace)
        )

        if not sensors_to_configure:
            return await self.flow.async_step_save_and_finish()

        if user_input is not None:
            sensor_coordinates = {}
            for sensor in sensors_to_configure:
                x = user_input.get(f"coord_{sensor}_x")
                y = user_input.get(f"coord_{sensor}_y")
                z = user_input.get(f"coord_{sensor}_z")
                if x is not None and y is not None and z is not None:
                    sensor_coordinates[sensor] = {"x": x, "y": y, "z": z}

            env_config["sensor_coordinates"] = sensor_coordinates
            return await self.flow.async_step_save_and_finish()

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
            CONF_PH_SENSORS,
            CONF_FEED_EC_SENSORS,
            CONF_BULK_EC_SENSORS,
            CONF_PORE_EC_SENSORS,
            CONF_RUNOFF_EC_SENSORS,
            CONF_DRAIN_VOLUME_SENSORS,
            CONF_IRRIGATION_FLOW_SENSORS,
            CONF_POWER_SENSORS,
            CONF_ENERGY_SENSORS,
            CONF_CAMERA_ENTITIES,
        ]:
            val = env_config.get(key)
            if not val:
                continue
            entities = val if isinstance(val, list) else [val]
            entities = [e for e in entities if isinstance(e, str)]
            if not entities:
                continue

            sensors_to_configure.extend(entities)

            if any(
                k in key
                for k in [
                    "humidifier",
                    "dehumidifier",
                    "tank",
                    "pump",
                    "camera",
                    "power",
                    "energy",
                    "drain",
                    "flow",
                ]
            ):
                sensors_allowed_outside.update(entities)

        if "irrigation_tanks" in env_config:
            for tank in env_config["irrigation_tanks"]:
                sensor = tank.get("sensor_entity")
                if isinstance(sensor, str):
                    sensors_to_configure.append(sensor)
                    sensors_allowed_outside.add(sensor)

        if growspace.irrigation_config:
            if isinstance(growspace.irrigation_config.irrigation_pump_entity, str):
                pump = growspace.irrigation_config.irrigation_pump_entity
                sensors_to_configure.append(pump)
                sensors_allowed_outside.add(pump)
            if isinstance(growspace.irrigation_config.drain_pump_entity, str):
                pump = growspace.irrigation_config.drain_pump_entity
                sensors_to_configure.append(pump)
                sensors_allowed_outside.add(pump)

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
        max_depth = get_dimension("length", 120.0)
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

    def get_advanced_bayesian_schema(self, options: dict[str, Any]) -> vol.Schema:
        """Build the schema for the advanced Bayesian settings form."""
        defaults = {
            CONF_PROB_TEMP_EXTREME_HEAT: (0.98, 0.05),
            CONF_PROB_TEMP_HIGH_HEAT: (0.85, 0.15),
            CONF_PROB_TEMP_WARM: (0.65, 0.30),
            CONF_PROB_TEMP_EXTREME_COLD: (0.95, 0.08),
            CONF_PROB_TEMP_COLD: (0.80, 0.20),
            CONF_PROB_HUMIDITY_TOO_DRY: (0.85, 0.20),
            CONF_PROB_HUMIDITY_HIGH_VEG_EARLY: (0.80, 0.20),
            CONF_PROB_HUMIDITY_HIGH_VEG_LATE: (0.85, 0.15),
            CONF_PROB_HUMIDITY_TOO_HUMID_FLOWER: (0.95, 0.10),
            CONF_PROB_HUMIDITY_HIGH_FLOWER: (0.75, 0.25),
            CONF_PROB_VPD_STRESS_VEG_EARLY: (0.85, 0.15),
            CONF_PROB_VPD_MILD_STRESS_VEG_EARLY: (0.60, 0.30),
            CONF_PROB_VPD_STRESS_VEG_LATE: (0.80, 0.18),
            CONF_PROB_VPD_MILD_STRESS_VEG_LATE: (0.55, 0.35),
            CONF_PROB_VPD_STRESS_FLOWER_EARLY: (0.85, 0.15),
            CONF_PROB_VPD_MILD_STRESS_FLOWER_EARLY: (0.60, 0.30),
            CONF_PROB_VPD_STRESS_FLOWER_LATE: (0.90, 0.12),
            CONF_PROB_VPD_MILD_STRESS_FLOWER_LATE: (0.65, 0.28),
            CONF_PROB_NIGHT_TEMP_HIGH: (0.80, 0.20),
            CONF_PROB_MOLD_TEMP_DANGER_ZONE: (0.85, 0.30),
            CONF_PROB_MOLD_HUMIDITY_HIGH_NIGHT: (0.99, 0.10),
            CONF_PROB_MOLD_VPD_LOW_NIGHT: (0.95, 0.20),
            CONF_PROB_MOLD_LIGHTS_OFF: (0.75, 0.30),
            CONF_PROB_MOLD_HUMIDITY_HIGH_DAY: (0.95, 0.20),
            CONF_PROB_MOLD_VPD_LOW_DAY: (0.90, 0.25),
            CONF_PROB_MOLD_FAN_OFF: (0.80, 0.15),
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
