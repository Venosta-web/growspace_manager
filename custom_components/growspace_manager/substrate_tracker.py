"""SubstrateTracker: turns live VWC readings into measured dryback events.

Fed reading-by-reading by the VWC steering minute loop, this tracker detects
two kinds of measured drybacks and persists them as a rolling event history on
the growspace model, so the metrics survive an HA restart without ever querying
the recorder (see ADR-0010).

* **Overnight Dryback** — shot-to-shot: the settled VWC peak after the day's
  *last* shot down to the minimum VWC before the *next* day's first shot.
  Lights on/off do not bound the window. On a zero-shot day the peak falls back
  to the lit-period maximum.
* **In-Cycle Dryback** — settled peak after one P2 shot down to the trough
  immediately before the next P2 shot. The day's set yields shots/day and the
  average P2 dryback.

All dryback values are absolute VWC percentage points (peak - trough); a 55% ->
45% drop is ``10.0`` (see CONTEXT.md "Dryback").

The tracker reads and writes directly to ``growspace.substrate_history`` so its
pending state (a peak awaiting its trough) persists and resumes correctly after
a mid-window restart.
"""

from __future__ import annotations

from datetime import datetime
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from .const import (
    SUBSTRATE_EC_TREND_DEADBAND,
    SUBSTRATE_MAX_EVENTS,
    SUBSTRATE_NOISE_FLOOR_PCT,
)

if TYPE_CHECKING:
    from .models import Growspace, SubstrateHistory

_LOGGER = logging.getLogger(__name__)


