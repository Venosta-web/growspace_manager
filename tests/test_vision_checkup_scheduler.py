"""Scheduling behavior for evidence-based Vision Checkups."""

from datetime import UTC, datetime, time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.vision_checkup_scheduler import (
    VisionCheckupScheduler,
    calculate_checkup_times,
)
from custom_components.growspace_manager.vision_connection import (
    VisionAvailability,
    VisionConnectionSource,
    VisionStatus,
)
from homeassistant.exceptions import ServiceValidationError


def test_calculate_checkup_times_for_18_hour_cycle() -> None:
    assert calculate_checkup_times(time(6), 18) == {
        "early": time(7),
        "mid": time(12),
        "late": time(23),
    }


def _growspace(*, enabled: bool = True, cameras: list[str] | None = None):
    return SimpleNamespace(
        id="tent1",
        environment_config=SimpleNamespace(
            camera_entities=cameras if cameras is not None else ["camera.canopy"],
            veg_day_hours=18,
            flower_day_hours=12,
            vision_checkup_config=SimpleNamespace(
                enabled=enabled,
                early_check_offset_minutes=60,
                mid_check_hours=6,
                late_check_offset_minutes=60,
            ),
        ),
        irrigation_strategy=SimpleNamespace(lights_on_time="06:00:00"),
    )


def _coordinator(growspace=None):
    services = SimpleNamespace(
        growspaces=SimpleNamespace(get_growspace_plants=MagicMock(return_value=[]))
    )
    return SimpleNamespace(
        growspaces={"tent1": growspace or _growspace()},
        services=services,
        options={},
    )


def test_schedule_registers_three_one_shot_timers() -> None:
    scheduler = VisionCheckupScheduler(MagicMock(), _coordinator())
    with (
        patch(
            "custom_components.growspace_manager.vision_checkup_scheduler.ha_now",
            return_value=datetime(2026, 9, 1, 5, tzinfo=UTC),
        ),
        patch(
            "custom_components.growspace_manager.vision_checkup_scheduler.async_track_point_in_utc_time",
            return_value=MagicMock(),
        ) as track,
    ):
        scheduler.schedule_growspace("tent1")

    assert track.call_count == 3
    assert len(scheduler._unsub_timers["tent1"]) == 3


@pytest.mark.parametrize(
    "growspace",
    [_growspace(enabled=False), _growspace(cameras=[])],
)
def test_schedule_skips_disabled_or_camera_less_growspaces(growspace) -> None:
    scheduler = VisionCheckupScheduler(MagicMock(), _coordinator(growspace))
    with patch(
        "custom_components.growspace_manager.vision_checkup_scheduler.async_track_point_in_utc_time"
    ) as track:
        scheduler.schedule_growspace("tent1")
    track.assert_not_called()


@pytest.mark.asyncio
async def test_manual_checkup_requires_a_ready_local_service() -> None:
    unavailable = VisionStatus(
        availability=VisionAvailability.UNAVAILABLE,
        connection_source=VisionConnectionSource.MANUAL,
    )
    coordinator = _coordinator()
    coordinator.vision_connection = SimpleNamespace(
        async_refresh_if_stale=AsyncMock(return_value=unavailable),
        negotiated=None,
    )
    scheduler = VisionCheckupScheduler(
        MagicMock(), coordinator, evidence_store=MagicMock()
    )

    with pytest.raises(ServiceValidationError, match="not ready"):
        await scheduler.run_vision_analysis("tent1", "manual")


@pytest.mark.asyncio
async def test_scheduled_callback_skips_unavailable_service_and_reschedules() -> None:
    unavailable = VisionStatus(
        availability=VisionAvailability.UNAVAILABLE,
        connection_source=VisionConnectionSource.SUPERVISOR,
    )
    coordinator = _coordinator()
    coordinator.vision_connection = SimpleNamespace(
        async_refresh_if_stale=AsyncMock(return_value=unavailable)
    )
    scheduler = VisionCheckupScheduler(MagicMock(), coordinator)
    scheduler.run_vision_analysis = AsyncMock()
    scheduler.schedule_growspace = MagicMock()

    await scheduler._create_checkup_callback("tent1", "early")(
        datetime(2026, 9, 1, 7, tzinfo=UTC)
    )

    scheduler.run_vision_analysis.assert_not_awaited()
    scheduler.schedule_growspace.assert_called_once_with("tent1")
