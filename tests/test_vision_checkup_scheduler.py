"""Tests for the VisionCheckupScheduler time calculation logic."""

from __future__ import annotations

from datetime import UTC, datetime, time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    IrrigationStrategy,
    VisionCheckupConfig,
    VisionCheckupResult,
)
from custom_components.growspace_manager.vision_checkup_scheduler import (
    VisionCheckupScheduler,
    calculate_checkup_times,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError


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
    assert scheduler._latest_public_paths == {}


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
    coordinator.async_commit = AsyncMock()
    coordinator._strain_library = MagicMock()
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
        patch.object(
            scheduler,
            "_process_camera_images",
            new_callable=AsyncMock,
            return_value=([], None, []),
        ),
        patch(
            "homeassistant.components.ai_task.async_generate_data",
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
    # Without a structure schema, ai_task returns .data as raw text (not a dict),
    # which breaks the data.get(...) parsing below. Lock the schema in.
    from custom_components.growspace_manager.vision_checkup_scheduler import (
        VISION_RESULT_SCHEMA,
    )

    assert call_kwargs["structure"] is VISION_RESULT_SCHEMA


@pytest.mark.asyncio
async def test_run_vision_analysis_no_cameras_raises_error(mock_hass, mock_coordinator):
    """Test that vision analysis raises ServiceValidationError when no cameras configured."""

    gs = _make_mock_growspace(camera_entities=[])
    mock_coordinator.growspaces = {"tent1": gs}

    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)
    with pytest.raises(ServiceValidationError, match="No cameras configured"):
        await scheduler.run_vision_analysis("tent1", "mid")


@pytest.mark.asyncio
async def test_run_vision_analysis_growspace_not_found(mock_hass, mock_coordinator):
    """Test that vision analysis raises ServiceValidationError when growspace not found."""

    mock_coordinator.growspaces = {}
    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)

    with pytest.raises(
        ServiceValidationError, match="Growspace 'nonexistent' not found"
    ):
        await scheduler.run_vision_analysis("nonexistent", "mid")


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
        patch.object(
            scheduler,
            "_process_camera_images",
            new_callable=AsyncMock,
            return_value=([], None, []),
        ),
        patch(
            "homeassistant.components.ai_task.async_generate_data",
            new_callable=AsyncMock,
            return_value=mock_result,
        ),
        patch.object(scheduler, "_gather_context_data", return_value=minimal_context),
    ):
        result = await scheduler.run_vision_analysis("tent1", "mid")

    assert result is not None
    assert len(gs.vision_checkup_history) == 1
    assert gs.vision_checkup_history[0].severity == "low"
    mock_coordinator.async_commit.assert_called_once()


@pytest.mark.asyncio
async def test_run_vision_analysis_ai_failure_raises_error(mock_hass, mock_coordinator):
    """Test that AI failure raises HomeAssistantError."""

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
        patch.object(
            scheduler,
            "_process_camera_images",
            new_callable=AsyncMock,
            return_value=([], None, []),
        ),
        patch(
            "homeassistant.components.ai_task.async_generate_data",
            new_callable=AsyncMock,
            side_effect=Exception("AI service unavailable"),
        ),
        patch.object(scheduler, "_gather_context_data", return_value=minimal_context),
    ):
        with pytest.raises(HomeAssistantError, match="AI vision analysis failed"):
            await scheduler.run_vision_analysis("tent1", "mid")


def test_schedule_growspace_creates_three_timers(mock_hass, mock_coordinator):
    """Test that scheduling a growspace creates 3 timers (early, mid, late)."""

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
            mock_now.return_value = datetime(2026, 3, 21, 10, 0, 0, tzinfo=UTC)
            scheduler.schedule_growspace("tent1")

    assert mock_track.call_count == 3
    assert "tent1" in scheduler._unsub_timers
    assert len(scheduler._unsub_timers["tent1"]) == 3


def test_schedule_growspace_skips_disabled_vision(mock_hass, mock_coordinator):
    """Test that scheduling skips growspaces with vision disabled."""

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
    """Test getting active day hours when a plant has entered flower.

    Resolution must key off ``flower_start`` (like the grow light
    controller), not the cached ``plant.stage`` attribute, since the latter
    is only set once at plant creation and never updated on flip.
    """

    gs = _make_mock_growspace()
    plant = MagicMock()
    plant.flower_start = "2000-01-01"
    mock_coordinator.services.growspaces.get_growspace_plants.return_value = [plant]
    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)
    assert scheduler._get_active_day_hours(gs) == 12


