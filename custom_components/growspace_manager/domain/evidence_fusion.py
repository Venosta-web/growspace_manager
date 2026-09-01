"""Evidence Fusion vocabulary.

ADR 0040 names this module as the home of Evidence Fusion: its enums, its frozen
input and output value objects, and one total ``fuse_evidence(...)``.  Only the
vocabulary is here.  The function and its value objects stay deferred until the
Visual Comparison Result producer exists, exactly as ADR 0040 decided; the
Vision Explainer (ADR 0042) needs the words now, and defining them twice would
guarantee they drift.

Fusion reports observations, never plant health.  Nothing in this vocabulary
asserts that a plant is healthy, unhealthy, stressed or visually symptomatic.

Pure module: no hass, no I/O.
"""

from __future__ import annotations

from enum import StrEnum


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
