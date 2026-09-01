"""Evidence Fusion vocabulary.

ADR 0040 names this module as the home of Evidence Fusion: its enums, frozen input
and output value objects, and one total ``fuse_evidence(...)``.

Fusion reports observations, never plant health.  Nothing in this vocabulary
asserts that a plant is healthy, unhealthy, stressed or visually symptomatic.

Pure module: no hass, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from custom_components.growspace_manager.models.vision_evidence import (
    BaselineState,
    CaptureTrigger,
    ComparisonVerdict,
)

VISUAL_PERSISTENCE_WINDOW = timedelta(hours=24)


class EnvironmentalVerdict(StrEnum):
    """The normalized reading of the stress and mold Evaluation Snapshots.

    ``WITHIN_EVALUATED_RANGE`` requires both evaluations to exist, be fresh and be
    inactive.  A zero probability produced from zero observations is
    ``UNAVAILABLE``, never evidence of normal conditions.
    """

    RISK = "risk"
    WITHIN_EVALUATED_RANGE = "within_evaluated_range"
    UNAVAILABLE = "unavailable"


class EvidenceFusionState(StrEnum):
    """The five Evidence Fusion States of ADR 0040.

    ``NO_DETECTED_CHANGE`` means only that complete available evidence found
    neither environmental risk nor material departure from recent scene history.
    ``CONCURRENT_...`` asserts co-occurrence, not correlation or causation.
    ``PERSISTENT_VISUAL_ANOMALY`` describes fusion precedence and persistence, not
    plant danger.
    """

    NO_DETECTED_CHANGE = "no_detected_change"
    ENVIRONMENTAL_RISK = "environmental_risk"
    VISUAL_ANOMALY = "visual_anomaly"
    CONCURRENT_ENVIRONMENTAL_RISK_AND_VISUAL_ANOMALY = (
        "concurrent_environmental_risk_and_visual_anomaly"
    )
    PERSISTENT_VISUAL_ANOMALY = "persistent_visual_anomaly"


class ConfidenceQualifier(StrEnum):
    """How firmly an available outcome is held.

    Uncertainty is a qualifier, not a sixth state.  ``MONITOR`` can never reach the
    concurrent or critical state.
    """

    CONFIRMED = "confirmed"
    MONITOR = "monitor"


class EvidenceCoverage(StrEnum):
    """Whether both evidence channels contributed to an available outcome."""

    COMPLETE = "complete"
    PARTIAL = "partial"


@dataclass(frozen=True, slots=True, kw_only=True)
class EnvironmentalEvidence:
    """One normalized reading of fresh stress and mold evaluations."""

    verdict: EnvironmentalVerdict
    unavailable_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Enforce the tagged available/unavailable input shape."""
        if (
            self.verdict is EnvironmentalVerdict.UNAVAILABLE
            and not self.unavailable_reasons
        ):
            raise ValueError("Unavailable environmental evidence requires a reason")
        if (
            self.verdict is not EnvironmentalVerdict.UNAVAILABLE
            and self.unavailable_reasons
        ):
            raise ValueError("Available environmental evidence cannot carry reasons")


@dataclass(frozen=True, slots=True, kw_only=True)
class VisualEvidence:
    """A Visual Comparison Result normalized for fusion."""

    verdict: ComparisonVerdict | None = None
    comparison_confidence: float | None = None
    unavailable_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Enforce the tagged available/unavailable input shape."""
        unavailable = self.verdict is None
        if unavailable != (self.comparison_confidence is None):
            raise ValueError("Visual verdict and confidence must be available together")
        if unavailable and not self.unavailable_reasons:
            raise ValueError("Unavailable visual evidence requires a reason")
        if not unavailable and self.unavailable_reasons:
            raise ValueError("Available visual evidence cannot carry reasons")
        if self.comparison_confidence is not None and not (
            0.0 <= self.comparison_confidence <= 1.0
        ):
            raise ValueError("Comparison Confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True, kw_only=True)
class AvailableFusionOutcome:
    """A fusion result with at least one positive evidence channel."""

    state: EvidenceFusionState
    confidence: ConfidenceQualifier
    coverage: EvidenceCoverage


@dataclass(frozen=True, slots=True, kw_only=True)
class UnavailableFusionOutcome:
    """A result for which neither channel can support an available state."""

    unavailable_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        """Require the evidence that made fusion unavailable."""
        if not self.unavailable_reasons:
            raise ValueError("An unavailable fusion outcome requires a reason")


FusionOutcome = AvailableFusionOutcome | UnavailableFusionOutcome


@dataclass(frozen=True, slots=True, kw_only=True)
class VisualPersistenceKey:
    """The provenance dimensions across which a material pair stays comparable."""

    camera_id: str
    grow_run_id: str
    model_id: str
    model_version: str
    framing_epoch_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class VisualPersistenceEvent:
    """One capture's inputs to the persistent-visual-anomaly rule."""

    key: VisualPersistenceKey
    capture_id: str
    captured_at: datetime
    trigger_source: CaptureTrigger
    verdict: ComparisonVerdict | None
    comparison_confidence: float | None
    baseline_state: BaselineState | None


