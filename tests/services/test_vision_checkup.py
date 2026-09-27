"""Tests for the trigger_vision_checkup service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.services.vision_checkup import (
    handle_restart_visual_baseline,
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


@pytest.mark.asyncio
async def test_restart_visual_baseline_validates_before_writing(mock_coordinator):
    """Unknown growspaces and unconfigured cameras leave evidence untouched."""
    hass = MagicMock()
    store = AsyncMock()
    hass.data = {DOMAIN: {"vision_evidence_store": store}}
    growspace = mock_coordinator.growspaces["tent1"]
    growspace.environment_config.camera_entities = ["camera.canopy"]
    call = MagicMock()
    call.data = {"growspace_id": "missing", "camera_id": "camera.canopy"}
    with pytest.raises(ServiceValidationError, match="Growspace 'missing' not found"):
        await handle_restart_visual_baseline(hass, mock_coordinator, call)
    call.data = {"growspace_id": "tent1", "camera_id": "camera.other"}
    with pytest.raises(ServiceValidationError, match="not configured"):
        await handle_restart_visual_baseline(hass, mock_coordinator, call)
    store.async_restart_visual_baseline.assert_not_awaited()

    hass.data[DOMAIN] = {}
    call.data["camera_id"] = "camera.canopy"
    with pytest.raises(ServiceValidationError, match="Store is unavailable"):
        await handle_restart_visual_baseline(hass, mock_coordinator, call)


@pytest.mark.asyncio
async def test_restart_visual_baseline_returns_epoch(mock_coordinator):
    """The Home Assistant action reports its durable boundary."""
    hass = MagicMock()
    store = AsyncMock()
    store.async_restart_visual_baseline.return_value = {
        "epoch_id": "epoch-2",
        "grow_run_id": "run-1",
        "started_at": "2026-09-26T10:00:00+00:00",
        "reason": "manual_restart",
    }
    hass.data = {DOMAIN: {"vision_evidence_store": store}}
    mock_coordinator.growspaces["tent1"].environment_config.camera_entities = [
        "camera.canopy"
    ]
    call = MagicMock()
    call.data = {"growspace_id": "tent1", "camera_id": "camera.canopy"}
    result = await handle_restart_visual_baseline(hass, mock_coordinator, call)
    store.async_restart_visual_baseline.assert_awaited_once_with(
        "tent1", "camera.canopy"
    )
    assert result == {
        "growspace_id": "tent1",
        "camera_id": "camera.canopy",
        **store.async_restart_visual_baseline.return_value,
    }
