"""Tests for the VisionCheckupScheduler time calculation logic."""

from __future__ import annotations

from datetime import UTC, time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.vision_checkup_scheduler import (
    VisionCheckupScheduler,
    calculate_checkup_times,
)
from homeassistant.core import HomeAssistant


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

    assert times["early"] == time(7, 0)  # 06:00 + 1h
    assert times["mid"] == time(12, 0)  # 06:00 + 6h
    assert times["late"] == time(23, 0)  # 06:00 + 18h - 1h = 23:00


def test_calculate_checkup_times_flower_12_12():
    """Test checkup times for 12/12 flowering cycle with lights on at 06:00."""
    times = calculate_checkup_times(
        lights_on_time=time(6, 0),
        day_hours=12,
        early_offset_minutes=60,
        mid_check_hours=6,
        late_offset_minutes=60,
    )

    assert times["early"] == time(7, 0)  # 06:00 + 1h
    assert times["mid"] == time(12, 0)  # 06:00 + 6h
    assert times["late"] == time(17, 0)  # 06:00 + 12h - 1h = 17:00


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
    assert times["mid"] == time(2, 0)  # 20:00 + 6h = 02:00 next day
    assert times["late"] == time(13, 0)  # 20:00 + 18h - 1h = 13:00 next day


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
    assert times["mid"] == time(0, 0)  # 18:00 + 6h = 00:00
    assert times["late"] == time(5, 0)  # 18:00 + 12h - 1h = 05:00


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
    env_config.camera_entities = (
        camera_entities if camera_entities is not None else ["camera.tent1_cam"]
    )
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
        "growspace": {
            "id": "tent1",
            "name": "Test Tent",
            "size": "3x3",
            "total_plants": 4,
        },
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
async def test_run_vision_analysis_stores_result_in_history(
    mock_hass, mock_coordinator
):
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
        "growspace": {
            "id": "tent1",
            "name": "Test Tent",
            "size": "3x3",
            "total_plants": 0,
        },
        "environment": {"sensors": {}},
        "analysis": {
            "stress": {"active": False, "reasons": []},
            "mold_risk": {"active": False, "reasons": []},
            "optimal": {"active": False, "reasons": []},
            "light_schedule": {"correct": True},
        },
        "plants": {
            "count": 0,
            "stages": {},
            "strains": [],
            "max_veg_days": 0,
            "max_flower_days": 0,
        },
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
        "growspace": {
            "id": "tent1",
            "name": "Test Tent",
            "size": "3x3",
            "total_plants": 0,
        },
        "environment": {"sensors": {}},
        "analysis": {
            "stress": {"active": False, "reasons": []},
            "mold_risk": {"active": False, "reasons": []},
            "optimal": {"active": False, "reasons": []},
            "light_schedule": {"correct": True},
        },
        "plants": {
            "count": 0,
            "stages": {},
            "strains": [],
            "max_veg_days": 0,
            "max_flower_days": 0,
        },
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


def test_schedule_growspace_creates_three_timers(mock_hass, mock_coordinator):
    """Test that scheduling a growspace creates 3 timers (early, mid, late)."""
    from custom_components.growspace_manager.vision_checkup_scheduler import (
        VisionCheckupScheduler,
    )

    gs = _make_mock_growspace(vision_enabled=True)
    mock_coordinator.growspaces = {"tent1": gs}

    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)

    with patch(
        "custom_components.growspace_manager.vision_checkup_scheduler.async_track_point_in_utc_time",
    ) as mock_track:
        mock_track.return_value = MagicMock()
        with patch(
            "custom_components.growspace_manager.vision_checkup_scheduler.ha_now",
        ) as mock_now:
            from datetime import datetime

            mock_now.return_value = datetime(2026, 3, 21, 10, 0, 0, tzinfo=UTC)
            scheduler.schedule_growspace("tent1")

    assert mock_track.call_count == 3
    assert "tent1" in scheduler._unsub_timers
    assert len(scheduler._unsub_timers["tent1"]) == 3


def test_schedule_growspace_skips_disabled_vision(mock_hass, mock_coordinator):
    """Test that scheduling skips growspaces with vision disabled."""
    from custom_components.growspace_manager.vision_checkup_scheduler import (
        VisionCheckupScheduler,
    )

    gs = _make_mock_growspace(vision_enabled=False)
    mock_coordinator.growspaces = {"tent1": gs}

    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)

    with patch(
        "custom_components.growspace_manager.vision_checkup_scheduler.async_track_point_in_utc_time",
    ) as mock_track:
        scheduler.schedule_growspace("tent1")

    mock_track.assert_not_called()
    assert "tent1" not in scheduler._unsub_timers


