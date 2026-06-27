"""Environment sensors configuration handler for Growspace Manager."""

from __future__ import annotations

from dataclasses import asdict
import logging
from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import (
    CANONICAL_ID_CURE,
    CANONICAL_ID_DRY,
    CONF_BULK_EC_SENSORS,
    CONF_CAMERA_ENTITIES,
    CONF_CIRCULATION_FAN_ENTITIES,
    CONF_CIRCULATION_FAN_ENTITY,
    CONF_CO2_SENSOR,
    CONF_CONFIGURE_ADVANCED,
    CONF_CONFIGURE_DEHUMIDIFIER,
    CONF_CONFIGURE_FAN_CONTROLLER,
    CONF_CONFIGURE_HUMIDIFIER,
    CONF_CONTROL_DEHUMIDIFIER,
    CONF_DEHUMIDIFIER_ENTITIES,
    CONF_DEHUMIDIFIER_ENTITY,
    CONF_DEHUMIDIFIER_THRESHOLDS,
    CONF_DRAIN_VOLUME_SENSORS,
    CONF_ENERGY_SENSORS,
    CONF_EXHAUST_FAN_ENTITIES,
    CONF_FEED_EC_SENSORS,
    CONF_HUMIDIFIER_ENTITIES,
    CONF_HUMIDIFIER_ENTITY,
    CONF_HUMIDITY_SENSOR,
    CONF_HUMIDITY_SENSORS,
    CONF_IRRIGATION_FLOW_SENSORS,
    CONF_IRRIGATION_TANK_SENSORS,
    CONF_IRRIGATION_TANK_VOLUME,
    CONF_IRRIGATION_TANK_WARNING_LEVEL,
    CONF_LIGHT_SENSOR,
    CONF_LIGHT_SENSORS,
    CONF_LST_OFFSET,
    CONF_PH_SENSORS,
    CONF_PORE_EC_SENSORS,
    CONF_POWER_SENSORS,
    CONF_RUNOFF_EC_SENSORS,
    CONF_SOIL_MOISTURE_SENSOR,
    CONF_TEMP_SENSOR,
    CONF_TEMP_SENSORS,
    CONF_VPD_SENSOR,
    CONF_VPD_SENSORS,
)
from custom_components.growspace_manager.models import EnvironmentConfig
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import selector

from . import AbortFlow, BaseConfigHandler

_LOGGER = logging.getLogger(__name__)


