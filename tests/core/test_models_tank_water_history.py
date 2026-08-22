"""Tests for TankWaterHistory and TankWaterEvent models."""

from custom_components.growspace_manager.models import (
    IrrigationTank,
    TankWaterEvent,
    TankWaterHistory,
)


def test_tank_water_event_defaults():
    event = TankWaterEvent()
    assert event.timestamp == ""
    assert event.liters == 0.0
    assert event.pct_delta == 0.0
    assert event.event_type == "consumption"


def test_tank_water_history_defaults():
    history = TankWaterHistory()
    assert history.snapshots == []
    assert history.events == []


def test_irrigation_tank_has_volume_and_history():
    tank = IrrigationTank(sensor_entity="sensor.tank_1")
    assert tank.volume_liters is None
    assert isinstance(tank.water_history, TankWaterHistory)


def test_irrigation_tank_roundtrip():
    """Serialisation via DataClassDictMixin must survive a round-trip."""
    tank = IrrigationTank(
        sensor_entity="sensor.tank_1",
        volume_liters=200.0,
    )
    d = tank.to_dict()
    tank2 = IrrigationTank.from_dict(d)
    assert tank2.volume_liters == 200.0
    assert isinstance(tank2.water_history, TankWaterHistory)
