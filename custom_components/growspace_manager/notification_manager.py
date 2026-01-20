"""Notification manager for Growspace Manager."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any, cast

from homeassistant.components import conversation
from homeassistant.core import Context, HomeAssistant
from homeassistant.util.dt import utcnow

from .const import (
    ATTR_TRIGGER_TYPE,
    CONF_AI_ENABLED,
    CONF_ASSISTANT_ID,
    CONF_NOTIFICATION_PERSONALITY,
    DEFAULT_COOLDOWN_MINUTES,
)

_LOGGER = logging.getLogger(__name__)


class NotificationManager:
    """Manages notifications for Growspace Manager."""

    def __init__(self, hass: HomeAssistant, coordinator: Any) -> None:
        """Initialize the notification manager."""
        self.hass = hass
        self.coordinator = coordinator
        self._last_notification_sent: dict[str, datetime] = {}
        self._notification_cooldown = timedelta(minutes=DEFAULT_COOLDOWN_MINUTES)

    def trigger_cooldown(self, growspace_id: str) -> None:
        """Manually trigger the notification cooldown for a growspace."""
        self._last_notification_sent[growspace_id] = utcnow()
        _LOGGER.debug("Notification cooldown triggered for %s", growspace_id)

    def generate_notification_message(
        self, base_message: str, reasons: list[tuple[float, str]]
    ) -> str:
        """Construct a detailed notification message from the list of reasons."""
        sorted_reasons = sorted(reasons, reverse=True)
        message = base_message

        for _, reason in sorted_reasons:
            if len(message) + len(reason) + 2 < 65:
                message += f", {reason}"
            else:
                break
        return message

    async def async_send_notification(
        self,
        growspace_id: str,
        title: str,
        message: str,
        sensor_states: dict[str, Any] | None = None,
    ) -> None:
        """Send a notification to the configured target for the growspace."""
        now = utcnow()

        # Check cooldown per growspace
        last_sent = self._last_notification_sent.get(growspace_id)
        if last_sent and (now - last_sent) < self._notification_cooldown:
            _LOGGER.debug(
                "Notification cooldown active for %s, skipping notification",
                growspace_id,
            )
            return

        growspace = self.coordinator.growspaces.get(growspace_id)
        if not growspace or not growspace.notification_target:
            _LOGGER.debug(
                "No notification target configured for %s, skipping notification",
                growspace_id,
            )
            return

        # Check if notifications are enabled in coordinator
        if not self.coordinator.is_notifications_enabled(growspace_id):
            _LOGGER.debug("Notifications disabled in coordinator for %s", growspace_id)
            return

        self._last_notification_sent[growspace_id] = now

        # AI Personality Injection
        final_message = message
        ai_settings = self.coordinator.options.get("ai_settings", {})

        if ai_settings.get(CONF_AI_ENABLED) and ai_settings.get(CONF_ASSISTANT_ID):
            final_message = await self._rewrite_with_ai(
                message, growspace.name, sensor_states, ai_settings
            )

        # Get the service name (e.g., "mobile_app_my_phone")
        notification_service = growspace.notification_target.replace("notify.", "")

        try:
            await self.hass.services.async_call(
                "notify",
                notification_service,
                {
                    "message": final_message,
                    "title": title,
                },
                blocking=False,
            )
            _LOGGER.info(
                "Notification sent to %s: %s - %s",
                notification_service,
                title,
                final_message,
            )
        except (AttributeError, TypeError, ValueError) as e:
            _LOGGER.error(
                "Failed to send notification to %s: %s", notification_service, e
            )

    async def _rewrite_with_ai(
        self,
        original_message: str,
        growspace_name: str,
        sensor_states: dict[str, Any] | None,
        ai_settings: dict[str, Any],
    ) -> str:
        """Rewrite the notification message using Home Assistant Assist."""
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

            if (
                result
                and result.response
                and result.response.speech
                and result.response.speech.get("plain")
            ):
                rewritten = result.response.speech["plain"]["speech"]
                # Validate the response isn't too long
                if len(rewritten) <= max_length:
                    _LOGGER.info("AI rewrote notification in %s style", personality)
                    return cast(str, rewritten)
                # Try to truncate intelligently if it's close
                if len(rewritten) < max_length + 50:
                    _LOGGER.info("AI response truncated to fit length limit")
                    return cast(str, rewritten[:max_length].rsplit(" ", 1)[0] + "...")
                _LOGGER.warning(
                    "AI response too long (%d chars > %d), using default",
                    len(rewritten),
                    max_length,
                )
            else:
                _LOGGER.warning("AI returned empty response, using default message")

        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to process AI notification: %s", err)

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
        # Format sensor readings for context
        readings = []
        if sensor_states:
            for k, v in sensor_states.items():
                if v is not None and not isinstance(v, bool):
                    readings.append(f"{k}: {v}")
        readings_str = ", ".join(readings)

        # Build a more sophisticated prompt for the AI
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
        else:  # Standard
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

    async def async_check_timed_notifications(self) -> None:
        """Check all configured timed notifications and send them if the conditions are met."""
        notifications = self.coordinator.options.get("timed_notifications", [])
        if not notifications:
            return

        plants_by_growspace = self._group_plants_by_growspace()

        for notification in notifications:
            await self._process_notification(notification, plants_by_growspace)

    def _group_plants_by_growspace(self) -> dict[str, list[Any]]:
        """Group plants by growspace ID."""
        plants_by_growspace: dict[str, list[Any]] = {}
        for plant in self.coordinator.plants.values():
            if plant.growspace_id not in plants_by_growspace:
                plants_by_growspace[plant.growspace_id] = []
            plants_by_growspace[plant.growspace_id].append(plant)
        return plants_by_growspace

    async def _process_notification(
        self, notification: dict[str, Any], plants_by_growspace: dict[str, list[Any]]
    ) -> None:
        """Process a single timed notification across relevant growspaces."""
        trigger_type = notification[ATTR_TRIGGER_TYPE]
        day_to_trigger = int(notification["day"])
        message = notification["message"]
        growspace_ids = notification.get("growspace_ids", [])
        notification_id = notification["id"]

        for gs_id in growspace_ids:
            growspace = self.coordinator.growspaces.get(gs_id)
            if not growspace:
                continue

            plants = plants_by_growspace.get(gs_id, [])
            for plant in plants:
                await self._check_and_trigger_plant_notification(
                    plant,
                    growspace,
                    notification_id,
                    trigger_type,
                    day_to_trigger,
                    message,
                )

    async def _check_and_trigger_plant_notification(
        self,
        plant: Any,
        growspace: Any,
        notification_id: str,
        trigger_type: str,
        day_to_trigger: int,
        message: str,
    ) -> None:
        """Check and trigger notification for a specific plant."""
        days_in_stage = self.coordinator.serializer.calculate_days_in_stage(
            plant, trigger_type
        )

        if days_in_stage >= day_to_trigger:
            notification_key = f"timed_{notification_id}"
            if not self.coordinator.notifications_sent.get(plant.plant_id, {}).get(
                notification_key, False
            ):
                _LOGGER.info(
                    "Triggering timed notification for plant %s in %s",
                    plant.plant_id,
                    growspace.name,
                )
                title = f"{growspace.name} - {trigger_type.capitalize()} Day {day_to_trigger}"

                await self.async_send_notification(
                    growspace.id
                    if hasattr(growspace, "id")
                    else growspace.growspace_id,
                    title,
                    message,
                )

                if plant.plant_id not in self.coordinator.notifications_sent:
                    self.coordinator.notifications_sent[plant.plant_id] = {}
                self.coordinator.notifications_sent[plant.plant_id][
                    notification_key
                ] = True
                await self.coordinator.async_save()