@pytest.mark.asyncio
async def test_get_active_day_hours_stale_stage_ignored(mock_hass, mock_coordinator):
    """A stale ``plant.stage`` of "flower" must not override flower_start.

    Regression test: the vision scheduler previously trusted the cached
    ``plant.stage`` attribute, which desynced from the actual grow light
    schedule (driven by ``flower_start``) once a plant had been created,
    producing checkup times that landed hours after lights had already
    turned off.
    """

    gs = _make_mock_growspace()
    plant = MagicMock()
    plant.stage = "flower"
    plant.flower_start = None
    mock_coordinator.services.growspaces.get_growspace_plants.return_value = [plant]
    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)
    assert scheduler._get_active_day_hours(gs) == 18


def test_get_lights_on_time_fallback(mock_hass, mock_coordinator):
    """Test fallback when lights on time misses seconds."""

    gs = _make_mock_growspace(lights_on_time="06:30")
    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)
    assert scheduler._get_lights_on_time(gs) == time(6, 30)


@pytest.mark.asyncio
async def test_run_vision_analysis_context_exception(mock_hass, mock_coordinator):
    """Test fallback context when context gathering fails."""

    gs = _make_mock_growspace()
    mock_coordinator.growspaces = {"tent1": gs}
    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)

    mock_result = MagicMock()
    mock_result.data = {"analysis": "Fallback analysis", "severity": "none"}

    with (
        patch.object(
            scheduler, "_gather_context_data", side_effect=Exception("DB Error")
        ),
        patch.object(
            scheduler,
            "_process_camera_images",
            new_callable=AsyncMock,
            return_value=([], None, []),
        ),
        patch(
            "homeassistant.components.ai_task.async_generate_data",
            new_callable=AsyncMock,
            return_value=mock_result,
        ),
    ):
        result = await scheduler.run_vision_analysis("tent1", "early")

    # Verify it still runs and returns a result using the fallback context
    assert result is not None
    assert result.analysis == "Fallback analysis"


def test_build_vision_prompt_with_history(mock_hass, mock_coordinator):
    """Test prompt building includes previous trend history."""

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

    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)
    with patch(
        "custom_components.growspace_manager.services.ai_assistant.GrowAssistant.gather_growspace_data"
    ) as mock_gather:
        mock_gather.return_value = {"a": 1}
        res = scheduler._gather_context_data("tent1")
        assert res == {"a": 1}
        mock_gather.assert_called_once_with("tent1")


# ---------------------------------------------------------------------------
# Shared helpers for image-processing tests
# ---------------------------------------------------------------------------


def _minimal_context() -> dict:
    """Return a minimal context dict accepted by run_vision_analysis."""
    return {
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


@pytest.fixture
def hass_with_executor(mock_hass, tmp_path):
    """Extend mock_hass with a functional executor and config.path backed by tmp_path."""
    # MagicMock(spec=HomeAssistant) blocks instance-only attrs; set config explicitly.
    mock_hass.config = MagicMock()
    mock_hass.config.path.side_effect = lambda *parts: str(tmp_path.joinpath(*parts))
    # HA core always populates media_dirs; the local source resolves snapshots here.
    mock_hass.config.media_dirs = {"local": str(tmp_path / "media")}

    async def fake_executor(func, *args):
        return func(*args)

    mock_hass.async_add_executor_job = fake_executor
    return mock_hass


# ---------------------------------------------------------------------------
# _process_camera_images tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_camera_images_returns_media_source_uris(
    hass_with_executor, mock_coordinator
):
    """Processed images are referenced via media-source://media_source/local/... URIs."""
    scheduler = VisionCheckupScheduler(hass_with_executor, mock_coordinator)

    mock_image = MagicMock()
    mock_image.content = b"\xff\xd8\xff\xe0fake"

    with (
        patch(
            "homeassistant.components.camera.async_get_image",
            new_callable=AsyncMock,
            return_value=mock_image,
        ),
        patch(
            "custom_components.growspace_manager.image_processor.GrowspaceImageProcessor.process_snapshot",
            return_value=(b"\xff\xd8\xff\xe0processed", 42.5),
        ),
    ):
        attachments, coverage, temp_paths = await scheduler._process_camera_images(
            "tent1", ["camera.tent1_cam"]
        )

    assert len(attachments) == 1
    uri = attachments[0]["media_content_id"]
    assert uri.startswith("media-source://media_source/local/growspace_vision/")
    assert "tent1" in uri
    assert uri.endswith(".jpg")
    assert coverage == 42.5
    assert len(temp_paths) == 1


