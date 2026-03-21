"""Tests for the trigger_vision_checkup service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.models import VisionCheckupResult
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
    """Test that the service returns analysis data on success."""
    mock_result = VisionCheckupResult(
        timestamp="2026-03-21T12:00:00",
        growspace_id="tent1",
        check_type="manual",
        analysis="All plants look healthy.",
        issues_detected=[],
        severity="none",
        recommendations=[],
    )
    mock_coordinator.vision_scheduler.run_vision_analysis.return_value = mock_result

    hass = MagicMock()
    call = MagicMock()
    call.data = {"growspace_id": "tent1"}

    result = await handle_trigger_vision_checkup(hass, mock_coordinator, call)

    mock_coordinator.vision_scheduler.run_vision_analysis.assert_called_once_with(
        "tent1", "manual"
    )
    assert result["severity"] == "none"
    assert result["analysis"] == "All plants look healthy."
    assert result["check_type"] == "manual"
    assert result["growspace_id"] == "tent1"


@pytest.mark.asyncio
async def test_trigger_vision_checkup_growspace_not_found(mock_coordinator):
    """Test error raised when growspace doesn't exist."""
    mock_coordinator.growspaces = {}

    hass = MagicMock()
    call = MagicMock()
    call.data = {"growspace_id": "nonexistent"}

    with pytest.raises(ServiceValidationError, match="not found"):
        await handle_trigger_vision_checkup(hass, mock_coordinator, call)


@pytest.mark.asyncio
async def test_trigger_vision_checkup_returns_none_raises(mock_coordinator):
    """Test error raised when vision analysis returns None."""
    mock_coordinator.vision_scheduler.run_vision_analysis.return_value = None

    hass = MagicMock()
    call = MagicMock()
    call.data = {"growspace_id": "tent1"}

    with pytest.raises(ServiceValidationError, match="could not be performed"):
        await handle_trigger_vision_checkup(hass, mock_coordinator, call)
