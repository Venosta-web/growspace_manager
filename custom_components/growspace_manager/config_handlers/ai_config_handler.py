"""AI Configuration Handler for Growspace Manager."""

from __future__ import annotations

import logging
from typing import Any, cast

import voluptuous as vol

from custom_components.growspace_manager.const import (
    AI_PERSONALITIES,
    CONF_AI_AUTO_ALERTS,
    CONF_AI_ENABLED,
    CONF_AI_TASK_ENTITY_ID,
    CONF_ASSISTANT_ID,
    CONF_BRIEFING_INTERVAL_MINUTES,
    CONF_BRIEFING_TRIGGER_ENTITIES,
    CONF_NOTIFICATION_PERSONALITY,
    CONF_VISION_CHECKUP_ENABLED,
    CONF_VISION_DEBUG_ENABLED,
    DEFAULT_BRIEFING_INTERVAL_MINUTES,
)
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import selector

from . import AbortFlow, BaseConfigHandler

_LOGGER = logging.getLogger(__name__)


class AIConfigHandler(BaseConfigHandler[dict[str, Any]]):
    """Handler for AI configuration steps."""

    async def get_ai_settings_schema(self) -> vol.Schema:
        """Build the schema for AI settings with enhanced options."""
        if self.config_entry is None:
            current_settings = {}
        else:
            current_settings = self.config_entry.options.get("ai_settings", {})

        schema: dict[Any, Any] = {
            vol.Required(
                CONF_AI_ENABLED, default=current_settings.get(CONF_AI_ENABLED, False)
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_ASSISTANT_ID,
                default=current_settings.get(CONF_ASSISTANT_ID),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="conversation")
            ),
        }

        schema[
            vol.Optional(
                CONF_NOTIFICATION_PERSONALITY,
                default=current_settings.get(CONF_NOTIFICATION_PERSONALITY, "Standard"),
            )
        ] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=AI_PERSONALITIES,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )

        # Add option to enable/disable AI notifications separately from advice
        schema[
            vol.Optional(
                CONF_AI_AUTO_ALERTS,
                default=current_settings.get(CONF_AI_AUTO_ALERTS, True),
            )
        ] = selector.BooleanSelector()

        # Add option to limit AI response length
        schema[
            vol.Optional(
                "max_response_length",
                default=current_settings.get("max_response_length", 250),
            )
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=50,
                max=1000,
                step=10,
                mode=selector.NumberSelectorMode.BOX,
            )
        )

        # Add vision checkup toggle
        schema[
            vol.Optional(
                CONF_VISION_CHECKUP_ENABLED,
                default=current_settings.get(CONF_VISION_CHECKUP_ENABLED, False),
            )
        ] = selector.BooleanSelector()

        # Add vision debug toggle
        schema[
            vol.Optional(
                CONF_VISION_DEBUG_ENABLED,
                default=current_settings.get(CONF_VISION_DEBUG_ENABLED, False),
            )
        ] = selector.BooleanSelector()

        schema[
            vol.Optional(
                CONF_AI_TASK_ENTITY_ID,
                default=current_settings.get(CONF_AI_TASK_ENTITY_ID),
            )
        ] = selector.EntitySelector(selector.EntitySelectorConfig(domain="ai_task"))

        schema[
            vol.Optional(
                CONF_BRIEFING_INTERVAL_MINUTES,
                default=current_settings.get(
                    CONF_BRIEFING_INTERVAL_MINUTES, DEFAULT_BRIEFING_INTERVAL_MINUTES
                ),
            )
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=5,
                max=1440,
                step=5,
                mode=selector.NumberSelectorMode.BOX,
            )
        )

        schema[
            vol.Optional(
                CONF_BRIEFING_TRIGGER_ENTITIES,
                default=current_settings.get(CONF_BRIEFING_TRIGGER_ENTITIES, []),
            )
        ] = selector.EntitySelector(
            selector.EntitySelectorConfig(multiple=True)
        )

        return vol.Schema(schema)

    async def async_step_configure_ai(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for configuring AI settings."""
        try:
            self.get_coordinator()
        except AbortFlow as e:
            return self.flow.async_abort(reason=e.reason)

        errors = {}

        if user_input is not None:
            # Validate that if AI is enabled, an assistant is selected
            if user_input.get(CONF_AI_ENABLED) and not user_input.get(
                CONF_ASSISTANT_ID
            ):
                errors["base"] = "assistant_required"
            else:
                new_options = await self.save_ai_settings(user_input)

                # Inform user about the changes
                return self.flow.async_create_entry(
                    title="",
                    data=new_options,
                    description="AI settings have been updated. "
                    + (
                        "AI features are now enabled. "
                        if user_input.get(CONF_AI_ENABLED)
                        else "AI features are disabled. "
                    ),
                )

        return self.flow.async_show_form(
            step_id="configure_ai",
            data_schema=await self.get_ai_settings_schema(),
            errors=errors,
        )

    async def save_ai_settings(self, user_input: dict[str, Any]) -> dict[str, Any]:
        """Save AI settings to the coordinator and config entry."""
        if self.config_entry is None:
            raise ValueError("Coordinator not found")
        coordinator = self.config_entry.runtime_data
        if coordinator is None:
            raise ValueError("Coordinator not found")
        new_options = self.config_entry.options.copy()
        new_options["ai_settings"] = user_input

        # Update coordinator's in-memory options
        coordinator.options = new_options

        # Save to storage
        await coordinator.services.save()

        return cast(dict[str, Any], new_options)
