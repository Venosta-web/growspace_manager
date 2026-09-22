"""Tests for the trigger_vision_checkup service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.services.vision_checkup import (
    handle_trigger_vision_checkup,
)
from homeassistant.exceptions import ServiceValidationError


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator with vision scheduler."""
    coordinator = MagicMock()
    coordinator.vision_scheduler = MagicMock()
    coordinator.vision_scheduler.run_vision_analysis = AsyncMock()
    coordinator.growspaces = {"tent1": MagicMock()}
    return coordinator


@pytest.mark.asyncio
async def test_trigger_vision_checkup_returns_analysis(mock_coordinator):
    """The compatibility response is non-assertive and carries V1 identity."""
    from types import SimpleNamespace

    report = SimpleNamespace(
        observation="Leaves are level across the canopy.",
        environmental_risk="Measurements are within their evaluated range.",
        hypothesis="",
        recommendations=("Continue monitoring.",),
    )
    mock_coordinator.vision_scheduler.run_vision_analysis.return_value = (
        SimpleNamespace(
            checkup=SimpleNamespace(
                growspace_id="tent1",
                checkup_id="01991f1d-5c00-7000-8000-000000000001",
                trigger_source=SimpleNamespace(value="manual"),
                light_window=SimpleNamespace(value="manual"),
                started_at=None,
                completed_at="2026-09-01T12:00:00+00:00",
                status=SimpleNamespace(value="completed"),
            ),
            captures=(
                SimpleNamespace(
                    report=report,
                    media_content_id="media-source://media_source/local/capture.jpg",
                ),
            ),
        )
    )

    store = AsyncMock()
    store.async_get_checkup_captures.return_value = []
    hass = MagicMock()
    hass.data = {DOMAIN: {"vision_evidence_store": store}}
    hass.config.media_dirs = {"local": "/media"}
    call = MagicMock()
    call.data = {"growspace_id": "tent1"}

    result = await handle_trigger_vision_checkup(hass, mock_coordinator, call)

    mock_coordinator.vision_scheduler.run_vision_analysis.assert_called_once_with(
        "tent1", "manual"
    )
    assert result["severity"] == "none"
    assert "Leaves are level" in result["analysis"]
    assert result["check_type"] == "manual"
    assert result["growspace_id"] == "tent1"
    assert result["issues_detected"] == []
    assert result["checkup_id"].startswith("01991f1d")
    assert result["snapshot_paths"] == ["media-source://media_source/local/capture.jpg"]
    assert result["checkup"] == {
        "result_schema": "evidence_v1",
        "checkup_id": "01991f1d-5c00-7000-8000-000000000001",
        "growspace_id": "tent1",
        "trigger_source": "manual",
        "light_window": "manual",
        "started_at": None,
        "completed_at": "2026-09-01T12:00:00+00:00",
        "status": "completed",
        "captures": [],
    }


@pytest.mark.asyncio
async def test_trigger_vision_checkup_growspace_not_found(mock_coordinator):
    """Test error raised when growspace doesn't exist."""
    mock_coordinator.growspaces = {}

    hass = MagicMock()
    call = MagicMock()
    call.data = {"growspace_id": "nonexistent"}

    with pytest.raises(ServiceValidationError, match="not found"):
        await handle_trigger_vision_checkup(hass, mock_coordinator, call)
