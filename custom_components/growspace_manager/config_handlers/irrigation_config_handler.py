"""Irrigation configuration handler for Growspace Manager."""

from __future__ import annotations

from dataclasses import asdict
import json
import logging
from typing import Any

import voluptuous as vol

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

        growspace_options = coordinator.services.growspaces.get_sorted_growspace_options()

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
        growspace = coordinator.services.growspaces.get_growspace(self.flow.selected_growspace_id)

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
        growspace = coordinator.services.growspaces.get_growspace(self.flow.selected_growspace_id)

        if not growspace:
            return self.flow.async_abort(reason="growspace_not_found")

        # Load ALL current irrigation options for the growspace from the Growspace object
        irrigation_options = asdict(growspace.irrigation_config)

        if user_input is not None:
            # Delegate update logic to coordinator
            await coordinator.services.growspaces.update_irrigation_config(
                self.flow.selected_growspace_id, **user_input
            )

            # This triggers async_update_listener in __init__.py, reloading the IrrigationCoordinator
            return self.flow.async_create_entry(
                title="",
                data=self.config_entry.options,  # No changes to ConfigEntry options
                description="Irrigation settings have been updated.",
            )

        # Describe schema to pass ALL data to the Lovelace component
        schema = self.get_irrigation_overview_schema(
            irrigation_options, self.flow.selected_growspace_id
        )

        return self.flow.async_show_form(
            step_id="irrigation_overview",
            data_schema=schema,
            description_placeholders={"growspace_name": growspace.name},
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
                selector.EntitySelectorConfig(domain=["switch", "input_boolean"])
            ),
            vol.Optional(
                "drain_pump_entity",
                description={"suggested_value": drain_pump_default},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["switch", "input_boolean"])
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
                "shot_duration_seconds",
                default=irrigation_options.get("shot_duration_seconds", 10),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    unit_of_measurement="sec",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                "shot_interval_minutes",
                default=irrigation_options.get("shot_interval_minutes", 15),
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
        }