@pytest.mark.asyncio
async def test_process_camera_images_saves_under_media_source_root(
    mock_hass, mock_coordinator, tmp_path
):
    """Snapshots are written to the dir the local media-source resolves to.

    In a Docker/HA-OS env config.path("media") (<config>/media) differs from
    hass.config.media_dirs["local"] (/media). Writing to the former while
    referencing media-source://media_source/local/... made the AI task fail
    with "does not exist". The write dir and the URI source must agree.
    """
    config_media = tmp_path / "config" / "media"
    local_media_root = tmp_path / "media"  # what media_dirs["local"] points to

    mock_hass.config = MagicMock()
    mock_hass.config.path.side_effect = lambda *parts: str(
        (tmp_path / "config").joinpath(*parts)
    )
    mock_hass.config.media_dirs = {"local": str(local_media_root)}

    async def fake_executor(func, *args):
        return func(*args)

    mock_hass.async_add_executor_job = fake_executor

    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)

    mock_image = MagicMock()
    mock_image.content = b"\xff\xd8\xff\xe0fake"

    with (
        patch(
            "homeassistant.components.camera.async_get_image",
            new_callable=AsyncMock,
            return_value=mock_image,
        ),
        patch(
            "custom_components.growspace_manager.image_processor.GrowspaceImageProcessor.process_snapshot",
            return_value=(b"\xff\xd8\xff\xe0processed", 42.5),
        ),
    ):
        attachments, _, temp_paths = await scheduler._process_camera_images(
            "tent1", ["camera.tent1_cam"]
        )

    assert len(temp_paths) == 1
    saved = temp_paths[0]
    # The file must live under the local media-source root, not <config>/media.
    assert saved.is_relative_to(local_media_root)
    assert not saved.is_relative_to(config_media)
    assert saved.exists()
    # The URI source id must match where the bytes were actually written.
    assert attachments[0]["media_content_id"].startswith(
        "media-source://media_source/local/growspace_vision/"
    )
    # A permanent copy is also written under <config>/www for the frontend.
    snapshot_dir = (
        tmp_path / "config" / "www" / "growspace_manager" / "snapshots" / "tent1"
    )
    snapshots = list(snapshot_dir.glob("*_processed.jpg"))
    assert len(snapshots) == 1
    assert scheduler._latest_public_paths["tent1"] == [
        f"/local/growspace_manager/snapshots/tent1/{snapshots[0].name}"
    ]


@pytest.mark.asyncio
async def test_process_camera_images_averages_coverage_across_cameras(
    hass_with_executor, mock_coordinator
):
    """Average coverage is computed across all successfully processed cameras."""
    scheduler = VisionCheckupScheduler(hass_with_executor, mock_coordinator)

    mock_image = MagicMock()
    mock_image.content = b"\xff\xd8\xff\xe0fake"

    coverages = iter([30.0, 70.0])

    with (
        patch(
            "homeassistant.components.camera.async_get_image",
            new_callable=AsyncMock,
            return_value=mock_image,
        ),
        patch(
            "custom_components.growspace_manager.image_processor.GrowspaceImageProcessor.process_snapshot",
            side_effect=lambda _: (b"\xff\xd8\xff\xe0ok", next(coverages)),
        ),
    ):
        _, coverage, _ = await scheduler._process_camera_images(
            "tent1", ["camera.cam1", "camera.cam2"]
        )

    assert coverage == 50.0


@pytest.mark.asyncio
async def test_process_camera_images_skips_failed_camera_fetch(
    hass_with_executor, mock_coordinator
):
    """A camera that fails to provide an image is skipped; others are processed."""
    scheduler = VisionCheckupScheduler(hass_with_executor, mock_coordinator)

    mock_image = MagicMock()
    mock_image.content = b"\xff\xd8\xff\xe0fake"

    with (
        patch(
            "homeassistant.components.camera.async_get_image",
            new_callable=AsyncMock,
            side_effect=[Exception("camera offline"), mock_image],
        ),
        patch(
            "custom_components.growspace_manager.image_processor.GrowspaceImageProcessor.process_snapshot",
            return_value=(b"\xff\xd8\xff\xe0ok", 55.0),
        ),
    ):
        attachments, coverage, _ = await scheduler._process_camera_images(
            "tent1", ["camera.dead", "camera.live"]
        )

    assert len(attachments) == 1
    assert coverage == 55.0


