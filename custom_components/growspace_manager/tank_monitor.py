"""Tank level monitor — low-level notifications and the Tank Offline Alert.

Two jobs, both per configured irrigation tank. A state change at or below the
tank's warning level sends the low-level notification. And every tank is
watched for an Unknown Tank Level (ADR-0050): the watch is folded on every state
change and on a one-minute tick — a stale sensor produces no event to react to —
and once a tank has been unknown for its growspace's grace period, one Tank
Offline Alert goes out, whether or not a cycle is due and whatever
``pause_on_low_tank`` says.

The watches live here, in a ``TankWatchBook``, because this is the one place
that sees every reading; the Pump Cycle Gate asks the same book for its view,
so the gate and the alert can never disagree about a tank.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_GROWSPACE_ID,
    CATEGORY_ALERT,
    EVENT_GROWSPACE_LOG_ENTRY,
    NotificationTier,
)
from .domain.sensor_validity import TANK_LEVEL_RANGE, validate_reading
from .domain.unknown_tank_level import (
    DEFAULT_STALE_AFTER_MINUTES,
    TankAlert,
    TankStatus,
    TankWatch,
    offline_alert_message,
    recovered_alert_message,
)
from .presentation import EntityQueries

if TYPE_CHECKING:
    from homeassistant.core import (
        CALLBACK_TYPE,
        Event,
        EventStateChangedData,
        HomeAssistant,
        State,
    )

    from .coordinator import GrowspaceCoordinator
    from .models import Growspace, IrrigationTank

_LOGGER = logging.getLogger(__name__)

# How often every tank is re-validated for the Tank Offline Alert.
TANK_WATCH_INTERVAL = timedelta(minutes=1)


def stale_after(tank: IrrigationTank) -> timedelta:
    """Return the tank's staleness window, tolerating a malformed stored value."""
    try:
        minutes = int(tank.stale_after_minutes)
    except TypeError, ValueError:
        minutes = DEFAULT_STALE_AFTER_MINUTES
    return timedelta(minutes=max(1, minutes))


def tank_unknown_grace(growspace: Growspace) -> timedelta:
    """Return the growspace's grace before a tank's level counts as unknown."""
    return timedelta(minutes=growspace.irrigation_config.tank_unknown_grace_minutes)


def offline_notification_id(growspace_id: str, entity_id: str) -> str:
    """Return the persistent notification id of one tank's offline alert."""
    return f"growspace_tank_offline_{growspace_id}_{entity_id}"


def unknown_tank_skip_notification_id(growspace_id: str) -> str:
    """Return the id of the notification a cycle refused on an unknown tank raises."""
    return f"growspace_tank_unknown_{growspace_id}"


class TankWatchBook:
    """The Unknown Tank Level watch of every configured tank, per growspace.

    Reads Home Assistant state and folds it into each tank's ``TankWatch``; it
    sends nothing. A watch begins when the book does, so a tank that has not
    read validly since the start has no level to hold.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Begin watching from now."""
        self._hass = hass
        self.started_at = dt_util.utcnow()
        self._watches: dict[tuple[str, str], TankWatch] = {}

    def observe(
        self,
        growspace_id: str,
        tank: IrrigationTank,
        now: datetime,
        state: State | None = None,
    ) -> TankWatch:
        """Fold the tank's current (or given) state in and return its watch."""
        key = (growspace_id, tank.sensor_entity)
        watch = self._watches.get(key)
        if watch is None:
            watch = self._watches[key] = TankWatch(watching_since=self.started_at)
        if state is None:
            state = self._hass.states.get(tank.sensor_entity)
        watch.observe(
            validate_reading(
                state.state if state else None,
                changed_at=state.last_changed if state else None,
                reported_at=state.last_reported if state else None,
                now=now,
                max_age=stale_after(tank),
                plausible=TANK_LEVEL_RANGE,
            )
        )
        return watch

    def status(
        self, growspace: Growspace, tank: IrrigationTank, now: datetime
    ) -> TankStatus:
        """Return the gate's view of one tank, freshly observed."""
        return self.observe(growspace.id, tank, now).status(
            tank.name, tank.sensor_entity, now, tank_unknown_grace(growspace)
        )

    def any_alerted(self, growspace_id: str) -> bool:
        """Return whether any tank in the growspace is in an alerted episode."""
        return any(
            watch.alerted
            for (owner, _), watch in self._watches.items()
            if owner == growspace_id
        )

    def prune(self, configured: set[tuple[str, str]]) -> list[tuple[str, str]]:
        """Forget tanks no longer configured; return those that had alerted."""
        gone = {
            key: self._watches.pop(key)
            for key in list(self._watches)
            if key not in configured
        }
        return [key for key, watch in gone.items() if watch.alerted]


