"""Scheduling behavior for evidence-based Vision Checkups."""

from datetime import UTC, datetime, time
import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.domain.visual_comparison import (
    BaselineEntry,
    BaselineKey,
    BaselineSnapshot,
    ComparisonDecision,
    ComparisonValue,
)
from custom_components.growspace_manager.models.vision_evidence import (
    AdmissionPhase,
    BaselineState,
    ComparisonOutcome,
    LightWindow,
)
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


def test_schedule_replaces_timers_handles_short_time_and_stops() -> None:
    growspace = _growspace()
    growspace.irrigation_strategy.lights_on_time = "06:00"
    scheduler = VisionCheckupScheduler(MagicMock(), _coordinator(growspace))
    old_unsubscribe = MagicMock()
    scheduler._unsub_timers["tent1"] = [old_unsubscribe]
    new_unsubscribes = [MagicMock(), MagicMock(), MagicMock()]
    current = datetime(2026, 9, 1, 23, 59, tzinfo=UTC)
    with (
        patch(
            "custom_components.growspace_manager.vision_checkup_scheduler.ha_now",
            return_value=current,
        ),
        patch(
            "custom_components.growspace_manager.vision_checkup_scheduler.async_track_point_in_utc_time",
            side_effect=new_unsubscribes,
        ) as track,
    ):
        scheduler.schedule_growspace("tent1")

    old_unsubscribe.assert_called_once_with()
    assert all(call.args[2] > current for call in track.call_args_list)

    scheduler.async_stop()

    for unsubscribe in new_unsubscribes:
        unsubscribe.assert_called_once_with()
    assert scheduler._unsub_timers == {}


def test_schedule_missing_growspace_and_schedule_all() -> None:
    scheduler = VisionCheckupScheduler(MagicMock(), _coordinator())
    with patch(
        "custom_components.growspace_manager.vision_checkup_scheduler.async_track_point_in_utc_time"
    ) as track:
        scheduler.schedule_growspace("missing")
    track.assert_not_called()

    scheduler.schedule_growspace = MagicMock()
    scheduler.schedule_all_growspaces()
    scheduler.schedule_growspace.assert_called_once_with("tent1")


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
@pytest.mark.parametrize(
    ("growspaces", "store", "message"),
    [
        ({}, MagicMock(), "not found"),
        ({"tent1": _growspace(cameras=[])}, MagicMock(), "No cameras configured"),
        ({"tent1": _growspace()}, None, "Evidence Store is unavailable"),
    ],
)
async def test_manual_checkup_validates_local_prerequisites(
    growspaces, store, message
) -> None:
    coordinator = _coordinator()
    coordinator.growspaces = growspaces
    scheduler = VisionCheckupScheduler(MagicMock(), coordinator, evidence_store=store)

    with pytest.raises(ServiceValidationError, match=message):
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


@pytest.mark.asyncio
async def test_scheduled_callback_contains_pipeline_failure_and_reschedules() -> None:
    ready = VisionStatus(
        availability=VisionAvailability.READY,
        connection_source=VisionConnectionSource.MANUAL,
    )
    coordinator = _coordinator()
    coordinator.vision_connection = SimpleNamespace(
        async_refresh_if_stale=AsyncMock(return_value=ready)
    )
    scheduler = VisionCheckupScheduler(MagicMock(), coordinator)
    scheduler.run_vision_analysis = AsyncMock(side_effect=RuntimeError("failed"))
    scheduler.schedule_growspace = MagicMock()

    await scheduler._create_checkup_callback("tent1", "early")(
        datetime(2026, 9, 1, 7, tzinfo=UTC)
    )

    scheduler.run_vision_analysis.assert_awaited_once_with("tent1", "early")
    scheduler.schedule_growspace.assert_called_once_with("tent1")


def _baseline_key() -> BaselineKey:
    return BaselineKey(
        growspace_id="tent1",
        camera_id="camera.canopy",
        light_window=LightWindow.EARLY,
        grow_run_id="run-1",
        model_id="dinov2-small",
        model_version="1.0.0",
        framing_epoch_id="epoch-1",
        scoring_policy_version=1,
    )


