"""Tests for AlertMonitor WebSocket handlers: get_ai_alerts and resolve_ai_alert."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.exceptions import EntityNotFoundError

GROWSPACE_ID = "tent1"


@pytest.fixture
def mock_alert_monitor():
    """Mock AlertMonitor returning wire-format dicts (as the real get_alerts() now does)."""
    monitor = MagicMock()
    monitor.get_alerts = MagicMock(
        return_value=[
            {
                "id": "aaaaaaaa-0000-0000-0000-000000000001",
                "growspace_id": GROWSPACE_ID,
                "type": "stress",
                "severity": "danger",
                "bayesian_reasons": ["High VPD"],
                "bayesian_probability": 0.91,
                "ai_reasoning": "Adjust humidity",
                "timestamp": 1736683200,
                "resolved": False,
                "resolution_note": None,
            }
        ]
    )
    monitor.resolve_alert = AsyncMock(return_value=True)
    return monitor


@pytest.fixture
def mock_coordinator(mock_alert_monitor):
    """Mock coordinator with alert_monitor exposed via the notifications facade."""
    coord = MagicMock()
    coord.alert_monitor = mock_alert_monitor
    coord.services.notifications.get_alerts = mock_alert_monitor.get_alerts
    coord.services.notifications.resolve_alert = mock_alert_monitor.resolve_alert
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

    result = await websocket_get_ai_alerts(hass, mock_coordinator, msg)

    mock_alert_monitor.get_alerts.assert_called_once_with(
        growspace_id=None, alert_type=None
    )
    assert len(result) == 1
    assert result[0]["type"] == "stress"
    assert result[0]["severity"] == "danger"


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

    await websocket_get_ai_alerts(hass, mock_coordinator, msg)

    mock_alert_monitor.get_alerts.assert_called_once_with(
        growspace_id=GROWSPACE_ID, alert_type="mold"
    )


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

    result = await websocket_resolve_ai_alert(hass, mock_coordinator, msg)

    mock_alert_monitor.resolve_alert.assert_awaited_once_with(alert_id, notes=None)
    assert result["success"] is True


async def test_resolve_ai_alert_with_resolution_note(
    mock_coordinator: MagicMock,
    mock_connection: MagicMock,
    mock_alert_monitor: MagicMock,
) -> None:
    """websocket_resolve_ai_alert accepts the resolution_note field and forwards it."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_resolve_ai_alert,
    )

    alert_id = "aaaaaaaa-0000-0000-0000-000000000001"
    msg = {
        "id": 5,
        "type": f"{DOMAIN}/resolve_ai_alert",
        "alert_id": alert_id,
        "resolution_note": "Fixed the dehumidifier",
    }
    hass = MagicMock()

    await websocket_resolve_ai_alert(hass, mock_coordinator, msg)

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
    mock_coordinator.services.notifications.resolve_alert = (
        mock_alert_monitor.resolve_alert
    )

    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_resolve_ai_alert,
    )

    msg = {
        "id": 6,
        "type": f"{DOMAIN}/resolve_ai_alert",
        "alert_id": "nonexistent-id",
    }
    hass = MagicMock()

    with pytest.raises(EntityNotFoundError, match="'nonexistent-id' not found"):
        await websocket_resolve_ai_alert(hass, mock_coordinator, msg)