@dataclass(frozen=True, slots=True, kw_only=True)
class VisualPersistenceState:
    """The active sequence of qualifying automatically scheduled comparisons."""

    key: VisualPersistenceKey
    last_capture_id: str
    last_captured_at: datetime
    consecutive_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class VisualPersistenceDecision:
    """The next temporal state and whether the current result meets persistence."""

    state: VisualPersistenceState | None
    persistence_met: bool


def evaluate_visual_persistence(
    state: VisualPersistenceState | None,
    event: VisualPersistenceEvent,
) -> VisualPersistenceDecision:
    """Track ADR 0040's scheduled, 24-hour, provenance-compatible pair."""
    if event.trigger_source is CaptureTrigger.MANUAL:
        return VisualPersistenceDecision(state=state, persistence_met=False)
    if not _qualifies_for_visual_persistence(event):
        return VisualPersistenceDecision(state=None, persistence_met=False)

    continues = (
        state is not None
        and state.key == event.key
        and event.captured_at - state.last_captured_at <= VISUAL_PERSISTENCE_WINDOW
    )
    consecutive_count = (
        state.consecutive_count + 1 if continues and state is not None else 1
    )
    next_state = VisualPersistenceState(
        key=event.key,
        last_capture_id=event.capture_id,
        last_captured_at=event.captured_at,
        consecutive_count=consecutive_count,
    )
    return VisualPersistenceDecision(
        state=next_state,
        persistence_met=consecutive_count >= 2,
    )


def fuse_evidence(
    environmental: EnvironmentalEvidence,
    visual: VisualEvidence,
    *,
    persistence_met: bool,
) -> FusionOutcome:
    """Evaluate ADR 0040's complete fusion truth table."""
    environmental_available = (
        environmental.verdict is not EnvironmentalVerdict.UNAVAILABLE
    )
    visual_available = visual.verdict is not None
    coverage = (
        EvidenceCoverage.COMPLETE
        if environmental_available and visual_available
        else EvidenceCoverage.PARTIAL
    )

    if not visual_available:
        if environmental.verdict is EnvironmentalVerdict.RISK:
            return AvailableFusionOutcome(
                state=EvidenceFusionState.ENVIRONMENTAL_RISK,
                confidence=ConfidenceQualifier.CONFIRMED,
                coverage=coverage,
            )
        reasons = (
            *environmental.unavailable_reasons,
            *visual.unavailable_reasons,
        )
        return UnavailableFusionOutcome(
            unavailable_reasons=tuple(dict.fromkeys(reasons))
        )

    visual_kind = _normalize_visual(visual, persistence_met=persistence_met)
    if visual_kind == "normal":
        if not environmental_available:
            return UnavailableFusionOutcome(
                unavailable_reasons=environmental.unavailable_reasons
            )
        state = (
            EvidenceFusionState.ENVIRONMENTAL_RISK
            if environmental.verdict is EnvironmentalVerdict.RISK
            else EvidenceFusionState.NO_DETECTED_CHANGE
        )
        return AvailableFusionOutcome(
            state=state,
            confidence=ConfidenceQualifier.CONFIRMED,
            coverage=coverage,
        )

    if visual_kind == "persistent":
        return AvailableFusionOutcome(
            state=EvidenceFusionState.PERSISTENT_VISUAL_ANOMALY,
            confidence=ConfidenceQualifier.CONFIRMED,
            coverage=coverage,
        )

    if visual_kind == "monitor":
        state = (
            EvidenceFusionState.ENVIRONMENTAL_RISK
            if environmental.verdict is EnvironmentalVerdict.RISK
            else EvidenceFusionState.VISUAL_ANOMALY
        )
        return AvailableFusionOutcome(
            state=state,
            confidence=ConfidenceQualifier.MONITOR,
            coverage=coverage,
        )

    state = (
        EvidenceFusionState.CONCURRENT_ENVIRONMENTAL_RISK_AND_VISUAL_ANOMALY
        if environmental.verdict is EnvironmentalVerdict.RISK
        else EvidenceFusionState.VISUAL_ANOMALY
    )
    return AvailableFusionOutcome(
        state=state,
        confidence=ConfidenceQualifier.CONFIRMED,
        coverage=coverage,
    )


def _normalize_visual(visual: VisualEvidence, *, persistence_met: bool) -> str:
    """Reduce an available comparison to the truth table's four visual columns."""
    if visual.verdict is ComparisonVerdict.NORMAL:
        return "normal"
    if (
        visual.verdict is ComparisonVerdict.MATERIAL_SCENE_CHANGE
        and visual.comparison_confidence == 1.0
    ):
        return "persistent" if persistence_met else "confirmed"
    return "monitor"


def _qualifies_for_visual_persistence(event: VisualPersistenceEvent) -> bool:
    """Return whether one scheduled comparison may advance persistence."""
    return (
        event.baseline_state is BaselineState.READY
        and event.verdict is ComparisonVerdict.MATERIAL_SCENE_CHANGE
        and event.comparison_confidence == 1.0
    )
