"""TankWaterTracker: records tank level snapshots and computes water usage events."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import (
    TANK_MAX_EVENTS,
    TANK_MAX_SNAPSHOTS,
    TANK_NOISE_FLOOR_PCT,
    TANK_REFILL_THRESHOLD_PCT,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .models import IrrigationTank

_BUCKET_15MIN = timedelta(minutes=15)
_BUCKET_1H = timedelta(hours=1)

_LOGGER = logging.getLogger(__name__)


def _parse_ts(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp string to a timezone-aware datetime."""
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=dt_util.UTC)
    return dt


def _floor_to_bucket(dt: datetime, bucket_size: timedelta) -> datetime:
    """Floor *dt* down to the nearest *bucket_size* boundary."""
    total_seconds = int(dt.timestamp())
    bucket_seconds = int(bucket_size.total_seconds())
    floored = (total_seconds // bucket_seconds) * bucket_seconds
    return datetime.fromtimestamp(floored, tz=dt.tzinfo)


def _build_buckets(
    reference_ts: str | None,
    num_buckets: int,
    bucket_size: timedelta,
) -> list[dict[str, Any]]:
    """Build an empty list of *num_buckets* consecutive time buckets.

    Buckets run from oldest to newest, each ending at the boundary that
    includes *reference_ts*.
    """
    if reference_ts is not None:
        ref_dt = _parse_ts(reference_ts)
    else:
        ref_dt = dt_util.utcnow()

    end_boundary = _floor_to_bucket(ref_dt, bucket_size) + bucket_size
    buckets: list[dict[str, Any]] = []
    for i in range(num_buckets - 1, -1, -1):
        bucket_start = end_boundary - bucket_size * (i + 1)
        buckets.append(
            {
                "bucket_start": bucket_start.isoformat(),
                "liters_consumed": 0.0,
                "liters_refilled": 0.0,
            }
        )
    return buckets


def _fill_buckets(
    buckets: list[dict[str, Any]],
    events: list[dict[str, Any]],
    bucket_size: timedelta,
) -> None:
    """Distribute events into their corresponding bucket (in-place)."""
    if not buckets:
        return
    first_start = _parse_ts(buckets[0]["bucket_start"])
    last_start = _parse_ts(buckets[-1]["bucket_start"])
    last_end = last_start + bucket_size

    for ev in events:
        ev_dt = _parse_ts(ev["timestamp"])
        if ev_dt < first_start or ev_dt >= last_end:
            continue
        # Find the bucket index
        delta_seconds = (ev_dt - first_start).total_seconds()
        idx = int(delta_seconds / bucket_size.total_seconds())
        idx = max(0, min(idx, len(buckets) - 1))
        if ev["event_type"] == "consumption":
            buckets[idx]["liters_consumed"] += ev["liters"]
        else:
            buckets[idx]["liters_refilled"] += ev["liters"]


class TankWaterTracker:
    """Tracks tank water levels, records events and provides aggregated history.

    Reads and writes directly to ``tank.water_history``.
    """

    def __init__(self, tank: IrrigationTank) -> None:
        """Initialize with a reference to an IrrigationTank instance."""
        self.tank = tank
        self._pending_peak: float | None = None
        self._unsub: Any | None = None

    # ── recording ────────────────────────────────────────────────────────────

    def record_level(self, level_pct: float, timestamp: str) -> None:
        """Record a tank level reading and derive consumption/refill events.

        Uses dual baselines to solve two independent problems:

        * ``last_recorded_level`` (trough) — only advances on formal events so
          cumulative rises can still accumulate to the refill threshold.
        * ``peak_level`` (consumption baseline) — advances when a minor rise is
          *confirmed* by a subsequent reading still above trough + noise_floor,
          so consumption after a partial top-up is measured from the new level
          rather than the pre-fill trough.

        The pending-peak confirmation step discards single-reading sensor
        spikes: a rise that reverts to the trough zone in the very next reading
        never commits as a new peak, preventing false consumption events.

        Args:
            level_pct: Current fill level as a percentage (0-100).
            timestamp: ISO-8601 timestamp string for this reading.
        """
        _LOGGER.debug(
            "TankWaterTracker(%s) recording level: %s%% at %s",
            self.tank.sensor_entity,
            level_pct,
            timestamp,
        )
        history = self.tank.water_history
        snapshot: dict[str, Any] = {"timestamp": timestamp, "level_pct": level_pct}

        # Append snapshot and prune window
        history.snapshots.append(snapshot)
        if len(history.snapshots) > TANK_MAX_SNAPSHOTS:
            history.snapshots = history.snapshots[-TANK_MAX_SNAPSHOTS:]

        if self.tank.last_recorded_level is None:
            self.tank.last_recorded_level = level_pct
            self.tank.peak_level = level_pct
            self._pending_peak = None
            return  # First reading — initialize baselines

        trough = self.tank.last_recorded_level

        # ── Confirm or discard any pending (unconfirmed) peak ─────────────────
        # A pending peak was queued by a minor rise on the previous reading.
        # Confirm it if the current level is still meaningfully above the trough
        # (genuine partial refill). Discard it if the level has returned to the
        # trough zone (sensor spike / round-trip noise).
        if self._pending_peak is not None:
            if level_pct >= trough + TANK_NOISE_FLOOR_PCT:
                # Level still above trough: commit the pending peak
                if level_pct >= self._pending_peak - TANK_NOISE_FLOOR_PCT:
                    self.tank.peak_level = self._pending_peak
            # else: level back near trough → spike, discard (peak_level unchanged)
            self._pending_peak = None

        peak = self.tank.peak_level if self.tank.peak_level is not None else trough

        delta_from_trough = round(level_pct - trough, 4)
        delta_from_peak = round(level_pct - peak, 4)

        def _liters(abs_pct: float) -> float:
            if self.tank.volume_liters is not None:
                return self.tank.volume_liters * abs_pct / 100.0
            return abs_pct

        event: dict[str, Any] | None = None

        if delta_from_trough >= TANK_REFILL_THRESHOLD_PCT:
            # Large single rise from trough: formal refill event
            event = {
                "timestamp": timestamp,
                "event_type": "refill",
                "pct_delta": delta_from_trough,
                "liters": _liters(delta_from_trough),
            }

        elif delta_from_peak <= -TANK_NOISE_FLOOR_PCT:
            # Level dropped below confirmed peak: consumption event
            abs_consumed = abs(delta_from_peak)
            event = {
                "timestamp": timestamp,
                "event_type": "consumption",
                "pct_delta": delta_from_peak,
                "liters": _liters(abs_consumed),
            }

        elif delta_from_trough >= TANK_NOISE_FLOOR_PCT:
            # Minor rise from trough: queue as pending peak candidate.
            # Only queue if the level is higher than the already-confirmed peak
            # (to avoid redundantly re-queuing a level we already track).
            if level_pct > peak and (
                self._pending_peak is None or level_pct > self._pending_peak
            ):
                self._pending_peak = level_pct
            return

        else:
            return  # Change too small to act on

        history.events.append(event)
        _LOGGER.debug(
            "TankWaterTracker(%s) recorded event: %s (delta: %s%%, liters: %s)",
            self.tank.sensor_entity,
            event["event_type"],
            event["pct_delta"],
            event["liters"],
        )
        self.tank.last_recorded_level = level_pct
        self.tank.peak_level = level_pct
        self._pending_peak = None

        if len(history.events) > TANK_MAX_EVENTS:
            history.events = history.events[-TANK_MAX_EVENTS:]

    # ── aggregation ───────────────────────────────────────────────────────────

    def get_history_24h(self, reference_ts: str | None = None) -> list[dict[str, Any]]:
        """Return 96 15-minute consumption/refill buckets for the last 24 hours."""
        buckets = _build_buckets(reference_ts, 96, _BUCKET_15MIN)
        _fill_buckets(buckets, self.tank.water_history.events, _BUCKET_15MIN)
        return buckets

    def get_history_7d(self, reference_ts: str | None = None) -> list[dict[str, Any]]:
        """Return 168 hourly consumption/refill buckets for the last 7 days."""
        buckets = _build_buckets(reference_ts, 168, _BUCKET_1H)
        _fill_buckets(buckets, self.tank.water_history.events, _BUCKET_1H)
        return buckets

    def get_total_liters_today(self, reference_ts: str | None = None) -> float:
        """Return total liters consumed since midnight UTC on the reference date."""
        if reference_ts is not None:
            ref_dt = _parse_ts(reference_ts)
        else:
            ref_dt = dt_util.utcnow()
        day_start = ref_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        return sum(
            ev["liters"]
            for ev in self.tank.water_history.events
            if ev["event_type"] == "consumption"
            and _parse_ts(ev["timestamp"]) >= day_start
        )

    def get_total_liters_7d(self, reference_ts: str | None = None) -> float:
        """Return total liters consumed in the last 7 days from the reference time."""
        if reference_ts is not None:
            ref_dt = _parse_ts(reference_ts)
        else:
            ref_dt = dt_util.utcnow()
        window_start = ref_dt - timedelta(days=7)
        return sum(
            ev["liters"]
            for ev in self.tank.water_history.events
            if ev["event_type"] == "consumption"
            and _parse_ts(ev["timestamp"]) >= window_start
        )

    # ── HA subscription ───────────────────────────────────────────────────────

    async def async_setup(
        self,
        hass: HomeAssistant,
        on_change: Any | None = None,
    ) -> Any:
        """Subscribe to state changes on the tank sensor entity.

        Args:
            hass: Home Assistant instance.
            on_change: Optional callback invoked after each successful recording.

        Returns:
            An unsubscribe callable.
        """

        def _handle_state_change(event: Any) -> None:
            """Handle a state-change event for the tank sensor."""
            new_state = event.data.get("new_state")
            if new_state is None:
                return
            try:
                level_pct = float(new_state.state)
            except (ValueError, TypeError):
                _LOGGER.debug(
                    "TankWaterTracker(%s) received invalid state: %s",
                    self.tank.sensor_entity,
                    new_state.state,
                )
                return
            self.record_level(level_pct, new_state.last_updated.isoformat())
            if on_change is not None:
                on_change()

        self._unsub = async_track_state_change_event(
            hass, self.tank.sensor_entity, _handle_state_change
        )
        return self._unsub

    async def async_unsubscribe(self) -> None:
        """Unsubscribe from state change events."""
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
