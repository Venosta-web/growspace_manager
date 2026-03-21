"""Tests for the VisionCheckupScheduler time calculation logic."""

from __future__ import annotations

from datetime import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.core import HomeAssistant

from custom_components.growspace_manager.vision_checkup_scheduler import (
    VisionCheckupScheduler,
    calculate_checkup_times,
)


def test_calculate_checkup_times_veg_18_6():
    """Test checkup times for 18/6 vegetative cycle with lights on at 06:00."""
    lights_on = time(6, 0)
    day_hours = 18

    times = calculate_checkup_times(
        lights_on_time=lights_on,
        day_hours=day_hours,
        early_offset_minutes=60,
        mid_check_hours=6,
        late_offset_minutes=60,
    )

    assert times["early"] == time(7, 0)   # 06:00 + 1h
    assert times["mid"] == time(12, 0)    # 06:00 + 6h
    assert times["late"] == time(23, 0)   # 06:00 + 18h - 1h = 23:00


def test_calculate_checkup_times_flower_12_12():
    """Test checkup times for 12/12 flowering cycle with lights on at 06:00."""
    times = calculate_checkup_times(
        lights_on_time=time(6, 0),
        day_hours=12,
        early_offset_minutes=60,
        mid_check_hours=6,
        late_offset_minutes=60,
    )

    assert times["early"] == time(7, 0)   # 06:00 + 1h
    assert times["mid"] == time(12, 0)    # 06:00 + 6h
    assert times["late"] == time(17, 0)   # 06:00 + 12h - 1h = 17:00


def test_calculate_checkup_times_wraps_midnight():
    """Test checkup times that wrap past midnight."""
    # Lights on at 20:00, 18h cycle -> lights off at 14:00 next day
    times = calculate_checkup_times(
        lights_on_time=time(20, 0),
        day_hours=18,
        early_offset_minutes=60,
        mid_check_hours=6,
        late_offset_minutes=60,
    )

    assert times["early"] == time(21, 0)  # 20:00 + 1h
    assert times["mid"] == time(2, 0)     # 20:00 + 6h = 02:00 next day
    assert times["late"] == time(13, 0)   # 20:00 + 18h - 1h = 13:00 next day


def test_calculate_checkup_times_flower_night_schedule():
    """Test 12/12 flower with lights on at 18:00 (common night schedule)."""
    times = calculate_checkup_times(
        lights_on_time=time(18, 0),
        day_hours=12,
        early_offset_minutes=60,
        mid_check_hours=6,
        late_offset_minutes=60,
    )

    assert times["early"] == time(19, 0)  # 18:00 + 1h
    assert times["mid"] == time(0, 0)     # 18:00 + 6h = 00:00
    assert times["late"] == time(5, 0)    # 18:00 + 12h - 1h = 05:00


def test_vision_checkup_scheduler_initializes():
    """Test VisionCheckupScheduler initializes with correct attributes."""
    hass = MagicMock(spec=HomeAssistant)
    coordinator = MagicMock()

    scheduler = VisionCheckupScheduler(hass, coordinator)

    assert scheduler.hass is hass
    assert scheduler.coordinator is coordinator
    assert scheduler._unsub_timers == {}


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    return hass


@pytest.fixture
def mock_coordinator(mock_hass):
    """Create a mock coordinator with minimal required attributes."""
    coordinator = MagicMock()
    coordinator.hass = mock_hass
    coordinator.options = {
        "ai_settings": {
            "ai_enabled": True,
            "assistant_id": "conversation.claude",
            "ai_task_entity_id": "ai_task.anthropic",
        }
    }
    coordinator.growspaces = {}
    coordinator.get_growspace_plants = MagicMock(return_value=[])
    coordinator.async_save = AsyncMock()
    coordinator.strain_library = MagicMock()
    return coordinator


def _make_mock_growspace(
    growspace_id="tent1",
    camera_entities=None,
    lights_on_time="06:00:00",
    veg_day_hours=18,
    flower_day_hours=12,
    vision_enabled=True,
):
    """Create a mock growspace with configurable settings."""
    from custom_components.growspace_manager.models import (
        EnvironmentConfig,
        IrrigationStrategy,
        VisionCheckupConfig,
    )

    gs = MagicMock()
    gs.id = growspace_id
    gs.name = "Test Tent"
    gs.vision_checkup_history = []

    env_config = MagicMock(spec=EnvironmentConfig)
    env_config.camera_entities = camera_entities if camera_entities is not None else ["camera.tent1_cam"]
    env_config.veg_day_hours = veg_day_hours
    env_config.flower_day_hours = flower_day_hours
    env_config.vision_checkup_config = VisionCheckupConfig(enabled=vision_enabled)

    gs.environment_config = env_config

    irrigation = MagicMock(spec=IrrigationStrategy)
    irrigation.lights_on_time = lights_on_time
    gs.irrigation_strategy = irrigation

    return gs


