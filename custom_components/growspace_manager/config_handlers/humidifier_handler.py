"""Humidifier configuration handler for Growspace Manager."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import (
    CONF_CONFIGURE_ADVANCED,
    CONF_DAY,
    CONF_NIGHT,
    CONF_OFF,
    CONF_ON,
    DEHUMIDIFIER_STAGES,
)
from custom_components.growspace_manager.humidifier_coordinator import (
    DEFAULT_THRESHOLDS,
)
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import selector

from . import AbortFlow, BaseConfigHandler

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
            new_thresholds: dict[str, Any] = {}
            for stage in DEHUMIDIFIER_STAGES:
                new_thresholds[stage] = {}
                for cycle in ["day", "night"]:
                    new_thresholds[stage][cycle] = {
                        "on": user_input[f"{stage}_{cycle}_on"],
                        "off": user_input[f"{stage}_{cycle}_off"],
                    }

            env_config = self.flow.env_config_step1.copy()
            env_config["humidifier_thresholds"] = new_thresholds

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
        schema_dict = {}
        for stage in DEHUMIDIFIER_STAGES:
            for cycle in [CONF_DAY, CONF_NIGHT]:
                defaults = current_thresholds.get(stage, {}).get(
                    cycle, DEFAULT_THRESHOLDS[stage][cycle]
                )

                schema_dict[
                    vol.Required(
                        f"{stage}_{cycle}_{CONF_ON}", default=defaults[CONF_ON]
                    )
                ] = selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.1,
                        max=3.0,
                        step=0.01,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="kPa",
                    )
                )

                schema_dict[
                    vol.Required(
                        f"{stage}_{cycle}_{CONF_OFF}", default=defaults[CONF_OFF]
                    )
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
