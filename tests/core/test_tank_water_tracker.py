"""Tests for TankWaterTracker."""
import pytest

from custom_components.growspace_manager.const import (
    TANK_MAX_EVENTS,
    TANK_MAX_SNAPSHOTS,
)
from custom_components.growspace_manager.models import IrrigationTank
from custom_components.growspace_manager.tank_water_tracker import TankWaterTracker


def _make_tank(volume: float = 200.0) -> IrrigationTank:
    return IrrigationTank(sensor_entity="sensor.tank", volume_liters=volume)


def _tracker(tank: IrrigationTank | None = None) -> TankWaterTracker:
    if tank is None:
        tank = _make_tank()
    return TankWaterTracker(tank)


# ── snapshot recording ────────────────────────────────────────────────────────

def test_record_first_snapshot_no_event():
    """First reading produces a snapshot but no event (no previous level)."""
    t = _tracker()
    t.record_level(50.0, "2026-03-22T10:00:00+00:00")
    assert len(t.tank.water_history.snapshots) == 1
    assert t.tank.water_history.events == []


def test_consumption_event_recorded():
    t = _tracker()
    t.record_level(50.0, "2026-03-22T10:00:00+00:00")
    t.record_level(48.0, "2026-03-22T10:15:00+00:00")
    events = t.tank.water_history.events
    assert len(events) == 1
    ev = events[0]
    assert ev["event_type"] == "consumption"
    assert abs(ev["liters"] - 200.0 * 2.0 / 100.0) < 0.01   # 4 L
    assert ev["pct_delta"] == pytest.approx(-2.0)


def test_refill_event_recorded():
    t = _tracker()
    t.record_level(40.0, "2026-03-22T10:00:00+00:00")
    t.record_level(80.0, "2026-03-22T11:00:00+00:00")
    events = t.tank.water_history.events
    assert len(events) == 1
    assert events[0]["event_type"] == "refill"
    assert abs(events[0]["liters"] - 200.0 * 40.0 / 100.0) < 0.01   # 80 L


def test_noise_below_floor_ignored():
    t = _tracker()
    t.record_level(50.0, "2026-03-22T10:00:00+00:00")
    t.record_level(50.2, "2026-03-22T10:05:00+00:00")  # +0.2% — below floor
    assert t.tank.water_history.events == []


def test_rolling_snapshot_window_enforced():
    t = _tracker()
    # Override on the history object itself
    t.tank.water_history.snapshots = []  # ensure empty
    # Use TANK_MAX_SNAPSHOTS constant and push over the limit
    for i in range(TANK_MAX_SNAPSHOTS + 5):
        t.record_level(float(50 - (i % 10)), f"2026-03-22T{i % 24:02d}:00:00+00:00")
    assert len(t.tank.water_history.snapshots) == TANK_MAX_SNAPSHOTS


def test_rolling_event_window_enforced():
    t = _tracker()
    # Generate many consumption events (alternating 50/45 -> 5% drops each pair)
    for i in range(TANK_MAX_EVENTS + 10):
        t.record_level(50.0, f"2026-03-22T00:{i % 60:02d}:00+00:00")
        t.record_level(45.0, f"2026-03-22T00:{i % 60:02d}:30+00:00")
    assert len(t.tank.water_history.events) == TANK_MAX_EVENTS


# ── aggregation helpers ───────────────────────────────────────────────────────

def test_get_history_24h_returns_96_buckets():
    """Returns 96 15-minute buckets for the last 24 hours."""
    t = _tracker()
    history = t.get_history_24h(reference_ts="2026-03-22T12:00:00+00:00")
    assert len(history) == 96
    for bucket in history:
        assert "bucket_start" in bucket
        assert "liters_consumed" in bucket
        assert "liters_refilled" in bucket


def test_get_history_7d_returns_168_buckets():
    """Returns 168 hourly buckets for the last 7 days."""
    t = _tracker()
    history = t.get_history_7d(reference_ts="2026-03-22T12:00:00+00:00")
    assert len(history) == 168
    for bucket in history:
        assert "bucket_start" in bucket
        assert "liters_consumed" in bucket


def test_total_liters_today():
    t = _tracker()
    t.record_level(60.0, "2026-03-22T08:00:00+00:00")
    t.record_level(55.0, "2026-03-22T10:00:00+00:00")  # −5% = 10 L
    t.record_level(53.0, "2026-03-22T12:00:00+00:00")  # −2% = 4 L
    total = t.get_total_liters_today(reference_ts="2026-03-22T12:00:00+00:00")
    assert abs(total - 14.0) < 0.01


def test_total_liters_7d():
    t = _tracker()
    t.record_level(60.0, "2026-03-16T08:00:00+00:00")
    t.record_level(55.0, "2026-03-16T10:00:00+00:00")  # 10 L
    t.record_level(70.0, "2026-03-18T08:00:00+00:00")  # refill — not consumption
    t.record_level(65.0, "2026-03-20T08:00:00+00:00")  # 10 L
    total = t.get_total_liters_7d(reference_ts="2026-03-22T12:00:00+00:00")
    assert abs(total - 20.0) < 0.01


def test_consumption_placed_in_correct_bucket():
    """Verify that a consumption event lands in the expected 15-min bucket."""
    t = _tracker()
    # 10:00 snapshot, 10:12 drop → should land in the 10:00-10:15 bucket
    t.record_level(50.0, "2026-03-22T10:00:00+00:00")
    t.record_level(48.0, "2026-03-22T10:12:00+00:00")  # 4 L consumption
    history = t.get_history_24h(reference_ts="2026-03-22T12:00:00+00:00")
    consumed = sum(b["liters_consumed"] for b in history)
    assert abs(consumed - 4.0) < 0.01
