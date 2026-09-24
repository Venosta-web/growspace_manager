"""One growspace's Climate Fail-Safe and Humidity Interlock (#792).

The humidifier, dehumidifier and exhaust controllers of a growspace share one
``ClimateSafety``. It reads their control inputs through one ``SensorWatch``
per sensor, so a VPD sensor the humidifier and dehumidifier both read learns
one cadence and has one invalid episode. It decides which controllers are in
their Safe State, raises one alert per Fail-Safe Episode, and lets the two
on/off controllers find each other for the interlock.

The rules are ``domain/climate_fail_safe.py``'s; this is the shell that reads
Home Assistant state and sends the notifications.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any, Protocol

from homeassistant.core import HomeAssistant
from homeassistant.util.dt import as_local, utcnow

from .const import NotificationTier
from .domain.climate_fail_safe import (
    ClimateRole,
    EpisodeAlert,
    FailSafeEpisode,
    RoleFailure,
    SafeState,
    fail_safe_due,
    failed_alert_message,
    failed_since,
    recovered_alert_message,
    safe_action,
)
from .domain.sensor_validity import PlausibleRange, SensorReading, SensorWatch
from .models import ClimateFailSafeConfig
from .reliability_store import climate_fail_safe

if TYPE_CHECKING:
    from .coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)

type Plausible = PlausibleRange | Callable[[str | None], PlausibleRange]


class InterlockPartner(Protocol):
    """What the Humidity Interlock needs of the other on/off controller."""

    demand_since: datetime | None

    def is_device_on(self) -> bool:
        """Return whether any of its devices is on."""
        ...

    async def async_interlock_off(self, winner: ClimateRole) -> None:
        """Switch its devices off because ``winner`` is taking over."""
        ...


def _stamp(value: Any) -> datetime | None:
    """Return a state timestamp, or None when the state carries none."""
    return value if isinstance(value, datetime) else None


def fallback_speed(configured: int, min_speed: int, max_speed: int) -> int:
    """Return the exhaust fallback speed inside the fan's own speed range."""
    return max(min_speed, min(max_speed, configured))


