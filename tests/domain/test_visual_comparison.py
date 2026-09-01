"""Behavior tests for rolling empirical Visual Comparison Results."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import math

import pytest

from custom_components.growspace_manager.domain.visual_comparison import (
    BaselineKey,
    VisualComparisonEngine,
    VisualEmbeddingCapture,
)
from custom_components.growspace_manager.models.vision_evidence import (
    BaselineState,
    CaptureTrigger,
    ComparisonOutcome,
    ComparisonVerdict,
    LightWindow,
)

BASE_TIME = datetime(2026, 8, 1, 6, tzinfo=UTC)


def _key(**changes: object) -> BaselineKey:
    values: dict[str, object] = {
        "growspace_id": "gs-1",
        "camera_id": "camera.canopy",
        "light_window": LightWindow.EARLY,
        "grow_run_id": "run-1",
        "model_id": "dinov2-small",
        "model_version": "1.0.0",
        "framing_epoch_id": "epoch-1",
        "scoring_policy_version": 1,
    }
    values.update(changes)
    return BaselineKey(**values)  # type: ignore[arg-type]


def _capture(
    number: int,
    values: tuple[float, ...] = (1.0, 0.0),
    *,
    trigger: CaptureTrigger = CaptureTrigger.SCHEDULED,
    quality_accepted: bool = True,
) -> VisualEmbeddingCapture:
    return VisualEmbeddingCapture(
        capture_id=f"capture-{number}",
        captured_at=BASE_TIME + timedelta(hours=number),
        values=values,
        trigger_source=trigger,
        quality_accepted=quality_accepted,
    )


def test_thirtieth_eligible_capture_readies_bucket_but_remains_monitoring() -> None:
    """The first scored comparison is capture 31, never bootstrap member 30."""
    engine = VisualComparisonEngine(bucket_id_factory=lambda: "bucket-1")
    baseline = None

    for number in range(1, 31):
        decision = engine.evaluate(_key(), _capture(number), baseline)
        baseline = decision.baseline
        assert decision.comparison is not None
        assert decision.comparison.outcome is ComparisonOutcome.MONITORING
        assert decision.comparison.anomaly_score is None
        assert decision.admitted is True

    assert decision.comparison.baseline_state is BaselineState.MONITORING
    assert decision.comparison.samples_collected == 30
    assert decision.comparison.samples_required == 30
    assert baseline is not None
    assert baseline.state is BaselineState.READY
    assert len(baseline.members) == 30
    assert len(baseline.calibration_distances) == 30


def test_ready_bucket_scores_strict_rank_and_rolls_only_normal_results() -> None:
    """A tie is normal; any distance above every zero-noise member is material."""
    engine = VisualComparisonEngine(bucket_id_factory=lambda: "bucket-1")
    baseline = None
    for number in range(1, 31):
        baseline = engine.evaluate(_key(), _capture(number), baseline).baseline
    assert baseline is not None

    tied = engine.evaluate(_key(), _capture(31), baseline)

    assert tied.comparison is not None
    assert tied.comparison.outcome is ComparisonOutcome.SCORED
    assert tied.comparison.raw_distance == 0.0
    assert tied.comparison.anomaly_score == 0.0
    assert tied.comparison.verdict is ComparisonVerdict.NORMAL
    assert tied.comparison.comparison_confidence == 0.0
    assert tied.admitted is True
    assert tied.evicted_capture_id == "capture-1"
    assert tied.baseline is not None
    assert [member.capture_id for member in tied.baseline.members] == [
        *(f"capture-{number}" for number in range(2, 31)),
        "capture-31",
    ]

    changed = engine.evaluate(
        _key(),
        _capture(32, values=(0.999, 0.04471017781221601)),
        baseline,
    )

    assert changed.comparison is not None
    assert changed.comparison.anomaly_score == 1.0
    assert changed.comparison.verdict is ComparisonVerdict.MATERIAL_SCENE_CHANGE
    assert changed.comparison.comparison_confidence == 1.0
    assert changed.admitted is False
    assert changed.baseline is baseline


def test_empirical_tail_and_confidence_use_persisted_bucket_calibration() -> None:
    """Strict rank reserves the observed upper tail and confidence is its margin."""
    engine = VisualComparisonEngine(bucket_id_factory=lambda: "bucket-1")
    baseline = None
    for number in range(1, 31):
        baseline = engine.evaluate(_key(), _capture(number), baseline).baseline
    assert baseline is not None
    tied_upper_distance = 1.0 - 0.7
    calibrated = replace(
        baseline,
        centroid=(1.0, 0.0),
        calibration_distances=(
            *(number / 100 for number in range(1, 30)),
            tied_upper_distance,
        ),
    )

    uncertain = engine.evaluate(
        _key(),
        _capture(31, values=(0.7, math.sqrt(0.51))),
        calibrated,
    )
    manual_normal = engine.evaluate(
        _key(),
        _capture(
            32,
            values=(0.79, math.sqrt(1.0 - 0.79**2)),
            trigger=CaptureTrigger.MANUAL,
        ),
        calibrated,
    )

    assert uncertain.comparison is not None
    assert uncertain.comparison.anomaly_score == pytest.approx(29 / 30)
    assert uncertain.comparison.verdict is ComparisonVerdict.UNCERTAIN
    assert uncertain.comparison.comparison_confidence == 0.0
    assert uncertain.admitted is False
    assert manual_normal.comparison is not None
    assert manual_normal.comparison.anomaly_score == pytest.approx(20 / 30)
    assert manual_normal.comparison.verdict is ComparisonVerdict.NORMAL
    assert manual_normal.comparison.comparison_confidence == pytest.approx(
        (0.27 - 0.21) / (0.27 - 0.155)
    )
    assert manual_normal.admitted is False


def test_bucket_stales_only_after_fourteen_elapsed_days_without_admission() -> None:
    """The exact validity boundary still scores; the next instant is monitoring."""
    engine = VisualComparisonEngine(bucket_id_factory=lambda: "bucket-1")
    baseline = None
    for number in range(1, 31):
        baseline = engine.evaluate(_key(), _capture(number), baseline).baseline
    assert baseline is not None
    assert baseline.last_admitted_at is not None

    at_boundary = engine.evaluate(
        _key(),
        replace(
            _capture(31, trigger=CaptureTrigger.MANUAL),
            captured_at=baseline.last_admitted_at + timedelta(days=14),
        ),
        baseline,
    )
    stale = engine.evaluate(
        _key(),
        replace(
            _capture(32),
            captured_at=baseline.last_admitted_at + timedelta(days=14, microseconds=1),
        ),
        baseline,
    )

    assert at_boundary.comparison is not None
    assert at_boundary.comparison.outcome is ComparisonOutcome.SCORED
    assert stale.comparison is not None
    assert stale.comparison.outcome is ComparisonOutcome.MONITORING
    assert stale.comparison.baseline_state is BaselineState.STALE
    assert stale.comparison.anomaly_score is None
    assert stale.admitted is False
    assert stale.baseline is not None
    assert stale.baseline.state is BaselineState.STALE
    assert stale.baseline.members == baseline.members


@pytest.mark.parametrize(
    "boundary_change",
    [
        {"grow_run_id": "run-2"},
        {"model_version": "2.0.0"},
        {"framing_epoch_id": "epoch-2"},
    ],
)
def test_run_model_and_framing_boundaries_start_fresh_monitoring_buckets(
    boundary_change: dict[str, object],
) -> None:
    """A provenance boundary preserves history but never reuses its calibration."""
    bucket_ids = iter(("bucket-1", "bucket-2"))
    engine = VisualComparisonEngine(bucket_id_factory=lambda: next(bucket_ids))
    original = engine.evaluate(_key(), _capture(1), None).baseline
    assert original is not None

    decision = engine.evaluate(_key(**boundary_change), _capture(2), original)

    assert decision.comparison is not None
    assert decision.comparison.outcome is ComparisonOutcome.MONITORING
    assert decision.admitted is True
    assert decision.baseline is not None
    assert decision.baseline.bucket_id == "bucket-2"
    assert [member.capture_id for member in original.members] == ["capture-1"]
    assert [member.capture_id for member in decision.baseline.members] == ["capture-2"]


def test_rejected_and_manual_bootstrap_captures_cannot_create_membership() -> None:
    """A rejection has no comparison; a manual check can monitor but not bootstrap."""
    engine = VisualComparisonEngine(bucket_id_factory=lambda: "bucket-1")

    rejected = engine.evaluate(
        _key(), _capture(1, quality_accepted=False), baseline=None
    )
    manual = engine.evaluate(
        _key(), _capture(2, trigger=CaptureTrigger.MANUAL), baseline=None
    )

    assert rejected.comparison is None
    assert rejected.baseline is None
    assert rejected.admitted is False
    assert manual.comparison is not None
    assert manual.comparison.outcome is ComparisonOutcome.MONITORING
    assert manual.comparison.samples_collected == 0
    assert manual.baseline is None
    assert manual.admitted is False
