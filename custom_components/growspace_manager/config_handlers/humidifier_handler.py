"""Humidifier configuration handler for Growspace Manager."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import CONF_CONFIGURE_ADVANCED
from custom_components.growspace_manager.humidifier_coordinator import (
    DEFAULT_THRESHOLDS,
)
from homeassistant.config_entries import ConfigFlowResult

from . import AbortFlow, BaseConfigHandler
from .stage_thresholds import build_stage_threshold_schema, parse_stage_thresholds

_LOGGER = logging.getLogger(__name__)


class HumidifierHandler(BaseConfigHandler[dict[str, Any]]):
    """Handle humidifier configuration step."""

    async def async_step_configure_humidifier(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for configuring humidifier thresholds."""
        try:
            coordinator = self.get_coordinator()
        except AbortFlow as e:
            return self.flow.async_abort(reason=e.reason)
        growspace_id = self.flow.selected_growspace_id
        growspace = coordinator.services.growspaces.get_growspace(growspace_id)

        if not growspace:
            return self.flow.async_abort(reason="growspace_not_found")

        current_thresholds = (
            growspace.environment_config.humidifier_thresholds
            if growspace.environment_config
            else {}
        )

        if user_input is not None:
            env_config = self.flow.env_config_step1.copy()
            env_config["humidifier_thresholds"] = parse_stage_thresholds(user_input)

            if env_config.get(CONF_CONFIGURE_ADVANCED):
                self.flow.env_config_step1 = env_config
                return await self.flow.async_step_configure_advanced_bayesian()

            env_config.pop(CONF_CONFIGURE_ADVANCED, None)
            self.flow.env_config_step1 = env_config
            return await self.flow.async_step_configure_sensor_placement()

        return self.flow.async_show_form(
            step_id="configure_humidifier",
            data_schema=self.get_humidifier_schema(current_thresholds),
            description_placeholders={"growspace_name": growspace.name},
        )

    def get_humidifier_schema(self, current_thresholds: dict[str, Any]) -> vol.Schema:
        """Generate schema for humidifier threshold settings."""
        return build_stage_threshold_schema(current_thresholds, DEFAULT_THRESHOLDS)