@pytest.mark.asyncio
async def test_run_vision_analysis_calls_ai_task(mock_hass, mock_coordinator):
    """Test that vision analysis calls async_generate_data with camera attachments."""
    gs = _make_mock_growspace()
    mock_coordinator.growspaces = {"tent1": gs}

    minimal_context = {
        "growspace": {"id": "tent1", "name": "Test Tent", "size": "3x3", "total_plants": 4},
        "environment": {"sensors": {"temperature_sensor": "25.5 C"}},
        "analysis": {
            "stress": {"active": False, "reasons": []},
            "mold_risk": {"active": False, "reasons": []},
            "optimal": {"active": True, "reasons": []},
            "light_schedule": {"correct": True},
        },
        "plants": {
            "count": 4,
            "stages": {"flower": 4},
            "strains": ["OG Kush"],
            "max_veg_days": 28,
            "max_flower_days": 35,
        },
        "strain_analytics": {},
    }

    mock_result = MagicMock()
    mock_result.data = {
        "analysis": "Plants look healthy with good coloring.",
        "issues_detected": [],
        "severity": "none",
        "recommendations": ["Continue current feeding schedule."],
    }

    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)

    with (
        patch(
            "custom_components.growspace_manager.vision_checkup_scheduler.async_generate_data",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_gen,
        patch.object(scheduler, "_gather_context_data", return_value=minimal_context),
    ):
        result = await scheduler.run_vision_analysis("tent1", "mid")

    assert result is not None
    assert result.check_type == "mid"
    assert result.growspace_id == "tent1"
    assert result.analysis == "Plants look healthy with good coloring."
    assert result.severity == "none"

    mock_gen.assert_called_once()
    call_kwargs = mock_gen.call_args.kwargs
    assert call_kwargs["task_name"] == "growspace_vision_checkup"
    assert len(call_kwargs["attachments"]) == 1
    assert "camera.tent1_cam" in call_kwargs["attachments"][0]["media_content_id"]


@pytest.mark.asyncio
async def test_run_vision_analysis_no_cameras_returns_none(mock_hass, mock_coordinator):
    """Test that vision analysis returns None when no cameras configured."""
    gs = _make_mock_growspace(camera_entities=[])
    mock_coordinator.growspaces = {"tent1": gs}

    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)
    result = await scheduler.run_vision_analysis("tent1", "mid")

    assert result is None


@pytest.mark.asyncio
async def test_run_vision_analysis_growspace_not_found(mock_hass, mock_coordinator):
    """Test that vision analysis returns None when growspace not found."""
    mock_coordinator.growspaces = {}
    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)
    result = await scheduler.run_vision_analysis("nonexistent", "mid")

    assert result is None


@pytest.mark.asyncio
async def test_run_vision_analysis_stores_result_in_history(mock_hass, mock_coordinator):
    """Test that vision analysis result is stored in growspace history."""
    gs = _make_mock_growspace()
    mock_coordinator.growspaces = {"tent1": gs}

    mock_result = MagicMock()
    mock_result.data = {
        "analysis": "Minor leaf drooping detected.",
        "issues_detected": ["leaf_drooping"],
        "severity": "low",
        "recommendations": ["Check watering schedule."],
    }

    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)

    minimal_context = {
        "growspace": {"id": "tent1", "name": "Test Tent", "size": "3x3", "total_plants": 0},
        "environment": {"sensors": {}},
        "analysis": {
            "stress": {"active": False, "reasons": []},
            "mold_risk": {"active": False, "reasons": []},
            "optimal": {"active": False, "reasons": []},
            "light_schedule": {"correct": True},
        },
        "plants": {"count": 0, "stages": {}, "strains": [], "max_veg_days": 0, "max_flower_days": 0},
        "strain_analytics": {},
    }

    with (
        patch(
            "custom_components.growspace_manager.vision_checkup_scheduler.async_generate_data",
            new_callable=AsyncMock,
            return_value=mock_result,
        ),
        patch.object(scheduler, "_gather_context_data", return_value=minimal_context),
    ):
        result = await scheduler.run_vision_analysis("tent1", "mid")

    assert result is not None
    assert len(gs.vision_checkup_history) == 1
    assert gs.vision_checkup_history[0].severity == "low"
    mock_coordinator.async_save.assert_called_once()


@pytest.mark.asyncio
async def test_run_vision_analysis_ai_failure_returns_none(mock_hass, mock_coordinator):
    """Test that AI failure returns None gracefully."""
    gs = _make_mock_growspace()
    mock_coordinator.growspaces = {"tent1": gs}

    minimal_context = {
        "growspace": {"id": "tent1", "name": "Test Tent", "size": "3x3", "total_plants": 0},
        "environment": {"sensors": {}},
        "analysis": {
            "stress": {"active": False, "reasons": []},
            "mold_risk": {"active": False, "reasons": []},
            "optimal": {"active": False, "reasons": []},
            "light_schedule": {"correct": True},
        },
        "plants": {"count": 0, "stages": {}, "strains": [], "max_veg_days": 0, "max_flower_days": 0},
        "strain_analytics": {},
    }

    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)

    with (
        patch(
            "custom_components.growspace_manager.vision_checkup_scheduler.async_generate_data",
            new_callable=AsyncMock,
            side_effect=Exception("AI service unavailable"),
        ),
        patch.object(scheduler, "_gather_context_data", return_value=minimal_context),
    ):
        result = await scheduler.run_vision_analysis("tent1", "mid")

    assert result is None