@pytest.mark.asyncio
async def test_process_camera_images_skips_failed_processing(
    hass_with_executor, mock_coordinator
):
    """A camera whose image fails to process is skipped; others are still used."""
    scheduler = VisionCheckupScheduler(hass_with_executor, mock_coordinator)

    mock_image = MagicMock()
    mock_image.content = b"\xff\xd8\xff\xe0fake"

    with (
        patch(
            "homeassistant.components.camera.async_get_image",
            new_callable=AsyncMock,
            return_value=mock_image,
        ),
        patch(
            "custom_components.growspace_manager.image_processor.GrowspaceImageProcessor.process_snapshot",
            side_effect=[ValueError("bad image"), (b"\xff\xd8\xff\xe0ok", 60.0)],
        ),
    ):
        attachments, coverage, _ = await scheduler._process_camera_images(
            "tent1", ["camera.bad", "camera.good"]
        )

    assert len(attachments) == 1
    assert coverage == 60.0


@pytest.mark.asyncio
async def test_process_camera_images_returns_empty_when_all_cameras_fail(
    hass_with_executor, mock_coordinator
):
    """Returns ([], None, []) when every camera fetch raises an exception."""
    scheduler = VisionCheckupScheduler(hass_with_executor, mock_coordinator)

    with patch(
        "homeassistant.components.camera.async_get_image",
        new_callable=AsyncMock,
        side_effect=Exception("all cameras offline"),
    ):
        attachments, coverage, temp_paths = await scheduler._process_camera_images(
            "tent1", ["camera.cam1", "camera.cam2"]
        )

    assert attachments == []
    assert coverage is None
    assert temp_paths == []


@pytest.mark.asyncio
async def test_process_camera_images_creates_output_directory(
    hass_with_executor, mock_coordinator, tmp_path
):
    """The growspace_vision media subdirectory is created on first use."""
    scheduler = VisionCheckupScheduler(hass_with_executor, mock_coordinator)

    expected_dir = tmp_path / "media" / "growspace_vision"
    assert not expected_dir.exists()

    mock_image = MagicMock()
    mock_image.content = b"\xff\xd8\xff\xe0fake"

    with (
        patch(
            "homeassistant.components.camera.async_get_image",
            new_callable=AsyncMock,
            return_value=mock_image,
        ),
        patch(
            "custom_components.growspace_manager.image_processor.GrowspaceImageProcessor.process_snapshot",
            return_value=(b"\xff\xd8\xff\xe0ok", 50.0),
        ),
    ):
        await scheduler._process_camera_images("tent1", ["camera.cam1"])

    assert expected_dir.exists()


# ---------------------------------------------------------------------------
# _build_vision_prompt — grid reference
# ---------------------------------------------------------------------------


def test_build_vision_prompt_makes_no_canopy_coverage_claim(
    mock_hass, mock_coordinator
):
    """The HSV green-pixel statistic is not stated to the model.

    It varies 31.5% inside one fixed camera's healthy bucket (hub#68), so
    presenting it as a measured fact alongside the image gave the model a
    quantity to reason from that does not mean what it appears to mean.
    """
    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)

    with patch(
        "custom_components.growspace_manager.services.ai_assistant.GrowAssistant._format_context_data",
        return_value="",
    ):
        prompt = scheduler._build_vision_prompt(
            "t1",
            "mid",
            {"growspace": {"name": "t", "id": "t1"}},
            [],
        )

    assert "CANOPY COVERAGE" not in prompt
    assert "HSV" not in prompt
    assert "green plant matter" not in prompt


def test_build_vision_prompt_includes_grid_sector_instructions(
    mock_hass, mock_coordinator
):
    """The prompt instructs the AI to reference grid sector labels for any issue."""
    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)

    with patch(
        "custom_components.growspace_manager.services.ai_assistant.GrowAssistant._format_context_data",
        return_value="",
    ):
        prompt = scheduler._build_vision_prompt(
            "t1", "mid", {"growspace": {"name": "t", "id": "t1"}}, []
        )

    assert "GRID REFERENCE" in prompt
    assert "A1" in prompt
    assert "D4" in prompt


