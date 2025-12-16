"""Irrigation configuration handler for Growspace Manager."""

from __future__ import annotations

import json
import logging
from typing import Any

import voluptuous as vol

from homeassistant.helpers import selector

from . import BaseConfigHandler

_LOGGER = logging.getLogger(__name__)


class IrrigationConfigHandler(BaseConfigHandler[dict[str, Any]]):
    """Handle irrigation configuration steps."""

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
            vol.Optional(
                "irrigation_pump_entity",
                default=irrigation_pump_default,
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["switch", "input_boolean"])
            ),
            vol.Optional(
                "drain_pump_entity",
                default=drain_pump_default,
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
            schema_dict.update(
                {
                    vol.Optional(
                        "lights_on_time",
                        default=irrigation_options.get("lights_on_time", "06:00:00"),
                    ): selector.TimeSelector(),
                    vol.Optional(
                        "target_vwc_percent",
                        default=irrigation_options.get("target_vwc_percent", 55.0),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0, max=100, step=0.1, unit_of_measurement="%"
                        )
                    ),
                    vol.Optional(
                        "p0_duration_minutes",
                        default=irrigation_options.get("p0_duration_minutes", 60),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(min=0, unit_of_measurement="min")
                    ),
                    vol.Optional(
                        "shot_duration_seconds",
                        default=irrigation_options.get("shot_duration_seconds", 10),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(min=1, unit_of_measurement="sec")
                    ),
                    vol.Optional(
                        "shot_interval_minutes",
                        default=irrigation_options.get("shot_interval_minutes", 15),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(min=1, unit_of_measurement="min")
                    ),
                    vol.Optional(
                        "maintenance_dryback_percent",
                        default=irrigation_options.get(
                            "maintenance_dryback_percent", 2.0
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0.1, step=0.1, unit_of_measurement="%"
                        )
                    ),
                    vol.Optional(
                        "p2_stop_before_lights_off_minutes",
                        default=irrigation_options.get(
                            "p2_stop_before_lights_off_minutes", 120
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(min=0, unit_of_measurement="min")
                    ),
                }
            )

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