def _parse_ts(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp to a timezone-aware datetime."""
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=dt_util.UTC)
    return dt


def _local_date(ts: str) -> str:
    """Return the local ISO date (YYYY-MM-DD) for an ISO timestamp."""
    return dt_util.as_local(_parse_ts(ts)).date().isoformat()


class SubstrateTracker:
    """Detects and persists measured substrate dryback events.

    The tracker is deterministic: feeding the same sequence of readings and shot
    events always yields the same persisted history, which makes it unit-testable
    from plain ``(timestamp, vwc, ...)`` sequences with no recorder fixtures.

    Public API:

    * :meth:`record_reading` — feed one VWC reading from the minute loop.
    * :meth:`record_pore_ec` — feed one averaged pore-EC reading from the loop.
    * :meth:`record_shot` — signal that a P1/P2 shot fired this tick.
    * :meth:`get_latest_overnight_dryback` — most recent overnight event, or None.
    * :meth:`get_incycle_drybacks_today` — today's in-cycle events.
    * :meth:`get_average_incycle_dryback_today` — mean of today's in-cycle drybacks.
    * :meth:`get_measured_peak_trough` — current measured peak/trough/dryback for
      the steering score, derived from live pending state with no recorder reads.
    """

    def __init__(self, growspace: Growspace) -> None:
        """Initialize with a reference to a Growspace instance."""
        self.growspace = growspace
        # Tracks whether the last shot's peak is still rising (not yet settled).
        # Rebuilt lazily from persisted pending state, so it survives a restart
        # by simply assuming the persisted pending peak is already settled.
        self._peak_settling = False

    @property
    def _history(self) -> SubstrateHistory:
        """Return the persisted substrate history for this growspace."""
        return self.growspace.substrate_history

    # ── feeding ────────────────────────────────────────────────────────────────

    def record_shot(self, phase: str, timestamp: str, vwc: float) -> None:
        """Signal that an irrigation shot fired.

        ``phase`` is the steering phase that fired the shot ("P1" or "P2").
        Both phases bound the overnight window (the day's *last* shot of any
        phase); only P2 shots bound in-cycle drybacks.
        """
        history = self._history
        day = _local_date(timestamp)

        # ── Overnight: a shot whose day is later than the pending peak's day
        # closes the prior day's window (shot-to-shot, crossing midnight). The
        # trough is the minimum VWC accumulated since the prior day's last shot
        # (or its lit-period max, on a zero-shot day) up to this moment. ──
        pending_peak_day = (
            _local_date(history.pending_overnight_peak_ts)
            if history.pending_overnight_peak_ts
            else None
        )
        if (
            history.pending_overnight_peak is not None
            and pending_peak_day is not None
            and day != pending_peak_day
        ):
            # The pre-shot VWC is the freshest "minimum before the first shot",
            # so fold it into the trough before closing the overnight window.
            if (
                history.pending_overnight_trough is None
                or vwc < history.pending_overnight_trough
            ):
                history.pending_overnight_trough = vwc
                history.pending_overnight_trough_ts = timestamp
            self._close_overnight(history)

        # A shot also resets the lit-period max / counter for its own day.
        if history.current_day != day:
            history.current_day = day
            history.shots_today = 0
            history.lit_period_max = None
            history.lit_period_max_ts = None
        history.shots_today += 1

        # Re-arm overnight peak from this shot: the day's *last* shot wins because
        # every shot overwrites the pending peak with its own settling window.
        history.pending_overnight_peak = vwc
        history.pending_overnight_peak_ts = timestamp
        history.pending_overnight_trough = vwc
        history.pending_overnight_trough_ts = timestamp
        self._peak_settling = True

        # ── In-cycle: only P2 shots bound in-cycle drybacks. ──
        if phase == "P2":
            if history.pending_incycle_peak is not None:
                # Close the in-cycle window: trough is the pre-shot minimum, with
                # this shot's own pre-shot VWC folded in as the freshest value.
                trough = history.pending_incycle_trough
                trough_ts = history.pending_incycle_trough_ts
                if trough is None or vwc < trough:
                    trough = vwc
                    trough_ts = timestamp
                if trough is not None and trough_ts is not None:
                    self._append_event(
                        "in_cycle",
                        history.pending_incycle_peak,
                        history.pending_incycle_peak_ts or trough_ts,
                        trough,
                        trough_ts,
                    )
            # Re-arm in-cycle peak from this P2 shot.
            history.pending_incycle_peak = vwc
            history.pending_incycle_peak_ts = timestamp
            history.pending_incycle_trough = vwc
            history.pending_incycle_trough_ts = timestamp

    def record_reading(self, vwc: float, timestamp: str, *, lit: bool = True) -> None:
        """Feed one VWC reading from the steering minute loop.

        ``lit`` marks whether the lit period is active; the lit-period maximum
        is the zero-shot-day fallback for the overnight peak.
        """
        history = self._history
        day = _local_date(timestamp)

        if history.current_day is None:
            history.current_day = day
        elif day != history.current_day:
            self._roll_reading_day(history, day)

        # ── Lit-period max (zero-shot-day fallback) ──
        if lit and (history.lit_period_max is None or vwc > history.lit_period_max):
            history.lit_period_max = vwc
            history.lit_period_max_ts = timestamp

        # ── Overnight peak settling / trough tracking ──
        if history.pending_overnight_peak is not None:
            if self._peak_settling and vwc >= history.pending_overnight_peak:
                # Still rising after the last shot — extend the settled peak.
                history.pending_overnight_peak = vwc
                history.pending_overnight_peak_ts = timestamp
                history.pending_overnight_trough = vwc
                history.pending_overnight_trough_ts = timestamp
            else:
                # Peak has settled; track the running minimum (the trough).
                if vwc < history.pending_overnight_peak - SUBSTRATE_NOISE_FLOOR_PCT:
                    self._peak_settling = False
                if (
                    history.pending_overnight_trough is None
                    or vwc < history.pending_overnight_trough
                ):
                    history.pending_overnight_trough = vwc
                    history.pending_overnight_trough_ts = timestamp

        # ── In-cycle peak settling / trough tracking ──
        if history.pending_incycle_peak is not None:
            if vwc >= history.pending_incycle_peak and self._peak_settling:
                history.pending_incycle_peak = vwc
                history.pending_incycle_peak_ts = timestamp
                history.pending_incycle_trough = vwc
                history.pending_incycle_trough_ts = timestamp
            elif (
                history.pending_incycle_trough is None
                or vwc < history.pending_incycle_trough
            ):
                history.pending_incycle_trough = vwc
                history.pending_incycle_trough_ts = timestamp

    def record_pore_ec(self, ec: float, timestamp: str) -> None:
        """Feed one averaged pore-EC reading for the daily EC-trend.

        The first reading of a local day fixes the day-start baseline; every
        reading updates the latest value. Comparing baseline against latest
        (with a deadband, see :meth:`get_ec_trend`) yields the day's EC trend.
        State is persisted on ``SubstrateHistory`` so a mid-day restart resumes
        the same baseline instead of resetting it.

        ``ec`` is the average of the configured pore-EC sensors; callers skip
        unknown/unavailable/non-numeric sensor states before averaging, so this
        method only ever sees a valid measured value.
        """
        history = self._history
        day = _local_date(timestamp)

        if history.ec_trend_day != day:
            # New local day: re-baseline. (A sensor that drops out mid-day and
            # returns later keeps the same baseline because the day is unchanged.)
            history.ec_trend_day = day
            history.ec_day_start_value = ec
            history.ec_day_start_ts = timestamp

        history.ec_latest_value = ec
        history.ec_latest_ts = timestamp

    # ── day rollover ────────────────────────────────────────────────────────────

    def _roll_reading_day(self, history: SubstrateHistory, day: str) -> None:
        """Advance to a new calendar day during the reading stream.

        The overnight window is *not* closed here — it closes on the next day's
        first shot (shot-to-shot, crossing midnight). But the per-day lit-period
        max must reset. When the day being left had **zero shots**, its overnight
        peak is its lit-period maximum, so that value is promoted into the
        pending peak before the reset; the running trough then continues to
        accumulate into the new day until the first shot closes the window.
        """
        if history.shots_today == 0 and history.lit_period_max is not None:
            # Zero-shot day: the lit-period max becomes the overnight peak.
            if (
                history.pending_overnight_peak is None
                or history.lit_period_max > history.pending_overnight_peak
            ):
                history.pending_overnight_peak = history.lit_period_max
                history.pending_overnight_peak_ts = history.lit_period_max_ts
                history.pending_overnight_trough = history.lit_period_max
                history.pending_overnight_trough_ts = history.lit_period_max_ts
                self._peak_settling = False

        history.current_day = day
        history.shots_today = 0
        history.lit_period_max = None
        history.lit_period_max_ts = None

    def _close_overnight(self, history: SubstrateHistory) -> None:
        """Commit the prior day's overnight dryback event, if derivable.

        Called on the first shot of a new day. ``shots_today`` reflects the day
        being closed; a zero count means the peak already fell back to that day's
        lit-period max in :meth:`_roll_reading_day`.
        """
        peak = history.pending_overnight_peak
        if peak is None:
            self._clear_overnight_pending(history)
            return
        peak_ts = history.pending_overnight_peak_ts or ""
        trough = history.pending_overnight_trough
        trough_ts = history.pending_overnight_trough_ts or peak_ts
        if trough is None:
            trough = peak
            trough_ts = peak_ts

        self._append_event("overnight", peak, peak_ts, trough, trough_ts)
        self._clear_overnight_pending(history)

    @staticmethod
    def _clear_overnight_pending(history: SubstrateHistory) -> None:
        """Reset the overnight pending peak/trough state."""
        history.pending_overnight_peak = None
        history.pending_overnight_peak_ts = None
        history.pending_overnight_trough = None
        history.pending_overnight_trough_ts = None

    # ── event bookkeeping ───────────────────────────────────────────────────────

    def _append_event(
        self,
        event_type: str,
        peak: float,
        peak_ts: str,
        trough: float,
        trough_ts: str,
    ) -> None:
        """Append a dryback event and prune the rolling window."""
        dryback = round(peak - trough, 4)
        event: dict[str, Any] = {
            "event_type": event_type,
            "peak_timestamp": peak_ts,
            "trough_timestamp": trough_ts,
            "peak_vwc": round(peak, 4),
            "trough_vwc": round(trough, 4),
            "dryback": dryback,
        }
        history = self._history
        history.events.append(event)
        if len(history.events) > SUBSTRATE_MAX_EVENTS:
            history.events = history.events[-SUBSTRATE_MAX_EVENTS:]
        _LOGGER.debug(
            "SubstrateTracker(%s) recorded %s dryback: %.2f points (%.2f -> %.2f)",
            self.growspace.id,
            event_type,
            dryback,
            peak,
            trough,
        )

    # ── metric accessors ────────────────────────────────────────────────────────

    def get_latest_overnight_dryback(self) -> dict[str, Any] | None:
        """Return the most recent committed overnight dryback event, or None."""
        for event in reversed(self._history.events):
            if event["event_type"] == "overnight":
                return event
        return None

    def get_incycle_drybacks_today(
        self, reference_ts: str | None = None
    ) -> list[dict[str, Any]]:
        """Return today's committed in-cycle dryback events (local date)."""
        ref = (
            dt_util.as_local(_parse_ts(reference_ts)) if reference_ts else dt_util.now()
        )
        today = ref.date().isoformat()
        return [
            event
            for event in self._history.events
            if event["event_type"] == "in_cycle"
            and event["trough_timestamp"]
            and _local_date(event["trough_timestamp"]) == today
        ]

    def get_average_incycle_dryback_today(
        self, reference_ts: str | None = None
    ) -> float | None:
        """Return the mean of today's in-cycle drybacks, or None if there are none."""
        events = self.get_incycle_drybacks_today(reference_ts)
        if not events:
            return None
        return float(round(sum(e["dryback"] for e in events) / len(events), 4))

    def get_shot_count_today(self, reference_ts: str | None = None) -> int:
        """Return the number of P2 in-cycle dryback shot-pairs recorded today.

        This is the in-cycle event count for the day, which equals the number of
        completed shot-to-shot P2 intervals — a usable shots/day proxy for the
        steering score.
        """
        return len(self.get_incycle_drybacks_today(reference_ts))

    def get_measured_peak_trough(self) -> tuple[float, float, float] | None:
        """Return ``(peak_vwc, trough_vwc, dryback)`` for the steering score.

        Prefers the live in-flight overnight window (settled peak and running
        trough so far) so the score reflects today's actual dryback as it
        develops; falls back to the latest committed overnight event after a day
        rollover. Returns None when nothing measured is available yet, so the
        score path can decline to emit a synthetic value.
        """
        history = self._history
        if (
            history.pending_overnight_peak is not None
            and history.pending_overnight_trough is not None
        ):
            peak = history.pending_overnight_peak
            trough = history.pending_overnight_trough
            return (peak, trough, round(peak - trough, 4))

        latest = self.get_latest_overnight_dryback()
        if latest is not None:
            return (latest["peak_vwc"], latest["trough_vwc"], latest["dryback"])
        return None

    def get_ec_trend(self) -> dict[str, Any] | None:
        """Return the current day's pore-EC trend, or None when unavailable.

        Returns ``None`` when no pore-EC reading has been ingested yet (no
        sensors configured, or none have produced a valid value today) — the
        caller must treat this as *unavailable*, distinct from ``"stable"``, so
        the steering score's EC component stays neutral and the payload can flag
        the metric for the card's unlock hint.

        Otherwise returns a dict with the trend direction and its inputs::

            {
                "trend": "rising" | "stable" | "falling",
                "day_start_ec": float,   # earliest reading of the local day
                "current_ec": float,     # latest reading
                "delta": float,          # current - day_start (signed)
            }

        A ``delta`` whose magnitude is at or below
        :data:`SUBSTRATE_EC_TREND_DEADBAND` reads ``"stable"`` so noise does not
        flap the trend between rising and falling.
        """
        history = self._history
        start = history.ec_day_start_value
        current = history.ec_latest_value
        if start is None or current is None:
            return None

        delta = round(current - start, 4)
        if abs(delta) <= SUBSTRATE_EC_TREND_DEADBAND:
            trend = "stable"
        elif delta > 0:
            trend = "rising"
        else:
            trend = "falling"

        return {
            "trend": trend,
            "day_start_ec": round(start, 4),
            "current_ec": round(current, 4),
            "delta": delta,
        }
