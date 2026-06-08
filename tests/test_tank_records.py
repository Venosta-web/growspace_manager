from datetime import UTC, datetime, timedelta

from custom_components.growspace_manager.models import IrrigationTank
from custom_components.growspace_manager.tank_water_tracker import TankWaterTracker


def test_refill_detection() -> None:
    """Verify that a single jump >= 3% is classified as a refill event."""
    tank = IrrigationTank(sensor_entity="sensor.test_tank", volume_liters=100.0)
    tracker = TankWaterTracker(tank)

    ts = datetime.now(tz=UTC).isoformat()
    tracker.record_level(50.0, ts)
    assert tank.last_recorded_level == 50.0

    # Single reading crosses the 3% refill threshold
    tracker.record_level(53.0, ts)

    events = tank.water_history.events
    assert len(events) >= 1
    refill_event = [e for e in events if e["event_type"] == "refill"][0]
    assert refill_event["pct_delta"] == 3.0
    assert tank.last_recorded_level == 53.0


def test_consumption_detection() -> None:
    """Verify that drops >= 1% (noise floor) are recorded as consumption events."""
    tank = IrrigationTank(sensor_entity="sensor.test_tank", volume_liters=100.0)
    tracker = TankWaterTracker(tank)

    ts = datetime.now(tz=UTC).isoformat()
    tracker.record_level(50.0, ts)

    # Three 1% drops: noise floor is 1.0%
    for i in range(1, 4):
        tracker.record_level(50.0 - i, ts)

    events = [e for e in tank.water_history.events if e["event_type"] == "consumption"]
    assert len(events) == 3
    for ev in events:
        assert round(ev["pct_delta"], 1) == -1.0

    assert tank.last_recorded_level == 47.0


def test_minor_refill_updates_peak_after_confirmation() -> None:
    """Verify that a minor refill (below 3%) advances the consumption baseline
    (peak_level) once a second reading confirms the level is stable.

    The trough baseline (last_recorded_level) is preserved so that cumulative rises
    can still accumulate toward the 3% refill threshold.  A single-reading spike that
    immediately reverts to the trough zone is discarded (no false consumption).
    """
    tank = IrrigationTank(sensor_entity="sensor.test_tank", volume_liters=100.0)
    tracker = TankWaterTracker(tank)

    ts = datetime.now(tz=UTC).isoformat()
    tracker.record_level(50.0, ts)

    # Add 1% water (below 3% refill threshold, but >= 1% noise floor)
    tracker.record_level(51.0, ts)

    # No refill event — rise is below refill threshold
    events = [e for e in tank.water_history.events if e["event_type"] == "refill"]
    assert len(events) == 0
    # Trough baseline (last_recorded_level) must NOT advance — preserved for refill accumulation
    assert tank.last_recorded_level == 50.0

    # Second reading at the same level confirms the peak
    tracker.record_level(51.0, ts)
    assert tank.peak_level == 51.0

    # A 1% drop from the confirmed peak (51.0 → 50.0) is detected as consumption
    tracker.record_level(50.0, ts)
    events = [e for e in tank.water_history.events if e["event_type"] == "consumption"]
    assert len(events) == 1
    assert round(events[0]["pct_delta"], 1) == -1.0


def test_sequential_refill_grouping() -> None:
    """Verify that multiple refill steps within a 10-minute window are grouped."""
    tank = IrrigationTank(sensor_entity="sensor.test_tank", volume_liters=100.0)
    tracker = TankWaterTracker(tank)

    base_ts = datetime.now(tz=UTC)

    # Initial level
    tracker.record_level(50.0, base_ts.isoformat())

    # First refill step (3% rise)
    step1_ts = base_ts + timedelta(seconds=30)
    tracker.record_level(53.0, step1_ts.isoformat())

    # Second refill step (4% rise)
    step2_ts = step1_ts + timedelta(seconds=45)
    tracker.record_level(57.0, step2_ts.isoformat())

    refill_events = [
        e for e in tank.water_history.events if e["event_type"] == "refill"
    ]
    assert len(refill_events) == 1
    assert refill_events[0]["liters"] == 7.0
    assert refill_events[0]["pct_delta"] == 7.0


def test_sequential_refill_no_grouping_outside_window() -> None:
    """Verify that refill steps > 10 minutes apart are NOT grouped."""
    tank = IrrigationTank(sensor_entity="sensor.test_tank", volume_liters=100.0)
    tracker = TankWaterTracker(tank)

    base_ts = datetime.now(tz=UTC)

    # Initial level
    tracker.record_level(50.0, base_ts.isoformat())

    # First refill step (3% rise)
    step1_ts = base_ts + timedelta(seconds=30)
    tracker.record_level(53.0, step1_ts.isoformat())

    # Second refill step (4% rise) 11 minutes later
    step2_ts = step1_ts + timedelta(minutes=11)
    tracker.record_level(57.0, step2_ts.isoformat())

    refill_events = [
        e for e in tank.water_history.events if e["event_type"] == "refill"
    ]
    assert len(refill_events) == 2
    assert refill_events[0]["pct_delta"] == 3.0
    assert refill_events[1]["pct_delta"] == 4.0