# ---------------------------------------------------------------------------
# run_vision_analysis — image processing integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_vision_analysis_uses_processed_image_attachments(
    mock_hass, mock_coordinator, tmp_path
):
    """run_vision_analysis passes the processed image URIs to async_generate_data."""
    gs = _make_mock_growspace()
    mock_coordinator.growspaces = {"tent1": gs}

    processed_uri = (
        "media-source://media_source/local/growspace_vision/tent1_20260101_120000_0.jpg"
    )
    fake_temp = tmp_path / "tent1_20260101_120000_0.jpg"
    fake_temp.write_bytes(b"test")

    mock_ai_result = MagicMock()
    mock_ai_result.data = {
        "analysis": "Healthy.",
        "issues_detected": [],
        "severity": "none",
        "recommendations": [],
    }

    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)

    with (
        patch.object(
            scheduler,
            "_process_camera_images",
            new_callable=AsyncMock,
            return_value=([{"media_content_id": processed_uri}], 55.0, [fake_temp]),
        ),
        patch(
            "homeassistant.components.ai_task.async_generate_data",
            new_callable=AsyncMock,
            return_value=mock_ai_result,
        ) as mock_gen,
        patch.object(
            scheduler, "_gather_context_data", return_value=_minimal_context()
        ),
    ):
        result = await scheduler.run_vision_analysis("tent1", "mid")

    assert result is not None
    assert mock_gen.call_args.kwargs["attachments"] == [
        {"media_content_id": processed_uri}
    ]


@pytest.mark.asyncio
async def test_run_vision_analysis_falls_back_to_raw_camera_uris_when_processing_fails(
    mock_hass, mock_coordinator
):
    """Falls back to raw camera URIs when _process_camera_images returns empty."""
    gs = _make_mock_growspace()
    mock_coordinator.growspaces = {"tent1": gs}

    mock_ai_result = MagicMock()
    mock_ai_result.data = {
        "analysis": "OK",
        "issues_detected": [],
        "severity": "none",
        "recommendations": [],
    }

    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)

    with (
        patch.object(
            scheduler,
            "_process_camera_images",
            new_callable=AsyncMock,
            return_value=([], None, []),
        ),
        patch(
            "homeassistant.components.ai_task.async_generate_data",
            new_callable=AsyncMock,
            return_value=mock_ai_result,
        ) as mock_gen,
        patch.object(
            scheduler, "_gather_context_data", return_value=_minimal_context()
        ),
    ):
        result = await scheduler.run_vision_analysis("tent1", "mid")

    assert result is not None
    attachment_uri = mock_gen.call_args.kwargs["attachments"][0]["media_content_id"]
    assert "camera.tent1_cam" in attachment_uri


@pytest.mark.asyncio
async def test_run_vision_analysis_snapshot_paths_contain_public_uris(
    hass_with_executor, mock_coordinator
):
    """snapshot_paths holds /local/... public URLs after real image processing."""
    gs = _make_mock_growspace()
    mock_coordinator.growspaces = {"tent1": gs}

    mock_image = MagicMock()
    mock_image.content = b"\xff\xd8\xff\xe0fake"

    mock_ai_result = MagicMock()
    mock_ai_result.data = {
        "analysis": "OK",
        "issues_detected": [],
        "severity": "none",
        "recommendations": [],
    }

    scheduler = VisionCheckupScheduler(hass_with_executor, mock_coordinator)

    with (
        patch(
            "homeassistant.components.camera.async_get_image",
            new_callable=AsyncMock,
            return_value=mock_image,
        ),
        patch(
            "custom_components.growspace_manager.image_processor.GrowspaceImageProcessor.process_snapshot",
            return_value=(b"\xff\xd8\xff\xe0processed", 55.0),
        ),
        patch(
            "homeassistant.components.ai_task.async_generate_data",
            new_callable=AsyncMock,
            return_value=mock_ai_result,
        ),
        patch.object(
            scheduler, "_gather_context_data", return_value=_minimal_context()
        ),
    ):
        result = await scheduler.run_vision_analysis("tent1", "mid")

    assert result is not None
    assert len(result.snapshot_paths) == 1
    assert result.snapshot_paths[0].startswith(
        "/local/growspace_manager/snapshots/tent1/"
    )
    assert result.snapshot_paths[0].endswith("_processed.jpg")
    # State is popped after use so it does not leak into the next run.
    assert "tent1" not in scheduler._latest_public_paths


