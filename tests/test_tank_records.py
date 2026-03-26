from datetime import UTC, datetime

from custom_components.growspace_manager.models import IrrigationTank
from custom_components.growspace_manager.tank_water_tracker import TankWaterTracker


def test_gradual_refill_detection():
    """Verify that multiple small increments cross the refill threshold."""
    tank = IrrigationTank(sensor_entity="sensor.test_tank", volume_liters=100.0)
    tracker = TankWaterTracker(tank)

    ts = datetime.now(tz=UTC).isoformat()
    # Initial level 50.0
    tracker.record_level(50.0, ts)
    assert tank.last_recorded_level == 50.0

    # Simulate gradual increase: 0.1% steps up to 53.5% (total 3.5% delta)
    # Refill threshold is 3.0%
    for i in range(1, 36):
        level = round(50.0 + (i * 0.1), 1)
        tracker.record_level(level, ts)

    # At i=30, level=53.0, delta=3.0. Should trigger refill.
    # At i=35, level=53.5, delta=0.5 from new baseline?
    # Wait, once refill is triggered, baseline resets to 53.0.

    events = tank.water_history.events
    assert len(events) >= 1
    refill_event = [e for e in events if e["event_type"] == "refill"][0]
    assert refill_event["pct_delta"] == 3.0
    assert tank.last_recorded_level == 53.0


def test_gradual_consumption_detection():
    """Verify that multiple small decrements cross the noise floor for consumption."""
    tank = IrrigationTank(sensor_entity="sensor.test_tank", volume_liters=100.0)
    tracker = TankWaterTracker(tank)

    ts = datetime.now(tz=UTC).isoformat()
    tracker.record_level(50.0, ts)

    # Noise floor is 0.3%
    # 0.1% steps down to 49.0% (total 1.0% drop)
    for i in range(1, 11):
        level = round(50.0 - (i * 0.1), 1)
        tracker.record_level(level, ts)

    # Should trigger consumption at 49.7, 49.4, 49.1
    events = [e for e in tank.water_history.events if e["event_type"] == "consumption"]
    assert len(events) == 3
    for ev in events:
        assert round(ev["pct_delta"], 1) == -0.3

    assert tank.last_recorded_level == 49.1


def test_small_refill_ignored():
    """Verify that refills below the 3.0% threshold are currently ignored as noise."""
    tank = IrrigationTank(sensor_entity="sensor.test_tank", volume_liters=100.0)
    tracker = TankWaterTracker(tank)

    ts = datetime.now(tz=UTC).isoformat()
    tracker.record_level(50.0, ts)

    # Add 1% water (below 3% threshold)
    tracker.record_level(51.0, ts)

    # No refill event should be created
    events = [e for e in tank.water_history.events if e["event_type"] == "refill"]
    assert len(events) == 0
    # Baseline should NOT update
    assert tank.last_recorded_level == 50.0

    # Now consume 0.3% (dropping from 51.0 to 50.7)
    # Relative to baseline 50.0, this is still a net +0.7%
    tracker.record_level(50.7, ts)
    events = [e for e in tank.water_history.events if e["event_type"] == "consumption"]
    assert len(events) == 0

    # Now drop to 49.7 (net -0.3% from baseline 50.0)
    tracker.record_level(49.7, ts)
    events = [e for e in tank.water_history.events if e["event_type"] == "consumption"]
    assert len(events) == 1
    assert round(events[0]["pct_delta"], 1) == -0.3
