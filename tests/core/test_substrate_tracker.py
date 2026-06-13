"""Tests for the SubstrateTracker.

Drives the tracker with plain ``(timestamp, vwc, ...)`` sequences — no recorder
fixtures — to exercise overnight + in-cycle dryback detection, the zero-shot-day
fallback, restart resumption, and sensor dropout (see ADR-0010).
"""

from __future__ import annotations

from custom_components.growspace_manager.const import SUBSTRATE_MAX_EVENTS
from custom_components.growspace_manager.models import Growspace, SubstrateHistory
from custom_components.growspace_manager.substrate_tracker import SubstrateTracker

# Local-midnight-anchored timestamps. The test HA timezone is UTC, so local date
# equals the UTC date for these.
DAY1 = "2026-03-22"
DAY2 = "2026-03-23"


def _ts(day: str, hour: int, minute: int = 0) -> str:
    """Build an ISO-8601 UTC timestamp on a given day."""
    return f"{day}T{hour:02d}:{minute:02d}:00+00:00"


def _tracker(growspace: Growspace | None = None) -> SubstrateTracker:
    if growspace is None:
        growspace = Growspace(id="tent1", name="Tent 1")
    return SubstrateTracker(growspace)


# ── overnight dryback (normal day) ──────────────────────────────────────────────


def test_overnight_dryback_shot_to_shot() -> None:
    """Overnight dryback runs from the day's last shot peak to the next day's first-shot trough."""
    t = _tracker()

    # Day 1: lights on, an early shot, then the day's LAST shot at 16:00.
    t.record_reading(40.0, _ts(DAY1, 6), lit=True)
    t.record_shot("P2", _ts(DAY1, 8), 42.0)
    # settled peak rises to 58 after the 8:00 shot
    t.record_reading(58.0, _ts(DAY1, 9), lit=True)
    t.record_reading(50.0, _ts(DAY1, 12), lit=True)
    # Day's last shot at 16:00 (well before lights-off — Auto-Advance style).
    t.record_shot("P2", _ts(DAY1, 16), 48.0)
    # Settle to a peak of 60 after the last shot.
    t.record_reading(60.0, _ts(DAY1, 17), lit=True)
    # Dryback overnight: VWC falls into the dark period.
    t.record_reading(52.0, _ts(DAY1, 20), lit=False)
    t.record_reading(45.0, _ts(DAY1, 23), lit=False)
    t.record_reading(40.0, _ts(DAY2, 3), lit=False)
    # Day 2 first shot at 8:00 closes the overnight window.
    t.record_shot("P2", _ts(DAY2, 8), 39.0)

    latest = t.get_latest_overnight_dryback()
    assert latest is not None
    assert latest["peak_vwc"] == 60.0
    assert latest["trough_vwc"] == 39.0
    # Absolute VWC points: 60 - 39 = 21.0
    assert latest["dryback"] == 21.0


def test_overnight_peak_is_the_last_shot_not_earlier_shots() -> None:
    """A higher earlier-shot peak does not win — the day's LAST shot bounds the window."""
    t = _tracker()
    t.record_shot("P2", _ts(DAY1, 8), 50.0)
    t.record_reading(70.0, _ts(DAY1, 9), lit=True)  # high early peak
    t.record_shot("P2", _ts(DAY1, 16), 55.0)  # last shot
    t.record_reading(60.0, _ts(DAY1, 17), lit=True)  # lower settled peak
    t.record_reading(40.0, _ts(DAY1, 23), lit=False)
    t.record_shot("P2", _ts(DAY2, 8), 39.0)

    latest = t.get_latest_overnight_dryback()
    assert latest is not None
    assert latest["peak_vwc"] == 60.0  # last shot's settled peak, not 70


# ── zero-shot day fallback ──────────────────────────────────────────────────────


def test_zero_shot_day_falls_back_to_lit_period_max() -> None:
    """On a day with zero shots the overnight peak is the lit-period maximum."""
    t = _tracker()
    # Day 1: NO shots, just lit readings. Max lit VWC is 52.
    t.record_reading(48.0, _ts(DAY1, 7), lit=True)
    t.record_reading(52.0, _ts(DAY1, 10), lit=True)
    t.record_reading(50.0, _ts(DAY1, 14), lit=True)
    t.record_reading(46.0, _ts(DAY1, 20), lit=False)
    t.record_reading(41.0, _ts(DAY2, 2), lit=False)
    # Day 2 first shot closes the zero-shot overnight window.
    t.record_shot("P2", _ts(DAY2, 8), 40.0)

    latest = t.get_latest_overnight_dryback()
    assert latest is not None
    assert latest["peak_vwc"] == 52.0  # lit-period max
    assert latest["trough_vwc"] == 40.0
    assert latest["dryback"] == 12.0


# ── in-cycle drybacks ───────────────────────────────────────────────────────────


def test_in_cycle_drybacks_between_p2_shots() -> None:
    """Each consecutive P2 shot pair yields one in-cycle dryback."""
    t = _tracker()
    t.record_shot("P2", _ts(DAY1, 10), 55.0)
    t.record_reading(58.0, _ts(DAY1, 10, 5), lit=True)  # settled peak
    t.record_reading(50.0, _ts(DAY1, 10, 40), lit=True)  # trough before next
    t.record_shot("P2", _ts(DAY1, 11), 50.0)  # closes first in-cycle
    t.record_reading(57.0, _ts(DAY1, 11, 5), lit=True)
    t.record_reading(49.0, _ts(DAY1, 11, 45), lit=True)
    t.record_shot("P2", _ts(DAY1, 12), 49.0)  # closes second in-cycle

    incycle = t.get_incycle_drybacks_today(reference_ts=_ts(DAY1, 12))
    assert len(incycle) == 2
    # First: peak 58, trough 50 → 8.0
    assert incycle[0]["dryback"] == 8.0
    # Second: peak 57, trough 49 → 8.0
    assert incycle[1]["dryback"] == 8.0
    avg = t.get_average_incycle_dryback_today(reference_ts=_ts(DAY1, 12))
    assert avg == 8.0
    assert t.get_shot_count_today(reference_ts=_ts(DAY1, 12)) == 2


