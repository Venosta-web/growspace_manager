"""Dehumidifier configuration handler for Growspace Manager."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import (
    CONF_CONFIGURE_DEHUMIDIFIER,
    CONF_CONFIGURE_FAN_CONTROLLER,
    CONF_CONFIGURE_HUMIDIFIER,
    CONF_CONTROL_DEHUMIDIFIER,
    CONF_DEHUMIDIFIER_ENTITIES,
    CONF_DEHUMIDIFIER_ENTITY,
    CONF_DEHUMIDIFIER_THRESHOLDS,
)
from custom_components.growspace_manager.dehumidifier_coordinator import (
    DEFAULT_THRESHOLDS,
)
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import selector

from . import AbortFlow, BaseConfigHandler
from .stage_thresholds import build_stage_threshold_schema, parse_stage_thresholds

_LOGGER = logging.getLogger(__name__)


class DehumidifierHandler(BaseConfigHandler[dict[str, Any]]):
    """Handle dehumidifier configuration step."""

    async def async_step_configure_dehumidifier(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for configuring dehumidifier thresholds."""
        try:
            coordinator = self.get_coordinator()
        except AbortFlow as e:
            return self.flow.async_abort(reason=e.reason)
        growspace_id = self.flow.selected_growspace_id
        growspace = coordinator.services.growspaces.get_growspace(growspace_id)

        if not growspace:
            return self.flow.async_abort(reason="growspace_not_found")

        current_thresholds = (
            growspace.environment_config.dehumidifier_thresholds
            if growspace.environment_config
            else {}
        )

        if user_input is not None:
            env_config = self.flow.env_config_step1.copy()
            env_config["dehumidifier_thresholds"] = parse_stage_thresholds(user_input)

            if env_config.get("configure_advanced"):
                self.flow.env_config_step1 = env_config
                return await self.flow.async_step_configure_advanced_bayesian()

            env_config.pop("configure_advanced", None)
            self.flow.env_config_step1 = env_config
            return await self.flow.async_step_configure_sensor_placement()

        return self.flow.async_show_form(
            step_id="configure_dehumidifier",
            data_schema=self.get_dehumidifier_schema(current_thresholds),
            description_placeholders={"growspace_name": growspace.name},
        )

    def get_dehumidifier_schema(self, current_thresholds: dict[str, Any]) -> vol.Schema:
        """Generate schema for dehumidifier settings."""
        return build_stage_threshold_schema(current_thresholds, DEFAULT_THRESHOLDS)

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
