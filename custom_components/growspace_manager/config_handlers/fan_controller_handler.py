"""Fan controller configuration handler for Growspace Manager."""

from __future__ import annotations

from dataclasses import asdict
import logging
from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import FanRegulationMode
from custom_components.growspace_manager.models import (
    CirculationFanConfig,
)
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import selector

from . import AbortFlow, BaseConfigHandler

_LOGGER = logging.getLogger(__name__)


class FanControllerHandler(BaseConfigHandler[dict[str, Any]]):
    """Handle the five fan controller configuration steps."""

    async def async_step_configure_fan_controller(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for configuring the circulation fan controller."""
        try:
            coordinator = self.get_coordinator()
        except AbortFlow as e:
            return self.flow.async_abort(reason=e.reason)
        growspace_id = self.flow.selected_growspace_id
        growspace = coordinator.services.growspaces.get_growspace(growspace_id)

        if not growspace:
            return self.flow.async_abort(reason="growspace_not_found")

        current_cfg = (
            growspace.environment_config.circulation_fan_config
            if growspace.environment_config
            else None
        ) or CirculationFanConfig()

        if user_input is not None:
            min_speed = user_input.get("min_speed", 0)
            max_speed = user_input.get("max_speed", 100)
            if min_speed >= max_speed:
                return self.flow.async_show_form(
                    step_id="configure_fan_controller",
                    data_schema=self.get_fan_controller_schema(current_cfg),
                    errors={"base": "fan_speed_invalid"},
                    description_placeholders={"growspace_name": growspace.name},
                )

            self.flow.fan_config_step1 = dict(user_input)
            regulation_mode = user_input.get("regulation_mode", FanRegulationMode.VPD)
            if regulation_mode == FanRegulationMode.VPD:
                return await self.flow.async_step_configure_fan_vpd()
            if regulation_mode == FanRegulationMode.HUMIDITY:
                return await self.flow.async_step_configure_fan_humidity()
            return await self.flow.async_step_configure_fan_temperature()

        return self.flow.async_show_form(
            step_id="configure_fan_controller",
            data_schema=self.get_fan_controller_schema(current_cfg),
            description_placeholders={"growspace_name": growspace.name},
        )

    async def async_step_configure_fan_vpd(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure VPD target, tolerance, and critical temperature limits."""
        try:
            coordinator = self.get_coordinator()
        except AbortFlow as e:
            return self.flow.async_abort(reason=e.reason)
        growspace_id = self.flow.selected_growspace_id
        growspace = coordinator.services.growspaces.get_growspace(growspace_id)

        if not growspace:
            return self.flow.async_abort(reason="growspace_not_found")

        current_cfg = (
            growspace.environment_config.circulation_fan_config
            if growspace.environment_config
            else None
        ) or CirculationFanConfig()

        if user_input is not None:
            stage_vpd_enabled = user_input.get("stage_vpd_enabled", current_cfg.stage_vpd_enabled)
            # When stage mode is off the user must supply vpd_target; re-render if missing.
            if not stage_vpd_enabled and "vpd_target" not in user_input:
                self.flow.fan_config_step1.update(user_input)
                return self.flow.async_show_form(
                    step_id="configure_fan_vpd",
                    data_schema=self.get_fan_vpd_schema(current_cfg, stage_vpd_enabled=False),
                    description_placeholders={"growspace_name": growspace.name},
                )
            # Preserve existing vpd_target when stage mode is on and no value was submitted.
            if stage_vpd_enabled and "vpd_target" not in user_input:
                user_input = dict(user_input)
                user_input["vpd_target"] = current_cfg.vpd_target
            self.flow.fan_config_step1.update(user_input)
            if self.flow.fan_config_step1.get("wind_enabled"):
                return await self.flow.async_step_configure_fan_wind()
            return await self._async_save_fan_config_and_continue(growspace)

        return self.flow.async_show_form(
            step_id="configure_fan_vpd",
            data_schema=self.get_fan_vpd_schema(current_cfg),
            description_placeholders={"growspace_name": growspace.name},
        )

    async def async_step_configure_fan_humidity(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure humidity target and tolerance."""
        try:
            coordinator = self.get_coordinator()
        except AbortFlow as e:
            return self.flow.async_abort(reason=e.reason)
        growspace_id = self.flow.selected_growspace_id
        growspace = coordinator.services.growspaces.get_growspace(growspace_id)

        if not growspace:
            return self.flow.async_abort(reason="growspace_not_found")

        current_cfg = (
            growspace.environment_config.circulation_fan_config
            if growspace.environment_config
            else None
        ) or CirculationFanConfig()

        if user_input is not None:
            self.flow.fan_config_step1.update(user_input)
            if self.flow.fan_config_step1.get("wind_enabled"):
                return await self.flow.async_step_configure_fan_wind()
            return await self._async_save_fan_config_and_continue(growspace)

        return self.flow.async_show_form(
            step_id="configure_fan_humidity",
            data_schema=self.get_fan_humidity_schema(current_cfg),
            description_placeholders={"growspace_name": growspace.name},
        )

    async def async_step_configure_fan_temperature(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure temperature target and tolerance."""
        try:
            coordinator = self.get_coordinator()
        except AbortFlow as e:
            return self.flow.async_abort(reason=e.reason)
        growspace_id = self.flow.selected_growspace_id
        growspace = coordinator.services.growspaces.get_growspace(growspace_id)

        if not growspace:
            return self.flow.async_abort(reason="growspace_not_found")

        current_cfg = (
            growspace.environment_config.circulation_fan_config
            if growspace.environment_config
            else None
        ) or CirculationFanConfig()

        if user_input is not None:
            self.flow.fan_config_step1.update(user_input)
            if self.flow.fan_config_step1.get("wind_enabled"):
                return await self.flow.async_step_configure_fan_wind()
            return await self._async_save_fan_config_and_continue(growspace)

        return self.flow.async_show_form(
            step_id="configure_fan_temperature",
            data_schema=self.get_fan_temperature_schema(current_cfg),
            description_placeholders={"growspace_name": growspace.name},
        )

    async def async_step_configure_fan_wind(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure wind oscillation parameters."""
        try:
            coordinator = self.get_coordinator()
        except AbortFlow as e:
            return self.flow.async_abort(reason=e.reason)
        growspace_id = self.flow.selected_growspace_id
        growspace = coordinator.services.growspaces.get_growspace(growspace_id)

        if not growspace:
            return self.flow.async_abort(reason="growspace_not_found")

        current_cfg = (
            growspace.environment_config.circulation_fan_config
            if growspace.environment_config
            else None
        ) or CirculationFanConfig()

        if user_input is not None:
            self.flow.fan_config_step1.update(user_input)
            return await self._async_save_fan_config_and_continue(growspace)

        return self.flow.async_show_form(
            step_id="configure_fan_wind",
            data_schema=self.get_fan_wind_schema(current_cfg),
            description_placeholders={"growspace_name": growspace.name},
        )

    async def _async_save_fan_config_and_continue(self, growspace: Any) -> ConfigFlowResult:
        """Persist the assembled fan config onto the growspace and continue the flow."""
        fan_data = self.flow.fan_config_step1
        fan_cfg = CirculationFanConfig(
            enabled=fan_data.get("enabled", False),
            regulation_mode=FanRegulationMode(
                fan_data.get("regulation_mode", FanRegulationMode.VPD)
            ),
            min_speed=int(fan_data.get("min_speed", 0)),
            max_speed=int(fan_data.get("max_speed", 100)),
            humidity_target=float(fan_data.get("humidity_target", 60.0)),
            humidity_tolerance=float(fan_data.get("humidity_tolerance", 5.0)),
            temperature_target=float(fan_data.get("temperature_target", 25.0)),
            temperature_tolerance=float(fan_data.get("temperature_tolerance", 2.0)),
            vpd_target=float(fan_data.get("vpd_target", 1.0)),
            vpd_tolerance=float(fan_data.get("vpd_tolerance", 0.2)),
            critical_temp_low=fan_data.get("critical_temp_low"),
            critical_temp_high=fan_data.get("critical_temp_high"),
            critical_temp_hysteresis=float(fan_data.get("critical_temp_hysteresis", 1.0)),
            wind_enabled=bool(fan_data.get("wind_enabled", False)),
            wind_period_seconds=int(fan_data.get("wind_period_seconds", 60)),
            wind_amplitude_pct=int(fan_data.get("wind_amplitude_pct", 10)),
            stage_vpd_enabled=bool(fan_data.get("stage_vpd_enabled", False)),
        )

        env_config = self.flow.env_config_step1.copy()
        env_config["circulation_fan_config"] = asdict(fan_cfg)
        self.flow.env_config_step1 = env_config

        return await self.flow.async_step_configure_sensor_placement()

    # -------------------------------------------------------------------------
    # Schemas
    # -------------------------------------------------------------------------

    def get_fan_controller_schema(self, current_cfg: CirculationFanConfig) -> vol.Schema:
        """Schema for the base fan controller step."""
        return vol.Schema(
            {
                vol.Required("enabled", default=current_cfg.enabled): selector.BooleanSelector(),
                vol.Required(
                    "regulation_mode",
                    default=current_cfg.regulation_mode.value
                    if current_cfg.regulation_mode
                    else FanRegulationMode.VPD.value,
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=mode.value, label=mode.value.replace("_", " ").title()
                            )
                            for mode in FanRegulationMode
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required("min_speed", default=current_cfg.min_speed): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=99, step=1, mode=selector.NumberSelectorMode.SLIDER,
                        unit_of_measurement="%",
                    )
                ),
                vol.Required("max_speed", default=current_cfg.max_speed): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=100, step=1, mode=selector.NumberSelectorMode.SLIDER,
                        unit_of_measurement="%",
                    )
                ),
                vol.Optional(
                    "wind_enabled", default=current_cfg.wind_enabled
                ): selector.BooleanSelector(),
            }
        )

    def get_fan_vpd_schema(
        self,
        current_cfg: CirculationFanConfig,
        stage_vpd_enabled: bool | None = None,
    ) -> vol.Schema:
        """Schema for the VPD fan mode step.

        When stage_vpd_enabled is True the vpd_target field is omitted — the
        coordinator derives the target from the current growth stage.
        """
        if stage_vpd_enabled is None:
            stage_vpd_enabled = current_cfg.stage_vpd_enabled

        schema: dict = {
            vol.Required(
                "stage_vpd_enabled", default=stage_vpd_enabled
            ): selector.BooleanSelector(),
        }

        if not stage_vpd_enabled:
            schema[vol.Required("vpd_target", default=current_cfg.vpd_target)] = (
                selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.1, max=3.0, step=0.05,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="kPa",
                    )
                )
            )

        schema[vol.Required("vpd_tolerance", default=current_cfg.vpd_tolerance)] = (
            selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.01, max=1.0, step=0.01,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="kPa",
                )
            )
        )
        schema[vol.Optional("critical_temp_low", default=current_cfg.critical_temp_low)] = (
            vol.Any(None, selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=10, max=40, step=0.5,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="°C",
                )
            ))
        )
        schema[vol.Optional("critical_temp_high", default=current_cfg.critical_temp_high)] = (
            vol.Any(None, selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=10, max=50, step=0.5,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="°C",
                )
            ))
        )
        schema[vol.Required(
            "critical_temp_hysteresis", default=current_cfg.critical_temp_hysteresis
        )] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0.1, max=5.0, step=0.1,
                mode=selector.NumberSelectorMode.BOX,
                unit_of_measurement="°C",
            )
        )

        return vol.Schema(schema)

    def get_fan_humidity_schema(self, current_cfg: CirculationFanConfig) -> vol.Schema:
        """Schema for the humidity fan mode step."""
        return vol.Schema(
            {
                vol.Required(
                    "humidity_target", default=current_cfg.humidity_target
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=20, max=90, step=1,
                        mode=selector.NumberSelectorMode.SLIDER,
                        unit_of_measurement="%",
                    )
                ),
                vol.Required(
                    "humidity_tolerance", default=current_cfg.humidity_tolerance
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=20, step=0.5,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="%",
                    )
                ),
            }
        )

    def get_fan_temperature_schema(self, current_cfg: CirculationFanConfig) -> vol.Schema:
        """Schema for the temperature fan mode step."""
        return vol.Schema(
            {
                vol.Required(
                    "temperature_target", default=current_cfg.temperature_target
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=15, max=35, step=0.5,
                        mode=selector.NumberSelectorMode.SLIDER,
                        unit_of_measurement="°C",
                    )
                ),
                vol.Required(
                    "temperature_tolerance", default=current_cfg.temperature_tolerance
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.5, max=10, step=0.5,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="°C",
                    )
                ),
            }
        )

    def get_fan_wind_schema(self, current_cfg: CirculationFanConfig) -> vol.Schema:
        """Schema for the wind oscillation step."""
        return vol.Schema(
            {
                vol.Required(
                    "wind_period_seconds", default=current_cfg.wind_period_seconds
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=10, max=600, step=10,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="seconds",
                    )
                ),
                vol.Required(
                    "wind_amplitude_pct", default=current_cfg.wind_amplitude_pct
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=5, max=50, step=5,
                        mode=selector.NumberSelectorMode.SLIDER,
                        unit_of_measurement="%",
                    )
                ),
            }
        )
