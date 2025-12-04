"""Environment configuration handler for Growspace Manager."""

from __future__ import annotations

import ast
import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector

from ..const import DEFAULT_FLOWER_DAY_HOURS, DEFAULT_VEG_DAY_HOURS
from ..dehumidifier_coordinator import DEFAULT_THRESHOLDS

_LOGGER = logging.getLogger(__name__)


class EnvironmentConfigHandler:
    """Handle environment configuration steps."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the handler."""
        self.hass = hass
        self.config_entry = config_entry

    def process_environment_input(
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

    def _add_basic_sensors_to_schema(
        self, schema_dict: dict, growspace_options: dict[str, Any]
    ) -> None:
        """Add basic sensors (temp, humidity, vpd) to the schema."""
        # Basic sensors
        for key, device_class in [
            ("temperature_sensor", "temperature"),
            ("humidity_sensor", "humidity"),
            ("soil_moisture_sensor", "moisture"),
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

        schema_dict[
            vol.Optional(
                entity_key,
                default=growspace_options.get(entity_key) or vol.UNDEFINED,
            )
        ] = selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=domain,
                device_class=device_class if device_class else [],
            )
        )

    def _add_exhaust_humidifier_to_schema(
        self, schema_dict: dict, growspace_options: dict[str, Any]
    ) -> None:
        """Add exhaust and humidifier to the schema."""
        # Exhaust Fan
        schema_dict[
            vol.Optional(
                "exhaust_fan_entity",
                default=growspace_options.get("exhaust_fan_entity") or vol.UNDEFINED,
            )
        ] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain=["fan", "input_boolean", "switch"])
        )

        # Humidifier
        schema_dict[
            vol.Optional(
                "humidifier_entity",
                default=growspace_options.get("humidifier_entity") or vol.UNDEFINED,
            )
        ] = selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=["humidifier", "input_boolean", "switch"]
            )
        )
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
                    domain=[
                        "switch",
                        "humidifier",
                        "sensor",
                        "binary_sensor",
                        "input_boolean",
                    ]
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

    def get_dehumidifier_schema(self, current_thresholds: dict[str, Any]) -> vol.Schema:
        """Generate schema for dehumidifier settings."""
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

        return vol.Schema(schema_dict)

    def get_advanced_bayesian_schema(self, options: dict) -> vol.Schema:
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
