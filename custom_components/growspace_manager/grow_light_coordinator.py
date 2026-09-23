"""Grow Light Coordinator for Growspace Manager.

Drives a growspace's grow lights from the photoperiod schedule (ADR-0023). It is
not sensor-regulated and follows two paths by device kind: plain ``switch.*`` /
``light.*`` lights are ticked live (each 10s tick reconciles to the desired
level — ``power`` inside the photoperiod, off outside it — so control is
level-based and self-heals across restarts), while AC Infinity lights are
configured once into their onboard ``Schedule`` mode and then run autonomously.

It also runs the Light Leak Guard (#794): at start-up and every minute it
watches the computed dark period for a managed grow light that is on, or an
illuminance sensor above its threshold, and raises one critical alert per
episode — optionally switching the managed grow lights off until lights-on.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .actuator_driver import resolve_actuator_driver, resolve_actuator_drivers
from .const import (
    ATTR_GROWSPACE_ID,
    CATEGORY_ALERT,
    EVENT_GROWSPACE_LOG_ENTRY,
    LIGHT_LEAK_SENSOR_TYPE,
    NotificationTier,
)
from .domain.light_leak import (
    EpisodeTransition,
    LeakCause,
    LightLeakEpisode,
    in_watched_dark_period,
    leak_causes,
)
from .domain.light_schedule import (
    desired_grow_light_power,
    is_dark_period,
    resolve_cycle_end_time,
    resolve_photoperiod_hours,
)
from .grow_light_ac_infinity import (
    ac_infinity_light_lit,
    ac_infinity_schedule_matches,
    push_ac_infinity_schedule,
    switch_off_ac_infinity_light,
)
from .utils import read_sensor_value

if TYPE_CHECKING:
    from datetime import date, datetime

    from .coordinator import GrowspaceCoordinator
    from .models import EnvironmentConfig, Growspace

_LOGGER = logging.getLogger(__name__)

_TICK_INTERVAL = timedelta(seconds=10)
_LEAK_CHECK_INTERVAL = timedelta(minutes=1)
# How long switched-off grow lights get to read back off before the guard says
# they did not. AC Infinity is cloud-polled, so one check interval is too tight.
_LEAK_READBACK_GRACE = timedelta(minutes=2)

# Sent when the controller starts up and finds a grow light still lit during
# what is now the dark period — e.g. the veg->flower flip shortened the day
# while GSM was down, so the light ran past its new off-time (ADR "Photoperiod
# Flip Transition"). The dark period is what matters biologically, so this warns
# rather than silently cutting the light.
_DARK_PERIOD_MESSAGE = (
    "Grow light was still on during the dark period; switching it off now. "
    "The light day may have shortened while Home Assistant was offline — verify "
    "your plants did not get light leak."
)


class GrowLightCoordinator:
    """Drives a growspace's grow lights on its photoperiod schedule."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        growspace_id: str,
        main_coordinator: GrowspaceCoordinator,
    ) -> None:
        """Initialize the GrowLightCoordinator."""
        self.hass = hass
        self.config_entry = config_entry
        self.growspace_id = growspace_id
        self.main_coordinator = main_coordinator
        self._remove_tick: Callable[[], None] | None = None
        self._remove_reconcile: Callable[[], None] | None = None
        self._remove_leak_check: Callable[[], None] | None = None
        self._last_dark_warn: date | None = None
        # Light Leak Guard state. It lives on the instance rather than being
        # reset by unload(), so a config edit mid-episode does not alert twice.
        self._leak_episode = LightLeakEpisode()
        self._leak_switched_off_at: datetime | None = None
        self._leak_restore_schedules = False

    @property
    def _growspace(self) -> Growspace | None:
        return self.main_coordinator.growspaces.get(self.growspace_id)

    @property
    def _env_config(self) -> EnvironmentConfig | None:
        gs = self._growspace
        return gs.environment_config if gs else None

    @property
    def _has_growlight_actuators(self) -> bool:
        """Whether any grow light — plain or AC Infinity — is configured."""
        env = self._env_config
        return bool(
            env and (env.growlight_entities or env.growlight_ac_infinity_devices)
        )

    def _controller_active(self, env: EnvironmentConfig) -> bool:
        """Whether GSM drives grow lights here, i.e. has lights it may switch."""
        return env.growlight_config.enabled and self._has_growlight_actuators

    async def async_setup(self) -> None:
        """Activate the controller: tick plain lights, configure AC Infinity ones."""
        env = self._env_config
        if env is None:
            return
        # The guard also watches rooms whose lights GSM does not drive, so it
        # starts before the controller's own gate.
        await self._start_light_leak_guard(env)
        if not env.growlight_config.enabled:
            return
        if not self._has_growlight_actuators:
            return

        # Detect a stale-on light from downtime BEFORE we act on it below (the
        # AC Infinity re-push would otherwise overwrite the evidence).
        await self._maybe_warn_dark_period_on(env)

        # Plain lights have no onboard schedule, so GSM ticks them live.
        if env.growlight_entities:
            self._remove_tick = async_track_time_interval(
                self.hass, self._on_tick, _TICK_INTERVAL
            )

        # AC Infinity lights run their onboard schedule autonomously; GSM writes
        # it (startup pass) and re-derives it at each local midnight so the
        # veg->flower flip re-pushes the shortened photoperiod (ADR-0025).
        if env.growlight_ac_infinity_devices:
            await self._reconcile_ac_infinity_schedules(env)
            self._schedule_next_reconcile()

        _LOGGER.info("GrowLightCoordinator started for %s", self.growspace_id)

    @callback
    def _on_tick(self, _now: object) -> None:
        """Handle the polling tick — schedule async reconciliation."""
        self.config_entry.async_create_background_task(
            self.hass, self._async_regulate(), "grow_light_regulate"
        )

    async def _async_regulate(self) -> None:
        """Reconcile every configured grow light to its desired power."""
        if not self.main_coordinator.irrigation_safety.automation_enabled(
            self.growspace_id
        ):
            return
        env = self._env_config
        if env is None or not env.growlight_config.enabled:
            return

        power = self._desired_power(env)
        drivers = resolve_actuator_drivers(self.hass, env.growlight_entities)
        for driver in drivers:
            if not self.main_coordinator.irrigation_safety.automation_enabled(
                self.growspace_id
            ):
                return
            await driver.set_speed(power)

    def _desired_power(self, env: EnvironmentConfig) -> int:
        """Compute the demand for now from the photoperiod schedule."""
        gs = self._growspace
        assert gs is not None  # guarded by callers via _env_config
        photoperiod_hours = self._photoperiod_hours(env)
        return desired_grow_light_power(
            dt_util.now(),
            gs.irrigation_strategy.lights_on_time,
            photoperiod_hours,
            env.growlight_config.power,
        )

    def _photoperiod_hours(self, env: EnvironmentConfig) -> float:
        """Resolve today's day length from plant stage."""
        plants = self.main_coordinator.services.growspaces.get_growspace_plants(
            self.growspace_id
        )
        return resolve_photoperiod_hours(
            plants, env.veg_day_hours, env.flower_day_hours, dt_util.now().date()
        )

    async def _reconcile_ac_infinity_schedules(self, env: EnvironmentConfig) -> None:
        """Re-push the derived schedule to any AC Infinity light that has drifted.

        Idempotent: a device already holding the desired schedule is left alone,
        so the steady-state midnight pass is a cheap comparison, not a write.
        """
        if not self.main_coordinator.irrigation_safety.automation_enabled(
            self.growspace_id
        ):
            return
        gs = self._growspace
        assert gs is not None  # guarded by callers via _env_config
        cfg = env.growlight_config
        on_time = gs.irrigation_strategy.lights_on_time
        off_time = resolve_cycle_end_time(on_time, self._photoperiod_hours(env))
        for device in env.growlight_ac_infinity_devices:
            if not self.main_coordinator.irrigation_safety.automation_enabled(
                self.growspace_id
            ):
                return
            if not ac_infinity_schedule_matches(
                self.hass,
                device,
                on_time=on_time,
                off_time=off_time,
                power=cfg.power,
                sunrise_enabled=cfg.sunrise_enabled,
                sunrise_minutes=cfg.sunrise_minutes,
            ):
                await push_ac_infinity_schedule(
                    self.hass,
                    device,
                    on_time=on_time,
                    off_time=off_time,
                    power=cfg.power,
                    sunrise_enabled=cfg.sunrise_enabled,
                    sunrise_minutes=cfg.sunrise_minutes,
                )

    async def _maybe_warn_dark_period_on(self, env: EnvironmentConfig) -> None:
        """Warn once if a grow light is still lit now that it should be dark.

        Only meaningful at startup/reconcile: during steady-state ticking the
        light is turned off exactly at cycle_end, so a light found lit in the
        dark period means it ran past its (possibly just-shortened) off-time
        while GSM was not driving it.
        """
        now = dt_util.now()
        if self._desired_power(env) != 0:
            return  # inside the photoperiod — the light is meant to be on
        if self._last_dark_warn == now.date():
            return
        if not self._growlight_lit_now(env, now):
            return

        self._last_dark_warn = now.date()
        gs = self._growspace
        name = gs.name if gs else self.growspace_id
        await self.main_coordinator.services.notifications.manager.async_send_notification(
            self.growspace_id,
            f"⚠️ Grow Light: {name}",
            _DARK_PERIOD_MESSAGE,
            tier=NotificationTier.WARNING,
        )

    def _growlight_lit_now(self, env: EnvironmentConfig, now: datetime) -> bool:
        """Whether any configured grow light is currently on."""
        return bool(self._lit_growlights(env, now))

    def _lit_growlights(self, env: EnvironmentConfig, now: datetime) -> list[str]:
        """Return the configured grow lights that are currently on.

        Plain lights are read from their entity state; an AC Infinity port from
        its Active Mode, or — while it runs its onboard schedule — from the
        on/off ``time`` window it currently holds. A port is named by its mode
        ``select``, the entity the grower picked it by.
        """
        lit = [
            entity_id
            for entity_id in env.growlight_entities
            if (driver := resolve_actuator_driver(self.hass, entity_id)) is not None
            and driver.is_on()
        ]
        lit.extend(
            device.mode_entity
            for device in env.growlight_ac_infinity_devices
            if ac_infinity_light_lit(self.hass, device, now)
        )
        return lit

    # --- Light Leak Guard (#794) ------------------------------------------

    def _leak_guard_active(self, env: EnvironmentConfig) -> bool:
        """Whether the guard has any evidence to watch: lights or a lux sensor."""
        cfg = env.light_leak_config
        return cfg.enabled and (
            bool(cfg.illuminance_sensor) or self._controller_active(env)
        )

    async def _start_light_leak_guard(self, env: EnvironmentConfig) -> None:
        """Check once now, then every minute."""
        if not self._leak_guard_active(env):
            return
        await self._async_check_light_leak()
        self._remove_leak_check = async_track_time_interval(
            self.hass, self._on_leak_check, _LEAK_CHECK_INTERVAL
        )

    @callback
    def _on_leak_check(self, _now: object) -> None:
        """Handle the guard's minute tick — schedule the async check."""
        self.config_entry.async_create_background_task(
            self.hass, self._async_check_light_leak(), "grow_light_leak_check"
        )

    async def _async_check_light_leak(self) -> None:
        """Gather this minute's evidence and act on the episode it produces."""
        env = self._env_config
        gs = self._growspace
        if env is None or gs is None:
            return
        cfg = env.light_leak_config
        now = dt_util.now()
        lights_on_time = gs.irrigation_strategy.lights_on_time

        if self._leak_restore_schedules and not is_dark_period(
            now, lights_on_time, self._photoperiod_hours(env)
        ):
            # Lights-on: hand the ports switched off by the guard back to their
            # onboard schedule. Plain lights need nothing — the tick drives them.
            self._leak_restore_schedules = False
            await self._reconcile_ac_infinity_schedules(env)

        plants = self.main_coordinator.services.growspaces.get_growspace_plants(
            self.growspace_id
        )
        watching = in_watched_dark_period(
            now,
            plants,
            lights_on_time=lights_on_time,
            veg_hours=env.veg_day_hours,
            flower_hours=env.flower_day_hours,
            all_stages=cfg.all_stages,
        )
        lit = (
            self._lit_growlights(env, now)
            if watching and self._controller_active(env)
            else []
        )
        illuminance = (
            read_sensor_value(self.hass, cfg.illuminance_sensor) if watching else None
        )
        causes = leak_causes(
            managed_light_on=bool(lit),
            illuminance=illuminance,
            threshold_lux=cfg.threshold_lux,
        )

        await self._read_back_switch_off(now, lit, watching=watching)

        duration = self._leak_episode.duration(now)
        transition = self._leak_episode.observe(
            now, bool(causes), timedelta(seconds=cfg.debounce_seconds)
        )
        if transition is EpisodeTransition.CONFIRMED:
            await self._alert_light_leak(env, causes, lit, illuminance)
        elif transition is EpisodeTransition.CLEARED:
            self._log_light_leak("Light leak ended", duration)

    async def _alert_light_leak(
        self,
        env: EnvironmentConfig,
        causes: frozenset[LeakCause],
        lit: list[str],
        illuminance: float | None,
    ) -> None:
        """Raise the episode's one alert, switching lights off if opted in."""
        gs = self._growspace
        assert gs is not None  # guarded by _async_check_light_leak
        cfg = env.light_leak_config
        on_time = gs.irrigation_strategy.lights_on_time
        off_time = resolve_cycle_end_time(on_time, self._photoperiod_hours(env))

        evidence: list[str] = []
        if LeakCause.ILLUMINANCE in causes:
            evidence.append(
                f"{cfg.illuminance_sensor} reads {illuminance:g} lx "
                f"(threshold {cfg.threshold_lux:g} lx)"
            )
        if LeakCause.MANAGED_LIGHT_ON in causes:
            evidence.append(f"grow light still on: {', '.join(lit)}")
        message = (
            f"Light during the dark period ({off_time[:5]}–{on_time[:5]}): "
            f"{'; '.join(evidence)}."
        )
        if cfg.switch_off_lights and self._controller_active(env):
            await self._switch_off_growlights(env)
            message += " Switching the managed grow lights off until lights-on."
        else:
            message += " Check the room for light leaks and the grow light timer."

        _LOGGER.warning("Light leak in growspace %s: %s", self.growspace_id, message)
        self._log_light_leak(message)
        await self.main_coordinator.services.notifications.manager.async_send_notification(
            self.growspace_id,
            f"🚨 Light Leak: {gs.name}",
            message,
            tier=NotificationTier.LIGHT_LEAK,
        )

    async def _switch_off_growlights(self, env: EnvironmentConfig) -> None:
        """Switch every managed grow light off and arm the read-back."""
        if not self.main_coordinator.irrigation_safety.automation_enabled(
            self.growspace_id
        ):
            return
        for driver in resolve_actuator_drivers(self.hass, env.growlight_entities):
            await driver.turn_off()
        for device in env.growlight_ac_infinity_devices:
            await switch_off_ac_infinity_light(self.hass, device)
        if env.growlight_ac_infinity_devices:
            self._leak_restore_schedules = True
        self._leak_switched_off_at = dt_util.now()

    async def _read_back_switch_off(
        self, now: datetime, lit: list[str], *, watching: bool
    ) -> None:
        """Confirm switched-off lights read back off, or say which did not."""
        switched_at = self._leak_switched_off_at
        if switched_at is None:
            return
        if not watching:
            self._leak_switched_off_at = None
            return
        if not lit:
            self._leak_switched_off_at = None
            self._log_light_leak("Managed grow lights read back off")
            return
        if now - switched_at < _LEAK_READBACK_GRACE:
            return

        self._leak_switched_off_at = None
        gs = self._growspace
        name = gs.name if gs else self.growspace_id
        message = (
            "Grow lights did not switch off after a light leak: "
            f"{', '.join(lit)}. Switch them off by hand."
        )
        _LOGGER.error("Light leak in growspace %s: %s", self.growspace_id, message)
        self._log_light_leak(message)
        await self.main_coordinator.services.notifications.manager.async_send_notification(
            self.growspace_id,
            f"🚨 Light Leak: {name}",
            message,
            tier=NotificationTier.LIGHT_LEAK,
        )

    def _log_light_leak(self, reason: str, duration: timedelta | None = None) -> None:
        """Record a light-leak logbook entry for this growspace."""
        data: dict[str, object] = {
            ATTR_GROWSPACE_ID: self.growspace_id,
            "category": CATEGORY_ALERT,
            "sensor_type": LIGHT_LEAK_SENSOR_TYPE,
            "reasons": [reason],
            "message": reason,
            "timestamp": dt_util.utcnow().isoformat(),
        }
        if duration is not None:
            data["duration_sec"] = int(duration.total_seconds())
        self.hass.bus.async_fire(EVENT_GROWSPACE_LOG_ENTRY, data)

    def _schedule_next_reconcile(self) -> None:
        """Schedule the next local-midnight re-derivation (self-rescheduling)."""
        self._cancel_reconcile_timer()
        now = dt_util.now()
        next_midnight = now.replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        self._remove_reconcile = async_track_point_in_utc_time(
            self.hass, self._on_midnight_reconcile, next_midnight
        )

    async def _on_midnight_reconcile(self, _now: datetime) -> None:
        """Re-derive and re-push at midnight (catches the veg->flower flip)."""
        try:
            env = self._env_config
            if (
                env is not None
                and env.growlight_config.enabled
                and env.growlight_ac_infinity_devices
            ):
                await self._reconcile_ac_infinity_schedules(env)
        except Exception:
            _LOGGER.exception(
                "Error reconciling grow light schedule for %s", self.growspace_id
            )
        self._schedule_next_reconcile()

    def _cancel_reconcile_timer(self) -> None:
        if self._remove_reconcile is not None:
            self._remove_reconcile()
            self._remove_reconcile = None

    async def async_restart(self) -> None:
        """Restart the controller after a config change."""
        self.unload()
        await self.async_setup()

    def unload(self) -> None:
        """Stop the live tick, the leak check and the midnight reconcile timer."""
        if self._remove_tick is not None:
            self._remove_tick()
            self._remove_tick = None
        if self._remove_leak_check is not None:
            self._remove_leak_check()
            self._remove_leak_check = None
        self._cancel_reconcile_timer()
