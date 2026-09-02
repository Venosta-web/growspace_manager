"""Camera-relative Frame Quality Gate owned by Home Assistant.

Growspace Vision owns the absolute single-frame floor.  This module consumes that
result and applies ADR 0005's history-relative rails to the service's quality
signals.  It is pure: callers persist the returned ``next_history``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from statistics import median

QUALITY_HISTORY_SIZE = 30
QUALITY_HISTORY_WARMUP = 10
MAX_CONSECUTIVE_RELATIVE_REJECTIONS = 2


class RelativeQualityReason(StrEnum):
    """Why Home Assistant rejected an otherwise service-accepted frame."""

    EXPOSURE_EXCURSION = "exposure_excursion"
    DETAIL_COLLAPSE = "detail_collapse"


@dataclass(frozen=True, slots=True, kw_only=True)
class QualitySignals:
    """The three quality measurements returned for every Vision Analysis."""

    mean_luminance: float
    clipped_pixel_fraction: float
    mean_absolute_gradient: float


@dataclass(frozen=True, slots=True)
class QualityDecision:
    """One first-class Frame Quality Result and the history it leaves behind."""

    accepted: bool
    reasons: tuple[str, ...]
    next_history: QualityHistory
    reanchored: bool = False


@dataclass(frozen=True, slots=True)
class QualityHistory:
    """Trailing accepted quality signals for one camera, across light windows."""

    accepted: tuple[QualitySignals, ...] = ()
    relative_rejection_streak: int = 0

    def evaluate(
        self,
        signals: QualitySignals,
        *,
        service_accepted: bool,
        service_reasons: tuple[str, ...] = (),
    ) -> QualityDecision:
        """Evaluate one capture and return its decision plus immutable next state."""
        if not service_accepted:
            return QualityDecision(
                accepted=False,
                reasons=service_reasons,
                next_history=QualityHistory(accepted=self.accepted),
            )

        if len(self.accepted) < QUALITY_HISTORY_WARMUP:
            return self._accept(signals)

        luminance_median = median(
            entry.mean_luminance for entry in self.accepted[-QUALITY_HISTORY_SIZE:]
        )
        gradient_median = median(
            entry.mean_absolute_gradient
            for entry in self.accepted[-QUALITY_HISTORY_SIZE:]
        )
        reasons: list[str] = []
        if (
            signals.mean_luminance < luminance_median * 0.5
            or signals.mean_luminance > luminance_median * 2.0
        ):
            reasons.append(RelativeQualityReason.EXPOSURE_EXCURSION)
        if signals.mean_absolute_gradient < gradient_median * 0.5:
            reasons.append(RelativeQualityReason.DETAIL_COLLAPSE)

        if not reasons:
            return self._accept(signals)
        if self.relative_rejection_streak < MAX_CONSECUTIVE_RELATIVE_REJECTIONS:
            return QualityDecision(
                accepted=False,
                reasons=tuple(reasons),
                next_history=QualityHistory(
                    accepted=self.accepted,
                    relative_rejection_streak=self.relative_rejection_streak + 1,
                ),
            )

        return QualityDecision(
            accepted=True,
            reasons=(),
            next_history=QualityHistory(accepted=(signals,)),
            reanchored=True,
        )

    def _accept(self, signals: QualitySignals) -> QualityDecision:
        """Admit one service- and rail-accepted capture to the rolling history."""
        accepted = (*self.accepted, signals)[-QUALITY_HISTORY_SIZE:]
        return QualityDecision(
            accepted=True,
            reasons=(),
            next_history=QualityHistory(accepted=accepted),
        )
