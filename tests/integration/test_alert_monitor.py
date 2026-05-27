"""Tests for AlertMonitor — persistent AI alert tracking."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest

from custom_components.growspace_manager.const import (
    ATTR_PROBABILITY,
    ATTR_REASONS,
    DOMAIN,
)

GROWSPACE_ID = "tent1"
STRESS_REASONS = ["High VPD: 1.8 kPa", "Fan off"]
MOLD_REASONS = ["High humidity: 85%", "Dense canopy"]


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
def monitor(mock_hass, store):
    """AlertMonitor with mocked dependencies."""
    from custom_components.growspace_manager.alert_monitor import AlertMonitor

    return AlertMonitor(hass=mock_hass, store=store)


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
    assert alert["alert_type"] == "stress"
    assert alert["bayesian_reasons"] == STRESS_REASONS
    assert alert["bayesian_probability"] == pytest.approx(0.91)
    assert alert["resolved"] is False
    assert alert["ai_reasoning"] is None
    assert alert["resolution_notes"] is None
    # UUID format
    parsed = uuid.UUID(alert["alert_id"])
    assert str(parsed) == alert["alert_id"]
    # ISO timestamp present
    assert "T" in alert["timestamp"]


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
    assert alerts[0]["alert_type"] == "mold"
    assert alerts[0]["bayesian_reasons"] == MOLD_REASONS


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
    assert results[0]["alert_type"] == "mold"


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
    alert_id = monitor.get_alerts()[0]["alert_id"]

    result = await monitor.resolve_alert(alert_id)

    assert result is True
    alert = monitor.get_alerts()[0]
    assert alert["resolved"] is True
    assert alert["resolution_notes"] is None


async def test_resolve_alert_stores_notes(monitor) -> None:
    """resolve_alert persists resolution notes."""
    await monitor.async_record_alert(GROWSPACE_ID, "stress", STRESS_REASONS, 0.9)
    alert_id = monitor.get_alerts()[0]["alert_id"]

    await monitor.resolve_alert(alert_id, notes="Adjusted dehumidifier target")

    alert = monitor.get_alerts()[0]
    assert alert["resolution_notes"] == "Adjusted dehumidifier target"


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

    monitor = AlertMonitor(hass=mock_hass, store=store, ai_assistant_factory=ai_factory)

    await monitor.async_record_alert(GROWSPACE_ID, "stress", STRESS_REASONS, 0.9)

    alert = monitor.get_alerts()[0]
    assert alert["ai_reasoning"] == "High VPD detected. Increase humidity or reduce temperature."


async def test_ai_failure_leaves_bayesian_only_alert(mock_hass, store) -> None:
    """When AI raises, the alert persists with ai_reasoning=None (not deleted)."""
    from custom_components.growspace_manager.alert_monitor import AlertMonitor

    ai_factory = MagicMock()
    ai_assistant = MagicMock()
    ai_assistant.generate_alert_message = AsyncMock(
        side_effect=Exception("AI unavailable")
    )
    ai_factory.return_value = ai_assistant

    monitor = AlertMonitor(hass=mock_hass, store=store, ai_assistant_factory=ai_factory)

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

    monitor = AlertMonitor(hass=mock_hass, store=store)

    for i in range(502):
        await monitor.async_record_alert(
            f"tent{i}", "stress", ["reason"], 0.9
        )

    alerts = monitor.get_alerts()
    assert len(alerts) == 500
    # Oldest two (tent0, tent1) should be gone
    ids = [a["growspace_id"] for a in alerts]
    assert "tent0" not in ids
    assert "tent1" not in ids
    assert "tent501" in ids


# ---------------------------------------------------------------------------
# State-change listener
# ---------------------------------------------------------------------------


async def test_state_change_off_to_on_creates_alert(mock_hass, store) -> None:
    """off→on transition on a registered sensor creates an alert."""
    from custom_components.growspace_manager.alert_monitor import AlertMonitor

    monitor = AlertMonitor(hass=mock_hass, store=store)
    monitor.register_sensor(
        entity_id="binary_sensor.growspace_manager_tent1_stress",
        growspace_id=GROWSPACE_ID,
        alert_type="stress",
    )

    old_state = MagicMock()
    old_state.state = "off"
    new_state = MagicMock()
    new_state.state = "on"
    new_state.attributes = {
        ATTR_REASONS: STRESS_REASONS,
        ATTR_PROBABILITY: 0.91,
    }

    event = MagicMock()
    event.data = {
        "entity_id": "binary_sensor.growspace_manager_tent1_stress",
        "old_state": old_state,
        "new_state": new_state,
    }

    await monitor._async_handle_state_change(event)

    alerts = monitor.get_alerts()
    assert len(alerts) == 1
    assert alerts[0]["growspace_id"] == GROWSPACE_ID
    assert alerts[0]["alert_type"] == "stress"


async def test_state_change_on_to_on_no_alert(mock_hass, store) -> None:
    """on→on transition (no rising edge) does NOT create a new alert."""
    from custom_components.growspace_manager.alert_monitor import AlertMonitor

    monitor = AlertMonitor(hass=mock_hass, store=store)
    monitor.register_sensor(
        entity_id="binary_sensor.growspace_manager_tent1_stress",
        growspace_id=GROWSPACE_ID,
        alert_type="stress",
    )

    old_state = MagicMock()
    old_state.state = "on"
    new_state = MagicMock()
    new_state.state = "on"
    new_state.attributes = {ATTR_REASONS: STRESS_REASONS, ATTR_PROBABILITY: 0.91}

    event = MagicMock()
    event.data = {
        "entity_id": "binary_sensor.growspace_manager_tent1_stress",
        "old_state": old_state,
        "new_state": new_state,
    }

    await monitor._async_handle_state_change(event)

    assert len(monitor.get_alerts()) == 0


async def test_state_change_on_to_off_no_alert(mock_hass, store) -> None:
    """on→off (falling edge) does NOT create a new alert."""
    from custom_components.growspace_manager.alert_monitor import AlertMonitor

    monitor = AlertMonitor(hass=mock_hass, store=store)
    monitor.register_sensor(
        entity_id="binary_sensor.growspace_manager_tent1_stress",
        growspace_id=GROWSPACE_ID,
        alert_type="stress",
    )

    old_state = MagicMock()
    old_state.state = "on"
    new_state = MagicMock()
    new_state.state = "off"
    new_state.attributes = {}

    event = MagicMock()
    event.data = {
        "entity_id": "binary_sensor.growspace_manager_tent1_stress",
        "old_state": old_state,
        "new_state": new_state,
    }

    await monitor._async_handle_state_change(event)

    assert len(monitor.get_alerts()) == 0


async def test_state_change_unregistered_sensor_ignored(mock_hass, store) -> None:
    """State changes for unregistered entities are silently ignored."""
    from custom_components.growspace_manager.alert_monitor import AlertMonitor

    monitor = AlertMonitor(hass=mock_hass, store=store)

    new_state = MagicMock()
    new_state.state = "on"
    new_state.attributes = {ATTR_REASONS: STRESS_REASONS, ATTR_PROBABILITY: 0.91}
    old_state = MagicMock()
    old_state.state = "off"

    event = MagicMock()
    event.data = {
        "entity_id": "binary_sensor.some_other_sensor",
        "old_state": old_state,
        "new_state": new_state,
    }

    await monitor._async_handle_state_change(event)

    assert len(monitor.get_alerts()) == 0


# ---------------------------------------------------------------------------
# Listener setup / teardown
# ---------------------------------------------------------------------------


async def test_async_setup_registers_listener(mock_hass, store) -> None:
    """async_setup registers a state_changed listener on hass.bus."""
    from custom_components.growspace_manager.alert_monitor import AlertMonitor

    monitor = AlertMonitor(hass=mock_hass, store=store)
    await monitor.async_setup()

    mock_hass.bus.async_listen.assert_called_once_with(
        "state_changed", monitor._async_handle_state_change
    )


async def test_async_unload_cancels_listener(mock_hass, store) -> None:
    """async_unload cancels the registered state_changed listener."""
    from custom_components.growspace_manager.alert_monitor import AlertMonitor

    cancel_mock = MagicMock()
    mock_hass.bus.async_listen.return_value = cancel_mock

    monitor = AlertMonitor(hass=mock_hass, store=store)
    await monitor.async_setup()
    monitor.async_unload()

    cancel_mock.assert_called_once()


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

    monitor = AlertMonitor(hass=mock_hass, store=store)
    await monitor.async_setup()

    alerts = monitor.get_alerts()
    assert len(alerts) == 1
    assert alerts[0]["alert_id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert alerts[0]["ai_reasoning"] == "Raise humidity"
