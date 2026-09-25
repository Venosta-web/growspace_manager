"""Deliver each new Capture Continuity Break to the grower, recoverably.

The Capture Continuity Monitor decides *that* a streak activated and whether
the activation is news; the Alert Monitor keeps its durable Triage Alert. This
module owns the one thing left: telling the grower once, through every
delivery channel, and remembering how far that got across restarts.

Delivery progress is a small durable record of its own
(``growspace_manager.continuity_notifications``), deliberately separate from
both the streak state the monitor rebuilds from evidence and the bounded
Triage Alert Inbox, so neither a recovery nor Inbox trimming can make an
activation announce itself again::

    {
        "deliveries": [
            {
                "activation_id": "<capture that began the streak>",
                "growspace_id": "<id>",
                "camera_id": "camera.canopy",
                "activated_at": "<ISO>",
                "channels": {
                    "home_assistant": {"status": "pending", "attempts": 0},
                    "device": {"status": "pending", "attempts": 0}
                }
            },
            ...
        ]
    }

A record exists only for an activation that was new when it was seen. It is
written before the monitor records the activating capture as processed, so a
crash anywhere after the Triage Alert still finds either this record or an
activation recovery reports as new — never neither.

**Delivery is at-least-once, not exactly-once.** A channel is attempted until
its success is recorded, under a stable per-streak notification id. A crash
between sending and recording success sends again under that same id. Home
Assistant replaces its persistent notification; a mobile app can repeat an
alert or sound because end-device receipt is not acknowledged.

The growspace notification switch mutes delivery, never the Triage Alert. A
channel that is muted when it would be attempted is recorded as suppressed and
is never sent later, so un-muting during an active streak sends no backlog.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

from .capture_continuity_monitor import ActivationOrigin
from .const import NOTIFICATION_CHANNEL, NOTIFICATION_GROUP, NOTIFICATION_ICON
from .domain.capture_continuity import CAPTURE_CONTINUITY_MESSAGE

if TYPE_CHECKING:
    from homeassistant.helpers.storage import Store

    from .capture_continuity_monitor import ContinuityActivation

_LOGGER = logging.getLogger(__name__)

# Waits before each retry of a failed attempt. Bounded: a channel that fails
# once more after the last one is given up, and says so in the log.
RETRY_DELAYS: tuple[timedelta, ...] = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(hours=1),
    timedelta(hours=4),
)
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1


class DeliveryChannel(StrEnum):
    """Where a Capture Continuity Break is announced."""

    HOME_ASSISTANT = "home_assistant"
    DEVICE = "device"


class DeliveryStatus(StrEnum):
    """How far one channel's delivery of one activation got."""

    PENDING = "pending"
    DELIVERED = "delivered"
    SUPPRESSED = "suppressed"
    FAILED = "failed"


type _DeliveryKey = tuple[str, str, str]


@dataclass(slots=True, kw_only=True)
class _ChannelProgress:
    status: DeliveryStatus
    attempts: int = 0


@dataclass(slots=True, kw_only=True)
class _Delivery:
    """One new activation and each channel's progress announcing it."""

    activation_id: str
    growspace_id: str
    camera_id: str
    activated_at: datetime
    channels: dict[DeliveryChannel, _ChannelProgress] = field(default_factory=dict)

    @property
    def key(self) -> _DeliveryKey:
        return (self.growspace_id, self.camera_id, self.activation_id)

    @property
    def unfinished(self) -> bool:
        return any(
            progress.status is DeliveryStatus.PENDING
            for progress in self.channels.values()
        )


def continuity_notification_id(
    growspace_id: str, camera_id: str, activation_id: str
) -> str:
    """Return the stable identifier every attempt for one streak sends under."""
    return f"growspace_capture_continuity_{growspace_id}_{camera_id}_{activation_id}"


