"""Tests for TankWaterTracker."""
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from custom_components.growspace_manager.const import (
    TANK_MAX_EVENTS,
    TANK_MAX_SNAPSHOTS,
    TANK_REFILL_THRESHOLD_PCT,
)
from custom_components.growspace_manager.models import IrrigationTank
from custom_components.growspace_manager.tank_water_tracker import (
    _BUCKET_15MIN,
    TankWaterTracker,
    _fill_buckets,
    _parse_ts,
)


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


# ── _parse_ts: naive datetime gets UTC tzinfo ────────────────────────────────

def test_parse_ts_naive_datetime_gets_utc():
    """_parse_ts must attach UTC tzinfo to naive ISO-8601 strings."""
    dt = _parse_ts("2026-03-22T10:00:00")  # no tzinfo
    assert dt.tzinfo is not None
    assert dt.tzinfo == UTC


# ── edge cases: no reference_ts (uses datetime.now) ──────────────────────────

def test_get_history_24h_no_reference_ts_uses_now():
    """get_history_24h without reference_ts falls back to datetime.now."""
    t = _tracker()
    history = t.get_history_24h()  # reference_ts=None
    assert len(history) == 96


def test_get_history_7d_no_reference_ts_uses_now():
    """get_history_7d without reference_ts falls back to datetime.now."""
    t = _tracker()
    history = t.get_history_7d()  # reference_ts=None
    assert len(history) == 168


def test_get_total_liters_today_no_reference_ts():
    """get_total_liters_today without reference_ts uses datetime.now."""
    t = _tracker()
    t.record_level(60.0, "2026-03-22T08:00:00+00:00")
    t.record_level(55.0, "2026-03-22T10:00:00+00:00")  # 10 L consumption
    # With no reference_ts the method uses now; result may be 0 if "today" is
    # different, but the method must not raise.
    result = t.get_total_liters_today()
    assert isinstance(result, float)


def test_get_total_liters_7d_no_reference_ts():
    """get_total_liters_7d without reference_ts uses datetime.now."""
    t = _tracker()
    result = t.get_total_liters_7d()
    assert isinstance(result, (int, float))


# ── small positive change below refill threshold is ignored ──────────────────

def test_small_positive_change_below_refill_threshold_ignored():
    """A rise smaller than TANK_REFILL_THRESHOLD_PCT must not emit a refill event."""
    t = _tracker()
    t.record_level(50.0, "2026-03-22T10:00:00+00:00")
    # Rise exactly one tick below the refill threshold (above noise floor)
    small_rise = TANK_REFILL_THRESHOLD_PCT - 0.01
    t.record_level(50.0 + small_rise, "2026-03-22T10:05:00+00:00")
    assert t.tank.water_history.events == []


def test_partial_refill_updates_baseline_so_consumption_is_accurate():
    """Small top-ups below the refill threshold must still move last_recorded_level.

    Without this, a drop after a partial refill would be measured against the
    pre-refill baseline and under-report the actual consumption.
    """
    t = _tracker()  # 200 L tank
    t.record_level(50.0, "2026-03-22T10:00:00+00:00")  # baseline = 50%
    # Partial top-up: +2% (< 3% refill threshold) — no event, but baseline must advance
    t.record_level(52.0, "2026-03-22T11:00:00+00:00")
    assert t.tank.water_history.events == [], "partial refill must not emit an event"
    assert t.tank.last_recorded_level == pytest.approx(52.0), (
        "baseline must advance to the actual level after a partial top-up"
    )
    # Now a drop of 4% from 52% → 48% should record 4% * 200 L = 8 L, not 4 L
    t.record_level(48.0, "2026-03-22T12:00:00+00:00")
    assert len(t.tank.water_history.events) == 1
    ev = t.tank.water_history.events[0]
    assert ev["event_type"] == "consumption"
    assert ev["liters"] == pytest.approx(200.0 * 4.0 / 100.0)  # 8 L, not 4 L


# ── consumption event without volume_liters falls back to pct_delta ──────────

def test_consumption_without_volume_liters_uses_pct_delta():
    """When volume_liters is None the event liters field equals abs pct_delta."""
    tank = IrrigationTank(sensor_entity="sensor.tank", volume_liters=None)
    t = TankWaterTracker(tank)
    t.record_level(50.0, "2026-03-22T10:00:00+00:00")
    t.record_level(46.0, "2026-03-22T10:15:00+00:00")  # −4%
    ev = t.tank.water_history.events[0]
    assert ev["event_type"] == "consumption"
    assert ev["liters"] == pytest.approx(4.0)


def test_refill_without_volume_liters_uses_pct_delta():
    """When volume_liters is None the refill liters field equals abs pct_delta."""
    tank = IrrigationTank(sensor_entity="sensor.tank", volume_liters=None)
    t = TankWaterTracker(tank)
    t.record_level(40.0, "2026-03-22T10:00:00+00:00")
    t.record_level(80.0, "2026-03-22T11:00:00+00:00")  # +40%
    ev = t.tank.water_history.events[0]
    assert ev["event_type"] == "refill"
    assert ev["liters"] == pytest.approx(40.0)


# ── _fill_buckets edge cases ──────────────────────────────────────────────────

def test_fill_buckets_ignores_events_outside_range():
    """Events outside the bucket window must not appear in any bucket."""
    t = _tracker()
    # Record a consumption event far in the past (well outside 24h window)
    t.record_level(60.0, "2020-01-01T00:00:00+00:00")
    t.record_level(55.0, "2020-01-01T01:00:00+00:00")  # 10 L, ancient
    history = t.get_history_24h(reference_ts="2026-03-22T12:00:00+00:00")
    consumed = sum(b["liters_consumed"] for b in history)
    assert consumed == pytest.approx(0.0)


