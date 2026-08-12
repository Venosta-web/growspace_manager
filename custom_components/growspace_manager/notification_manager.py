"""Notification manager for Growspace Manager."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any, ClassVar

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.event import async_call_later
from homeassistant.util.dt import utcnow

from .const import (
    ATTR_TRIGGER_TYPE,
    CONF_AI_ENABLED,
    CONF_ASSISTANT_ID,
    CRITICAL_COOLDOWN_MINUTES,
    CRITICAL_PROBABILITY_THRESHOLD,
    DEFAULT_COOLDOWN_MINUTES,
    ESCALATION_DELAY_MINUTES,
    MIN_STRESS_DURATION_SECONDS,
    NOTIFICATION_CHANNEL,
    NOTIFICATION_DEBOUNCE_SECONDS,
    NOTIFICATION_GROUP,
    NOTIFICATION_ICON,
    PHOTOPERIOD_FLIP_COOLDOWN_MINUTES,
    RECOVERY_COOLDOWN_MINUTES,
    WARNING_COOLDOWN_MINUTES,
    WARNING_PERSISTENCE_MINUTES,
    GrowspaceSensorType,
    NotificationTier,
)
from .domain import calculate_days_in_stage
from .exceptions import GrowspaceError
from .notification_rewriter import AINotificationRewriter
from .notifications.evaluation_snapshot import EvaluationSnapshot
from .notifications.formatting import generate_notification_message
from .notifications.timed import normalize_timed_notifications

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

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: GrowspaceCoordinator,
        ai_rewriter: AINotificationRewriter,
    ) -> None:
        """Initialize the notification manager."""
        self.hass = hass
        self.coordinator = coordinator
        self._ai_rewriter = ai_rewriter
        # Legacy cooldown for timed notifications (non-tiered)
        self._last_notification_sent: dict[str, datetime] = {}
        self._notification_cooldown = timedelta(minutes=DEFAULT_COOLDOWN_MINUTES)
        # Latest evaluation snapshot per (growspace_id, sensor_type), used to
        # build batched notifications without holding live entity references.
        self._latest_snapshots: dict[tuple[str, str], EvaluationSnapshot] = {}
        self._batch_timers: dict[str, CALLBACK_TYPE] = {}
        self._pending_alerts: dict[str, PendingAlert] = {}
        self._cooldowns: dict[str, dict[str, datetime]] = {}
        # Last observed light state per growspace, for flip-cooldown dedup
        # across the multiple sensor types reporting the same growspace.
        self._last_lights_on: dict[str, bool] = {}

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
        "recovery": timedelta(
            minutes=RECOVERY_COOLDOWN_MINUTES
        ),  # TODO: migrate to NotificationTier.RECOVERY
        NotificationTier.PHOTOPERIOD_FLIP: timedelta(
            minutes=PHOTOPERIOD_FLIP_COOLDOWN_MINUTES
        ),
    }

    _TIER_OPTION_KEYS: ClassVar[dict[str, tuple[str, int]]] = {
        NotificationTier.CRITICAL: (
            "critical_cooldown_minutes",
            CRITICAL_COOLDOWN_MINUTES,
        ),
        NotificationTier.WARNING: (
            "warning_cooldown_minutes",
            WARNING_COOLDOWN_MINUTES,
        ),
        "recovery": ("recovery_cooldown_minutes", RECOVERY_COOLDOWN_MINUTES),
    }

    def _get_notification_option(self, key: str, fallback: int) -> int:
        """Read a timing/cooldown value from notification_settings options, with fallback."""
        settings: dict = self.coordinator.options.get("notification_settings", {})
        return settings.get(key, fallback)

    def _get_tier_cooldown(self, tier: str) -> timedelta:
        """Return the cooldown timedelta for a tier, respecting user-configured options."""
        if tier in self._TIER_OPTION_KEYS:
            option_key, fallback = self._TIER_OPTION_KEYS[tier]
            return timedelta(
                minutes=self._get_notification_option(option_key, fallback)
            )
        return self._TIER_COOLDOWNS.get(
            tier, timedelta(minutes=CRITICAL_COOLDOWN_MINUTES)
        )

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
        cooldown_duration = self._get_tier_cooldown(tier)
        return (now - last_sent) < cooldown_duration

    @callback
    def report_evaluation(self, snapshot: EvaluationSnapshot) -> None:
        """Process a Bayesian sensor evaluation snapshot.

        Called by sensors on every probability update. Stores the latest
        snapshot for batch aggregation and drives the pending-alert lifecycle
        (for non-optimal sensors).
        """
        growspace_id = snapshot.growspace_id
        sensor_type = snapshot.sensor_type
        snap_key = (growspace_id, sensor_type)

        self._handle_light_flip(growspace_id, snapshot.lights_on)

        # Maintain the latest-snapshot store for batched notifications. Only
        # triggered snapshots are retained; a resolved one is dropped.
        if snapshot.is_on:
            self._latest_snapshots[snap_key] = snapshot
        else:
            self._latest_snapshots.pop(snap_key, None)

        # The optimal-conditions sensor never participates in pending alerts.
        if sensor_type == GrowspaceSensorType.OPTIMAL:
            return

        alert_key = f"{growspace_id}_{sensor_type}"

        if not self.coordinator.services.growspaces.get_growspace_plants(growspace_id):
            self._latest_snapshots.pop(snap_key, None)
            alert = self._pending_alerts.pop(alert_key, None)
            if alert and alert.notification_timer is not None:
                alert.notification_timer()
                alert.notification_timer = None
            return

        if not snapshot.is_on:
            alert = self._pending_alerts.pop(alert_key, None)
            if alert:
                if alert.notification_timer is not None:
                    alert.notification_timer()
                    alert.notification_timer = None
                if alert.notified_as_critical:
                    self._schedule_recovery(growspace_id, alert)
            return

        probability = snapshot.probability
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
                sensor_name=snapshot.sensor_name,
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
                self.hass,
                self._get_notification_option(
                    "min_stress_duration_seconds", MIN_STRESS_DURATION_SECONDS
                ),
                _fire_critical,
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

    def trigger_cooldown(self, growspace_id: str) -> None:
        """Manually trigger notification cooldown for a growspace (e.g., light switch)."""
        self._set_cooldown(growspace_id, NotificationTier.CRITICAL)
        self._set_cooldown(growspace_id, NotificationTier.WARNING)
        self._last_notification_sent[growspace_id] = utcnow()
        _LOGGER.debug("Notification cooldown triggered for %s", growspace_id)

    @callback
    def _handle_light_flip(self, growspace_id: str, lights_on: bool | None) -> None:
        """Trigger a cooldown when the growspace light state flips.

        Snapshots from the multiple sensor types covering one growspace are
        deduped by comparing against the stored value, so a single physical
        flip triggers exactly one cooldown. ``None`` readings are ignored and
        never overwrite a known state.
        """
        if lights_on is None:
            return
        previous = self._last_lights_on.get(growspace_id)
        self._last_lights_on[growspace_id] = lights_on
        if previous is not None and previous != lights_on:
            _LOGGER.debug(
                "Light switched in %s. Triggering notification cooldown",
                growspace_id,
            )
            self.trigger_cooldown(growspace_id)

    def generate_notification_message(
        self, base_message: str, reasons: list[tuple[float, str]]
    ) -> str:
        """Construct a detailed notification message from the list of reasons."""
        return generate_notification_message(base_message, reasons)

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

        active_snapshots = [
            snap
            for (gid, _sensor_type), snap in self._latest_snapshots.items()
            if gid == growspace_id and snap.is_on
        ]

        if not active_snapshots:
            return

        # Aggregate unique reasons across all triggered sensors
        combined_reasons: list[tuple[float, str]] = []
        seen_reasons: set[str] = set()
        sensor_names: list[str] = []
        all_sensor_states: dict[str, Any] = {}

        for snap in active_snapshots:
            sensor_names.append(snap.sensor_name)
            all_sensor_states.update(snap.sensor_states)
            for r_prob, r_text in snap.reasons:
                if r_text not in seen_reasons:
                    combined_reasons.append((r_prob, r_text))
                    seen_reasons.add(r_text)

        # Build composite title and message
        growspace = self.coordinator.growspaces.get(growspace_id)
        gs_name = growspace.name if growspace else growspace_id

        if len(active_snapshots) == 1:
            snap = active_snapshots[0]
            if snap.notification_title and snap.notification_message:
                title, base_message = (
                    snap.notification_title,
                    snap.notification_message,
                )
            else:
                title = f"\U0001f534 {snap.sensor_name}: {gs_name}"
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
        if not self.coordinator.services.notifications.is_notifications_enabled(
            growspace_id
        ):
            _LOGGER.debug("Notifications disabled in coordinator for %s", growspace_id)
            return

        # AI Personality Injection
        final_message = message
        ai_settings = self.coordinator.options.get("ai_settings", {})

        if ai_settings.get(CONF_AI_ENABLED) and ai_settings.get(CONF_ASSISTANT_ID):
            final_message = await self._ai_rewriter.async_rewrite(
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

    async def async_check_timed_notifications(self) -> None:
        """Check all configured timed notifications and send them if the conditions are met."""
        notifications = normalize_timed_notifications(
            self.coordinator.options.get("timed_notifications", [])
        )
        if not notifications:
            return

        plants_by_growspace = self._group_plants_by_growspace()

        for notification in notifications:
            await self._process_notification(notification, plants_by_growspace)

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
                if elapsed >= self._get_notification_option(
                    "escalation_delay_minutes", ESCALATION_DELAY_MINUTES
                ):
                    if not self._is_on_cooldown(
                        growspace_id, NotificationTier.CRITICAL, now
                    ):
                        await self._send_escalation(growspace_id, alert, elapsed)
                        alert.escalated = True
                continue

            # Warning persistence check: not yet notified, persistence met
            if not alert.notified:
                elapsed = (now - alert.first_triggered).total_seconds() / 60
                if elapsed >= self._get_notification_option(
                    "warning_persistence_minutes", WARNING_PERSISTENCE_MINUTES
                ):
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
            if not self.coordinator.notification_state.sent.get(plant.plant_id, {}).get(
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

                if plant.plant_id not in self.coordinator.notification_state.sent:
                    self.coordinator.notification_state.sent[plant.plant_id] = {}
                self.coordinator.notification_state.sent[plant.plant_id][
                    notification_key
                ] = True
                await self.coordinator.async_commit()