@pytest.mark.asyncio
async def test_run_vision_analysis_deletes_temp_files_after_success(
    mock_hass, mock_coordinator, tmp_path
):
    """Temporary processed image files are deleted after a successful AI call."""
    gs = _make_mock_growspace()
    mock_coordinator.growspaces = {"tent1": gs}

    fake_temp = tmp_path / "vision_tmp.jpg"
    fake_temp.write_bytes(b"test")
    assert fake_temp.exists()

    mock_ai_result = MagicMock()
    mock_ai_result.data = {
        "analysis": "OK",
        "issues_detected": [],
        "severity": "none",
        "recommendations": [],
    }

    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)

    with (
        patch.object(
            scheduler,
            "_process_camera_images",
            new_callable=AsyncMock,
            return_value=(
                [
                    {
                        "media_content_id": "media-source://media_source/local/growspace_vision/tmp.jpg"
                    }
                ],
                50.0,
                [fake_temp],
            ),
        ),
        patch(
            "homeassistant.components.ai_task.async_generate_data",
            new_callable=AsyncMock,
            return_value=mock_ai_result,
        ),
        patch.object(
            scheduler, "_gather_context_data", return_value=_minimal_context()
        ),
    ):
        await scheduler.run_vision_analysis("tent1", "mid")

    assert not fake_temp.exists()


@pytest.mark.asyncio
async def test_run_vision_analysis_deletes_temp_files_after_ai_failure(
    mock_hass, mock_coordinator, tmp_path
):
    """Temporary files are cleaned up even when the AI call raises an exception."""
    gs = _make_mock_growspace()
    mock_coordinator.growspaces = {"tent1": gs}

    fake_temp = tmp_path / "vision_tmp.jpg"
    fake_temp.write_bytes(b"test")

    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)

    with (
        patch.object(
            scheduler,
            "_process_camera_images",
            new_callable=AsyncMock,
            return_value=(
                [{"media_content_id": "media-source://..."}],
                50.0,
                [fake_temp],
            ),
        ),
        patch(
            "homeassistant.components.ai_task.async_generate_data",
            new_callable=AsyncMock,
            side_effect=Exception("AI service down"),
        ),
        patch.object(
            scheduler, "_gather_context_data", return_value=_minimal_context()
        ),
    ):
        with pytest.raises(HomeAssistantError, match="AI vision analysis failed"):
            await scheduler.run_vision_analysis("tent1", "mid")

    assert not fake_temp.exists()


@pytest.mark.asyncio
async def test_callback_triggers_notification(mock_hass, mock_coordinator):
    """Test callback triggers notification on high severity."""

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


@pytest.mark.asyncio
async def test_process_camera_images_mkdir_oserror(
    hass_with_executor, mock_coordinator
):
    """Test OSError when creating media directory returns empty results."""
    scheduler = VisionCheckupScheduler(hass_with_executor, mock_coordinator)

    with patch("pathlib.Path.mkdir", side_effect=OSError("Permission denied")):
        attachments, coverage, temp_paths = await scheduler._process_camera_images(
            "tent1", ["camera.cam1"]
        )

    assert attachments == []
    assert coverage is None
    assert temp_paths == []


@pytest.mark.asyncio
async def test_process_camera_images_write_oserror(
    hass_with_executor, mock_coordinator, tmp_path
):
    """Test OSError when writing processed image saves other images but skips failed."""
    scheduler = VisionCheckupScheduler(hass_with_executor, mock_coordinator)

    mock_image = MagicMock()
    mock_image.content = b"fake"

    def mock_write_bytes(self, data):
        if "_0.jpg" in str(self):
            raise OSError("Disk full")
        # Let cam2 succeed by writing normally
        with open(self, "wb") as f:
            f.write(data)

    with (
        patch(
            "homeassistant.components.camera.async_get_image",
            new_callable=AsyncMock,
            return_value=mock_image,
        ),
        patch(
            "custom_components.growspace_manager.image_processor.GrowspaceImageProcessor.process_snapshot",
            return_value=(b"ok", 50.0),
        ),
        patch("pathlib.Path.write_bytes", new=mock_write_bytes),
    ):
        attachments, coverage, temp_paths = await scheduler._process_camera_images(
            "tent1", ["camera.cam1", "camera.cam2"]
        )

    # cam1 fails, cam2 succeeds
    assert len(attachments) == 1
    assert coverage == 50.0
    assert len(temp_paths) == 1