def test_schedule_growspace_skips_no_cameras(mock_hass, mock_coordinator):
    """Test that scheduling skips growspaces with no cameras."""
    from custom_components.growspace_manager.vision_checkup_scheduler import (
        VisionCheckupScheduler,
    )

    gs = _make_mock_growspace(camera_entities=[])
    mock_coordinator.growspaces = {"tent1": gs}

    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)

    with patch(
        "custom_components.growspace_manager.vision_checkup_scheduler.async_track_point_in_utc_time",
    ) as mock_track:
        scheduler.schedule_growspace("tent1")

    mock_track.assert_not_called()


def test_async_stop_cancels_all_timers(mock_hass, mock_coordinator):
    """Test that async_stop cancels all registered timers."""
    from custom_components.growspace_manager.vision_checkup_scheduler import (
        VisionCheckupScheduler,
    )

    mock_unsub_1 = MagicMock()
    mock_unsub_2 = MagicMock()
    mock_unsub_3 = MagicMock()

    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)
    scheduler._unsub_timers = {
        "tent1": [mock_unsub_1, mock_unsub_2, mock_unsub_3],
    }

    scheduler.async_stop()

    mock_unsub_1.assert_called_once()
    mock_unsub_2.assert_called_once()
    mock_unsub_3.assert_called_once()
    assert scheduler._unsub_timers == {}


@pytest.mark.asyncio
async def test_get_active_day_hours_flower(mock_hass, mock_coordinator):
    """Test getting active day hours when a plant is in flower."""
    from custom_components.growspace_manager.vision_checkup_scheduler import (
        VisionCheckupScheduler,
    )

    gs = _make_mock_growspace()
    plant = MagicMock()
    plant.stage = "flower"
    mock_coordinator.get_growspace_plants.return_value = [plant]
    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)
    assert scheduler._get_active_day_hours(gs) == 12


def test_get_lights_on_time_fallback(mock_hass, mock_coordinator):
    """Test fallback when lights on time misses seconds."""
    from custom_components.growspace_manager.vision_checkup_scheduler import (
        VisionCheckupScheduler,
    )

    gs = _make_mock_growspace(lights_on_time="06:30")
    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)
    assert scheduler._get_lights_on_time(gs) == time(6, 30)


@pytest.mark.asyncio
async def test_run_vision_analysis_context_exception(mock_hass, mock_coordinator):
    """Test fallback context when context gathering fails."""
    from custom_components.growspace_manager.vision_checkup_scheduler import (
        VisionCheckupScheduler,
    )

    gs = _make_mock_growspace()
    mock_coordinator.growspaces = {"tent1": gs}
    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)

    with (
        patch.object(
            scheduler, "_gather_context_data", side_effect=Exception("DB Error")
        ),
        patch(
            "custom_components.growspace_manager.vision_checkup_scheduler.async_generate_data",
            new_callable=AsyncMock,
        ) as mock_gen,
    ):
        mock_result = MagicMock()
        mock_result.data = {"analysis": "Fallback analysis", "severity": "none"}
        mock_gen.return_value = mock_result

        result = await scheduler.run_vision_analysis("tent1", "early")

        # Verify it still runs and returns a result using the fallback context
        assert result is not None
        assert result.analysis == "Fallback analysis"


def test_build_vision_prompt_with_history(mock_hass, mock_coordinator):
    """Test prompt building includes previous trend history."""
    from custom_components.growspace_manager.models import VisionCheckupResult
    from custom_components.growspace_manager.vision_checkup_scheduler import (
        VisionCheckupScheduler,
    )

    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)

    context = {"growspace": {"name": "test", "id": "t1"}}

    prev = VisionCheckupResult(
        timestamp="2026-03-21T12:00:00",
        growspace_id="t1",
        check_type="mid",
        snapshot_paths=[],
        analysis="Good",
        issues_detected=["spot"],
        severity="low",
        recommendations=[],
    )

    with patch(
        "custom_components.growspace_manager.services.ai_assistant.GrowAssistant._format_context_data",
        return_value="Context Formatting",
    ):
        prompt = scheduler._build_vision_prompt("t1", "early", context, [prev])
        assert "PREVIOUS CHECKUP HISTORY" in prompt
        assert "severity=low" in prompt
        assert "issues=spot" in prompt