class EnvironmentSensorsHandler(BaseConfigHandler[dict[str, Any]]):
    """Handle growspace selection and the main environment sensors configuration step."""

    async def async_step_select_growspace_for_env(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show a form to select a growspace before configuring its environment."""
        try:
            coordinator = self.get_coordinator()
        except AbortFlow as e:
            return self.flow.async_abort(reason=e.reason)

        growspace_options = coordinator.services.growspaces.get_sorted_growspace_options()

        if not growspace_options:
            return self.flow.async_abort(reason="no_growspaces")

        if user_input is not None:
            self.flow.selected_growspace_id = user_input["growspace_id"]
            return await self.flow.async_step_configure_environment()

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
        growspace = coordinator.services.growspaces.get_growspace(growspace_id)

        if not growspace:
            return self.flow.async_abort(reason="growspace_not_found")

        if growspace.environment_config:
            growspace_options = asdict(growspace.environment_config)

            if growspace_options.get("irrigation_tanks"):
                tank_sensors = [
                    tank["sensor_entity"]
                    for tank in growspace_options["irrigation_tanks"]
                ]
                warning_level = growspace_options["irrigation_tanks"][0].get(
                    "warning_level", 30.0
                )
                growspace_options[CONF_IRRIGATION_TANK_SENSORS] = tank_sensors
                growspace_options[CONF_IRRIGATION_TANK_WARNING_LEVEL] = warning_level
                volume_liters = growspace_options["irrigation_tanks"][0].get(
                    "volume_liters"
                )
                if volume_liters is not None:
                    growspace_options[CONF_IRRIGATION_TANK_VOLUME] = volume_liters
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
            existing_tanks = (
                growspace.environment_config.irrigation_tanks
                if growspace.environment_config
                else []
            )
            env_config = self._process_irrigation_tanks(
                env_config, existing_tanks=existing_tanks
            )
            self.flow.env_config_step1 = env_config
            return await self._determine_next_step(user_input)

        return self.flow.async_show_form(
            step_id="configure_environment",
            data_schema=self.get_environment_schema_step1(
                growspace_options, stage=growspace.growspace_type
            ),
            description_placeholders={"growspace_name": growspace.name},
        )

    def _clean_and_merge_input(
        self, user_input: dict[str, Any], growspace_options: dict[str, Any]
    ) -> dict[str, Any]:
        """Clean user input and merge with existing options."""
        cleaned_input = self.clean_input(user_input)
        merged = self.merge_options(growspace_options, cleaned_input)

        env_config = {
            k: v
            for k, v in merged.items()
            if k not in ("configure_dehumidifier", "configure_advanced", CONF_CONFIGURE_FAN_CONTROLLER)
        }

        if "sensor_groups" in cleaned_input:
            env_config["sensor_groups"] = cleaned_input["sensor_groups"]

        if not merged.get("configure_dehumidifier"):
            env_config["dehumidifier_thresholds"] = {}

        return env_config

    def _process_irrigation_tanks(
        self,
        env_config: dict[str, Any],
        existing_tanks: list | None = None,
    ) -> dict[str, Any]:
        """Convert irrigation tank sensors to IrrigationTank instances."""
        tank_sensors = env_config.get(CONF_IRRIGATION_TANK_SENSORS, [])
        warning_level = env_config.get(CONF_IRRIGATION_TANK_WARNING_LEVEL, 30.0)
        volume_liters = env_config.get(CONF_IRRIGATION_TANK_VOLUME)

        existing_by_entity: dict[str, Any] = {}
        if existing_tanks:
            for t in existing_tanks:
                entity = (
                    t.sensor_entity
                    if hasattr(t, "sensor_entity")
                    else t.get("sensor_entity")
                )
                if entity:
                    existing_by_entity[entity] = t

        if tank_sensors:
            irrigation_tanks = []
            for i, sensor_entity in enumerate(tank_sensors, start=1):
                state_obj = self.hass.states.get(sensor_entity)
                tank_name = (
                    state_obj.attributes.get("friendly_name", f"Tank {i}")
                    if state_obj
                    else f"Tank {i}"
                )
                tank_dict: dict[str, Any] = {
                    "sensor_entity": sensor_entity,
                    "name": tank_name,
                    "warning_level": warning_level,
                    "enable_prediction": True,
                    "enable_lights_bias": False,
                    "enable_vpd_weighting": False,
                    "volume_liters": volume_liters,
                }
                existing = existing_by_entity.get(sensor_entity)
                if existing is not None:
                    water_history = (
                        existing.water_history
                        if hasattr(existing, "water_history")
                        else existing.get("water_history")
                    )
                    last_level = (
                        existing.last_recorded_level
                        if hasattr(existing, "last_recorded_level")
                        else existing.get("last_recorded_level")
                    )
                    peak_level = (
                        existing.peak_level
                        if hasattr(existing, "peak_level")
                        else existing.get("peak_level")
                    )
                    if water_history is not None:
                        try:
                            tank_dict["water_history"] = asdict(water_history)
                        except TypeError:
                            tank_dict["water_history"] = water_history
                    if last_level is not None:
                        tank_dict["last_recorded_level"] = last_level
                    if peak_level is not None:
                        tank_dict["peak_level"] = peak_level
                irrigation_tanks.append(tank_dict)
            env_config["irrigation_tanks"] = irrigation_tanks
        else:
            env_config["irrigation_tanks"] = []

        env_config.pop(CONF_IRRIGATION_TANK_SENSORS, None)
        env_config.pop(CONF_IRRIGATION_TANK_WARNING_LEVEL, None)
        env_config.pop(CONF_IRRIGATION_TANK_VOLUME, None)

        return env_config

    async def _determine_next_step(
        self, user_input: dict[str, Any]
    ) -> ConfigFlowResult:
        """Determine which configuration step to show next."""
        cleaned_input = self.clean_input(user_input)
        merged = self.merge_options({}, cleaned_input)

        if merged.get(CONF_CONFIGURE_DEHUMIDIFIER):
            return await self.flow.async_step_configure_dehumidifier()

        if merged.get(CONF_CONFIGURE_FAN_CONTROLLER):
            return await self.flow.async_step_configure_fan_controller()

        if merged.get("configure_advanced") or cleaned_input.get("configure_advanced"):
            return await self.flow.async_step_configure_advanced_bayesian()

        return await self.flow.async_step_configure_sensor_placement()

    async def _async_save_and_finish(self, growspace: Any, env_config: dict[str, Any]) -> ConfigFlowResult:
        """Save env config and finish the flow."""
        coordinator = self.config_entry.runtime_data

        env_config.pop("configure_advanced", None)
        env_config.pop("configure_dehumidifier", None)

        growspace.environment_config = EnvironmentConfig.from_dict(env_config)
        await coordinator.services.save()
        await coordinator.async_refresh()

        _LOGGER.info(
            "Environment configuration saved for growspace %s: %s",
            growspace.name,
            env_config,
        )
        return self.flow.async_create_entry(title="", data=self.config_entry.options)

    # -------------------------------------------------------------------------
    # Schema builders
    # -------------------------------------------------------------------------

    def get_environment_schema_step1(
        self, growspace_options: dict[str, Any], stage: str | None = None
    ) -> vol.Schema:
        """Build the schema for the first step of environment configuration."""
        schema_dict: dict[Any, Any] = {}

        self._add_basic_sensors_to_schema(schema_dict, growspace_options)
        self._add_lst_offset_to_schema(schema_dict, growspace_options, stage=stage)
        self._add_optional_features_to_schema(schema_dict, growspace_options)
        self._add_exhaust_humidifier_to_schema(schema_dict, growspace_options)
        self._add_dehumidifier_entity_selectors(schema_dict, growspace_options)
        self._add_dehumidifier_control_toggles(schema_dict, growspace_options)
        self._add_dehumidifier_threshold_selectors(schema_dict, growspace_options)
        self._add_advanced_sensors_to_schema(schema_dict, growspace_options)
        self._add_camera_config_to_schema(schema_dict, growspace_options)

        return vol.Schema(schema_dict)

    def clean_input(self, user_input: dict[str, Any]) -> dict[str, Any]:
        """Override clean_input to explicitly allow clearing specific fields."""
        cleaned = super().clean_input(user_input)

        list_fields = [
            CONF_TEMP_SENSORS,
            CONF_HUMIDITY_SENSORS,
            CONF_VPD_SENSORS,
            CONF_LIGHT_SENSORS,
            CONF_EXHAUST_FAN_ENTITIES,
            CONF_CIRCULATION_FAN_ENTITIES,
            CONF_HUMIDIFIER_ENTITIES,
            CONF_DEHUMIDIFIER_ENTITIES,
            CONF_PH_SENSORS,
            CONF_FEED_EC_SENSORS,
            CONF_BULK_EC_SENSORS,
            CONF_PORE_EC_SENSORS,
            CONF_RUNOFF_EC_SENSORS,
            CONF_DRAIN_VOLUME_SENSORS,
            CONF_IRRIGATION_FLOW_SENSORS,
            CONF_CAMERA_ENTITIES,
            CONF_POWER_SENSORS,
            CONF_ENERGY_SENSORS,
        ]

        optional_fields = [
            CONF_VPD_SENSOR,
            CONF_SOIL_MOISTURE_SENSOR,
            CONF_LIGHT_SENSOR,
            CONF_CO2_SENSOR,
        ]

        for field in list_fields:
            if field in user_input:
                val = user_input[field]
                if isinstance(val, list):
                    cleaned[field] = [v for v in val if v]
                elif val:
                    cleaned[field] = [val]
                else:
                    cleaned[field] = []

        for field in optional_fields:
            if field in user_input and (
                user_input[field] is None or user_input[field] == ""
            ):
                cleaned[field] = None
            elif field not in user_input and field not in list_fields:
                pass

        for plural_key, singular_key in [
            (CONF_TEMP_SENSORS, CONF_TEMP_SENSOR),
            (CONF_HUMIDITY_SENSORS, CONF_HUMIDITY_SENSOR),
            (CONF_VPD_SENSORS, CONF_VPD_SENSOR),
            (CONF_LIGHT_SENSORS, CONF_LIGHT_SENSOR),
        ]:
            if plural_key in cleaned:
                if cleaned[plural_key]:
                    cleaned[singular_key] = cleaned[plural_key][0]
                else:
                    cleaned[singular_key] = None

        return cleaned

    def _add_basic_sensors_to_schema(
        self, schema_dict: dict[Any, Any], growspace_options: dict[str, Any]
    ) -> None:
        """Add basic sensors (temp, humidity, vpd) to the schema."""
        for key, device_class in [
            (CONF_TEMP_SENSOR, "temperature"),
            (CONF_HUMIDITY_SENSOR, "humidity"),
        ]:
            suggested_value = growspace_options.get(f"{key}s", []) or (
                [growspace_options.get(key)] if growspace_options.get(key) else []
            )

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

        suggested_volume = growspace_options.get(CONF_IRRIGATION_TANK_VOLUME)
        schema_dict[
            vol.Optional(
                CONF_IRRIGATION_TANK_VOLUME,
                description={"suggested_value": suggested_volume},
            )
        ] = vol.Any(
            None,
            vol.All(vol.Coerce(float), vol.Range(min=0.1)),
        )

    def _add_lst_offset_to_schema(
        self,
        schema_dict: dict[Any, Any],
        growspace_options: dict[str, Any],
        stage: str | None = None,
    ) -> None:
        """Add LST offset to the schema if applicable."""
        has_temp = bool(growspace_options.get(CONF_TEMP_SENSOR)) or bool(
            growspace_options.get(CONF_TEMP_SENSORS)
        )
        has_humidity = bool(growspace_options.get(CONF_HUMIDITY_SENSOR)) or bool(
            growspace_options.get(CONF_HUMIDITY_SENSORS)
        )
        has_vpd = bool(growspace_options.get(CONF_VPD_SENSOR)) or bool(
            growspace_options.get(CONF_VPD_SENSORS)
        )
        if has_temp and has_humidity and not has_vpd:
            default_offset = -2.0
            if stage in (CANONICAL_ID_DRY, CANONICAL_ID_CURE):
                default_offset = 0.0
            schema_dict[
                vol.Optional(
                    CONF_LST_OFFSET,
                    default=growspace_options.get(CONF_LST_OFFSET, default_offset),
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
            self._add_feature_entity_selector(schema_dict, feature, growspace_options)

    def _add_feature_entity_selector(
        self,
        schema_dict: dict[Any, Any],
        feature: str,
        growspace_options: dict[str, Any],
    ) -> None:
        """Add the entity selector for a specific feature."""
        if feature == "light":
            entity_key = CONF_LIGHT_SENSORS
            domain = ["switch", "light", "input_boolean", "sensor"]
            device_class = None
            suggested_val = growspace_options.get(CONF_LIGHT_SENSORS) or (
                [growspace_options[CONF_LIGHT_SENSOR]]
                if growspace_options.get(CONF_LIGHT_SENSOR)
                else []
            )
        elif feature == "fan":
            entity_key = CONF_CIRCULATION_FAN_ENTITIES
            domain = ["fan", "switch", "input_boolean", "sensor", "input_number"]
            device_class = None
            suggested_val = growspace_options.get(CONF_CIRCULATION_FAN_ENTITIES) or (
                [growspace_options[CONF_CIRCULATION_FAN_ENTITY]]
                if growspace_options.get(CONF_CIRCULATION_FAN_ENTITY)
                else []
            )
        else:  # co2
            entity_key = CONF_CO2_SENSOR
            domain = ["sensor", "input_number"]
            device_class = ["carbon_dioxide"]
            suggested_val = growspace_options.get(entity_key)

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

    def _add_dehumidifier_entity_selectors(
        self, schema_dict: dict[Any, Any], growspace_options: dict[str, Any]
    ) -> None:
        """Add dehumidifier entity selectors to the schema."""
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

    def _add_dehumidifier_control_toggles(
        self, schema_dict: dict[Any, Any], growspace_options: dict[str, Any]
    ) -> None:
        """Add control and configuration toggles to the schema."""
        schema_dict[
            vol.Optional(
                CONF_CONTROL_DEHUMIDIFIER,
                default=growspace_options.get(CONF_CONTROL_DEHUMIDIFIER, False),
            )
        ] = selector.BooleanSelector()

        schema_dict[
            vol.Optional(
                CONF_CONFIGURE_HUMIDIFIER,
                default=growspace_options.get(CONF_CONFIGURE_HUMIDIFIER, False),
            )
        ] = selector.BooleanSelector()

        schema_dict[
            vol.Optional(
                CONF_CONFIGURE_DEHUMIDIFIER,
                default=growspace_options.get(
                    CONF_CONFIGURE_DEHUMIDIFIER,
                    bool(growspace_options.get(CONF_DEHUMIDIFIER_THRESHOLDS)),
                ),
            )
        ] = selector.BooleanSelector()

        fan_config = growspace_options.get("circulation_fan_config") or {}
        fan_currently_configured = (
            fan_config.get("enabled", False) if isinstance(fan_config, dict) else False
        )
        schema_dict[
            vol.Optional(
                CONF_CONFIGURE_FAN_CONTROLLER,
                default=growspace_options.get(
                    CONF_CONFIGURE_FAN_CONTROLLER, fan_currently_configured
                ),
            )
        ] = selector.BooleanSelector()

    def _add_dehumidifier_threshold_selectors(
        self, schema_dict: dict[Any, Any], growspace_options: dict[str, Any]
    ) -> None:
        """Add environmental thresholds, trend analysis, and photoperiod to the schema."""
        from custom_components.growspace_manager.const import (  # noqa: PLC0415
            CONF_FLOWER_EARLY_DAY_HOURS,
            CONF_FLOWER_LATE_DAY_HOURS,
            CONF_FLOWER_MID_DAY_HOURS,
            CONF_MIN_SOURCE_AIR_TEMP,
            CONF_MOLD_THRESHOLD,
            CONF_STRESS_THRESHOLD,
            CONF_TREND_TEMPERATURE_DURATION,
            CONF_TREND_TEMPERATURE_SENSITIVITY,
            CONF_TREND_TEMPERATURE_THRESHOLD,
            CONF_TREND_VPD_DURATION,
            CONF_TREND_VPD_SENSITIVITY,
            CONF_TREND_VPD_THRESHOLD,
            CONF_VEG_DAY_HOURS,
            DEFAULT_FLOWER_DAY_HOURS,
            DEFAULT_VEG_DAY_HOURS,
            PlantStage,
        )

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

        schema_dict[
            vol.Optional(
                CONF_MIN_SOURCE_AIR_TEMP,
                default=growspace_options.get(CONF_MIN_SOURCE_AIR_TEMP, 18),
            )
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=10, max=25, step=1, mode=selector.NumberSelectorMode.SLIDER
            )
        )

        trend_configs = {
            "vpd": {
                "threshold": CONF_TREND_VPD_THRESHOLD,
                "duration": CONF_TREND_VPD_DURATION,
                "sensitivity": CONF_TREND_VPD_SENSITIVITY,
                "default": 1.2,
            },
            "temperature": {
                "threshold": CONF_TREND_TEMPERATURE_THRESHOLD,
                "duration": CONF_TREND_TEMPERATURE_DURATION,
                "sensitivity": CONF_TREND_TEMPERATURE_SENSITIVITY,
                "default": 26.0,
            },
        }

        for config in trend_configs.values():
            threshold_key = config["threshold"]
            duration_key = config["duration"]
            sensitivity_key = config["sensitivity"]
            default_val = config["default"]

            schema_dict[
                vol.Optional(
                    threshold_key,
                    default=growspace_options.get(threshold_key, default_val),
                )
            ] = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.1, max=50.0, step=0.1, mode=selector.NumberSelectorMode.BOX
                )
            )

            schema_dict[
                vol.Optional(
                    duration_key,
                    default=growspace_options.get(duration_key, 30),
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

            schema_dict[
                vol.Optional(
                    sensitivity_key,
                    default=growspace_options.get(sensitivity_key, 0.5),
                )
            ] = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.1, max=1.0, step=0.1, mode=selector.NumberSelectorMode.SLIDER
                )
            )

        schema_dict[
            vol.Optional(
                CONF_VEG_DAY_HOURS,
                default=growspace_options.get(
                    CONF_VEG_DAY_HOURS, DEFAULT_VEG_DAY_HOURS
                ),
            )
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1, max=24, step=1, mode=selector.NumberSelectorMode.BOX
            )
        )

        stage_keys = {
            PlantStage.FLOWER_EARLY: CONF_FLOWER_EARLY_DAY_HOURS,
            PlantStage.FLOWER_MID: CONF_FLOWER_MID_DAY_HOURS,
            PlantStage.FLOWER_LATE: CONF_FLOWER_LATE_DAY_HOURS,
        }
        for key in stage_keys.values():
            schema_dict[
                vol.Optional(
                    key,
                    default=growspace_options.get(key, DEFAULT_FLOWER_DAY_HOURS),
                )
            ] = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=24, step=1, mode=selector.NumberSelectorMode.BOX
                )
            )

        schema_dict[vol.Optional(CONF_CONFIGURE_ADVANCED, default=False)] = (
            selector.BooleanSelector()
        )

    def _add_advanced_sensors_to_schema(
        self, schema_dict: dict[Any, Any], growspace_options: dict[str, Any]
    ) -> None:
        """Add advanced sensors to the schema."""
        for key, device_class in [
            (CONF_PH_SENSORS, "ph"),
            (CONF_FEED_EC_SENSORS, None),
            (CONF_BULK_EC_SENSORS, None),
            (CONF_PORE_EC_SENSORS, None),
            (CONF_RUNOFF_EC_SENSORS, None),
            (CONF_DRAIN_VOLUME_SENSORS, "water"),
            (CONF_IRRIGATION_FLOW_SENSORS, "water"),
            (CONF_POWER_SENSORS, "power"),
            (CONF_ENERGY_SENSORS, "energy"),
        ]:
            suggested_val = growspace_options.get(key, [])
            selector_config = selector.EntitySelectorConfig(
                domain=["sensor", "input_number", "number"],
                multiple=True,
                device_class=device_class or None,
            )

            schema_dict[
                vol.Optional(key, description={"suggested_value": suggested_val})
            ] = selector.EntitySelector(selector_config)

    def _add_camera_config_to_schema(
        self, schema_dict: dict[Any, Any], growspace_options: dict[str, Any]
    ) -> None:
        """Add camera configuration to the schema."""
        suggested_cameras = growspace_options.get(CONF_CAMERA_ENTITIES, [])
        schema_dict[
            vol.Optional(
                CONF_CAMERA_ENTITIES,
                description={"suggested_value": suggested_cameras},
            )
        ] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain="camera", multiple=True)
        )

        schema_dict[
            vol.Optional(
                "snapshot_interval_hours",
                default=growspace_options.get("snapshot_interval_hours", 24),
            )
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1, max=168, step=1, mode=selector.NumberSelectorMode.BOX
            )
        )