def test_p1_shots_do_not_create_in_cycle_drybacks() -> None:
    """Only P2 shots bound in-cycle drybacks; P1 ramp-up shots do not."""
    t = _tracker()
    t.record_shot("P1", _ts(DAY1, 6), 40.0)
    t.record_reading(50.0, _ts(DAY1, 6, 10), lit=True)
    t.record_shot("P1", _ts(DAY1, 6, 20), 48.0)
    assert t.get_incycle_drybacks_today(reference_ts=_ts(DAY1, 7)) == []


# ── restart mid-window ──────────────────────────────────────────────────────────


def test_restart_resumes_pending_overnight_window() -> None:
    """A pending peak awaiting its trough survives a restart and resolves correctly."""
    growspace = Growspace(id="tent1", name="Tent 1")
    t1 = _tracker(growspace)

    # Day 1 last shot + settled peak, then VWC starts dropping.
    t1.record_shot("P2", _ts(DAY1, 16), 50.0)
    t1.record_reading(60.0, _ts(DAY1, 17), lit=True)  # settled peak 60
    t1.record_reading(54.0, _ts(DAY1, 20), lit=False)

    # Serialize as the storage layer would, then deserialize (simulated restart).
    serialized = growspace.to_dict()
    restored = Growspace.from_dict(serialized)
    assert restored.substrate_history.pending_overnight_peak == 60.0
    assert restored.substrate_history.pending_overnight_trough == 54.0

    # A fresh tracker resumes from the restored history.
    t2 = SubstrateTracker(restored)
    t2.record_reading(42.0, _ts(DAY2, 3), lit=False)  # new running minimum
    t2.record_shot("P2", _ts(DAY2, 8), 41.0)  # closes overnight

    latest = t2.get_latest_overnight_dryback()
    assert latest is not None
    assert latest["peak_vwc"] == 60.0
    # The next-day first shot's pre-shot VWC (41) is the freshest, lowest trough.
    assert latest["trough_vwc"] == 41.0
    assert latest["dryback"] == 19.0


# ── sensor dropout ──────────────────────────────────────────────────────────────


def test_sensor_dropout_does_not_corrupt_window() -> None:
    """A gap in readings (sensor dropout) leaves the pending window intact."""
    t = _tracker()
    t.record_shot("P2", _ts(DAY1, 16), 50.0)
    t.record_reading(60.0, _ts(DAY1, 17), lit=True)  # settled peak
    # Sensor drops out 18:00-22:00: the loop simply records no readings.
    t.record_reading(44.0, _ts(DAY1, 22), lit=False)  # back online, lower
    t.record_shot("P2", _ts(DAY2, 8), 43.0)

    latest = t.get_latest_overnight_dryback()
    assert latest is not None
    assert latest["peak_vwc"] == 60.0
    assert latest["trough_vwc"] == 43.0  # next-day first shot is the final trough


def test_no_events_before_any_window_closes() -> None:
    """No overnight event exists until a window actually closes."""
    t = _tracker()
    t.record_shot("P2", _ts(DAY1, 8), 50.0)
    t.record_reading(55.0, _ts(DAY1, 9), lit=True)
    assert t.get_latest_overnight_dryback() is None
    assert t.get_measured_peak_trough() is not None  # live pending window


# ── measured peak/trough for the steering score ─────────────────────────────────


def test_measured_peak_trough_prefers_live_window() -> None:
    """get_measured_peak_trough reflects the in-flight overnight window."""
    t = _tracker()
    t.record_shot("P2", _ts(DAY1, 16), 50.0)
    t.record_reading(60.0, _ts(DAY1, 17), lit=True)
    t.record_reading(48.0, _ts(DAY1, 22), lit=False)

    measured = t.get_measured_peak_trough()
    assert measured is not None
    peak, trough, dryback = measured
    assert peak == 60.0
    assert trough == 48.0
    assert dryback == 12.0


def test_measured_peak_trough_none_when_no_data() -> None:
    """Returns None when no measured window or event exists yet."""
    t = _tracker()
    assert t.get_measured_peak_trough() is None


# ── rolling window bound ────────────────────────────────────────────────────────


def test_event_history_is_bounded() -> None:
    """The rolling event history never exceeds SUBSTRATE_MAX_EVENTS."""
    growspace = Growspace(id="tent1", name="Tent 1")
    history: SubstrateHistory = growspace.substrate_history
    history.events = [
        {
            "event_type": "in_cycle",
            "peak_timestamp": _ts(DAY1, 10),
            "trough_timestamp": _ts(DAY1, 11),
            "peak_vwc": 55.0,
            "trough_vwc": 50.0,
            "dryback": 5.0,
        }
        for _ in range(SUBSTRATE_MAX_EVENTS)
    ]
    t = SubstrateTracker(growspace)
    # Two more P2 shots commit one new in-cycle event, triggering the prune.
    t.record_shot("P2", _ts(DAY1, 12), 50.0)
    t.record_reading(55.0, _ts(DAY1, 12, 5), lit=True)
    t.record_reading(49.0, _ts(DAY1, 12, 45), lit=True)
    t.record_shot("P2", _ts(DAY1, 13), 49.0)
    assert len(history.events) == SUBSTRATE_MAX_EVENTS