def _baseline() -> BaselineSnapshot:
    key = _baseline_key()
    return BaselineSnapshot(
        bucket_id="bucket-1",
        key=key,
        created_at=datetime(2026, 9, 1, 6, tzinfo=UTC),
        state=BaselineState.MONITORING,
        members=(
            BaselineEntry(
                capture_id="capture-1",
                admitted_at=datetime(2026, 9, 1, 6, tzinfo=UTC),
                values=(1.0, 0.0),
            ),
        ),
        centroid=(1.0, 0.0),
        calibration_distances=(0.1,),
        last_admitted_at=datetime(2026, 9, 1, 6, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_baseline_snapshot_rehydrates_member_embeddings() -> None:
    baseline = _baseline()
    bucket = SimpleNamespace(
        bucket_id=baseline.bucket_id,
        created_at=baseline.created_at.isoformat(),
        state=baseline.state,
        model_id=baseline.key.model_id,
        model_version=baseline.key.model_version,
        centroid=struct.pack("<2f", *baseline.centroid),
        calibration_distances=struct.pack("<1f", *baseline.calibration_distances),
        last_admitted_at=baseline.last_admitted_at.isoformat(),
    )
    member = SimpleNamespace(
        capture_id="capture-1", admitted_at=baseline.created_at.isoformat()
    )
    store = SimpleNamespace(
        async_get_active_baseline_members=AsyncMock(return_value=[member]),
        async_get_embedding=AsyncMock(
            return_value=SimpleNamespace(values_f32=struct.pack("<2f", 1.0, 0.0))
        ),
    )
    scheduler = VisionCheckupScheduler(
        MagicMock(), _coordinator(), evidence_store=store
    )

    restored = await scheduler._baseline_snapshot(bucket, baseline.key)

    assert restored is not None
    assert restored.bucket_id == baseline.bucket_id
    assert restored.members == baseline.members
    assert restored.centroid == baseline.centroid
    assert restored.calibration_distances == pytest.approx(
        baseline.calibration_distances
    )


@pytest.mark.asyncio
async def test_baseline_snapshot_refuses_member_without_embedding() -> None:
    baseline = _baseline()
    bucket = SimpleNamespace(
        bucket_id=baseline.bucket_id,
        model_id=baseline.key.model_id,
        model_version=baseline.key.model_version,
    )
    store = SimpleNamespace(
        async_get_active_baseline_members=AsyncMock(
            return_value=[
                SimpleNamespace(
                    capture_id="capture-1",
                    admitted_at=baseline.created_at.isoformat(),
                )
            ]
        ),
        async_get_embedding=AsyncMock(return_value=None),
    )
    scheduler = VisionCheckupScheduler(
        MagicMock(), _coordinator(), evidence_store=store
    )

    with pytest.raises(RuntimeError, match="no matching embedding"):
        await scheduler._baseline_snapshot(bucket, baseline.key)


def test_persistence_records_encode_admission_decision() -> None:
    baseline = _baseline()
    scheduler = VisionCheckupScheduler(MagicMock(), _coordinator())
    capture = SimpleNamespace(
        capture_id="capture-2",
        captured_at=datetime(2026, 9, 1, 7, tzinfo=UTC).isoformat(),
    )
    comparison = ComparisonValue(
        outcome=ComparisonOutcome.MONITORING,
        baseline_state=BaselineState.MONITORING,
        samples_collected=1,
    )

    bucket, member = scheduler._persistence_records(
        capture,
        ComparisonDecision(comparison=comparison, baseline=baseline, admitted=False),
    )
    assert bucket is not None
    assert member is None

    bucket, member = scheduler._persistence_records(
        capture,
        ComparisonDecision(comparison=comparison, baseline=baseline, admitted=True),
    )
    assert bucket is not None
    assert member is not None
    assert member.admission_phase is AdmissionPhase.BOOTSTRAP
