"""Tests for the VisionCheckupSensor."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.growspace_manager.models import VisionCheckupResult
from custom_components.growspace_manager.sensor import VisionCheckupSensor


def _make_coordinator(growspace_id="tent1", history=None, has_cameras=True):
    """Create a mock coordinator for sensor tests."""
    coordinator = MagicMock()

    gs = MagicMock()
    gs.id = growspace_id
    gs.name = "Test Tent"
    gs.vision_checkup_history = history or []
    gs.environment_config.camera_entities = ["camera.cam1"] if has_cameras else []

    coordinator.growspaces = {growspace_id: gs}
    coordinator.data = {}
    return coordinator


def test_vision_sensor_no_history_returns_none():
    """Test sensor returns None state when no checkups performed."""
    coordinator = _make_coordinator()
    sensor = VisionCheckupSensor(coordinator, "tent1", "Test Tent")

    assert sensor.native_value is None


def test_vision_sensor_returns_latest_severity():
    """Test sensor returns severity of latest checkup."""
    result = VisionCheckupResult(
        timestamp="2026-03-21T12:00:00",
        growspace_id="tent1",
        check_type="mid",
        analysis="Minor drooping detected.",
        issues_detected=["leaf_drooping"],
        severity="low",
        recommendations=["Check watering."],
    )
    coordinator = _make_coordinator(history=[result])
    sensor = VisionCheckupSensor(coordinator, "tent1", "Test Tent")

    assert sensor.native_value == "low"


def test_vision_sensor_extra_attributes_no_history():
    """Test sensor attributes when no history."""
    coordinator = _make_coordinator()
    sensor = VisionCheckupSensor(coordinator, "tent1", "Test Tent")

    attrs = sensor.extra_state_attributes
    assert attrs["last_check_type"] is None
    assert attrs["last_analysis"] is None
    assert attrs["issues_detected"] == []
    assert attrs["recommendations"] == []
    assert attrs["last_checkup_time"] is None
    assert attrs["total_checkups"] == 0


def test_vision_sensor_extra_attributes_with_history():
    """Test sensor attributes reflect latest result."""
    result = VisionCheckupResult(
        timestamp="2026-03-21T12:00:00",
        growspace_id="tent1",
        check_type="mid",
        analysis="Nutrient burn on leaf tips.",
        issues_detected=["nutrient_burn"],
        severity="medium",
        recommendations=["Reduce EC by 0.3."],
    )
    coordinator = _make_coordinator(history=[result])
    sensor = VisionCheckupSensor(coordinator, "tent1", "Test Tent")

    attrs = sensor.extra_state_attributes
    assert attrs["last_check_type"] == "mid"
    assert attrs["last_analysis"] == "Nutrient burn on leaf tips."
    assert attrs["issues_detected"] == ["nutrient_burn"]
    assert attrs["recommendations"] == ["Reduce EC by 0.3."]
    assert attrs["last_checkup_time"] == "2026-03-21T12:00:00"
    assert attrs["total_checkups"] == 1


def test_vision_sensor_unique_id():
    """Test sensor has correct unique ID."""
    coordinator = _make_coordinator()
    sensor = VisionCheckupSensor(coordinator, "tent1", "Test Tent")

    assert sensor.unique_id == "tent1_vision_checkup"
