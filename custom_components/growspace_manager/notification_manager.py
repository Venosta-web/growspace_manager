"""Notification manager for Growspace Manager."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any, ClassVar, cast

from homeassistant.components import conversation
from homeassistant.core import CALLBACK_TYPE, Context, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import intent
from homeassistant.helpers.event import async_call_later
from homeassistant.util.dt import utcnow

from .const import (
    ATTR_TRIGGER_TYPE,
    CONF_AI_ENABLED,
    CONF_ASSISTANT_ID,
    CONF_NOTIFICATION_PERSONALITY,
    CRITICAL_COOLDOWN_MINUTES,
    CRITICAL_PROBABILITY_THRESHOLD,
    DEFAULT_COOLDOWN_MINUTES,
    ESCALATION_DELAY_MINUTES,
    MAX_NOTIFICATION_LENGTH,
    MIN_STRESS_DURATION_SECONDS,
    NOTIFICATION_CHANNEL,
    NOTIFICATION_DEBOUNCE_SECONDS,
    NOTIFICATION_GROUP,
    NOTIFICATION_ICON,
    RECOVERY_COOLDOWN_MINUTES,
    WARNING_COOLDOWN_MINUTES,
    WARNING_PERSISTENCE_MINUTES,
    NotificationTier,
)
from .domain import calculate_days_in_stage
from .exceptions import GrowspaceError
from .presentation import EntityQueries

if TYPE_CHECKING:
    from .coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass
class PendingAlert:
    """Tracks the state of an active alert for a sensor."""

    growspace_id: str
    first_triggered: datetime
    last_probability: float
    peak_probability: float
    sensor_name: str
    notified: bool = False
    escalated: bool = False
    notified_as_critical: bool = False
    notification_timer: CALLBACK_TYPE | None = None


class NotificationManager:
    """Manages notifications for Growspace Manager."""

    def __init__(self, hass: HomeAssistant, coordinator: GrowspaceCoordinator) -> None:
        """Initialize the notification manager."""
        self.hass = hass
        self.coordinator = coordinator
        # Legacy cooldown for timed notifications (non-tiered)
        self._last_notification_sent: dict[str, datetime] = {}
        self._notification_cooldown = timedelta(minutes=DEFAULT_COOLDOWN_MINUTES)
        self._registered_sensors: dict[str, set[Any]] = {}
        self._batch_timers: dict[str, CALLBACK_TYPE] = {}
        self._pending_alerts: dict[str, PendingAlert] = {}
        self._cooldowns: dict[str, dict[str, datetime]] = {}
        self._ai_cooldown_until: datetime | None = None

    @callback
    def shutdown(self) -> None:
        """Shutdown the notification manager and cancel all timers."""
        for timer in self._batch_timers.values():
            timer()
        self._batch_timers.clear()

        for alert in self._pending_alerts.values():
            if alert.notification_timer is not None:
                alert.notification_timer()
                alert.notification_timer = None
        self._pending_alerts.clear()

    _TIER_COOLDOWNS: ClassVar[dict[str, timedelta]] = {
        NotificationTier.CRITICAL: timedelta(minutes=CRITICAL_COOLDOWN_MINUTES),
        NotificationTier.WARNING: timedelta(minutes=WARNING_COOLDOWN_MINUTES),
        "recovery": timedelta(minutes=RECOVERY_COOLDOWN_MINUTES),
    }

    def _set_cooldown(self, growspace_id: str, tier: str) -> None:
        """Set cooldown timestamp for a specific tier and growspace."""
        if growspace_id not in self._cooldowns:
            self._cooldowns[growspace_id] = {}
        self._cooldowns[growspace_id][tier] = utcnow()

    def _is_on_cooldown(self, growspace_id: str, tier: str, now: datetime) -> bool:
        """Check if a specific tier is on cooldown for a growspace."""
        cooldown_map = self._cooldowns.get(growspace_id, {})
        last_sent = cooldown_map.get(tier)
        if not last_sent:
            return False
        cooldown_duration = self._TIER_COOLDOWNS.get(
            tier, timedelta(minutes=CRITICAL_COOLDOWN_MINUTES)
        )
        return (now - last_sent) < cooldown_duration

    @callback
    def update_pending_alert(self, growspace_id: str, sensor: Any) -> None:
        """Update or create a pending alert based on sensor state.

        Called by sensors on every probability update instead of
        async_schedule_notification directly.
        """
        if not self.coordinator.services.growspaces.get_growspace_plants(growspace_id):
            alert = self._pending_alerts.pop(
                f"{growspace_id}_{sensor.entity_description.sensor_type}", None
            )
            if alert and alert.notification_timer is not None:
                alert.notification_timer()
                alert.notification_timer = None
            return

        alert_key = f"{growspace_id}_{sensor.entity_description.sensor_type}"

        if not sensor.is_on:
            alert = self._pending_alerts.pop(alert_key, None)
            if alert:
                if alert.notification_timer is not None:
                    alert.notification_timer()
                    alert.notification_timer = None
                if alert.notified_as_critical:
                    self._schedule_recovery(growspace_id, alert)
            return

        probability = sensor._probability  # noqa: SLF001
        now = utcnow()

        if alert_key in self._pending_alerts:
            alert = self._pending_alerts[alert_key]
            alert.last_probability = probability
            alert.peak_probability = max(alert.peak_probability, probability)
        else:
            alert = PendingAlert(
                growspace_id=growspace_id,
                first_triggered=now,
                last_probability=probability,
                peak_probability=probability,
                sensor_name=sensor.name,
            )
            self._pending_alerts[alert_key] = alert

        if (
            probability >= CRITICAL_PROBABILITY_THRESHOLD
            and not alert.notified_as_critical
            and alert.notification_timer is None
        ):

            @callback
            def _fire_critical(_now: datetime) -> None:
                pending = self._pending_alerts.get(alert_key)
                if pending is None:
                    return
                pending.notification_timer = None
                pending.notified_as_critical = True
                pending.notified = True
                self.async_schedule_notification(growspace_id)

            alert.notification_timer = async_call_later(
                self.hass, MIN_STRESS_DURATION_SECONDS, _fire_critical
            )
        elif (
            probability < CRITICAL_PROBABILITY_THRESHOLD
            and alert.notification_timer is not None
        ):
            alert.notification_timer()
            alert.notification_timer = None

    @callback
    def _schedule_recovery(self, growspace_id: str, alert: PendingAlert) -> None:
        """Schedule a recovery notification for a resolved critical alert."""
        self.coordinator.config_entry.async_create_background_task(
            self.hass,
            self._async_send_recovery(growspace_id, alert),
            f"recovery_notification_{growspace_id}_{alert.sensor_name}",
        )

    async def _async_send_recovery(
        self, growspace_id: str, alert: PendingAlert
    ) -> None:
        """Send a recovery notification for a resolved critical alert."""
        now = utcnow()
        if self._is_on_cooldown(growspace_id, "recovery", now):
            return

        growspace = self.coordinator.growspaces.get(growspace_id)
        gs_name = growspace.name if growspace else growspace_id

        elapsed = (now - alert.first_triggered).total_seconds() / 60
        title = f"\u2705 Resolved: {gs_name}"
        message = (
            f"{alert.sensor_name} in {gs_name} has resolved "
            f"after {int(elapsed)} minutes"
        )

        self._set_cooldown(growspace_id, "recovery")
        await self.async_send_notification(growspace_id, title, message)

    def attach_sensor(self, growspace_id: str, sensor: Any) -> None:
        """Register a sensor for batch notification tracking."""
        if growspace_id not in self._registered_sensors:
            self._registered_sensors[growspace_id] = set()
        self._registered_sensors[growspace_id].add(sensor)

    def detach_sensor(self, growspace_id: str, sensor: Any) -> None:
        """Unregister a sensor."""
        if growspace_id in self._registered_sensors:
            self._registered_sensors[growspace_id].discard(sensor)

    def trigger_cooldown(self, growspace_id: str) -> None:
        """Manually trigger notification cooldown for a growspace (e.g., light switch)."""
        self._set_cooldown(growspace_id, NotificationTier.CRITICAL)
        self._set_cooldown(growspace_id, NotificationTier.WARNING)
        self._last_notification_sent[growspace_id] = utcnow()
        _LOGGER.debug("Notification cooldown triggered for %s", growspace_id)

    def generate_notification_message(
        self, base_message: str, reasons: list[tuple[float, str]]
    ) -> str:
        """Construct a detailed notification message from the list of reasons."""
        sorted_reasons = sorted(reasons, reverse=True)
        message = base_message

        # Increased limit from 65 to MAX_NOTIFICATION_LENGTH for modern mobile displays
        for _, reason in sorted_reasons:
            if len(message) + len(reason) + 2 < MAX_NOTIFICATION_LENGTH:
                message += f", {reason}"
            else:
                break
        return message

    @callback
    def async_schedule_notification(self, growspace_id: str) -> None:
        """Schedule a debounced batched notification for a growspace."""
        if timer := self._batch_timers.get(growspace_id):
            timer()

        @callback
        def _send_notification(_: datetime) -> None:
            self.coordinator.config_entry.async_create_background_task(
                self.hass,
                self._async_send_batched_notification(growspace_id),
                f"batched_notification_{growspace_id}",
            )

        self._batch_timers[growspace_id] = async_call_later(
            self.hass,
            NOTIFICATION_DEBOUNCE_SECONDS,
            _send_notification,
        )

    async def _async_send_batched_notification(self, growspace_id: str) -> None:
        """Collect triggered sensors and send a consolidated notification."""
        if timer := self._batch_timers.pop(growspace_id, None):
            timer()

        now = utcnow()

        # Check tier-aware cooldown for critical (batched notifications are always critical)
        if self._is_on_cooldown(growspace_id, NotificationTier.CRITICAL, now):
            _LOGGER.debug(
                "Critical cooldown active for %s, skipping batch",
                growspace_id,
            )
            return

        sensors = self._registered_sensors.get(growspace_id, set())
        active_sensors = [s for s in sensors if s.is_on]

        if not active_sensors:
            return

        # Aggregate unique reasons across all sensors
        combined_reasons: list[tuple[float, str]] = []
        seen_reasons: set[str] = set()
        sensor_names: list[str] = []
        all_sensor_states: dict[str, Any] = {}

        for sensor in active_sensors:
            try:
                name = sensor.name
            except AttributeError:
                name = sensor.entity_id
            sensor_names.append(name)
            all_sensor_states.update(sensor.sensor_states)
            for r_prob, r_text in sensor.reasons:
                if r_text not in seen_reasons:
                    combined_reasons.append((r_prob, r_text))
                    seen_reasons.add(r_text)

        # Build composite title and message
        growspace = self.coordinator.growspaces.get(growspace_id)
        gs_name = growspace.name if growspace else growspace_id

        if len(active_sensors) == 1:
            sensor = active_sensors[0]
            title_msg = sensor.get_notification_title_message(True)
            if title_msg and len(title_msg) == 2:
                title, base_message = title_msg
            else:
                title = (
                    f"\U0001f534 {getattr(sensor, 'name', sensor.entity_id)}: {gs_name}"
                )
                base_message = f"Issue detected in {gs_name}"
        else:
            title = f"\U0001f534 Multiple Critical: {gs_name}"
            base_message = f"Critical alerts in {gs_name} ({', '.join(sensor_names)})"

        message = self.generate_notification_message(base_message, combined_reasons)

        await self.async_send_notification(
            growspace_id,
            title,
            message,
            sensor_states=all_sensor_states,
            tier=NotificationTier.CRITICAL,
        )

    async def async_send_notification(
        self,
        growspace_id: str,
        title: str,
        message: str,
        sensor_states: dict[str, Any] | None = None,
        tier: str | None = None,
    ) -> None:
        """Send a notification to the configured target for the growspace."""
        now = utcnow()

        if tier:
            if self._is_on_cooldown(growspace_id, tier, now):
                _LOGGER.debug(
                    "Tier %s cooldown active for %s, skipping notification",
                    tier,
                    growspace_id,
                )
                return
        else:
            # Legacy cooldown for timed/tank notifications
            last_sent = self._last_notification_sent.get(growspace_id)
            if last_sent and (now - last_sent) < self._notification_cooldown:
                _LOGGER.debug(
                    "Notification cooldown active for %s, skipping notification",
                    growspace_id,
                )
                return
            self._last_notification_sent[growspace_id] = now

        growspace = self.coordinator.growspaces.get(growspace_id)
        if not growspace or not growspace.notification_target:
            _LOGGER.debug(
                "No notification target configured for %s, skipping notification",
                growspace_id,
            )
            return

        if not self.coordinator.services.growspaces.get_growspace_plants(growspace_id):
            _LOGGER.debug(
                "Growspace %s has no plants, skipping notification",
                growspace_id,
            )
            return

        # Check if notifications are enabled in coordinator
        if not self.coordinator.services.notifications.is_notifications_enabled(growspace_id):
            _LOGGER.debug("Notifications disabled in coordinator for %s", growspace_id)
            return

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
                    "data": {
                        "group": NOTIFICATION_GROUP,
                        "channel": NOTIFICATION_CHANNEL,
                        "notification_icon": NOTIFICATION_ICON,
                        "push": {"thread-id": NOTIFICATION_GROUP},
                    },
                },
                blocking=False,
            )
            _LOGGER.info(
                "Notification sent to %s: %s - %s",
                notification_service,
                title,
                final_message,
            )
            if tier:
                self._set_cooldown(growspace_id, tier)
        except (
            AttributeError,
            KeyError,
            ValueError,
            ServiceValidationError,
            GrowspaceError,
        ):
            _LOGGER.error("Failed to send notification to %s", notification_service)

    async def _rewrite_with_ai(
        self,
        original_message: str,
        growspace_name: str,
        sensor_states: dict[str, Any] | None,
        ai_settings: dict[str, Any],
    ) -> str:
        """Rewrite the notification message using Home Assistant Assist."""
        if self._ai_cooldown_until and utcnow() < self._ai_cooldown_until:
            _LOGGER.debug("AI notification generation is on rate-limit cooldown")
            return original_message

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
                    # Validate the response isn't too long
                    if len(rewritten) <= max_length:
                        _LOGGER.info("AI rewrote notification in %s style", personality)
                        return cast(str, rewritten)
                    # Try to truncate intelligently if it's close
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

    async def async_check_tank_levels(self) -> None:
        """Check all irrigation tank levels and notify if below warning threshold."""

        entity_queries = EntityQueries(self.hass)

        for growspace in self.coordinator.growspaces.values():
            if (
                not growspace.environment_config
                or not growspace.environment_config.irrigation_tanks
            ):
                continue

            for tank in growspace.environment_config.irrigation_tanks:
                state_obj = self.hass.states.get(tank.sensor_entity)
                level = (
                    entity_queries.parse_tank_level(state_obj.state)
                    if state_obj
                    else None
                )

                if level is not None and level <= tank.warning_level:
                    await self.async_send_notification(
                        growspace.id,
                        title="⚠️ Low Irrigation Tank Level",
                        message=f"{tank.name} in {growspace.name} is at {level:.0f}% (warning at {tank.warning_level:.0f}%)",
                        tier=NotificationTier.CRITICAL,
                    )

    async def async_check_pending_alerts(self) -> None:
        """Check all pending alerts for persistence thresholds and escalation.

        Called from coordinator._async_update_data on every update cycle.
        """
        now = utcnow()

        for _alert_key, alert in list(self._pending_alerts.items()):
            growspace_id = alert.growspace_id

            # Escalation check: critical, notified, not yet escalated, 30+ min
            if (
                alert.notified_as_critical
                and alert.notified
                and not alert.escalated
                and alert.last_probability >= CRITICAL_PROBABILITY_THRESHOLD
            ):
                elapsed = (now - alert.first_triggered).total_seconds() / 60
                if elapsed >= ESCALATION_DELAY_MINUTES:
                    if not self._is_on_cooldown(
                        growspace_id, NotificationTier.CRITICAL, now
                    ):
                        await self._send_escalation(growspace_id, alert, elapsed)
                        alert.escalated = True
                continue

            # Warning persistence check: not yet notified, persistence met
            if not alert.notified:
                elapsed = (now - alert.first_triggered).total_seconds() / 60
                if elapsed >= WARNING_PERSISTENCE_MINUTES:
                    if not self._is_on_cooldown(
                        growspace_id, NotificationTier.WARNING, now
                    ):
                        await self._send_warning(growspace_id, alert, elapsed)
                        alert.notified = True

    async def _send_warning(
        self, growspace_id: str, alert: PendingAlert, elapsed_minutes: float
    ) -> None:
        """Send a warning-tier notification."""
        growspace = self.coordinator.growspaces.get(growspace_id)
        gs_name = growspace.name if growspace else growspace_id

        title = f"\u26a0\ufe0f {alert.sensor_name}: {gs_name}"
        message = (
            f"{alert.sensor_name} detected in {gs_name} "
            f"for {int(elapsed_minutes)} minutes"
        )

        await self.async_send_notification(
            growspace_id, title, message, tier=NotificationTier.WARNING
        )

    async def _send_escalation(
        self, growspace_id: str, alert: PendingAlert, elapsed_minutes: float
    ) -> None:
        """Send an escalation reminder for a critical alert."""
        growspace = self.coordinator.growspaces.get(growspace_id)
        gs_name = growspace.name if growspace else growspace_id

        title = f"\U0001f534 Still active: {gs_name}"
        message = (
            f"Still active after {int(elapsed_minutes)} minutes "
            f"(peak: {int(alert.peak_probability * 100)}%)"
        )

        await self.async_send_notification(
            growspace_id, title, message, tier=NotificationTier.CRITICAL
        )

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
        days_in_stage = calculate_days_in_stage(plant, trigger_type)

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
                await self.coordinator.async_commit()
