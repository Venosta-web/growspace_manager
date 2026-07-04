"""Photoperiod flip checker — notifies when any plant enters flower stage today."""

from __future__ import annotations

from datetime import date, timedelta
import logging
from typing import TYPE_CHECKING

from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util.dt import now as ha_now

from .const import NotificationTier

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.core import CALLBACK_TYPE, HomeAssistant

    from .coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)

_AUTO_TRACKING_MESSAGE = (
    "Plants entering flower — light schedule will auto-adapt from sensor. "
    "Verify your hardware timer is set to 12h."
)
_MANUAL_MESSAGE = "Plants entering flower — update your lights-on time to 12h."
# Used when a Grow Light Controller owns the schedule: GSM applies the 12h day
# itself, so the message confirms and asks the user to verify rather than to act.
_CONTROLLER_MESSAGE = (
    "Plants entering flower — GSM shortened the light day to 12h. Verify your hardware."
)


def _growlight_controls(growspace: object) -> bool:
    """Whether a Grow Light Controller owns this growspace's photoperiod."""
    env = getattr(growspace, "environment_config", None)
    if env is None:
        return False
    cfg = env.growlight_config
    return bool(
        cfg.enabled and (env.growlight_entities or env.growlight_ac_infinity_devices)
    )


class PhotoperiodFlipChecker:
    """Sends a daily notification when any plant in a growspace enters flower stage."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: GrowspaceCoordinator,
    ) -> None:
        """Initialize the photoperiod flip checker."""
        self.hass = hass
        self.coordinator = coordinator
        self._unsub_timers: dict[str, CALLBACK_TYPE] = {}

    def _cancel_timer(self, growspace_id: str) -> None:
        if unsub := self._unsub_timers.pop(growspace_id, None):
            unsub()

    def async_stop(self) -> None:
        """Cancel all scheduled timers."""
        for growspace_id in list(self._unsub_timers):
            self._cancel_timer(growspace_id)

    def schedule_growspace(self, growspace_id: str) -> None:
        """Schedule midnight flip check and run an immediate startup check."""
        self._cancel_timer(growspace_id)

        now = ha_now()
        next_midnight = now.replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)

        self._unsub_timers[growspace_id] = async_track_point_in_utc_time(
            self.hass,
            self._create_callback(growspace_id),
            next_midnight,
        )

        self.coordinator.config_entry.async_create_background_task(
            self.hass,
            self._check_growspace(growspace_id),
            f"photoperiod_flip_startup_{growspace_id}",
        )

    def schedule_all_growspaces(self) -> None:
        """Schedule flip checks for all growspaces."""
        for growspace_id in self.coordinator.growspaces:
            self.schedule_growspace(growspace_id)

    def _create_callback(self, growspace_id: str):
        """Return a one-shot midnight callback that checks and reschedules."""

        async def _callback(_now: datetime) -> None:
            try:
                await self._check_growspace(growspace_id)
            except Exception:
                _LOGGER.exception(
                    "Error during photoperiod flip check for %s", growspace_id
                )
            self.schedule_growspace(growspace_id)

        return _callback

    async def _check_growspace(self, growspace_id: str) -> None:
        """Check whether any plant flips to flower today and notify if so."""
        growspace = self.coordinator.growspaces.get(growspace_id)
        if not growspace:
            return

        plants = self.coordinator.services.growspaces.get_growspace_plants(growspace_id)
        if not plants:
            return

        today = ha_now().date()
        flipped = False
        for plant in plants:
            if not plant.flower_start:
                continue
            try:
                if date.fromisoformat(plant.flower_start) == today:
                    flipped = True
                    break
            except ValueError:
                _LOGGER.warning(
                    "Malformed flower_start %r for plant in growspace %s",
                    plant.flower_start,
                    growspace_id,
                )

        if not flipped:
            return

        if _growlight_controls(growspace):
            message = _CONTROLLER_MESSAGE
        elif growspace.irrigation_strategy.auto_light_tracking:
            message = _AUTO_TRACKING_MESSAGE
        else:
            message = _MANUAL_MESSAGE
        title = f"🌸 Photoperiod Flip: {growspace.name}"

        await self.coordinator.services.notifications.manager.async_send_notification(
            growspace_id,
            title,
            message,
            tier=NotificationTier.PHOTOPERIOD_FLIP,
        )
