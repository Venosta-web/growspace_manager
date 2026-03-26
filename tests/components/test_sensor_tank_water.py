"""Tests for TankDerivedWaterSensor."""

from unittest.mock import AsyncMock, MagicMock, patch

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
from homeassistant.helpers.update_coordinator import CoordinatorEntity


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
    coordinator.get_tank_tracker.return_value = tracker
    return coordinator, growspace, tank


def test_native_value_liters_today():
    coordinator, _, tank = _make_coordinator()
    sensor = TankDerivedWaterSensor(coordinator, "gs_1", tank)
    assert sensor.native_value == pytest.approx(8.5)


def test_extra_attrs_keys():
    coordinator, _, tank = _make_coordinator()
    sensor = TankDerivedWaterSensor(coordinator, "gs_1", tank)
    attrs = sensor.extra_state_attributes
    assert "liters_today" in attrs
    assert "liters_7d" in attrs
    assert "volume_liters" in attrs
    assert attrs["volume_liters"] == 200.0


def test_unique_id_format():
    coordinator, _, tank = _make_coordinator()
    sensor = TankDerivedWaterSensor(coordinator, "gs_1", tank)
    assert "gs_1" in sensor.unique_id
    assert "tank_derived_water" in sensor.unique_id
    assert "tank_1" in sensor.unique_id  # from sensor entity name


def test_unavailable_when_tracker_none():
    coordinator, _, tank = _make_coordinator()
    coordinator.get_tank_tracker.return_value = None
    sensor = TankDerivedWaterSensor(coordinator, "gs_1", tank)
    assert sensor.available is False
    assert sensor.native_value is None


def test_should_create_when_no_flow_or_drain_sensors():
    _, growspace, tank = _make_coordinator()
    assert _should_create_derived_water_sensor(growspace, tank) is True


def test_should_not_create_when_flow_sensors_present():
    _, growspace, tank = _make_coordinator(flow_sensors=["sensor.flow"])
    assert _should_create_derived_water_sensor(growspace, tank) is False


def test_should_not_create_when_drain_sensors_present():
    _, growspace, tank = _make_coordinator(drain_sensors=["sensor.drain"])
    assert _should_create_derived_water_sensor(growspace, tank) is False


def test_should_not_create_when_no_volume():
    tank = IrrigationTank(sensor_entity="sensor.t", volume_liters=None)
    env = EnvironmentConfig(irrigation_tanks=[tank])
    growspace = Growspace(id="g1", name="G", environment_config=env)
    assert _should_create_derived_water_sensor(growspace, tank) is False


def test_extra_state_attributes_tracker_none():
    """Test extra_state_attributes returns {} when tracker is None (sensor.py:787)."""
    coordinator, _, tank = _make_coordinator()
    coordinator.get_tank_tracker.return_value = None
    sensor = TankDerivedWaterSensor(coordinator, "gs_1", tank)
    assert sensor.extra_state_attributes == {}


@pytest.mark.asyncio
async def test_async_added_to_hass_tracker_none():
    """Test async_added_to_hass returns early when tracker is None (sensor.py:801-806)."""
    coordinator, _, tank = _make_coordinator()
    coordinator.get_tank_tracker.return_value = None
    sensor = TankDerivedWaterSensor(coordinator, "gs_1", tank)

    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        await sensor.async_added_to_hass()

    # get_tank_tracker was called and returned None, so early return happened
    coordinator.get_tank_tracker.assert_called_once_with("gs_1", "sensor.tank_1")


@pytest.mark.asyncio
async def test_async_added_to_hass_with_tracker():
    """Test async_added_to_hass registers unsub when tracker is available (sensor.py:808-812)."""
    coordinator, _, tank = _make_coordinator()
    tracker = MagicMock()
    unsub = MagicMock()
    tracker.async_setup = AsyncMock(return_value=unsub)
    coordinator.get_tank_tracker.return_value = tracker
    sensor = TankDerivedWaterSensor(coordinator, "gs_1", tank)
    sensor.async_on_remove = MagicMock()

    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        await sensor.async_added_to_hass()

    tracker.async_setup.assert_awaited_once()
    sensor.async_on_remove.assert_called_once_with(unsub)


@pytest.mark.asyncio
async def test_async_added_to_hass_on_change_invokes_schedule():
    """Test the _on_change callback triggers schedule_update_ha_state (sensor.py:809)."""
    coordinator, _, tank = _make_coordinator()
    captured: list = []

    async def fake_async_setup(hass, callback):
        captured.append(callback)
        return MagicMock()

    tracker = MagicMock()
    tracker.async_setup = fake_async_setup
    coordinator.get_tank_tracker.return_value = tracker
    sensor = TankDerivedWaterSensor(coordinator, "gs_1", tank)
    sensor.async_on_remove = MagicMock()
    sensor.schedule_update_ha_state = MagicMock()

    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        await sensor.async_added_to_hass()

    assert len(captured) == 1
    captured[0]()  # Invoke _on_change to hit line 809
    sensor.schedule_update_ha_state.assert_called_once()