class ContinuityNotifier:
    """Announce each new Capture Continuity Break once per channel."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: Any,
        store: Store[dict[str, Any]],
    ) -> None:
        """Initialise the notifier.

        Args:
            hass: Home Assistant instance.
            coordinator: The GrowspaceCoordinator; read for growspace names,
                the notification switch and the config entry whose unload
                cancels delivery work.
            store: Pre-constructed ``Store`` targeting
                ``growspace_manager.continuity_notifications``.
        """
        self._hass = hass
        self._coordinator = coordinator
        self._store = store
        self._deliveries: dict[_DeliveryKey, _Delivery] = {}
        self._retries: dict[tuple[_DeliveryKey, DeliveryChannel], CALLBACK_TYPE] = {}
        self._senders: dict[DeliveryChannel, Callable[[_Delivery], Awaitable[None]]] = {
            DeliveryChannel.HOME_ASSISTANT: self._async_send_persistent,
            DeliveryChannel.DEVICE: self._async_send_device,
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_start(self, activations: Iterable[ContinuityActivation]) -> None:
        """Resume unfinished delivery and adopt new activations recovery found.

        ``activations`` is every condition active after recovery. One that is
        new and has no record yet was activated by a checkup that never
        finished processing, so it is announced now; a historical one never
        is. Records that are finished and no longer describe an active
        condition are dropped, which is what keeps this store small.
        """
        data = await self._store.async_load() or {}
        self._deliveries = {
            delivery.key: delivery
            for delivery in _load_deliveries(data.get("deliveries", []))
        }
        # A record written before device delivery existed has already seen
        # its activation. Adding a target or upgrading must not page it now.
        for delivery in self._deliveries.values():
            delivery.channels.setdefault(
                DeliveryChannel.DEVICE,
                _ChannelProgress(status=DeliveryStatus.SUPPRESSED),
            )
        current: set[_DeliveryKey] = set()
        for activation in activations:
            key = _key(activation)
            current.add(key)
            if (
                activation.origin is ActivationOrigin.NEW
                and key not in self._deliveries
            ):
                self._deliveries[key] = self._open(activation)
        self._deliveries = {
            key: delivery
            for key, delivery in self._deliveries.items()
            if delivery.unfinished or key in current
        }
        await self._async_save()
        for delivery in list(self._deliveries.values()):
            self._schedule_pending(delivery)

    @callback
    def async_stop(self) -> None:
        """Cancel every scheduled retry; unfinished work resumes on next start."""
        for cancel in self._retries.values():
            cancel()
        self._retries.clear()

    # ------------------------------------------------------------------
    # Activation intake
    # ------------------------------------------------------------------

    async def async_announce(self, activation: ContinuityActivation) -> None:
        """Record a live activation's delivery durably, then attempt it.

        Called once per genuinely new activation, before the activating
        capture is recorded as processed. An activation that already has a
        record — the same one seen again — is not announced twice. Never
        raises: a delivery problem must not fail the Vision Checkup that
        produced the activation.
        """
        key = _key(activation)
        if key in self._deliveries:
            return
        # A new activation of the same Camera Assignment means the previous
        # streak is over; its finished record has nothing left to protect.
        self._deliveries = {
            other: delivery
            for other, delivery in self._deliveries.items()
            if delivery.unfinished or other[:2] != key[:2]
        }
        delivery = self._deliveries[key] = self._open(activation)
        await self._async_save()
        self._schedule_pending(delivery)

    async def async_mute(self, growspace_id: str) -> None:
        """Suppress every unfinished delivery for a growspace just muted."""
        changed = False
        for delivery in self._deliveries.values():
            if delivery.growspace_id != growspace_id:
                continue
            for channel, progress in delivery.channels.items():
                if progress.status is not DeliveryStatus.PENDING:
                    continue
                progress.status = DeliveryStatus.SUPPRESSED
                self._cancel_retry(delivery.key, channel)
                changed = True
        if changed:
            await self._async_save()

    # ------------------------------------------------------------------
    # Delivery
    # ------------------------------------------------------------------

    def _open(self, activation: ContinuityActivation) -> _Delivery:
        """Begin one activation's delivery, suppressed outright when muted."""
        status = (
            DeliveryStatus.SUPPRESSED
            if self._muted(activation.growspace_id)
            else DeliveryStatus.PENDING
        )
        device_status = (
            DeliveryStatus.SUPPRESSED
            if status is DeliveryStatus.SUPPRESSED
            or self._device_target(activation.growspace_id) is None
            else DeliveryStatus.PENDING
        )
        return _Delivery(
            activation_id=activation.activation_id,
            growspace_id=activation.growspace_id,
            camera_id=activation.camera_id,
            activated_at=activation.activated_at,
            channels={
                DeliveryChannel.HOME_ASSISTANT: _ChannelProgress(status=status),
                DeliveryChannel.DEVICE: _ChannelProgress(status=device_status),
            },
        )

    @callback
    def _schedule_pending(self, delivery: _Delivery) -> None:
        for channel, progress in delivery.channels.items():
            if progress.status is DeliveryStatus.PENDING:
                self._spawn(delivery.key, channel)

    @callback
    def _spawn(self, key: _DeliveryKey, channel: DeliveryChannel) -> None:
        self._coordinator.config_entry.async_create_background_task(
            self._hass,
            self._async_attempt(key, channel),
            f"growspace_continuity_notification_{channel}_{'_'.join(key)}",
        )

    async def _async_attempt(self, key: _DeliveryKey, channel: DeliveryChannel) -> None:
        """Attempt one pending channel once and record the outcome durably.

        Only a pending channel is ever attempted, and muting cancels its retry,
        so the switch is re-read here only for a mute by some other route.
        """
        delivery = self._deliveries[key]
        progress = delivery.channels[channel]
        if progress.status is not DeliveryStatus.PENDING:
            return
        if self._muted(delivery.growspace_id):
            progress.status = DeliveryStatus.SUPPRESSED
            await self._async_save()
            return
        try:
            await self._senders[channel](delivery)
        # Any failure at all is retried or given up; none may escape into the
        # checkup, and none may leave the channel pending with nothing queued.
        except Exception:
            progress.attempts += 1
            if progress.attempts >= MAX_ATTEMPTS:
                progress.status = DeliveryStatus.FAILED
                _LOGGER.warning(
                    "Giving up announcing the capture continuity break on %s in "
                    "%s through %s after %d attempts; its Triage Alert remains",
                    delivery.camera_id,
                    delivery.growspace_id,
                    channel,
                    progress.attempts,
                    exc_info=True,
                )
            else:
                delay = RETRY_DELAYS[progress.attempts - 1]
                _LOGGER.info(
                    "Announcing the capture continuity break on %s in %s through "
                    "%s failed; retrying in %s",
                    delivery.camera_id,
                    delivery.growspace_id,
                    channel,
                    delay,
                    exc_info=True,
                )
                self._schedule_retry(key, channel, delay)
        else:
            if progress.status is DeliveryStatus.PENDING:
                progress.status = DeliveryStatus.DELIVERED
        await self._async_save()

    @callback
    def _schedule_retry(
        self, key: _DeliveryKey, channel: DeliveryChannel, delay: timedelta
    ) -> None:
        @callback
        def _retry(_now: datetime) -> None:
            self._retries.pop((key, channel), None)
            self._spawn(key, channel)

        self._retries[(key, channel)] = async_call_later(self._hass, delay, _retry)

    @callback
    def _cancel_retry(self, key: _DeliveryKey, channel: DeliveryChannel) -> None:
        if cancel := self._retries.pop((key, channel), None):
            cancel()

    async def _async_send_persistent(self, delivery: _Delivery) -> None:
        """Create the streak's Home Assistant persistent notification.

        Blocking, so a failure raises here instead of being lost after the
        call was merely scheduled. The canonical message is sent as it is:
        an equipment warning is never rewritten by AI.
        """
        title, message = self._render(delivery)
        await self._hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": title,
                "message": message,
                "notification_id": continuity_notification_id(*delivery.key),
            },
            blocking=True,
        )

    async def _async_send_device(self, delivery: _Delivery) -> None:
        """Await the configured mobile notify action for this streak."""
        target = self._device_target(delivery.growspace_id)
        if target is None:
            # The target was removed after activation; absence is suppression,
            # not a failed action to retry until a new phone is configured.
            delivery.channels[DeliveryChannel.DEVICE].status = DeliveryStatus.SUPPRESSED
            return
        title, message = self._render(delivery)
        await self._hass.services.async_call(
            "notify",
            target,
            {
                "title": title,
                "message": message,
                "data": {
                    "tag": continuity_notification_id(*delivery.key),
                    "group": NOTIFICATION_GROUP,
                    "channel": NOTIFICATION_CHANNEL,
                    "notification_icon": NOTIFICATION_ICON,
                    "push": {"thread-id": NOTIFICATION_GROUP},
                },
            },
            blocking=True,
        )

    def _device_target(self, growspace_id: str) -> str | None:
        growspace = self._coordinator.growspaces.get(growspace_id)
        target = getattr(growspace, "notification_target", None)
        if not isinstance(target, str) or not target:
            return None
        return target.removeprefix("notify.")

    def _render(self, delivery: _Delivery) -> tuple[str, str]:
        """Name the growspace and camera around the canonical message."""
        growspace = self._coordinator.growspaces.get(delivery.growspace_id)
        growspace_name = growspace.name if growspace else delivery.growspace_id
        state = self._hass.states.get(delivery.camera_id)
        camera = (
            f"{state.name} ({delivery.camera_id})"
            if state is not None and state.name != delivery.camera_id
            else delivery.camera_id
        )
        return (
            f"⚠️ Capture Continuity Break: {growspace_name}",
            f"{CAPTURE_CONTINUITY_MESSAGE}\n\n"
            f"Camera: {camera}\nGrowspace: {growspace_name}",
        )

    def _muted(self, growspace_id: str) -> bool:
        return not self._coordinator.services.notifications.is_notifications_enabled(
            growspace_id
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _async_save(self) -> None:
        """Persist delivery progress, logging rather than raising on failure.

        Progress that fails to save is still acted on in memory. After a
        restart that costs at most a repeated attempt under the same
        notification id, or a retry this run had not finished; raising would
        fail the Vision Checkup instead.
        """
        try:
            await self._store.async_save(
                {
                    "deliveries": [
                        {
                            "activation_id": delivery.activation_id,
                            "growspace_id": delivery.growspace_id,
                            "camera_id": delivery.camera_id,
                            "activated_at": delivery.activated_at.isoformat(),
                            "channels": {
                                channel.value: {
                                    "status": progress.status.value,
                                    "attempts": progress.attempts,
                                }
                                for channel, progress in delivery.channels.items()
                            },
                        }
                        for delivery in self._deliveries.values()
                    ]
                }
            )
        except Exception:
            _LOGGER.exception("Could not save capture continuity delivery progress")


def _key(activation: ContinuityActivation) -> _DeliveryKey:
    return (activation.growspace_id, activation.camera_id, activation.activation_id)


def _load_deliveries(rows: Any) -> list[_Delivery]:
    """Read stored deliveries, discarding only a row that cannot be read.

    A discarded row costs only its own record: a finished one had nothing left
    to do, and an unfinished one goes unannounced rather than blocking every
    other activation's delivery.
    """
    deliveries: list[_Delivery] = []
    for row in rows:
        try:
            activated_at = datetime.fromisoformat(row["activated_at"])
            deliveries.append(
                _Delivery(
                    activation_id=str(row["activation_id"]),
                    growspace_id=str(row["growspace_id"]),
                    camera_id=str(row["camera_id"]),
                    activated_at=activated_at,
                    # A channel this version does not deliver through is
                    # left out rather than costing the whole record.
                    channels={
                        DeliveryChannel(channel): _ChannelProgress(
                            status=DeliveryStatus(progress["status"]),
                            attempts=int(progress["attempts"]),
                        )
                        for channel, progress in row["channels"].items()
                        if channel in DeliveryChannel
                    },
                )
            )
        except KeyError, TypeError, ValueError, AttributeError:
            _LOGGER.warning("Discarding unreadable continuity delivery %s", row)
    return deliveries
