"""Normalize Bayesian Evaluation Snapshots for Vision evidence fusion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast

from custom_components.growspace_manager.notifications.evaluation_snapshot import (
    EvaluationSnapshot,
)

from .evidence_fusion import EnvironmentalEvidence, EnvironmentalVerdict

ENVIRONMENTAL_EVIDENCE_MAX_AGE = timedelta(minutes=30)


@dataclass(frozen=True, slots=True, kw_only=True)
class NormalizedEnvironmentalEvidence:
    """Capture-relative Bayesian evidence without raw sensor observations."""

    verdict: EnvironmentalVerdict
    evaluated_at: datetime | None = None
    stress_reasons: tuple[str, ...] = ()
    mold_reasons: tuple[str, ...] = ()
    unavailable_reasons: tuple[str, ...] = ()

    def fusion_input(self) -> EnvironmentalEvidence:
        """Return the narrower value accepted by the fusion policy."""
        return EnvironmentalEvidence(
            verdict=self.verdict,
            unavailable_reasons=self.unavailable_reasons,
        )


def environmental_evidence_at(
    captured_at: datetime,
    *,
    stress: EvaluationSnapshot | None,
    mold: EvaluationSnapshot | None,
) -> NormalizedEnvironmentalEvidence:
    """Normalize the latest stress and mold evaluations at capture time."""
    if captured_at.tzinfo is None:
        raise ValueError("captured_at must be timezone-aware")

    snapshots = {"stress": stress, "mold": mold}
    unavailable: list[str] = []
    available: dict[str, EvaluationSnapshot] = {}
    for sensor_type, snapshot in snapshots.items():
        reason = _unavailable_reason(captured_at, sensor_type, snapshot)
        if reason is None:
            assert snapshot is not None
            available[sensor_type] = snapshot
        else:
            unavailable.append(reason)

    active = [snapshot for snapshot in available.values() if snapshot.is_on]
    if active:
        evaluated = [snapshot.evaluated_at for snapshot in active]
        assert all(moment is not None for moment in evaluated)
        return NormalizedEnvironmentalEvidence(
            verdict=EnvironmentalVerdict.RISK,
            evaluated_at=max(cast("datetime", moment) for moment in evaluated),
            stress_reasons=_reasons(available.get("stress")),
            mold_reasons=_reasons(available.get("mold")),
        )
    if len(available) == 2:
        evaluated = [snapshot.evaluated_at for snapshot in available.values()]
        assert all(moment is not None for moment in evaluated)
        return NormalizedEnvironmentalEvidence(
            verdict=EnvironmentalVerdict.WITHIN_EVALUATED_RANGE,
            evaluated_at=max(cast("datetime", moment) for moment in evaluated),
        )
    return NormalizedEnvironmentalEvidence(
        verdict=EnvironmentalVerdict.UNAVAILABLE,
        unavailable_reasons=tuple(unavailable),
    )


def _unavailable_reason(
    captured_at: datetime,
    sensor_type: str,
    snapshot: EvaluationSnapshot | None,
) -> str | None:
    if snapshot is None or snapshot.evaluated_at is None:
        return f"{sensor_type}_missing"
    if snapshot.evaluated_at.tzinfo is None:
        return f"{sensor_type}_missing"
    if snapshot.evaluated_at > captured_at:
        return f"{sensor_type}_after_capture"
    if captured_at - snapshot.evaluated_at > ENVIRONMENTAL_EVIDENCE_MAX_AGE:
        return f"{sensor_type}_stale"
    if not snapshot.has_observations:
        return f"{sensor_type}_no_valid_observations"
    return None


def _reasons(snapshot: EvaluationSnapshot | None) -> tuple[str, ...]:
    if snapshot is None or not snapshot.is_on:
        return ()
    return tuple(reason for _weight, reason in sorted(snapshot.reasons, reverse=True))
