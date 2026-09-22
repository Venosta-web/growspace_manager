"""Immutable snapshot of a Bayesian sensor evaluation.

The binary sensors push one of these to the notification manager on every
update via ``report_evaluation``. It replaces the previous arrangement where
the manager held live entity references and re-read their mutable state at
debounce-fire time. All fields are frozen at snapshot time, including the
precomputed notification title/message.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..bayesian_evaluator import ReasonList


@dataclass(frozen=True, slots=True)
class EvaluationSnapshot:
    """A point-in-time view of one sensor's evaluation result."""

    growspace_id: str
    sensor_type: str
    sensor_name: str
    probability: float
    threshold: float
    is_on: bool
    reasons: ReasonList
    sensor_states: dict[str, Any]
    lights_on: bool | None
    # Precomputed for the triggered state; None when the strategy supplies no
    # title/message (e.g. drying/curing) or the sensor is not triggered.
    notification_title: str | None
    notification_message: str | None
    # Capture-relative Vision evidence may use the snapshot only when it was
    # evaluated at or before the image, is fresh, and had real observations.
    evaluated_at: datetime | None = None
    has_observations: bool = False
