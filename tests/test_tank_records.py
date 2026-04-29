from datetime import UTC, datetime

from custom_components.growspace_manager.models import IrrigationTank
from custom_components.growspace_manager.tank_water_tracker import TankWaterTracker


def test_refill_detection():
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


def test_consumption_detection():
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


def test_minor_refill_updates_baseline():
    """Verify that a minor refill (below 3%) updates the baseline for accurate future consumption.

    Since the noise floor is 1.0%, a 1% rise is treated as a baseline adjustment rather
    than a formal refill event. Subsequent consumption is measured from the updated baseline.
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

    # Baseline advances to the new actual level
    assert tank.last_recorded_level == 51.0

    # A 1% drop from the updated baseline (51.0 → 50.0) is detected as consumption
    tracker.record_level(50.0, ts)
    events = [e for e in tank.water_history.events if e["event_type"] == "consumption"]
    assert len(events) == 1
    assert round(events[0]["pct_delta"], 1) == -1.0
