"""Tests for AlertMonitor — persistent AI alert tracking."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest

GROWSPACE_ID = "tent1"
STRESS_REASONS = ["High VPD: 1.8 kPa", "Fan off"]
MOLD_REASONS = ["High humidity: 85%", "Dense canopy"]


def _continuity_state(
    *,
    latest_capture_id: str = "capture-3",
    camera_id: str = "camera.canopy",
):
    from custom_components.growspace_manager.domain.capture_continuity import (
        CaptureContinuityState,
        ContinuityReason,
    )

    return CaptureContinuityState(
        growspace_id=GROWSPACE_ID,
        camera_id=camera_id,
        streak_started_at=datetime(2026, 9, 1, 6, tzinfo=UTC),
        consecutive_count=3,
        reason_counts=((ContinuityReason.FRAME_REJECTED, 3),),
        latest_capture_id=latest_capture_id,
        latest_captured_at=datetime(2026, 9, 1, 8, tzinfo=UTC),
        condition_active=True,
    )


@pytest.fixture
def store():
    """Mock HA Store that returns no existing data."""
    s = MagicMock()
    s.async_load = AsyncMock(return_value=None)
    s.async_save = AsyncMock()
    return s


@pytest.fixture
def mock_hass(store):
    """Mock HomeAssistant instance."""
    hass = MagicMock()
    hass.bus = MagicMock()
    hass.bus.async_listen = MagicMock(return_value=MagicMock())
    hass.async_create_task = MagicMock(side_effect=lambda coro: coro)
    return hass


@pytest.fixture
def mock_coordinator():
    """Minimal coordinator stub for AlertMonitor."""
    coordinator = MagicMock()
    coordinator.options = {}
    return coordinator


@pytest.fixture
def monitor(mock_hass, store, mock_coordinator):
    """AlertMonitor with mocked dependencies."""
    from custom_components.growspace_manager.alert_monitor import AlertMonitor

    return AlertMonitor(hass=mock_hass, coordinator=mock_coordinator, store=store)


# ---------------------------------------------------------------------------
# Tracer bullet: async_record_alert creates a well-formed alert
# ---------------------------------------------------------------------------


async def test_record_alert_creates_alert_with_required_fields(
    monitor,
) -> None:
    """Calling async_record_alert creates an AiAlert with all required fields."""
    await monitor.async_record_alert(
        growspace_id=GROWSPACE_ID,
        alert_type="stress",
        reasons=STRESS_REASONS,
        probability=0.91,
    )

    alerts = monitor.get_alerts()
    assert len(alerts) == 1

    alert = alerts[0]
    assert alert["growspace_id"] == GROWSPACE_ID
    assert alert["type"] == "stress"
    assert alert["bayesian_reasons"] == STRESS_REASONS
    assert alert["bayesian_probability"] == pytest.approx(0.91)
    assert alert["resolved"] is False
    assert alert["ai_reasoning"] is None
    assert alert["resolution_note"] is None
    # UUID format (wire format key is "id")
    parsed = uuid.UUID(alert["id"])
    assert str(parsed) == alert["id"]
    # Timestamp is a Unix epoch int in wire format
    assert isinstance(alert["timestamp"], int)
    assert alert["timestamp"] > 0


async def test_record_alert_mold_type(monitor) -> None:
    """async_record_alert works for mold alert type."""
    await monitor.async_record_alert(
        growspace_id=GROWSPACE_ID,
        alert_type="mold",
        reasons=MOLD_REASONS,
        probability=0.82,
    )

    alerts = monitor.get_alerts()
    assert len(alerts) == 1
    assert alerts[0]["type"] == "mold"
    assert alerts[0]["bayesian_reasons"] == MOLD_REASONS


async def test_capture_continuity_alert_is_equipment_evidence_only(monitor) -> None:
    """The equipment branch cannot carry Bayesian probability or AI reasoning."""
    await monitor.async_record_capture_continuity_break(_continuity_state())

    alert = monitor.get_alerts()[0]

    assert alert["type"] == "capture_continuity_break"
    assert alert["severity"] == "warning"
    assert alert["camera_id"] == "camera.canopy"
    assert alert["consecutive_count"] == 3
    assert alert["reason_counts"] == {"frame_rejected": 3}
    assert alert["latest_capture_id"] == "capture-3"
    assert alert["condition_active"] is True
    assert alert["cleared_at"] is None
    assert "bayesian_reasons" not in alert
    assert "bayesian_probability" not in alert
    assert "ai_reasoning" not in alert


async def test_cleared_continuity_condition_rearms_without_resolving_alert(
    monitor,
) -> None:
    """A later streak gets a new alert even while the cleared first stays unread."""
    first = await monitor.async_record_capture_continuity_break(_continuity_state())
    cleared_at = datetime(2026, 9, 1, 9, tzinfo=UTC)

    assert await monitor.async_clear_capture_continuity_break(
        "camera.canopy", cleared_at=cleared_at
    )
    second = await monitor.async_record_capture_continuity_break(
        _continuity_state(latest_capture_id="capture-7")
    )

    alerts = monitor.get_alerts(alert_type="capture_continuity_break")
    assert first["alert_id"] != second["alert_id"]
    assert len(alerts) == 2
    assert alerts[0]["condition_active"] is False
    assert alerts[0]["cleared_at"] == int(cleared_at.timestamp())
    assert alerts[0]["resolved"] is False
    assert alerts[1]["condition_active"] is True


async def test_active_continuity_alert_updates_without_duplication(monitor) -> None:
    """Later captures in one streak update its single durable alert."""
    first = await monitor.async_record_capture_continuity_break(_continuity_state())

    updated = await monitor.async_record_capture_continuity_break(
        _continuity_state(latest_capture_id="capture-4")
    )

    assert updated is first
    assert updated["latest_capture_id"] == "capture-4"
    assert len(monitor.get_alerts(alert_type="capture_continuity_break")) == 1


async def test_continuity_alerts_honor_the_retention_cap(monitor) -> None:
    """Equipment alerts use the same bounded durable inbox as other alert types."""
    monitor.MAX_ALERTS = 1
    first = await monitor.async_record_capture_continuity_break(_continuity_state())

    second = await monitor.async_record_capture_continuity_break(
        _continuity_state(camera_id="camera.side", latest_capture_id="capture-side-3")
    )

    assert monitor._alerts == [second]
    assert first not in monitor._alerts


async def test_clear_continuity_break_returns_false_without_active_alert(
    monitor,
) -> None:
    """Clearing an unknown or already-cleared camera is an idempotent no-op."""
    assert not await monitor.async_clear_capture_continuity_break(
        "camera.missing",
        cleared_at=datetime(2026, 9, 1, 9, tzinfo=UTC),
    )


# ---------------------------------------------------------------------------
# get_alerts filtering
# ---------------------------------------------------------------------------


async def test_get_alerts_filter_by_growspace_id(monitor) -> None:
    """get_alerts(growspace_id=...) returns only matching alerts."""
    await monitor.async_record_alert(GROWSPACE_ID, "stress", STRESS_REASONS, 0.9)
    await monitor.async_record_alert("other_tent", "mold", MOLD_REASONS, 0.8)

    results = monitor.get_alerts(growspace_id=GROWSPACE_ID)
    assert len(results) == 1
    assert results[0]["growspace_id"] == GROWSPACE_ID


async def test_get_alerts_filter_by_alert_type(monitor) -> None:
    """get_alerts(alert_type=...) returns only matching alerts."""
    await monitor.async_record_alert(GROWSPACE_ID, "stress", STRESS_REASONS, 0.9)
    await monitor.async_record_alert(GROWSPACE_ID, "mold", MOLD_REASONS, 0.8)

    results = monitor.get_alerts(alert_type="mold")
    assert len(results) == 1
    assert results[0]["type"] == "mold"


async def test_get_alerts_returns_all_when_no_filter(monitor) -> None:
    """get_alerts() returns all alerts."""
    await monitor.async_record_alert(GROWSPACE_ID, "stress", STRESS_REASONS, 0.9)
    await monitor.async_record_alert(GROWSPACE_ID, "mold", MOLD_REASONS, 0.8)

    assert len(monitor.get_alerts()) == 2


# ---------------------------------------------------------------------------
# resolve_alert
# ---------------------------------------------------------------------------


async def test_resolve_alert_marks_resolved(monitor) -> None:
    """resolve_alert marks an alert as resolved."""
    await monitor.async_record_alert(GROWSPACE_ID, "stress", STRESS_REASONS, 0.9)
    alert_id = monitor.get_alerts()[0]["id"]

    result = await monitor.resolve_alert(alert_id)

    assert result is True
    alert = monitor.get_alerts()[0]
    assert alert["resolved"] is True
    assert alert["resolution_note"] is None


async def test_resolve_alert_stores_notes(monitor) -> None:
    """resolve_alert persists resolution notes."""
    await monitor.async_record_alert(GROWSPACE_ID, "stress", STRESS_REASONS, 0.9)
    alert_id = monitor.get_alerts()[0]["id"]

    await monitor.resolve_alert(alert_id, notes="Adjusted dehumidifier target")

    alert = monitor.get_alerts()[0]
    assert alert["resolution_note"] == "Adjusted dehumidifier target"


async def test_resolve_alert_returns_false_for_unknown_id(monitor) -> None:
    """resolve_alert returns False when the alert_id does not exist."""
    result = await monitor.resolve_alert("nonexistent-uuid")

    assert result is False


# ---------------------------------------------------------------------------
# AI enrichment
# ---------------------------------------------------------------------------


async def test_ai_reasoning_populated_when_available(mock_hass, store) -> None:
    """AI reasoning is written to alert when AI succeeds."""
    from custom_components.growspace_manager.alert_monitor import AlertMonitor

    ai_factory = MagicMock()
    ai_assistant = MagicMock()
    ai_assistant.generate_alert_message = AsyncMock(
        return_value="High VPD detected. Increase humidity or reduce temperature."
    )
    ai_factory.return_value = ai_assistant

    coord = MagicMock()
    coord.options = {"ai_enabled": True, "ai_auto_alerts": True}
    monitor = AlertMonitor(
        hass=mock_hass, coordinator=coord, store=store, ai_assistant_factory=ai_factory
    )

    await monitor.async_record_alert(GROWSPACE_ID, "stress", STRESS_REASONS, 0.9)

    alert = monitor.get_alerts()[0]
    assert (
        alert["ai_reasoning"]
        == "High VPD detected. Increase humidity or reduce temperature."
    )


async def test_ai_failure_leaves_bayesian_only_alert(mock_hass, store) -> None:
    """When AI raises, the alert persists with ai_reasoning=None (not deleted)."""
    from custom_components.growspace_manager.alert_monitor import AlertMonitor

    ai_factory = MagicMock()
    ai_assistant = MagicMock()
    ai_assistant.generate_alert_message = AsyncMock(
        side_effect=Exception("AI unavailable")
    )
    ai_factory.return_value = ai_assistant

    coord = MagicMock()
    coord.options = {"ai_enabled": True, "ai_auto_alerts": True}
    monitor = AlertMonitor(
        hass=mock_hass, coordinator=coord, store=store, ai_assistant_factory=ai_factory
    )

    await monitor.async_record_alert(GROWSPACE_ID, "stress", STRESS_REASONS, 0.9)

    alerts = monitor.get_alerts()
    assert len(alerts) == 1  # record persisted despite AI failure
    assert alerts[0]["ai_reasoning"] is None


# ---------------------------------------------------------------------------
# 500-record cap
# ---------------------------------------------------------------------------


async def test_cap_evicts_oldest_at_500(mock_hass, store) -> None:
    """Alerts are capped at 500; oldest are evicted."""
    from custom_components.growspace_manager.alert_monitor import AlertMonitor

    coord = MagicMock()
    coord.options = {}
    monitor = AlertMonitor(hass=mock_hass, coordinator=coord, store=store)

    for i in range(502):
        await monitor.async_record_alert(f"tent{i}", "stress", ["reason"], 0.9)

    alerts = monitor.get_alerts()
    assert len(alerts) == 500
    # Oldest two (tent0, tent1) should be gone
    ids = [a["growspace_id"] for a in alerts]
    assert "tent0" not in ids
    assert "tent1" not in ids
    assert "tent501" in ids


# ---------------------------------------------------------------------------
# Wire format serialisation (get_alerts returns public wire format, not storage)
# ---------------------------------------------------------------------------


async def test_get_alerts_stress_uses_wire_format(monitor) -> None:
    """get_alerts() returns wire-format fields: id, type, severity, Unix timestamp, resolution_note."""
    await monitor.async_record_alert(
        growspace_id=GROWSPACE_ID,
        alert_type="stress",
        reasons=STRESS_REASONS,
        probability=0.91,
    )

    alert = monitor.get_alerts()[0]

    # Renamed fields
    assert "id" in alert
    assert "alert_id" not in alert
    assert "type" in alert
    assert "alert_type" not in alert
    assert alert["type"] == "stress"
    assert "resolution_note" in alert
    assert "resolution_notes" not in alert

    # Severity injected
    assert alert["severity"] == "danger"

    # Timestamp is a Unix epoch int, not an ISO string
    assert isinstance(alert["timestamp"], int)
    assert alert["timestamp"] > 0


async def test_get_alerts_mold_severity_is_warning(monitor) -> None:
    """get_alerts() maps mold alert_type to severity='warning'."""
    await monitor.async_record_alert(
        growspace_id=GROWSPACE_ID,
        alert_type="mold",
        reasons=MOLD_REASONS,
        probability=0.82,
    )

    alert = monitor.get_alerts()[0]
    assert alert["severity"] == "warning"


async def test_get_alerts_unknown_type_severity_defaults_to_info(monitor) -> None:
    """get_alerts() defaults severity to 'info' for unknown alert types."""
    await monitor.async_record_alert(
        growspace_id=GROWSPACE_ID,
        alert_type="unknown_future_type",
        reasons=["some reason"],
        probability=0.5,
    )

    alert = monitor.get_alerts()[0]
    assert alert["severity"] == "info"


async def test_async_setup_loads_persisted_alerts(mock_hass) -> None:
    """async_setup loads previously stored alerts from the Store."""
    from custom_components.growspace_manager.alert_monitor import AlertMonitor

    existing = {
        "alerts": [
            {
                "alert_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "growspace_id": "tent1",
                "alert_type": "stress",
                "bayesian_reasons": ["High VPD"],
                "bayesian_probability": 0.88,
                "ai_reasoning": "Raise humidity",
                "timestamp": "2026-01-12T12:00:00+00:00",
                "resolved": False,
                "resolution_notes": None,
            }
        ]
    }
    store = MagicMock()
    store.async_load = AsyncMock(return_value=existing)
    store.async_save = AsyncMock()

    coord = MagicMock()
    coord.options = {}
    monitor = AlertMonitor(hass=mock_hass, coordinator=coord, store=store)
    await monitor.async_start()

    alerts = monitor.get_alerts()
    assert len(alerts) == 1
    assert alerts[0]["id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert alerts[0]["ai_reasoning"] == "Raise humidity"
