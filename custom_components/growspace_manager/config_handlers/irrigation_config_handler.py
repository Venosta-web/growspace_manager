"""Irrigation configuration handler for Growspace Manager."""

from __future__ import annotations

from dataclasses import asdict
import json
import logging
from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import ShotSizingMode, SubstrateMediaType
from custom_components.growspace_manager.services.irrigation_change import (
    IrrigationChangeError,
)
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import selector

from . import AbortFlow, BaseConfigHandler

_LOGGER = logging.getLogger(__name__)


class IrrigationConfigHandler(BaseConfigHandler[dict[str, Any]]):
    """Handle irrigation configuration steps."""

    async def async_step_select_growspace_for_irrigation(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show a form to select a growspace before configuring its irrigation."""
        try:
            coordinator = self.get_coordinator()
        except AbortFlow as e:
            return self.flow.async_abort(reason=e.reason)

        growspace_options = (
            coordinator.services.growspaces.get_sorted_growspace_options()
        )

        if not growspace_options:
            return self.flow.async_abort(reason="no_growspaces")

        if user_input is not None:
            self.flow.selected_growspace_id = user_input["growspace_id"]
            return await self.async_step_configure_irrigation()

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
            step_id="select_growspace_for_irrigation", data_schema=vol.Schema(schema)
        )

    async def async_step_configure_irrigation(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the irrigation configuration menu for a selected growspace."""
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

        # Route directly to the unified overview step
        return await self.async_step_irrigation_overview()

    async def async_step_irrigation_overview(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the unified irrigation management screen for the Lovelace card."""
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

        # Load ALL current irrigation options for the growspace. The strategy and
        # config carry disjoint field names, so a flat merge seeds every form
        # field from its stored value (config wins on the impossible collision).
        # ``use_vwc_steering`` is the form's name for the strategy ``enabled`` flag.
        irrigation_options = {
            **asdict(growspace.irrigation_strategy),
            **asdict(growspace.irrigation_config),
            "use_vwc_steering": growspace.irrigation_strategy.enabled,
        }

        errors: dict[str, str] = {}
        error_message: str | None = None
        if user_input is not None:
            change_values = dict(user_input)
            for display_field in (
                "current_irrigation_times",
                "current_drain_times",
                "growspace_id_read_only",
            ):
                change_values.pop(display_field, None)
            try:
                await coordinator.services.growspaces.update_irrigation_config(
                    growspace_id, change_values
                )
            except IrrigationChangeError as err:
                errors["base"] = "invalid_irrigation_change"
                error_message = str(err)
                irrigation_options.update(user_input)
            else:
                if self.config_entry is None:
                    return self.flow.async_abort(reason="setup_error")
                # This triggers async_update_listener in __init__.py, reloading the IrrigationCoordinator
                return self.flow.async_create_entry(
                    title="",
                    data=self.config_entry.options,  # No changes to ConfigEntry options
                    description="Irrigation settings have been updated.",
                )

        # Describe schema to pass ALL data to the Lovelace component
        schema = self.get_irrigation_overview_schema(irrigation_options, growspace_id)

        description_placeholders = {"growspace_name": growspace.name}
        if error_message is not None:
            description_placeholders["error"] = error_message
        return self.flow.async_show_form(
            step_id="irrigation_overview",
            data_schema=schema,
            errors=errors,
            description_placeholders=description_placeholders,
        )

    def get_irrigation_overview_schema(
        self, irrigation_options: dict[str, Any], growspace_id: str
    ) -> vol.Schema:
        """Generate the unified schema for pump entities and durations."""
        # Ensure EntitySelector receives None instead of ""
        irrigation_pump_default = irrigation_options.get("irrigation_pump_entity")
        if not irrigation_pump_default:
            irrigation_pump_default = None

        drain_pump_default = irrigation_options.get("drain_pump_entity")
        if not drain_pump_default:
            drain_pump_default = None

        schema_dict = {
            # R/W Fields: Pump Settings (User edits and submits these)
            # Use description/suggested_value (not default) so that clearing the
            # EntitySelector omits the key from user_input — allowing the coordinator
            # to set it to None rather than voluptuous restoring the old value.
            vol.Optional(
                "irrigation_pump_entity",
                description={"suggested_value": irrigation_pump_default},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["switch"])
            ),
            vol.Optional(
                "drain_pump_entity",
                description={"suggested_value": drain_pump_default},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["switch"])
            ),
            vol.Optional(
                "irrigation_duration",
                default=irrigation_options.get("irrigation_duration", 30),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Optional(
                "drain_duration",
                default=irrigation_options.get("drain_duration", 30),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Optional(
                "soil_trigger_percent",
                description={
                    "suggested_value": irrigation_options.get("soil_trigger_percent")
                },
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.0,
                    max=100.0,
                    step=0.1,
                    unit_of_measurement="%",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                "daily_volume_cap_liters",
                description={
                    "suggested_value": irrigation_options.get("daily_volume_cap_liters")
                },
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.0,
                    step=0.1,
                    unit_of_measurement="L",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                "max_cycles_per_day",
                description={
                    "suggested_value": irrigation_options.get("max_cycles_per_day")
                },
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    step=1,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                "skip_during_dark",
                default=irrigation_options.get("skip_during_dark", False),
            ): selector.BooleanSelector(),
            vol.Optional(
                "pause_on_low_tank",
                default=irrigation_options.get("pause_on_low_tank", True),
            ): selector.BooleanSelector(),
            vol.Optional(
                "log_to_logbook",
                default=irrigation_options.get("log_to_logbook", True),
            ): selector.BooleanSelector(),
            # VWC Crop Steering Settings
            vol.Optional(
                "use_vwc_steering",
                default=irrigation_options.get("use_vwc_steering", False),
            ): selector.BooleanSelector(),
        }

        # Add VWC Steering parameters if enabled
        if irrigation_options.get("use_vwc_steering"):
            vwc_schema = self._build_vwc_steering_schema(irrigation_options)
            schema_dict.update(vwc_schema)

        # Add Read-only Fields: Schedules and ID
        schema_dict.update(
            {
                vol.Optional(
                    "current_irrigation_times",
                    default=json.dumps(irrigation_options.get("irrigation_times", [])),
                ): selector.TextSelector(),
                vol.Optional(
                    "current_drain_times",
                    default=json.dumps(irrigation_options.get("drain_times", [])),
                ): selector.TextSelector(),
                vol.Optional(
                    "growspace_id_read_only", default=growspace_id
                ): selector.TextSelector(),
            }
        )

        return vol.Schema(schema_dict)

    def _build_vwc_steering_schema(
        self, irrigation_options: dict[str, Any]
    ) -> dict[Any, Any]:
        """Build the VWC (Volumetric Water Content) crop steering schema."""
        substrate_profile = irrigation_options.get("substrate_profile") or {}
        return {
            vol.Optional(
                "lights_on_time",
                default=irrigation_options.get("lights_on_time", "06:00:00"),
            ): selector.TimeSelector(),
            vol.Optional(
                "target_vwc_percent",
                default=irrigation_options.get("target_vwc_percent", 55.0),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=100,
                    step=0.1,
                    unit_of_measurement="%",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                "p0_duration_minutes",
                default=irrigation_options.get("p0_duration_minutes", 60),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    unit_of_measurement="min",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                "p1_shot_duration_seconds",
                default=irrigation_options.get(
                    "p1_shot_duration_seconds",
                    irrigation_options.get("shot_duration_seconds", 10),
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    unit_of_measurement="sec",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                "p1_shot_interval_minutes",
                default=irrigation_options.get(
                    "p1_shot_interval_minutes",
                    irrigation_options.get("shot_interval_minutes", 15),
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    unit_of_measurement="min",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                "p2_shot_duration_seconds",
                default=irrigation_options.get(
                    "p2_shot_duration_seconds",
                    irrigation_options.get("shot_duration_seconds", 10),
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    unit_of_measurement="sec",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                "p2_shot_interval_minutes",
                default=irrigation_options.get(
                    "p2_shot_interval_minutes",
                    irrigation_options.get("shot_interval_minutes", 15),
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    unit_of_measurement="min",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                "maintenance_dryback_percent",
                default=irrigation_options.get("maintenance_dryback_percent", 2.0),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.1,
                    step=0.1,
                    unit_of_measurement="%",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                "p2_stop_before_lights_off_minutes",
                default=irrigation_options.get(
                    "p2_stop_before_lights_off_minutes", 120
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    unit_of_measurement="min",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                "auto_advance_p1_to_p2",
                default=irrigation_options.get("auto_advance_p1_to_p2", False),
            ): selector.BooleanSelector(),
            vol.Optional(
                "auto_advance_p2_to_p3",
                default=irrigation_options.get("auto_advance_p2_to_p3", False),
            ): selector.BooleanSelector(),
            vol.Optional(
                "halt_on_runoff_ec_threshold",
                description={
                    "suggested_value": irrigation_options.get(
                        "halt_on_runoff_ec_threshold"
                    )
                },
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.0,
                    step=0.1,
                    unit_of_measurement="mS/cm",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            # Pore EC Target Band — distinct from the per-stage *feed* EC ranges;
            # pore EC legitimately runs above feed EC when stacking (CONTEXT.md).
            vol.Optional(
                "pore_ec_target_min",
                description={
                    "suggested_value": irrigation_options.get("pore_ec_target_min")
                },
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.0,
                    step=0.1,
                    unit_of_measurement="mS/cm",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                "pore_ec_target_max",
                description={
                    "suggested_value": irrigation_options.get("pore_ec_target_max")
                },
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.0,
                    step=0.1,
                    unit_of_measurement="mS/cm",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                "ec_modulation_enabled",
                default=irrigation_options.get("ec_modulation_enabled", False),
            ): selector.BooleanSelector(),
            # Shot Sizing Mode + Substrate Profile (Volume Mode, ADR-0011).
            # Optional/suggested_value so untouched submissions round-trip the
            # stored values idempotently and Seconds Mode users are unaffected.
            # The flat substrate fields are folded into the nested profile on
            # submit by the shared _build_substrate_profile_update helper.
            vol.Optional(
                "shot_sizing_mode",
                description={
                    "suggested_value": irrigation_options.get(
                        "shot_sizing_mode", ShotSizingMode.SECONDS.value
                    )
                },
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value=mode.value, label=mode.value)
                        for mode in ShotSizingMode
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                "substrate_media_type",
                description={
                    "suggested_value": substrate_profile.get(
                        "media_type", SubstrateMediaType.COCO.value
                    )
                },
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value=media.value, label=media.value)
                        for media in SubstrateMediaType
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                "substrate_liters_per_pot",
                description={
                    "suggested_value": substrate_profile.get("liters_per_pot")
                },
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.0,
                    step=0.1,
                    unit_of_measurement="L",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                "pump_flow_rate_ml_per_sec",
                description={
                    "suggested_value": irrigation_options.get(
                        "pump_flow_rate_ml_per_sec"
                    )
                },
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.0,
                    step=0.1,
                    unit_of_measurement="mL/s",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                "p1_shot_volume_percent",
                description={
                    "suggested_value": irrigation_options.get("p1_shot_volume_percent")
                },
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.0,
                    max=100.0,
                    step=0.1,
                    unit_of_measurement="%",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                "p2_shot_volume_percent",
                description={
                    "suggested_value": irrigation_options.get("p2_shot_volume_percent")
                },
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.0,
                    max=100.0,
                    step=0.1,
                    unit_of_measurement="%",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
        }
