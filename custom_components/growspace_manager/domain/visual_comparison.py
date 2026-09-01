"""Rolling empirical Visual Comparison engine.

The engine owns Baseline Bucket state transitions and centroid-cosine calibration.
It is pure apart from its injected bucket identity factory; callers persist the
returned decision through the Vision Evidence Store.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import math
from statistics import median
import uuid

from custom_components.growspace_manager.models.vision_evidence import (
    BaselineState,
    CaptureTrigger,
    ComparisonOutcome,
    ComparisonVerdict,
    LightWindow,
)

BASELINE_SIZE = 30
BASELINE_STALE_AFTER = timedelta(days=14)


@dataclass(frozen=True, slots=True, kw_only=True)
class BaselineKey:
    """Every provenance dimension that makes embeddings comparable."""

    growspace_id: str
    camera_id: str
    light_window: LightWindow
    grow_run_id: str
    model_id: str
    model_version: str
    framing_epoch_id: str
    scoring_policy_version: int


@dataclass(frozen=True, slots=True, kw_only=True)
class VisualEmbeddingCapture:
    """One analyzed capture as the comparison engine sees it."""

    capture_id: str
    captured_at: datetime
    values: tuple[float, ...]
    trigger_source: CaptureTrigger
    quality_accepted: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class BaselineEntry:
    """One active member of a rolling Baseline Bucket."""

    capture_id: str
    admitted_at: datetime
    values: tuple[float, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class BaselineSnapshot:
    """The complete in-memory state of one Baseline Bucket."""

    bucket_id: str
    key: BaselineKey
    created_at: datetime
    state: BaselineState
    members: tuple[BaselineEntry, ...] = ()
    centroid: tuple[float, ...] = ()
    calibration_distances: tuple[float, ...] = ()
    last_admitted_at: datetime | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ComparisonValue:
    """One first-class Visual Comparison Result without persistence identity."""

    outcome: ComparisonOutcome
    baseline_state: BaselineState
    samples_collected: int
    samples_required: int = BASELINE_SIZE
    raw_distance: float | None = None
    anomaly_score: float | None = None
    verdict: ComparisonVerdict | None = None
    comparison_confidence: float | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ComparisonDecision:
    """A comparison plus the Baseline Bucket mutation it requires."""

    comparison: ComparisonValue | None
    baseline: BaselineSnapshot | None
    admitted: bool = False
    evicted_capture_id: str | None = None


class VisualComparisonEngine:
    """Evaluate captures against one rolling empirical Baseline Bucket."""

    def __init__(self, bucket_id_factory: Callable[[], str] | None = None) -> None:
        """Accept a deterministic identity factory for persistence and tests."""
        self._bucket_id_factory = bucket_id_factory or (lambda: str(uuid.uuid4()))

    def evaluate(
        self,
        key: BaselineKey,
        capture: VisualEmbeddingCapture,
        baseline: BaselineSnapshot | None,
    ) -> ComparisonDecision:
        """Evaluate one capture and return its comparison and next bucket state."""
        if not capture.quality_accepted:
            return ComparisonDecision(comparison=None, baseline=baseline)
        if capture.trigger_source is CaptureTrigger.MANUAL and (
            baseline is None or baseline.key != key
        ):
            return ComparisonDecision(
                comparison=ComparisonValue(
                    outcome=ComparisonOutcome.MONITORING,
                    baseline_state=BaselineState.MONITORING,
                    samples_collected=0,
                ),
                baseline=None,
            )
        if baseline is None or baseline.key != key:
            baseline = BaselineSnapshot(
                bucket_id=self._bucket_id_factory(),
                key=key,
                created_at=capture.captured_at,
                state=BaselineState.MONITORING,
            )

        if (
            baseline.state is BaselineState.READY
            and baseline.last_admitted_at is not None
            and capture.captured_at - baseline.last_admitted_at > BASELINE_STALE_AFTER
        ):
            stale = replace(baseline, state=BaselineState.STALE)
            return ComparisonDecision(
                comparison=ComparisonValue(
                    outcome=ComparisonOutcome.MONITORING,
                    baseline_state=BaselineState.STALE,
                    samples_collected=len(stale.members),
                ),
                baseline=stale,
            )
        if baseline.state is BaselineState.STALE:
            return ComparisonDecision(
                comparison=ComparisonValue(
                    outcome=ComparisonOutcome.MONITORING,
                    baseline_state=BaselineState.STALE,
                    samples_collected=len(baseline.members),
                ),
                baseline=baseline,
            )
        if baseline.state is BaselineState.READY:
            return self._score_ready(capture, baseline)

        if capture.trigger_source is CaptureTrigger.MANUAL:
            return ComparisonDecision(
                comparison=ComparisonValue(
                    outcome=ComparisonOutcome.MONITORING,
                    baseline_state=baseline.state,
                    samples_collected=len(baseline.members),
                ),
                baseline=baseline,
            )

        entry = BaselineEntry(
            capture_id=capture.capture_id,
            admitted_at=capture.captured_at,
            values=_normalize(capture.values),
        )
        members = (*baseline.members, entry)
        state = BaselineState.MONITORING
        centroid: tuple[float, ...] = ()
        calibration: tuple[float, ...] = ()
        if len(members) == BASELINE_SIZE:
            state = BaselineState.READY
            centroid, calibration = _calibrate(members)

        next_baseline = BaselineSnapshot(
            bucket_id=baseline.bucket_id,
            key=baseline.key,
            created_at=baseline.created_at,
            state=state,
            members=members,
            centroid=centroid,
            calibration_distances=calibration,
            last_admitted_at=capture.captured_at,
        )
        return ComparisonDecision(
            comparison=ComparisonValue(
                outcome=ComparisonOutcome.MONITORING,
                baseline_state=baseline.state,
                samples_collected=len(members),
            ),
            baseline=next_baseline,
            admitted=True,
        )

    def _score_ready(
        self,
        capture: VisualEmbeddingCapture,
        baseline: BaselineSnapshot,
    ) -> ComparisonDecision:
        """Score before any normal-result rolling admission."""
        current = _normalize(capture.values)
        raw_distance = _clamp(1.0 - _dot(current, baseline.centroid), 0.0, 2.0)
        anomaly_score = (
            sum(distance < raw_distance for distance in baseline.calibration_distances)
            / BASELINE_SIZE
        )
        if anomaly_score < 0.9:
            verdict = ComparisonVerdict.NORMAL
        elif anomaly_score < 1.0:
            verdict = ComparisonVerdict.UNCERTAIN
        else:
            verdict = ComparisonVerdict.MATERIAL_SCENE_CHANGE

        calibration_median = median(baseline.calibration_distances)
        sorted_distances = sorted(baseline.calibration_distances)
        tail_start = sorted_distances[26]
        upper = sorted_distances[-1]
        if verdict is ComparisonVerdict.NORMAL:
            confidence = _clamp(
                (tail_start - raw_distance)
                / max(tail_start - calibration_median, 0.000001),
                0.0,
                1.0,
            )
        elif verdict is ComparisonVerdict.UNCERTAIN:
            confidence = 0.0
        else:
            confidence = _clamp(
                (raw_distance - upper) / max(upper - tail_start, 0.000001),
                0.0,
                1.0,
            )

        comparison = ComparisonValue(
            outcome=ComparisonOutcome.SCORED,
            baseline_state=BaselineState.READY,
            samples_collected=BASELINE_SIZE,
            raw_distance=raw_distance,
            anomaly_score=anomaly_score,
            verdict=verdict,
            comparison_confidence=confidence,
        )
        if (
            verdict is not ComparisonVerdict.NORMAL
            or capture.trigger_source is CaptureTrigger.MANUAL
        ):
            return ComparisonDecision(comparison=comparison, baseline=baseline)

        evicted = baseline.members[0]
        entry = BaselineEntry(
            capture_id=capture.capture_id,
            admitted_at=capture.captured_at,
            values=current,
        )
        members = (*baseline.members[1:], entry)
        centroid, calibration = _calibrate(members)
        next_baseline = BaselineSnapshot(
            bucket_id=baseline.bucket_id,
            key=baseline.key,
            created_at=baseline.created_at,
            state=BaselineState.READY,
            members=members,
            centroid=centroid,
            calibration_distances=calibration,
            last_admitted_at=capture.captured_at,
        )
        return ComparisonDecision(
            comparison=comparison,
            baseline=next_baseline,
            admitted=True,
            evicted_capture_id=evicted.capture_id,
        )


def _normalize(values: tuple[float, ...]) -> tuple[float, ...]:
    """Return one unit vector and refuse dimensionless or zero embeddings."""
    if not values:
        raise ValueError("A Visual Embedding must have at least one dimension")
    norm = math.sqrt(sum(value * value for value in values))
    if not math.isfinite(norm) or norm == 0:
        raise ValueError("A Visual Embedding must have a finite non-zero norm")
    return tuple(value / norm for value in values)


def _calibrate(
    members: tuple[BaselineEntry, ...],
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Compute the centroid and all leave-one-out cosine distances."""
    dimension = len(members[0].values)
    if any(len(member.values) != dimension for member in members):
        raise ValueError("Every Baseline Bucket embedding must share one dimension")
    summed = tuple(
        sum(member.values[index] for member in members) for index in range(dimension)
    )
    centroid = _normalize(summed)
    calibration = tuple(
        1.0
        - _dot(
            member.values,
            _normalize(
                tuple(
                    summed[index] - member.values[index] for index in range(dimension)
                )
            ),
        )
        for member in members
    )
    return centroid, calibration


def _dot(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    """Return a dot product after enforcing one embedding dimension."""
    if len(left) != len(right):
        raise ValueError("Every compared Visual Embedding must share one dimension")
    return sum(a * b for a, b in zip(left, right, strict=True))


def _clamp(value: float, lower: float, upper: float) -> float:
    """Clamp a floating-point value to a closed interval."""
    return min(max(value, lower), upper)
