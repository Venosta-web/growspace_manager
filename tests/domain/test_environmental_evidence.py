"""Behavior tests for Vision's Bayesian environmental evidence adapter."""

from datetime import UTC, datetime, timedelta

from custom_components.growspace_manager.domain.environmental_evidence import (
    environmental_evidence_at,
)
from custom_components.growspace_manager.domain.evidence_fusion import (
    EnvironmentalVerdict,
)
from custom_components.growspace_manager.notifications.evaluation_snapshot import (
    EvaluationSnapshot,
)

CAPTURED_AT = datetime(2026, 9, 1, 12, tzinfo=UTC)


def _snapshot(
    sensor_type: str,
    *,
    evaluated_at: datetime = CAPTURED_AT,
    is_on: bool = False,
    has_observations: bool = True,
    reasons: list[tuple[float, str]] | None = None,
) -> EvaluationSnapshot:
    return EvaluationSnapshot(
        growspace_id="tent1",
        sensor_type=sensor_type,
        sensor_name=sensor_type.title(),
        probability=0.8 if is_on else 0.1,
        threshold=0.7,
        is_on=is_on,
        reasons=reasons or [],
        sensor_states={},
        lights_on=True,
        notification_title=None,
        notification_message=None,
        evaluated_at=evaluated_at,
        has_observations=has_observations,
    )


def test_fresh_inactive_stress_and_mold_are_within_evaluated_range() -> None:
    evidence = environmental_evidence_at(
        CAPTURED_AT,
        stress=_snapshot("stress"),
        mold=_snapshot("mold"),
    )

    assert evidence.verdict is EnvironmentalVerdict.WITHIN_EVALUATED_RANGE
    assert evidence.stress_reasons == ()
    assert evidence.mold_reasons == ()
    assert evidence.evaluated_at == CAPTURED_AT
    assert evidence.unavailable_reasons == ()


def test_active_snapshot_preserves_only_normalized_bayesian_reasons() -> None:
    evidence = environmental_evidence_at(
        CAPTURED_AT,
        stress=_snapshot(
            "stress",
            is_on=True,
            reasons=[(0.9, "High VPD"), (0.7, "Warm air")],
        ),
        mold=_snapshot("mold"),
    )

    assert evidence.verdict is EnvironmentalVerdict.RISK
    assert evidence.stress_reasons == ("High VPD", "Warm air")
    assert evidence.mold_reasons == ()


def test_stale_future_missing_and_zero_observation_snapshots_are_unavailable() -> None:
    stale = environmental_evidence_at(
        CAPTURED_AT,
        stress=_snapshot("stress", evaluated_at=CAPTURED_AT - timedelta(minutes=31)),
        mold=_snapshot("mold"),
    )
    future = environmental_evidence_at(
        CAPTURED_AT,
        stress=_snapshot("stress", evaluated_at=CAPTURED_AT + timedelta(seconds=1)),
        mold=_snapshot("mold"),
    )
    missing = environmental_evidence_at(
        CAPTURED_AT,
        stress=None,
        mold=_snapshot("mold"),
    )
    empty = environmental_evidence_at(
        CAPTURED_AT,
        stress=_snapshot("stress", has_observations=False),
        mold=_snapshot("mold"),
    )

    assert stale.unavailable_reasons == ("stress_stale",)
    assert future.unavailable_reasons == ("stress_after_capture",)
    assert missing.unavailable_reasons == ("stress_missing",)
    assert empty.unavailable_reasons == ("stress_no_valid_observations",)
    for evidence in (stale, future, missing, empty):
        assert evidence.verdict is EnvironmentalVerdict.UNAVAILABLE
