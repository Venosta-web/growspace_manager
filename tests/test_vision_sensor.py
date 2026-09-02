"""Tests for the operational VisionCheckupSensor contract."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.growspace_manager.sensor import VisionCheckupSensor
from custom_components.growspace_manager.vision_connection import (
    VisionAvailability,
    VisionConnectionSource,
    VisionStatus,
    VisionUnavailableReason,
)


def _coordinator(latest=None, *, status: VisionStatus | None = None):
    coordinator = MagicMock()
    coordinator.vision_scheduler.latest_checkup.return_value = latest
    coordinator.vision_connection.status = status or VisionStatus(
        availability=VisionAvailability.READY,
        connection_source=VisionConnectionSource.SUPERVISOR,
    )
    return coordinator


def test_vision_sensor_has_no_state_before_a_ready_service_runs_a_checkup():
    """Ready with no durable result is not itself a completed checkup."""
    sensor = VisionCheckupSensor(_coordinator(), "tent1", "Test Tent")

    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {
        "checkup_id": None,
        "last_checkup_time": None,
        "trigger_source": None,
        "cameras": {},
    }


def test_vision_sensor_projects_latest_operational_state_per_camera():
    """The retained entity reports operation and never aggregates severity."""
    latest = {
        "result_schema": "evidence_v1",
        "checkup_id": "checkup-1",
        "completed_at": "2026-09-01T12:00:00+00:00",
        "trigger_source": "scheduled",
        "status": "partial",
        "captures": [
            {
                "camera_id": "camera.canopy",
                "analysis_state": "analyzed",
                "fusion": {
                    "state": "visual_anomaly",
                    "confidence": "monitor",
                    "coverage": "complete",
                    "unavailable_reasons": [],
                },
            },
            {
                "camera_id": "camera.side",
                "analysis_state": "failed",
                "fusion": {"unavailable_reasons": ["vision_unavailable"]},
            },
        ],
    }
    sensor = VisionCheckupSensor(_coordinator(latest), "tent1", "Test Tent")

    assert sensor.native_value == "partial"
    assert sensor.extra_state_attributes == {
        "checkup_id": "checkup-1",
        "last_checkup_time": "2026-09-01T12:00:00+00:00",
        "trigger_source": "scheduled",
        "cameras": {
            "camera.canopy": {
                "analysis_state": "analyzed",
                "fusion_state": "visual_anomaly",
                "fusion_confidence": "monitor",
                "fusion_coverage": "complete",
                "unavailable_reasons": [],
            },
            "camera.side": {
                "analysis_state": "failed",
                "fusion_state": None,
                "fusion_confidence": None,
                "fusion_coverage": None,
                "unavailable_reasons": ["vision_unavailable"],
            },
        },
    }


def test_vision_sensor_surfaces_service_unavailability_without_legacy_history():
    """No stale cloud severity remains when the required local service is down."""
    status = VisionStatus(
        availability=VisionAvailability.UNAVAILABLE,
        connection_source=VisionConnectionSource.SUPERVISOR,
        reason=VisionUnavailableReason.NOT_RUNNING,
    )
    sensor = VisionCheckupSensor(_coordinator(status=status), "tent1", "Test Tent")

    assert sensor.native_value == "unavailable"
    assert sensor.extra_state_attributes["reason"] == "not_running"


def test_vision_sensor_keeps_its_existing_unique_id():
    """Automations retain the same entity identity through the cutover."""
    sensor = VisionCheckupSensor(_coordinator(), "tent1", "Test Tent")

    assert sensor.unique_id == "tent1_vision_checkup"
