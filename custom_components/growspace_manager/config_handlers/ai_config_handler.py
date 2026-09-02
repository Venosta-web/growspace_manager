"""AI Configuration Handler for Growspace Manager."""

from __future__ import annotations

import logging
from typing import Any

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
    CONF_VISION_ACCESS_TOKEN,
    CONF_VISION_CONNECTION_MODE,
    CONF_VISION_DEBUG_ENABLED,
    CONF_VISION_ENDPOINT_URL,
    CONF_VISION_EXPLAINER_SEES_IMAGE,
    DEFAULT_BRIEFING_INTERVAL_MINUTES,
    DEFAULT_VISION_CONNECTION_MODE,
    VISION_SETTINGS_KEY,
)
from custom_components.growspace_manager.exceptions import (
    VisionAuthError,
    VisionError,
    VisionIncompatibleError,
    VisionModelUnavailableError,
    VisionNotConfiguredError,
    VisionTransportError,
)
from custom_components.growspace_manager.vision_connection import (
    VisionConnection,
    VisionConnectionMode,
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

        # The local checkup is complete without cloud AI. This setting controls
        # only whether the optional observation pass may inspect the image.
        schema[
            vol.Optional(
                CONF_VISION_EXPLAINER_SEES_IMAGE,
                default=current_settings.get(CONF_VISION_EXPLAINER_SEES_IMAGE, True),
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
        ] = selector.EntitySelector(selector.EntitySelectorConfig(multiple=True))

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

        return new_options

    def get_vision_connection_schema(self) -> vol.Schema:
        """Build the schema for the Growspace Vision connection settings."""
        current = self._vision_settings()
        return vol.Schema(
            {
                vol.Required(
                    CONF_VISION_CONNECTION_MODE,
                    default=current.get(
                        CONF_VISION_CONNECTION_MODE, DEFAULT_VISION_CONNECTION_MODE
                    ),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=VisionConnectionMode.AUTOMATIC.value,
                                label="Discover the Growspace Vision App automatically",
                            ),
                            selector.SelectOptionDict(
                                value=VisionConnectionMode.MANUAL.value,
                                label="Use a manually configured endpoint",
                            ),
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
                vol.Optional(
                    CONF_VISION_ENDPOINT_URL,
                    default=current.get(CONF_VISION_ENDPOINT_URL, ""),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
                ),
                vol.Optional(
                    CONF_VISION_ACCESS_TOKEN,
                    default=current.get(CONF_VISION_ACCESS_TOKEN, ""),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
            }
        )

    async def async_step_configure_vision(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and save the Growspace Vision connection settings.

        The submitted connection is probed before it is stored, so a wrong
        endpoint or token is a form error rather than a checkup that only fails
        hours later during a scheduled run.
        """
        try:
            self.get_coordinator()
        except AbortFlow as e:
            return self.flow.async_abort(reason=e.reason)

        errors: dict[str, str] = {}

        if user_input is not None:
            settings = _normalize_vision_settings(user_input)
            try:
                await self._async_probe_vision(settings)
            except VisionNotConfiguredError:
                errors["base"] = "vision_not_configured"
            except VisionAuthError:
                errors["base"] = "vision_invalid_auth"
            except VisionIncompatibleError:
                errors["base"] = "vision_incompatible"
            except VisionModelUnavailableError:
                errors["base"] = "vision_model_unavailable"
            except VisionError:
                errors["base"] = "vision_cannot_connect"
            else:
                new_options = await self.save_vision_settings(settings)
                return self.flow.async_create_entry(title="", data=new_options)

        return self.flow.async_show_form(
            step_id="configure_vision",
            data_schema=self.get_vision_connection_schema(),
            errors=errors,
        )

    async def save_vision_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        """Persist the connection settings and refresh the live coordinator."""
        if self.config_entry is None:
            raise ValueError("Coordinator not found")
        coordinator = self.config_entry.runtime_data
        if coordinator is None:
            raise ValueError("Coordinator not found")

        new_options = dict(self.config_entry.options)
        new_options[VISION_SETTINGS_KEY] = settings
        coordinator.options = new_options
        await coordinator.services.save()
        await coordinator.vision_connection.async_refresh()
        return new_options

    async def _async_probe_vision(self, settings: dict[str, Any]) -> None:
        """Resolve and negotiate these settings, raising a `VisionError` if unusable.

        Anything the client does not already type — a URL `aiohttp` refuses to
        parse, say — becomes a transport failure, so the caller only has to
        handle the Vision hierarchy.
        """
        connection = VisionConnection(
            self.hass, lambda: {VISION_SETTINGS_KEY: settings}
        )
        try:
            endpoint = await connection.async_resolve_endpoint()
            await connection.build_client(endpoint).async_negotiate()
        except VisionError:
            raise
        except Exception as err:
            _LOGGER.debug("Growspace Vision connection probe failed", exc_info=True)
            raise VisionTransportError("Growspace Vision could not be reached") from err

    def _vision_settings(self) -> dict[str, Any]:
        if self.config_entry is None:
            return {}
        settings = self.config_entry.options.get(VISION_SETTINGS_KEY)
        return dict(settings) if isinstance(settings, dict) else {}


def _normalize_vision_settings(user_input: dict[str, Any]) -> dict[str, Any]:
    """Reduce the submitted form to what the selected mode actually uses.

    Switching back to automatic drops the manual endpoint and token rather than
    keeping them out of sight, so there is no dormant credential to fall back
    to and no secret retained for a connection the grower stopped using.
    """
    mode = str(
        user_input.get(CONF_VISION_CONNECTION_MODE, DEFAULT_VISION_CONNECTION_MODE)
    )
    if mode != VisionConnectionMode.MANUAL:
        return {CONF_VISION_CONNECTION_MODE: VisionConnectionMode.AUTOMATIC.value}
    return {
        CONF_VISION_CONNECTION_MODE: VisionConnectionMode.MANUAL.value,
        CONF_VISION_ENDPOINT_URL: str(
            user_input.get(CONF_VISION_ENDPOINT_URL) or ""
        ).strip(),
        CONF_VISION_ACCESS_TOKEN: str(
            user_input.get(CONF_VISION_ACCESS_TOKEN) or ""
        ).strip(),
    }
