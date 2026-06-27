"""Tests for the get_briefing WebSocket handler schema.

Regression test for: schema rejected growspace_id even though the frontend
always sends it, causing 'extra keys not allowed' errors in HA logs.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.websocket.ai_assistant import (
    SCHEMA_WS_GET_BRIEFING,
    WS_TYPE_GET_BRIEFING,
    websocket_get_briefing,
)


@pytest.fixture
def mock_connection() -> MagicMock:
    conn = MagicMock()
    conn.send_result = MagicMock()
    conn.send_error = MagicMock()
    return conn


def _make_coordinator(briefing: dict) -> MagicMock:
    coord = MagicMock()
    coord.options = {}
    scheduler = MagicMock()
    scheduler.async_get_briefing = AsyncMock(return_value=briefing)
    coord.briefing_scheduler = scheduler
    return coord


# ---------------------------------------------------------------------------
# Schema regression tests
# ---------------------------------------------------------------------------


def test_schema_accepts_growspace_id() -> None:
    """Schema must accept growspace_id — frontend always sends it."""
    msg = {
        "id": 1,
        "type": WS_TYPE_GET_BRIEFING,
        "growspace_id": "tent1",
    }
    validated = SCHEMA_WS_GET_BRIEFING(msg)
    assert validated["growspace_id"] == "tent1"


def test_schema_accepts_empty_growspace_id() -> None:
    """Schema must accept growspace_id='' — the main dialog card uses '' as default."""
    msg = {
        "id": 1,
        "type": WS_TYPE_GET_BRIEFING,
        "growspace_id": "",
    }
    validated = SCHEMA_WS_GET_BRIEFING(msg)
    assert validated["growspace_id"] == ""


def test_schema_accepts_growspace_id_with_force_refresh() -> None:
    """Schema must accept both growspace_id and force_refresh together."""
    msg = {
        "id": 1,
        "type": WS_TYPE_GET_BRIEFING,
        "growspace_id": "tent1",
        "force_refresh": True,
    }
    validated = SCHEMA_WS_GET_BRIEFING(msg)
    assert validated["growspace_id"] == "tent1"
    assert validated["force_refresh"] is True


def test_schema_growspace_id_is_optional() -> None:
    """growspace_id is optional — existing callers that omit it must still work."""
    msg = {
        "id": 1,
        "type": WS_TYPE_GET_BRIEFING,
    }
    validated = SCHEMA_WS_GET_BRIEFING(msg)
    assert "growspace_id" not in validated


# ---------------------------------------------------------------------------
# Handler tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_briefing_returns_briefing(mock_connection: MagicMock) -> None:
    """Handler returns the briefing from the scheduler."""
    stub_briefing = {"summary": "All good", "ai_available": True}
    coordinator = _make_coordinator(stub_briefing)
    msg = {"id": 1, "type": WS_TYPE_GET_BRIEFING, "growspace_id": "tent1"}

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.growspace_manager.websocket.ai_assistant._get_coordinator",
            lambda h, c: coordinator,
        )
        await websocket_get_briefing(MagicMock(), mock_connection, msg)

    mock_connection.send_result.assert_called_once_with(1, stub_briefing)


@pytest.mark.asyncio
async def test_get_briefing_passes_force_refresh(mock_connection: MagicMock) -> None:
    """Handler passes force_refresh=True to the scheduler."""
    coordinator = _make_coordinator({"summary": "Fresh"})
    msg = {"id": 2, "type": WS_TYPE_GET_BRIEFING, "growspace_id": "", "force_refresh": True}

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.growspace_manager.websocket.ai_assistant._get_coordinator",
            lambda h, c: coordinator,
        )
        await websocket_get_briefing(MagicMock(), mock_connection, msg)

    coordinator.briefing_scheduler.async_get_briefing.assert_called_once_with(force_refresh=True)


@pytest.mark.asyncio
async def test_get_briefing_sends_error_when_coordinator_missing(
    mock_connection: MagicMock,
) -> None:
    """Handler sends not_found when the coordinator is unavailable."""
    msg = {"id": 3, "type": WS_TYPE_GET_BRIEFING}

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.growspace_manager.websocket.ai_assistant._get_coordinator",
            lambda h, c: None,
        )
        await websocket_get_briefing(MagicMock(), mock_connection, msg)

    mock_connection.send_error.assert_called_once()
    assert mock_connection.send_error.call_args[0][1] == "not_found"
