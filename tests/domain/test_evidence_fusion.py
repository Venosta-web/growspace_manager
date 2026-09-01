"""Exhaustive behavior tests for the Evidence Fusion truth table."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.growspace_manager.domain.evidence_fusion import (
    AvailableFusionOutcome,
    ConfidenceQualifier,
    EnvironmentalEvidence,
    EnvironmentalVerdict,
    EvidenceCoverage,
    EvidenceFusionState,
    UnavailableFusionOutcome,
    VisualEvidence,
    VisualPersistenceEvent,
    VisualPersistenceKey,
    evaluate_visual_persistence,
    fuse_evidence,
)
from custom_components.growspace_manager.models.vision_evidence import (
    BaselineState,
    CaptureTrigger,
    ComparisonVerdict,
)

ENV_UNAVAILABLE = EnvironmentalEvidence(
    verdict=EnvironmentalVerdict.UNAVAILABLE,
    unavailable_reasons=("environmental_evidence",),
)
ENV_WITHIN_RANGE = EnvironmentalEvidence(
    verdict=EnvironmentalVerdict.WITHIN_EVALUATED_RANGE
)
ENV_RISK = EnvironmentalEvidence(verdict=EnvironmentalVerdict.RISK)
VISUAL_UNAVAILABLE = VisualEvidence(
    unavailable_reasons=("baseline_stale",),
)
VISUAL_NORMAL = VisualEvidence(
    verdict=ComparisonVerdict.NORMAL,
    comparison_confidence=0.8,
)
VISUAL_MONITOR = VisualEvidence(
    verdict=ComparisonVerdict.UNCERTAIN,
    comparison_confidence=0.0,
)
VISUAL_CONFIRMED = VisualEvidence(
    verdict=ComparisonVerdict.MATERIAL_SCENE_CHANGE,
    comparison_confidence=1.0,
)
PERSISTENCE_TIME = datetime(2026, 9, 1, 6, tzinfo=UTC)
PERSISTENCE_KEY = VisualPersistenceKey(
    camera_id="camera.canopy",
    grow_run_id="run-1",
    model_id="dinov2-small",
    model_version="1.0.0",
    framing_epoch_id="epoch-1",
)


def test_evidence_value_objects_reject_invalid_tagged_shapes() -> None:
    """Available and unavailable evidence cannot be represented ambiguously."""
    with pytest.raises(ValueError, match="environmental evidence requires a reason"):
        EnvironmentalEvidence(verdict=EnvironmentalVerdict.UNAVAILABLE)
    with pytest.raises(ValueError, match="cannot carry reasons"):
        EnvironmentalEvidence(
            verdict=EnvironmentalVerdict.RISK,
            unavailable_reasons=("not_applicable",),
        )
    with pytest.raises(ValueError, match="available together"):
        VisualEvidence(verdict=ComparisonVerdict.NORMAL)
    with pytest.raises(ValueError, match="visual evidence requires a reason"):
        VisualEvidence()
    with pytest.raises(ValueError, match="cannot carry reasons"):
        VisualEvidence(
            verdict=ComparisonVerdict.NORMAL,
            comparison_confidence=1.0,
            unavailable_reasons=("not_applicable",),
        )
    with pytest.raises(ValueError, match="between 0 and 1"):
        VisualEvidence(
            verdict=ComparisonVerdict.NORMAL,
            comparison_confidence=1.01,
        )
    with pytest.raises(ValueError, match="fusion outcome requires a reason"):
        UnavailableFusionOutcome(unavailable_reasons=())


def _persistence_event(
    number: int,
    *,
    key: VisualPersistenceKey = PERSISTENCE_KEY,
    trigger: CaptureTrigger = CaptureTrigger.SCHEDULED,
    verdict: ComparisonVerdict | None = ComparisonVerdict.MATERIAL_SCENE_CHANGE,
    confidence: float | None = 1.0,
    baseline_state: BaselineState | None = BaselineState.READY,
) -> VisualPersistenceEvent:
    return VisualPersistenceEvent(
        key=key,
        capture_id=f"capture-{number}",
        captured_at=PERSISTENCE_TIME + timedelta(hours=number),
        trigger_source=trigger,
        verdict=verdict,
        comparison_confidence=confidence,
        baseline_state=baseline_state,
    )


def _available(
    state: EvidenceFusionState,
    confidence: ConfidenceQualifier,
    coverage: EvidenceCoverage,
) -> AvailableFusionOutcome:
    return AvailableFusionOutcome(
        state=state,
        confidence=confidence,
        coverage=coverage,
    )


@pytest.mark.parametrize(
    ("environmental", "visual", "persistence_met", "expected"),
    [
        (
            ENV_UNAVAILABLE,
            VISUAL_UNAVAILABLE,
            False,
            UnavailableFusionOutcome(
                unavailable_reasons=("environmental_evidence", "baseline_stale")
            ),
        ),
        (
            ENV_WITHIN_RANGE,
            VISUAL_UNAVAILABLE,
            False,
            UnavailableFusionOutcome(unavailable_reasons=("baseline_stale",)),
        ),
        (
            ENV_RISK,
            VISUAL_UNAVAILABLE,
            False,
            _available(
                EvidenceFusionState.ENVIRONMENTAL_RISK,
                ConfidenceQualifier.CONFIRMED,
                EvidenceCoverage.PARTIAL,
            ),
        ),
        (
            ENV_UNAVAILABLE,
            VISUAL_NORMAL,
            False,
            UnavailableFusionOutcome(unavailable_reasons=("environmental_evidence",)),
        ),
        (
            ENV_WITHIN_RANGE,
            VISUAL_NORMAL,
            False,
            _available(
                EvidenceFusionState.NO_DETECTED_CHANGE,
                ConfidenceQualifier.CONFIRMED,
                EvidenceCoverage.COMPLETE,
            ),
        ),
        (
            ENV_RISK,
            VISUAL_NORMAL,
            False,
            _available(
                EvidenceFusionState.ENVIRONMENTAL_RISK,
                ConfidenceQualifier.CONFIRMED,
                EvidenceCoverage.COMPLETE,
            ),
        ),
        (
            ENV_UNAVAILABLE,
            VISUAL_MONITOR,
            False,
            _available(
                EvidenceFusionState.VISUAL_ANOMALY,
                ConfidenceQualifier.MONITOR,
                EvidenceCoverage.PARTIAL,
            ),
        ),
        (
            ENV_WITHIN_RANGE,
            VISUAL_MONITOR,
            False,
            _available(
                EvidenceFusionState.VISUAL_ANOMALY,
                ConfidenceQualifier.MONITOR,
                EvidenceCoverage.COMPLETE,
            ),
        ),
        (
            ENV_RISK,
            VISUAL_MONITOR,
            False,
            _available(
                EvidenceFusionState.ENVIRONMENTAL_RISK,
                ConfidenceQualifier.MONITOR,
                EvidenceCoverage.COMPLETE,
            ),
        ),
        (
            ENV_UNAVAILABLE,
            VISUAL_CONFIRMED,
            False,
            _available(
                EvidenceFusionState.VISUAL_ANOMALY,
                ConfidenceQualifier.CONFIRMED,
                EvidenceCoverage.PARTIAL,
            ),
        ),
        (
            ENV_WITHIN_RANGE,
            VISUAL_CONFIRMED,
            False,
            _available(
                EvidenceFusionState.VISUAL_ANOMALY,
                ConfidenceQualifier.CONFIRMED,
                EvidenceCoverage.COMPLETE,
            ),
        ),
        (
            ENV_RISK,
            VISUAL_CONFIRMED,
            False,
            _available(
                EvidenceFusionState.CONCURRENT_ENVIRONMENTAL_RISK_AND_VISUAL_ANOMALY,
                ConfidenceQualifier.CONFIRMED,
                EvidenceCoverage.COMPLETE,
            ),
        ),
        (
            ENV_UNAVAILABLE,
            VISUAL_CONFIRMED,
            True,
            _available(
                EvidenceFusionState.PERSISTENT_VISUAL_ANOMALY,
                ConfidenceQualifier.CONFIRMED,
                EvidenceCoverage.PARTIAL,
            ),
        ),
        (
            ENV_WITHIN_RANGE,
            VISUAL_CONFIRMED,
            True,
            _available(
                EvidenceFusionState.PERSISTENT_VISUAL_ANOMALY,
                ConfidenceQualifier.CONFIRMED,
                EvidenceCoverage.COMPLETE,
            ),
        ),
        (
            ENV_RISK,
            VISUAL_CONFIRMED,
            True,
            _available(
                EvidenceFusionState.PERSISTENT_VISUAL_ANOMALY,
                ConfidenceQualifier.CONFIRMED,
                EvidenceCoverage.COMPLETE,
            ),
        ),
    ],
)
def test_evidence_fusion_truth_table(
    environmental: EnvironmentalEvidence,
    visual: VisualEvidence,
    persistence_met: bool,
    expected: AvailableFusionOutcome | UnavailableFusionOutcome,
) -> None:
    """Every environmental/visual coverage cell has one total outcome."""
    assert (
        fuse_evidence(
            environmental,
            visual,
            persistence_met=persistence_met,
        )
        == expected
    )


@pytest.mark.parametrize(
    "visual",
    [VISUAL_NORMAL, VISUAL_MONITOR, VISUAL_UNAVAILABLE],
)
def test_persistence_is_ignored_without_full_confidence_material_change(
    visual: VisualEvidence,
) -> None:
    """An irrelevant persistence flag can never manufacture a persistent state."""
    assert fuse_evidence(ENV_WITHIN_RANGE, visual, persistence_met=True) == (
        fuse_evidence(ENV_WITHIN_RANGE, visual, persistence_met=False)
    )


def test_two_qualifying_scheduled_changes_within_day_meet_persistence() -> None:
    """Persistence strengthens only a consecutive, provenance-compatible pair."""
    first = evaluate_visual_persistence(None, _persistence_event(1))

    second = evaluate_visual_persistence(first.state, _persistence_event(2))

    assert first.persistence_met is False
    assert second.persistence_met is True
    assert second.state is not None
    assert second.state.consecutive_count == 2


def test_manual_capture_neither_advances_nor_resets_visual_persistence() -> None:
    """A manual material result stays observe-only and leaves the scheduled pair."""
    first = evaluate_visual_persistence(None, _persistence_event(1))

    manual = evaluate_visual_persistence(
        first.state,
        _persistence_event(2, trigger=CaptureTrigger.MANUAL),
    )
    second_scheduled = evaluate_visual_persistence(
        manual.state,
        _persistence_event(3),
    )

    assert manual.state is first.state
    assert manual.persistence_met is False
    assert second_scheduled.persistence_met is True


@pytest.mark.parametrize(
    "event",
    [
        _persistence_event(2, verdict=ComparisonVerdict.NORMAL, confidence=0.8),
        _persistence_event(2, verdict=ComparisonVerdict.UNCERTAIN, confidence=0.0),
        _persistence_event(2, verdict=None, confidence=None, baseline_state=None),
        _persistence_event(2, baseline_state=BaselineState.STALE),
    ],
)
def test_scheduled_non_qualifying_result_breaks_visual_persistence(
    event: VisualPersistenceEvent,
) -> None:
    """Normal, uncertain, rejected, unavailable, and stale results break the pair."""
    first = evaluate_visual_persistence(None, _persistence_event(1))

    broken = evaluate_visual_persistence(first.state, event)

    assert broken.state is None
    assert broken.persistence_met is False


def test_time_and_provenance_boundaries_restart_visual_persistence() -> None:
    """A stale pair or a run/model/framing change begins again at one."""
    first = evaluate_visual_persistence(None, _persistence_event(1))
    assert first.state is not None
    changed_key = replace(PERSISTENCE_KEY, grow_run_id="run-2")

    late = evaluate_visual_persistence(
        first.state,
        replace(
            _persistence_event(2),
            captured_at=first.state.last_captured_at + timedelta(hours=24, seconds=1),
        ),
    )
    changed = evaluate_visual_persistence(
        first.state,
        _persistence_event(2, key=changed_key),
    )

    assert late.persistence_met is False
    assert late.state is not None and late.state.consecutive_count == 1
    assert changed.persistence_met is False
    assert changed.state is not None and changed.state.consecutive_count == 1
    assert changed.state.key == changed_key