class TankLevelMonitor:
    """Watches every configured tank and sends its notifications."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: GrowspaceCoordinator,
        notify: Callable[..., Coroutine[Any, Any, None]],
    ) -> None:
        """Initialise the monitor."""
        self.hass = hass
        self.coordinator = coordinator
        self._notify = notify
        self._unsubs: list[CALLBACK_TYPE] = []
        self._entity_queries = EntityQueries(hass)
        self.watches = TankWatchBook(hass)

    async def async_start(self) -> None:
        """Subscribe to every configured tank sensor and start the watch tick."""
        for growspace in self.coordinator.growspaces.values():
            if (
                not growspace.environment_config
                or not growspace.environment_config.irrigation_tanks
            ):
                continue
            for tank in growspace.environment_config.irrigation_tanks:
                self._subscribe_tank(growspace.id, growspace.name, tank)
        self._unsubs.append(
            async_track_time_interval(
                self.hass, self._async_watch_tick, TANK_WATCH_INTERVAL
            )
        )

    def _subscribe_tank(
        self, growspace_id: str, growspace_name: str, tank: Any
    ) -> None:
        """Register a state-change listener for a single tank sensor."""
        entity_queries = self._entity_queries

        async def _on_state_change(event: Event[EventStateChangedData]) -> None:
            new_state = event.data.get("new_state")
            if new_state is None:
                return
            # Every reading is folded, so the watch holds the last valid level
            # rather than whatever the tick last happened to see.
            self.watches.observe(growspace_id, tank, dt_util.utcnow(), new_state)
            level = entity_queries.parse_tank_level(new_state.state)
            if level is not None and level <= tank.warning_level:
                await self._notify(
                    growspace_id,
                    title="⚠️ Low Irrigation Tank Level",
                    message=(
                        f"{tank.name} in {growspace_name} is at {level:.0f}%"
                        f" (warning at {tank.warning_level:.0f}%)"
                    ),
                    tier=NotificationTier.CRITICAL,
                )

        unsub = async_track_state_change_event(
            self.hass, tank.sensor_entity, _on_state_change
        )
        self._unsubs.append(unsub)

    async def _async_watch_tick(self, now: datetime | None = None) -> None:
        """Re-validate every configured tank and announce episode changes."""
        now = now or dt_util.utcnow()
        configured: set[tuple[str, str]] = set()
        for growspace in list(self.coordinator.growspaces.values()):
            env = growspace.environment_config
            for tank in env.irrigation_tanks if env else ():
                configured.add((growspace.id, tank.sensor_entity))
                watch = self.watches.observe(growspace.id, tank, now)
                transition = watch.alert(now, tank_unknown_grace(growspace))
                if transition is TankAlert.OFFLINE:
                    await self._async_alert_offline(growspace, tank, watch, now)
                elif transition is TankAlert.RECOVERED:
                    await self._async_alert_recovered(growspace, tank, watch)
        for growspace_id, entity_id in self.watches.prune(configured):
            await self._async_dismiss(growspace_id, entity_id)

    async def _async_alert_offline(
        self,
        growspace: Growspace,
        tank: IrrigationTank,
        watch: TankWatch,
        now: datetime,
    ) -> None:
        """Send one episode's Tank Offline Alert."""
        unknown = watch.status(
            tank.name, tank.sensor_entity, now, tank_unknown_grace(growspace)
        ).unknown
        if unknown is None:  # pragma: no cover - alert() fires only past grace
            return
        message = offline_alert_message(
            unknown,
            growspace_name=growspace.name,
            since_local=dt_util.as_local(unknown.since).strftime("%H:%M"),
            stale_after_minutes=int(stale_after(tank).total_seconds() // 60),
            irrigation_paused=growspace.irrigation_config.pause_on_low_tank,
        )
        title = f"⚠️ Tank Offline: {growspace.name}"
        _LOGGER.warning("Tank offline in growspace %s: %s", growspace.id, message)
        self._log(growspace.id, message)
        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": title,
                "message": message,
                "notification_id": offline_notification_id(
                    growspace.id, tank.sensor_entity
                ),
            },
            blocking=False,
        )
        await self._notify(
            growspace.id,
            title=title,
            message=message,
            tier=NotificationTier.TANK_OFFLINE,
        )

    async def _async_alert_recovered(
        self, growspace: Growspace, tank: IrrigationTank, watch: TankWatch
    ) -> None:
        """Announce that an alerted tank reads again, and clear its alert."""
        message = recovered_alert_message(
            tank.name, growspace.name, watch.last_valid_level or 0.0
        )
        _LOGGER.info("Tank back online in growspace %s: %s", growspace.id, message)
        self._log(growspace.id, message)
        await self._async_dismiss(growspace.id, tank.sensor_entity)
        if not self.watches.any_alerted(growspace.id):
            # The refused cycle's notice says irrigation resumes once the tank
            # reports; with every tank here reporting, it no longer holds.
            await self.hass.services.async_call(
                "persistent_notification",
                "dismiss",
                {"notification_id": unknown_tank_skip_notification_id(growspace.id)},
                blocking=False,
            )
        await self._notify(
            growspace.id,
            title=f"✅ Tank Back Online: {growspace.name}",
            message=message,
            tier=NotificationTier.TANK_OFFLINE,
        )

    async def _async_dismiss(self, growspace_id: str, entity_id: str) -> None:
        await self.hass.services.async_call(
            "persistent_notification",
            "dismiss",
            {"notification_id": offline_notification_id(growspace_id, entity_id)},
            blocking=False,
        )

    def _log(self, growspace_id: str, message: str) -> None:
        self.hass.bus.async_fire(
            EVENT_GROWSPACE_LOG_ENTRY,
            {
                ATTR_GROWSPACE_ID: growspace_id,
                "message": message,
                "category": CATEGORY_ALERT,
                "timestamp": dt_util.utcnow().isoformat(),
            },
        )

    def async_stop(self) -> None:
        """Cancel all subscriptions."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