def test_fill_buckets_refill_in_bucket():
    """Refill events must accumulate in liters_refilled for the correct bucket."""
    t = _tracker()
    t.record_level(40.0, "2026-03-22T10:00:00+00:00")
    t.record_level(80.0, "2026-03-22T10:05:00+00:00")  # +40% refill = 80 L
    history = t.get_history_24h(reference_ts="2026-03-22T12:00:00+00:00")
    refilled = sum(b["liters_refilled"] for b in history)
    assert abs(refilled - 80.0) < 0.01


def test_fill_buckets_empty_buckets_list_is_safe():
    """_fill_buckets with an empty bucket list must not raise."""
    _fill_buckets([], [{"timestamp": "2026-03-22T10:00:00+00:00", "event_type": "consumption", "liters": 5.0}], _BUCKET_15MIN)


# ── HA subscription: async_setup / async_unsubscribe ─────────────────────────

@pytest.mark.asyncio
async def test_async_setup_subscribes_to_state_changes():
    """async_setup must register a state-change listener and return the unsub callable."""
    t = _tracker()
    hass = MagicMock()
    on_change = MagicMock()
    mock_unsub = MagicMock()

    with patch(
        "custom_components.growspace_manager.tank_water_tracker.async_track_state_change_event",
        return_value=mock_unsub,
    ) as mock_track:
        result = await t.async_setup(hass, on_change)

    mock_track.assert_called_once()
    assert result is mock_unsub


@pytest.mark.asyncio
async def test_async_unsubscribe_calls_unsub():
    """async_unsubscribe must call the stored unsub callable exactly once."""
    t = _tracker()
    hass = MagicMock()
    mock_unsub = MagicMock()

    with patch(
        "custom_components.growspace_manager.tank_water_tracker.async_track_state_change_event",
        return_value=mock_unsub,
    ):
        await t.async_setup(hass, MagicMock())

    await t.async_unsubscribe()
    mock_unsub.assert_called_once()
    assert t._unsub is None


@pytest.mark.asyncio
async def test_async_unsubscribe_safe_before_setup():
    """Calling async_unsubscribe before async_setup must not raise."""
    t = _tracker()
    await t.async_unsubscribe()  # Should not raise


@pytest.mark.asyncio
async def test_async_setup_records_level_on_state_change():
    """The state-change callback must record the level and call on_change."""
    t = _tracker()
    hass = MagicMock()
    on_change = MagicMock()
    captured: dict = {}

    def _fake_track(hass, entities, callback):
        captured["fn"] = callback
        return MagicMock()

    with patch(
        "custom_components.growspace_manager.tank_water_tracker.async_track_state_change_event",
        side_effect=_fake_track,
    ):
        await t.async_setup(hass, on_change)

    # Simulate a valid state-change event
    new_state = MagicMock()
    new_state.state = "75.5"
    new_state.last_updated = datetime(2026, 3, 22, 10, 0, 0, tzinfo=UTC)
    event = MagicMock()
    event.data = {"new_state": new_state}

    captured["fn"](event)

    assert len(t.tank.water_history.snapshots) == 1
    assert t.tank.water_history.snapshots[0]["level_pct"] == pytest.approx(75.5)
    on_change.assert_called_once()


@pytest.mark.asyncio
async def test_async_setup_ignores_none_new_state():
    """The callback must silently ignore events where new_state is None."""
    t = _tracker()
    hass = MagicMock()
    captured: dict = {}

    def _fake_track(hass, entities, callback):
        captured["fn"] = callback
        return MagicMock()

    with patch(
        "custom_components.growspace_manager.tank_water_tracker.async_track_state_change_event",
        side_effect=_fake_track,
    ):
        await t.async_setup(hass, MagicMock())

    event = MagicMock()
    event.data = {"new_state": None}
    captured["fn"](event)

    assert t.tank.water_history.snapshots == []


@pytest.mark.asyncio
async def test_async_setup_ignores_non_numeric_state():
    """The callback must silently ignore state values that are not numeric."""
    t = _tracker()
    hass = MagicMock()
    captured: dict = {}

    def _fake_track(hass, entities, callback):
        captured["fn"] = callback
        return MagicMock()

    with patch(
        "custom_components.growspace_manager.tank_water_tracker.async_track_state_change_event",
        side_effect=_fake_track,
    ):
        await t.async_setup(hass, MagicMock())

    bad_state = MagicMock()
    bad_state.state = "unavailable"
    bad_state.last_updated = datetime(2026, 3, 22, 10, 0, 0, tzinfo=UTC)
    event = MagicMock()
    event.data = {"new_state": bad_state}
    captured["fn"](event)

    assert t.tank.water_history.snapshots == []


@pytest.mark.asyncio
async def test_async_setup_on_change_not_called_when_none():
    """When on_change is None the callback must not raise."""
    t = _tracker()
    hass = MagicMock()
    captured: dict = {}

    def _fake_track(hass, entities, callback):
        captured["fn"] = callback
        return MagicMock()

    with patch(
        "custom_components.growspace_manager.tank_water_tracker.async_track_state_change_event",
        side_effect=_fake_track,
    ):
        await t.async_setup(hass, None)  # on_change=None

    new_state = MagicMock()
    new_state.state = "60.0"
    new_state.last_updated = datetime(2026, 3, 22, 10, 0, 0, tzinfo=UTC)
    event = MagicMock()
    event.data = {"new_state": new_state}

    captured["fn"](event)  # Must not raise even though on_change is None
    assert len(t.tank.water_history.snapshots) == 1
