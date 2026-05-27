"""Tests for AlertMonitor WebSocket handlers: get_ai_alerts and resolve_ai_alert."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.const import DOMAIN


GROWSPACE_ID = "tent1"


@pytest.fixture
def mock_alert_monitor():
    """Mock AlertMonitor."""
    monitor = MagicMock()
    monitor.get_alerts = MagicMock(return_value=[
        {
            "alert_id": "aaaaaaaa-0000-0000-0000-000000000001",
            "growspace_id": GROWSPACE_ID,
            "alert_type": "stress",
            "bayesian_reasons": ["High VPD"],
            "bayesian_probability": 0.91,
            "ai_reasoning": "Adjust humidity",
            "timestamp": "2026-01-12T12:00:00+00:00",
            "resolved": False,
            "resolution_notes": None,
        }
    ])
    monitor.resolve_alert = AsyncMock(return_value=True)
    return monitor


@pytest.fixture
def mock_coordinator(mock_alert_monitor):
    """Mock coordinator with alert_monitor."""
    coord = MagicMock()
    coord.alert_monitor = mock_alert_monitor
    return coord


@pytest.fixture
def mock_connection():
    """Mock WebSocket connection."""
    conn = MagicMock()
    conn.send_result = MagicMock()
    conn.send_error = MagicMock()
    return conn


# ---------------------------------------------------------------------------
# get_ai_alerts
# ---------------------------------------------------------------------------


async def test_get_ai_alerts_returns_all_alerts(
    mock_coordinator: MagicMock,
    mock_connection: MagicMock,
    mock_alert_monitor: MagicMock,
) -> None:
    """websocket_get_ai_alerts returns all alerts when no filter given."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_get_ai_alerts,
    )

    msg = {"id": 1, "type": f"{DOMAIN}/get_ai_alerts"}
    hass = MagicMock()
    hass.data = {DOMAIN: {}}

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.growspace_manager.websocket.ai_assistant._get_coordinator",
            lambda h, c: mock_coordinator,
        )
        await websocket_get_ai_alerts(hass, mock_connection, msg)

    mock_alert_monitor.get_alerts.assert_called_once_with(
        growspace_id=None, alert_type=None
    )
    mock_connection.send_result.assert_called_once()
    result = mock_connection.send_result.call_args[0][1]
    assert len(result["alerts"]) == 1
    assert result["alerts"][0]["alert_type"] == "stress"


async def test_get_ai_alerts_passes_filters(
    mock_coordinator: MagicMock,
    mock_connection: MagicMock,
    mock_alert_monitor: MagicMock,
) -> None:
    """websocket_get_ai_alerts forwards growspace_id and alert_type filters."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_get_ai_alerts,
    )

    msg = {
        "id": 2,
        "type": f"{DOMAIN}/get_ai_alerts",
        "growspace_id": GROWSPACE_ID,
        "alert_type": "mold",
    }
    hass = MagicMock()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.growspace_manager.websocket.ai_assistant._get_coordinator",
            lambda h, c: mock_coordinator,
        )
        await websocket_get_ai_alerts(hass, mock_connection, msg)

    mock_alert_monitor.get_alerts.assert_called_once_with(
        growspace_id=GROWSPACE_ID, alert_type="mold"
    )


async def test_get_ai_alerts_no_coordinator_sends_error(
    mock_connection: MagicMock,
) -> None:
    """websocket_get_ai_alerts sends an error when no coordinator is found."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_get_ai_alerts,
    )

    msg = {"id": 3, "type": f"{DOMAIN}/get_ai_alerts"}
    hass = MagicMock()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.growspace_manager.websocket.ai_assistant._get_coordinator",
            lambda h, c: None,
        )
        await websocket_get_ai_alerts(hass, mock_connection, msg)

    mock_connection.send_error.assert_called_once()
    error_code = mock_connection.send_error.call_args[0][1]
    assert error_code == "not_found"


# ---------------------------------------------------------------------------
# resolve_ai_alert
# ---------------------------------------------------------------------------


async def test_resolve_ai_alert_success(
    mock_coordinator: MagicMock,
    mock_connection: MagicMock,
    mock_alert_monitor: MagicMock,
) -> None:
    """websocket_resolve_ai_alert resolves the alert and returns success."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_resolve_ai_alert,
    )

    alert_id = "aaaaaaaa-0000-0000-0000-000000000001"
    msg = {
        "id": 4,
        "type": f"{DOMAIN}/resolve_ai_alert",
        "alert_id": alert_id,
    }
    hass = MagicMock()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.growspace_manager.websocket.ai_assistant._get_coordinator",
            lambda h, c: mock_coordinator,
        )
        await websocket_resolve_ai_alert(hass, mock_connection, msg)

    mock_alert_monitor.resolve_alert.assert_awaited_once_with(alert_id, notes=None)
    mock_connection.send_result.assert_called_once()
    result = mock_connection.send_result.call_args[0][1]
    assert result["success"] is True


async def test_resolve_ai_alert_with_notes(
    mock_coordinator: MagicMock,
    mock_connection: MagicMock,
    mock_alert_monitor: MagicMock,
) -> None:
    """websocket_resolve_ai_alert forwards optional notes."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_resolve_ai_alert,
    )

    alert_id = "aaaaaaaa-0000-0000-0000-000000000001"
    msg = {
        "id": 5,
        "type": f"{DOMAIN}/resolve_ai_alert",
        "alert_id": alert_id,
        "notes": "Fixed the dehumidifier",
    }
    hass = MagicMock()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.growspace_manager.websocket.ai_assistant._get_coordinator",
            lambda h, c: mock_coordinator,
        )
        await websocket_resolve_ai_alert(hass, mock_connection, msg)

    mock_alert_monitor.resolve_alert.assert_awaited_once_with(
        alert_id, notes="Fixed the dehumidifier"
    )


async def test_resolve_ai_alert_not_found_sends_error(
    mock_coordinator: MagicMock,
    mock_connection: MagicMock,
    mock_alert_monitor: MagicMock,
) -> None:
    """websocket_resolve_ai_alert sends an error when alert_id is not found."""
    mock_alert_monitor.resolve_alert = AsyncMock(return_value=False)

    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_resolve_ai_alert,
    )

    msg = {
        "id": 6,
        "type": f"{DOMAIN}/resolve_ai_alert",
        "alert_id": "nonexistent-id",
    }
    hass = MagicMock()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.growspace_manager.websocket.ai_assistant._get_coordinator",
            lambda h, c: mock_coordinator,
        )
        await websocket_resolve_ai_alert(hass, mock_connection, msg)

    mock_connection.send_error.assert_called_once()
    error_code = mock_connection.send_error.call_args[0][1]
    assert error_code == "not_found"


async def test_resolve_ai_alert_no_coordinator_sends_error(
    mock_connection: MagicMock,
) -> None:
    """websocket_resolve_ai_alert sends error when no coordinator found."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_resolve_ai_alert,
    )

    msg = {
        "id": 7,
        "type": f"{DOMAIN}/resolve_ai_alert",
        "alert_id": "some-id",
    }
    hass = MagicMock()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.growspace_manager.websocket.ai_assistant._get_coordinator",
            lambda h, c: None,
        )
        await websocket_resolve_ai_alert(hass, mock_connection, msg)

    mock_connection.send_error.assert_called_once()
