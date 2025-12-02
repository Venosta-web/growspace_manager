"""AI Configuration Handler for Growspace Manager."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import conversation
from homeassistant.helpers import selector

from ..const import (
    AI_PERSONALITIES,
    CONF_AI_ENABLED,
    CONF_ASSISTANT_ID,
    CONF_NOTIFICATION_PERSONALITY,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class AIConfigHandler:
    """Handler for AI configuration steps."""

    def __init__(self, hass, config_entry):
        """Initialize the AI config handler."""
        self.hass = hass
        self.config_entry = config_entry

    async def get_ai_settings_schema(self) -> vol.Schema:
        """Build the schema for AI settings with enhanced options."""
        current_settings = self.config_entry.options.get("ai_settings", {})

        # Get available conversation agents (LLM integrations)
        assistants = []
        try:
            # Try to get agents from the conversation integration
            if hasattr(conversation, "async_get_conversation_agents"):
                # Newer HA versions
                agents_dict = await conversation.async_get_conversation_agents(
                    self.hass
                )
                assistants = [
                    {"id": agent_id, "name": agent_info.name}
                    for agent_id, agent_info in agents_dict.items()
                ]
            else:
                # Fallback for older versions
                agent_manager = self.hass.data.get("conversation")
                if agent_manager and hasattr(agent_manager, "async_get_agents"):
                    assistants = await agent_manager.async_get_agents()
        except Exception as err:
            _LOGGER.warning("Could not fetch conversation agents: %s", err)

        # Filter to valid agents with id and name
        valid_assistants = [
            a for a in assistants if isinstance(a, dict) and "id" in a and "name" in a
        ]

        if not valid_assistants:
            # If no agents found, try to get at least the default
            try:
                default_agent = await conversation.async_get_agent(self.hass)
                if default_agent and hasattr(default_agent, "id"):
                    valid_assistants = [
                        {"id": default_agent.id, "name": "Default Assistant"}
                    ]
            except Exception:
                pass

        assistant_options = [
            selector.SelectOptionDict(value=assistant["id"], label=assistant["name"])
            for assistant in valid_assistants
        ]

        schema = {
            vol.Required(
                CONF_AI_ENABLED, default=current_settings.get(CONF_AI_ENABLED, False)
            ): selector.BooleanSelector(),
        }

        if assistant_options:
            schema[
                vol.Optional(
                    CONF_ASSISTANT_ID,
                    default=current_settings.get(CONF_ASSISTANT_ID),
                )
            ] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=assistant_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        else:
            # Show a text field if no assistants detected (shouldn't happen normally)
            schema[
                vol.Optional(
                    CONF_ASSISTANT_ID, default=current_settings.get(CONF_ASSISTANT_ID)
                )
            ] = selector.TextSelector(
                selector.TextSelectorConfig(
                    type=selector.TextSelectorType.TEXT,
                )
            )

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
                "ai_notifications_enabled",
                default=current_settings.get("ai_notifications_enabled", True),
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

        return vol.Schema(schema)

    async def save_ai_settings(self, user_input: dict[str, Any]) -> dict[str, Any]:
        """Save AI settings to the coordinator and config entry."""
        coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]["coordinator"]
        new_options = self.config_entry.options.copy()
        new_options["ai_settings"] = user_input

        # Update coordinator's in-memory options
        coordinator.options = new_options

        # Save to storage
        await coordinator.async_save()

        return new_options
