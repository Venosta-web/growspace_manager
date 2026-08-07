"""AI notification rewriter for Growspace Manager."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any, cast

from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import intent
from homeassistant.util.dt import utcnow

from .const import CONF_ASSISTANT_ID, CONF_NOTIFICATION_PERSONALITY
from .exceptions import GrowspaceError

_LOGGER = logging.getLogger(__name__)


class AINotificationRewriter:
    """Rewrites notification messages using the HA Assist conversation API."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialise the rewriter."""
        self.hass = hass
        self._ai_cooldown_until: datetime | None = None

    async def async_rewrite(
        self,
        original_message: str,
        growspace_name: str,
        sensor_states: dict[str, Any] | None,
        ai_settings: dict[str, Any],
    ) -> str:
        """Rewrite a notification message using Home Assistant Assist.

        Returns the rewritten message, or the original if AI is unavailable.
        """
        if self._ai_cooldown_until and utcnow() < self._ai_cooldown_until:
            _LOGGER.debug("AI notification generation is on rate-limit cooldown")
            return original_message

        # Imported here rather than at module scope: the conversation component pulls
        # in the HA intent stack (hassil, home-assistant-intents) at import time, so a
        # module-scope import makes every module that transitively reaches this file —
        # including __init__ — fail to import when that stack is unavailable.
        from homeassistant.components import conversation  # noqa: PLC0415

        try:
            personality = ai_settings.get(CONF_NOTIFICATION_PERSONALITY, "Standard")
            agent_id = ai_settings.get(CONF_ASSISTANT_ID)
            max_length = ai_settings.get("max_response_length", 250)

            prompt = self._build_rewrite_prompt(
                original_message,
                growspace_name,
                sensor_states,
                personality,
                max_length,
            )

            _LOGGER.debug("Sending notification rewrite prompt to AI assistant")

            result = await conversation.async_converse(
                self.hass,
                text=prompt,
                conversation_id=None,
                context=Context(),
                agent_id=agent_id,
            )

            if result and result.response:
                if (
                    getattr(result.response, "error_code", None) is not None
                    or getattr(result.response, "response_type", None)
                    == intent.IntentResponseType.ERROR
                ):
                    err_msg = ""
                    if result.response.speech and result.response.speech.get("plain"):
                        err_msg = result.response.speech["plain"]["speech"]

                    err_code = getattr(result.response, "error_code", "") or ""
                    if (
                        any(
                            s in err_msg
                            for s in ("429", "Too Many Requests", "RESOURCE_EXHAUSTED")
                        )
                        or "resource_exhausted" in err_code.lower()
                    ):
                        _LOGGER.warning(
                            "AI notification rate limit reached (429), pausing AI features temporarily"
                        )
                        self._ai_cooldown_until = utcnow() + timedelta(minutes=15)
                    else:
                        _LOGGER.warning(
                            "AI notification generation failed: %s", err_msg
                        )
                    return original_message

                if result.response.speech and result.response.speech.get("plain"):
                    rewritten = result.response.speech["plain"]["speech"]
                    if len(rewritten) <= max_length:
                        _LOGGER.info("AI rewrote notification in %s style", personality)
                        return cast(str, rewritten)
                    if len(rewritten) < max_length + 50:
                        _LOGGER.info("AI response truncated to fit length limit")
                        return cast(
                            str, rewritten[:max_length].rsplit(" ", 1)[0] + "..."
                        )
                    _LOGGER.warning(
                        "AI response too long (%d chars > %d), using default",
                        len(rewritten),
                        max_length,
                    )
                else:
                    _LOGGER.warning("AI returned empty speech, using default message")
            else:
                _LOGGER.warning("AI returned empty response, using default message")

        except (
            AttributeError,
            KeyError,
            ValueError,
            ServiceValidationError,
            GrowspaceError,
        ):
            _LOGGER.error("Failed to process AI notification")

        return original_message

    def _build_rewrite_prompt(
        self,
        original_message: str,
        growspace_name: str,
        sensor_states: dict[str, Any] | None,
        personality: str,
        max_length: int,
    ) -> str:
        """Build the prompt for the AI to rewrite the notification."""
        readings = []
        if sensor_states:
            for k, v in sensor_states.items():
                if v is not None and not isinstance(v, bool):
                    readings.append(f"{k}: {v}")
        readings_str = ", ".join(readings)

        system_context = (
            f"You are a {personality} cannabis cultivation assistant. "
            "Your job is to rewrite alerts in your unique style while keeping them informative.\n\n"
        )

        if personality.lower() == "scientific":
            system_context += (
                "Use precise technical terminology. Be analytical and data-driven. "
                "Reference specific thresholds and values."
            )
        elif personality.lower() == "chill stoner":
            system_context += (
                "Be laid-back and friendly, but still helpful. Use casual language. "
                "Keep the vibe relaxed but don't skip important details."
            )
        elif personality.lower() == "strict coach":
            system_context += (
                "Be direct and authoritative. Emphasize urgency where appropriate. "
                "Make it clear what needs to be done immediately."
            )
        elif personality.lower() == "pirate":
            system_context += (
                "Write like a pirate (arr, matey, etc.) but maintain clarity. "
                "Make it fun while conveying the essential information."
            )
        else:
            system_context += (
                "Be clear, professional, and helpful. "
                "Keep the message concise but informative."
            )

        return (
            f"{system_context}\n\n"
            f"Original Alert: {original_message}\n"
            f"Current Sensor Data: {readings_str}\n"
            f"Growspace: {growspace_name}\n\n"
            f"Rewrite this alert in 1-2 sentences. Keep it under {max_length} characters. "
            "Include specific sensor values if they're relevant to the alert."
        )