def test_schedule_growspace_missing_growspace(mock_hass, mock_coordinator):
    """Test scheduling handles missing growspace."""
    from custom_components.growspace_manager.vision_checkup_scheduler import (
        VisionCheckupScheduler,
    )

    mock_coordinator.growspaces = {}
    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)

    with patch(
        "custom_components.growspace_manager.vision_checkup_scheduler.async_track_point_in_utc_time"
    ) as mock_track:
        scheduler.schedule_growspace("missing")
        mock_track.assert_not_called()


@pytest.mark.asyncio
async def test_callback_exception_reschedules(mock_hass, mock_coordinator):
    """Test callback catches exceptions and still reschedules."""
    from datetime import datetime

    from custom_components.growspace_manager.vision_checkup_scheduler import (
        VisionCheckupScheduler,
    )

    gs = _make_mock_growspace()
    mock_coordinator.growspaces = {"tent1": gs}
    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)

    callback = scheduler._create_checkup_callback("tent1", "early")

    with (
        patch.object(
            scheduler, "run_vision_analysis", side_effect=Exception("API Error")
        ),
        patch.object(scheduler, "schedule_growspace") as mock_schedule,
    ):
        await callback(datetime.now())
        mock_schedule.assert_called_once_with("tent1")


@pytest.mark.asyncio
async def test_send_vision_notification_no_target(mock_hass, mock_coordinator):
    """Test notification exits if no target configured."""
    from custom_components.growspace_manager.vision_checkup_scheduler import (
        VisionCheckupScheduler,
    )

    gs = _make_mock_growspace()
    gs.notification_target = None
    mock_coordinator.growspaces = {"tent1": gs}
    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)

    result = MagicMock()
    mock_call = AsyncMock()
    mock_hass.services = MagicMock()
    mock_hass.services.async_call = mock_call
    await scheduler._send_vision_notification("tent1", result)
    mock_call.assert_not_called()


@pytest.mark.asyncio
async def test_send_vision_notification_exception(mock_hass, mock_coordinator):
    """Test notification handles exceptions gracefully."""
    from custom_components.growspace_manager.models import VisionCheckupResult
    from custom_components.growspace_manager.vision_checkup_scheduler import (
        VisionCheckupScheduler,
    )

    gs = _make_mock_growspace()
    gs.notification_target = "notify.mobile_app"
    mock_coordinator.growspaces = {"tent1": gs}
    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)

    result = VisionCheckupResult(
        timestamp="2026-03-21T12:00:00",
        growspace_id="tent1",
        check_type="mid",
        snapshot_paths=[],
        analysis="Bad",
        issues_detected=["bug"],
        severity="critical",
        recommendations=["fix"],
    )

    mock_call = AsyncMock(side_effect=Exception("Call failed"))
    mock_hass.services = MagicMock()
    mock_hass.services.async_call = mock_call
    await scheduler._send_vision_notification("tent1", result)
    mock_call.assert_called_once()
    # Should complete without raising


def test_gather_context_data(mock_hass, mock_coordinator):
    """Test gathering context data uses the assistant."""
    from custom_components.growspace_manager.vision_checkup_scheduler import (
        VisionCheckupScheduler,
    )

    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)
    with patch(
        "custom_components.growspace_manager.services.ai_assistant.GrowAssistant.gather_growspace_data"
    ) as mock_gather:
        mock_gather.return_value = {"a": 1}
        res = scheduler._gather_context_data("tent1")
        assert res == {"a": 1}
        mock_gather.assert_called_once_with("tent1")


@pytest.mark.asyncio
async def test_callback_triggers_notification(mock_hass, mock_coordinator):
    """Test callback triggers notification on high severity."""
    from datetime import datetime

    from custom_components.growspace_manager.vision_checkup_scheduler import (
        VisionCheckupScheduler,
    )

    gs = _make_mock_growspace()
    mock_coordinator.growspaces = {"tent1": gs}
    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)
    callback = scheduler._create_checkup_callback("tent1", "early")

    mock_result = MagicMock()
    mock_result.severity = "critical"

    with (
        patch.object(scheduler, "run_vision_analysis", return_value=mock_result),
        patch.object(
            scheduler, "_send_vision_notification", new_callable=AsyncMock
        ) as mock_notify,
        patch.object(scheduler, "schedule_growspace"),
    ):
        await callback(datetime.now())
        mock_notify.assert_called_once_with("tent1", mock_result)