class ClimateSafety:
    """The fail-safe and interlock state shared by one growspace's climate controllers."""

    def __init__(
        self,
        hass: HomeAssistant,
        growspace_id: str,
        main_coordinator: GrowspaceCoordinator,
    ) -> None:
        """Create the shared state for one growspace."""
        self.hass = hass
        self.growspace_id = growspace_id
        self.main_coordinator = main_coordinator
        self._watches: dict[str, SensorWatch] = {}
        self._inputs: dict[ClimateRole, dict[str, Plausible]] = {}
        self._episode = FailSafeEpisode()
        self._on_off: dict[ClimateRole, InterlockPartner] = {}

    @property
    def config(self) -> ClimateFailSafeConfig:
        """Return the growspace's live Climate Fail-Safe configuration."""
        growspace = self.main_coordinator.growspaces.get(self.growspace_id)
        env = getattr(growspace, "environment_config", None)
        config = getattr(env, "climate_fail_safe_config", None)
        return (
            config
            if isinstance(config, ClimateFailSafeConfig)
            else ClimateFailSafeConfig()
        )

    def safe_state(self, role: ClimateRole) -> SafeState:
        """Return the configured Safe State of an on/off controller."""
        return SafeState(getattr(self.config, f"{role.value}_safe_state"))

    def max_runtime(self, role: ClimateRole) -> timedelta | None:
        """Return an on/off device's maximum continuous runtime, or None."""
        minutes = getattr(self.config, f"{role.value}_max_runtime_minutes")
        return timedelta(minutes=minutes) if minutes > 0 else None

    def exhaust_fallback_speed(self) -> int:
        """Return the speed the exhaust runs at in its Safe State."""
        growspace = self.main_coordinator.growspaces.get(self.growspace_id)
        configured = self.config.exhaust_fallback_speed
        if growspace is None:
            return configured
        cfg = growspace.environment_config.exhaust_fan_config
        return fallback_speed(configured, cfg.min_speed, cfg.max_speed)

    def _stale_cap(self) -> timedelta | None:
        minutes = self.config.sensor_stale_after_minutes
        return timedelta(minutes=minutes) if minutes > 0 else None

    def reading(
        self, entity_id: str, plausible: Plausible, now: datetime | None = None
    ) -> SensorReading:
        """Validate one control input through its shared watch."""
        now = now or utcnow()
        watch = self._watches.get(entity_id)
        if watch is None:
            watch = self._watches[entity_id] = SensorWatch(watching_since=now)
        state = self.hass.states.get(entity_id)
        band = plausible
        if not isinstance(band, PlausibleRange):
            unit = state.attributes.get("unit_of_measurement") if state else None
            band = band(unit)
        return watch.read(
            state.state if state else None,
            changed_at=_stamp(getattr(state, "last_changed", None)),
            reported_at=_stamp(getattr(state, "last_reported", None)),
            now=now,
            stale_cap=self._stale_cap(),
            plausible=band,
        )

    def register(self, role: ClimateRole, controller: InterlockPartner) -> None:
        """Make an on/off controller findable by its interlock partner."""
        self._on_off[role] = controller

    def partner(self, role: ClimateRole) -> InterlockPartner | None:
        """Return the other on/off controller of the growspace, if any."""
        other = (
            ClimateRole.DEHUMIDIFIER
            if role is ClimateRole.HUMIDIFIER
            else ClimateRole.HUMIDIFIER
        )
        return self._on_off.get(other)

    def record(self, counter: str) -> None:
        """Count one climate effect in the growspace's reliability evidence."""
        self.main_coordinator.reliability.record(self.growspace_id, counter)

    def is_failed(self, role: ClimateRole) -> bool:
        """Return whether ``role`` was in its Safe State at the last evaluation."""
        return role in self._episode.failed

    def withdraw(self, role: ClimateRole) -> None:
        """Stop considering a controller that has been unloaded."""
        self._inputs.pop(role, None)

    async def async_failure(
        self, role: ClimateRole, inputs: Mapping[str, Plausible]
    ) -> RoleFailure | None:
        """Return why ``role`` is in its Safe State, or None while it can see.

        ``inputs`` are the controller's control sensors as it reads them now.
        Every controller is evaluated, not only this one, so the controllers a
        dead sensor takes down together are announced together.
        """
        if inputs:
            self._inputs[role] = dict(inputs)
        else:
            self._inputs.pop(role, None)
        now = utcnow()
        timeout = timedelta(minutes=self.config.sensor_timeout_minutes)
        failed: dict[ClimateRole, RoleFailure] = {}
        for each, sensors in self._inputs.items():
            readings = {
                entity_id: self.reading(entity_id, plausible, now)
                for entity_id, plausible in sensors.items()
            }
            since = failed_since(
                readings,
                {
                    entity_id: self._watches[entity_id].invalid_since or now
                    for entity_id in readings
                },
            )
            if since is not None and fail_safe_due(since, now, timeout):
                failed[each] = RoleFailure(tuple(readings), since)
        for entered in failed.keys() - self._episode.failed.keys():
            self.record(climate_fail_safe(entered))
        transition = self._episode.update(failed, now)
        if transition is not EpisodeAlert.NONE:
            await self._async_announce(transition)
        return failed.get(role)

    def _notification_id(self) -> str:
        return f"growspace_climate_fail_safe_{self.growspace_id}"

    def _growspace_name(self) -> str:
        growspace = self.main_coordinator.growspaces.get(self.growspace_id)
        return str(getattr(growspace, "name", self.growspace_id))

    async def _async_announce(self, transition: EpisodeAlert) -> None:
        """Send, update or clear the episode's alert."""
        name = self._growspace_name()
        if transition is EpisodeAlert.RECOVERED:
            message = recovered_alert_message(name)
            _LOGGER.info("Growspace %s: %s", self.growspace_id, message)
            await self.hass.services.async_call(
                "persistent_notification",
                "dismiss",
                {"notification_id": self._notification_id()},
                blocking=False,
            )
            await self._async_push(f"✅ Climate Control Resumed: {name}", message)
            return
        failed = self._episode.failed
        actions = {
            role: safe_action(
                role,
                None if role is ClimateRole.EXHAUST else self.safe_state(role),
                self.exhaust_fallback_speed(),
            )
            for role in failed
        }
        since = min(failure.since for failure in failed.values())
        message = failed_alert_message(
            name, failed, actions, since_local=as_local(since).strftime("%H:%M")
        )
        title = f"⚠️ Climate Fail-Safe: {name}"
        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": title,
                "message": message,
                "notification_id": self._notification_id(),
            },
            blocking=False,
        )
        if transition is EpisodeAlert.FAILED:
            _LOGGER.warning("Growspace %s: %s", self.growspace_id, message)
            await self._async_push(title, message)

    async def _async_push(self, title: str, message: str) -> None:
        """Push to the growspace's notification target on the sensor alert tier."""
        await self.main_coordinator.services.notifications.manager.async_send_notification(
            self.growspace_id,
            title,
            message,
            tier=NotificationTier.SENSOR_INVALID,
        )
