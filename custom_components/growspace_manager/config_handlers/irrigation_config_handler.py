"""Irrigation configuration handler for Growspace Manager."""

from __future__ import annotations

import json
import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector

_LOGGER = logging.getLogger(__name__)


class IrrigationConfigHandler:
    """Handle irrigation configuration steps."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the handler."""
        self.hass = hass
        self.config_entry = config_entry

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

        return vol.Schema(
            {
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
                # Read-only Fields: Schedules and ID (Passed to frontend for visual use/service calls)
                # Must be stringified to pass complex objects through schema inputs
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
