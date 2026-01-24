"""Test Sensor Group functionality."""

import json
from dataclasses import asdict

from custom_components.growspace_manager.models import EnvironmentConfig, SensorGroup
from custom_components.growspace_manager.serializers import GrowspaceSerializer


def test_sensor_group_model():
    """Test SensorGroup model creation."""
    group = SensorGroup(
        id="test_group",
        name="Test Group",
        x=1.5,
        y=2.0,
        z=0.5,
        temperature_sensors=["sensor.temp1"],
        humidity_sensors=["sensor.hum1"],
        vpd_sensors=["sensor.vpd1"],
    )

    assert group.id == "test_group"
    assert group.name == "Test Group"
    assert group.x == 1.5
    assert group.temperature_sensors == ["sensor.temp1"]


def test_environment_config_with_groups():
    """Test EnvironmentConfig with sensor groups."""
    group = SensorGroup(id="g1", name="Group 1", x=10, y=20, z=0)

    config = EnvironmentConfig(
        temperature_sensor="sensor.main_temp", sensor_groups=[group]
    )

    assert len(config.sensor_groups) == 1
    assert config.sensor_groups[0].name == "Group 1"

    # Test dictionary conversion (mashumaro or asdict)
    data = config.to_dict()
    assert "sensor_groups" in data
    assert len(data["sensor_groups"]) == 1
    assert data["sensor_groups"][0]["id"] == "g1"


def test_deserialization_from_dict():
    """Test creating SensorGroup from dict (simulating service call logic)."""
    data = {
        "id": "g2",
        "name": "Group 2",
        "x": 5.5,
        "y": 6.6,
        "temperature_sensors": ["t1", "t2"],
    }

    # Simulate logic in environment.py
    group = SensorGroup(**data)
    assert group.id == "g2"
    assert group.x == 5.5
    assert group.z == 0.0  # Default
    assert len(group.temperature_sensors) == 2
