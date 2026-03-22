"""Tests for TankDerivedWaterSensor."""
from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    IrrigationTank,
)
from custom_components.growspace_manager.sensor import (
    TankDerivedWaterSensor,
    _should_create_derived_water_sensor,
)


def _make_coordinator(volume: float = 200.0, flow_sensors=None, drain_sensors=None):
    tank = IrrigationTank(sensor_entity="sensor.tank_1", volume_liters=volume)
    env = EnvironmentConfig(
        irrigation_tanks=[tank],
        irrigation_flow_sensors=flow_sensors or [],
        drain_volume_sensors=drain_sensors or [],
    )
    growspace = Growspace(id="gs_1", name="Test", environment_config=env)
    coordinator = MagicMock()
    coordinator.last_update_success = True
    tracker = MagicMock()
    tracker.get_total_liters_today.return_value = 8.5
    tracker.get_total_liters_7d.return_value = 42.0
    tracker.get_history_24h.return_value = []
    tracker.get_history_7d.return_value = []
    tracker.tank.water_history.events = []
    coordinator.get_tank_tracker.return_value = tracker
    return coordinator, growspace, tank


def test_native_value_liters_today():
    coordinator, growspace, tank = _make_coordinator()
    sensor = TankDerivedWaterSensor(coordinator, "gs_1", tank)
    assert sensor.native_value == pytest.approx(8.5)


def test_extra_attrs_keys():
    coordinator, growspace, tank = _make_coordinator()
    sensor = TankDerivedWaterSensor(coordinator, "gs_1", tank)
    attrs = sensor.extra_state_attributes
    assert "liters_today" in attrs
    assert "liters_7d" in attrs
    assert "history_24h" in attrs
    assert "history_7d" in attrs
    assert "volume_liters" in attrs
    assert attrs["volume_liters"] == 200.0


def test_unique_id_format():
    coordinator, growspace, tank = _make_coordinator()
    sensor = TankDerivedWaterSensor(coordinator, "gs_1", tank)
    assert "gs_1" in sensor.unique_id
    assert "tank_derived_water" in sensor.unique_id
    assert "tank_1" in sensor.unique_id  # from sensor entity name


def test_unavailable_when_tracker_none():
    coordinator, growspace, tank = _make_coordinator()
    coordinator.get_tank_tracker.return_value = None
    sensor = TankDerivedWaterSensor(coordinator, "gs_1", tank)
    assert sensor.available is False
    assert sensor.native_value is None


def test_should_create_when_no_flow_or_drain_sensors():
    coordinator, growspace, tank = _make_coordinator()
    assert _should_create_derived_water_sensor(growspace, tank) is True


def test_should_not_create_when_flow_sensors_present():
    coordinator, growspace, tank = _make_coordinator(flow_sensors=["sensor.flow"])
    assert _should_create_derived_water_sensor(growspace, tank) is False


def test_should_not_create_when_drain_sensors_present():
    coordinator, growspace, tank = _make_coordinator(drain_sensors=["sensor.drain"])
    assert _should_create_derived_water_sensor(growspace, tank) is False


def test_should_not_create_when_no_volume():
    tank = IrrigationTank(sensor_entity="sensor.t", volume_liters=None)
    env = EnvironmentConfig(irrigation_tanks=[tank])
    growspace = Growspace(id="g1", name="G", environment_config=env)
    assert _should_create_derived_water_sensor(growspace, tank) is False