@pytest.mark.asyncio
async def test_run_vision_analysis_saves_debug_images(
    mock_hass, mock_coordinator, tmp_path
):
    """Test debug images are saved if debug enabled."""
    gs = _make_mock_growspace()
    mock_coordinator.growspaces = {"tent1": gs}
    mock_coordinator.options["ai_settings"]["vision_debug_enabled"] = True

    mock_hass.config = MagicMock()
    mock_hass.config.path.side_effect = lambda *parts: str(tmp_path.joinpath(*parts))

    async def fake_executor(func, *args):
        return func(*args)

    mock_hass.async_add_executor_job = fake_executor

    fake_temp = tmp_path / "vision_tmp.jpg"
    fake_temp.write_bytes(b"test")

    mock_ai_result = MagicMock()
    mock_ai_result.data = {"analysis": "OK", "severity": "none"}

    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)

    with (
        patch.object(
            scheduler,
            "_process_camera_images",
            new_callable=AsyncMock,
            return_value=(
                [{"media_content_id": "media-source://tmp"}],
                50.0,
                [fake_temp],
            ),
        ),
        patch(
            "homeassistant.components.ai_task.async_generate_data",
            new_callable=AsyncMock,
            return_value=mock_ai_result,
        ),
        patch.object(
            scheduler, "_gather_context_data", return_value=_minimal_context()
        ),
    ):
        await scheduler.run_vision_analysis("tent1", "mid")

    debug_dir = tmp_path / "openCVDebug"
    assert debug_dir.exists()
    assert (debug_dir / "vision_tmp.jpg").exists()
    assert not fake_temp.exists()  # Deleted correctly


@pytest.mark.asyncio
async def test_run_vision_analysis_debug_images_exception(
    mock_hass, mock_coordinator, tmp_path
):
    """Test debug image path exception and unlink exception."""
    gs = _make_mock_growspace()
    mock_coordinator.growspaces = {"tent1": gs}
    mock_coordinator.options["ai_settings"]["vision_debug_enabled"] = True

    mock_hass.config = MagicMock()
    mock_hass.config.path.side_effect = lambda *parts: str(tmp_path.joinpath(*parts))

    async def fake_executor(func, *args):
        return func(*args)

    mock_hass.async_add_executor_job = fake_executor

    fake_temp = tmp_path / "vision_tmp.jpg"
    fake_temp.write_bytes(b"test")

    mock_ai_result = MagicMock()
    mock_ai_result.data = {"analysis": "OK"}

    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)

    with (
        patch.object(
            scheduler,
            "_process_camera_images",
            new_callable=AsyncMock,
            return_value=(
                [{"media_content_id": "media-source://tmp"}],
                50.0,
                [fake_temp],
            ),
        ),
        patch(
            "homeassistant.components.ai_task.async_generate_data",
            new_callable=AsyncMock,
            return_value=mock_ai_result,
        ),
        patch.object(
            scheduler, "_gather_context_data", return_value=_minimal_context()
        ),
        patch("shutil.copy2", side_effect=Exception("Copy failed")),
        patch("pathlib.Path.unlink", side_effect=OSError("Cannot delete")),
    ):
        await scheduler.run_vision_analysis("tent1", "mid")

    # Should handle exceptions and complete gracefully
    assert fake_temp.exists()  # Could not be deleted due to OSError


@pytest.mark.asyncio
async def test_run_vision_analysis_no_ai_entity(mock_hass, mock_coordinator):
    """Test that vision analysis raises ServiceValidationError when no AI entity configured (vision_checkup_scheduler.py:439)."""

    mock_coordinator.options = {"ai_settings": {}}  # No ai_task_entity_id
    gs = _make_mock_growspace(camera_entities=["camera.tent1_cam"])
    mock_coordinator.growspaces = {"tent1": gs}

    scheduler = VisionCheckupScheduler(mock_hass, mock_coordinator)
    with pytest.raises(ServiceValidationError, match="No AI task entity configured"):
        await scheduler.run_vision_analysis("tent1", "mid")
