"""Pure Plant Lifecycle domain model.

This module owns lifecycle reasoning only.  It deliberately has no persistence,
Home Assistant, event-bus, growspace, or clock dependency: every date that can
affect a result is supplied by the caller.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Final

type DateInput = date | datetime | str


class LifecycleStage(StrEnum):
    """Canonical stages understood by the lifecycle graph."""

    UNKNOWN = "unknown"
    SEEDLING = "seedling"
    CLONE = "clone"
    MOTHER = "mother"
    VEG = "veg"
    FLOWER = "flower"
    DRY = "dry"
    CURE = "cure"


KNOWN_STAGES: Final[tuple[LifecycleStage, ...]] = tuple(
    stage for stage in LifecycleStage if stage is not LifecycleStage.UNKNOWN
)

TRANSITION_GRAPH: Final[dict[LifecycleStage, frozenset[LifecycleStage]]] = {
    LifecycleStage.SEEDLING: frozenset({LifecycleStage.VEG}),
    LifecycleStage.CLONE: frozenset({LifecycleStage.VEG}),
    LifecycleStage.VEG: frozenset({LifecycleStage.MOTHER, LifecycleStage.FLOWER}),
    LifecycleStage.MOTHER: frozenset({LifecycleStage.VEG, LifecycleStage.FLOWER}),
    LifecycleStage.FLOWER: frozenset({LifecycleStage.DRY, LifecycleStage.VEG}),
    LifecycleStage.DRY: frozenset({LifecycleStage.CURE}),
    LifecycleStage.CURE: frozenset(),
}


class RepairWarningCode(StrEnum):
    """Machine-readable reasons a stored lifecycle needs repair."""

    EMPTY_HISTORY = "empty_history"
    MALFORMED_ITEM = "malformed_item"
    INVALID_DATE = "invalid_date"
    UNKNOWN_STAGE = "unknown_stage"
    FUTURE_DATE = "future_date"
    NONCHRONOLOGICAL = "nonchronological"
    NEGATIVE_INTERVAL = "negative_interval"
    OVERLAPPING_INTERVALS = "overlapping_intervals"
    OPEN_INTERVAL_NOT_LAST = "open_interval_not_last"
    NO_OPEN_INTERVAL = "no_open_interval"
    GRAPH_INVALID = "graph_invalid"
    CURRENT_STAGE_MISMATCH = "current_stage_mismatch"


@dataclass(frozen=True, slots=True)
class LifecycleRepairWarning:
    """A precise problem found while reconstructing or validating history."""

    code: RepairWarningCode
    message: str
    interval_index: int | None = None


@dataclass(frozen=True, slots=True)
class StageInterval:
    """One immutable half-open lifecycle interval ``[start, end)``."""

    stage: LifecycleStage
    started_on: date
    ended_on: date | None = None

    @property
    def days(self) -> int | None:
        """Return closed duration; open intervals have no fixed duration."""
        if self.ended_on is None:
            return None
        return (self.ended_on - self.started_on).days

    def as_history_item(self) -> dict[str, str | None]:
        """Project into the existing persisted Stage History shape."""
        return {
            "stage": self.stage.value,
            "start": self.started_on.isoformat(),
            "end": self.ended_on.isoformat() if self.ended_on else None,
        }


# Stored data is untrusted at this seam; malformed entries must become repair
# warnings instead of escaping as type/runtime errors.
type HistoryInput = Sequence[object]


@dataclass(frozen=True, slots=True)
class StageHistory:
    """Parsed history plus the maximal trustworthy prefix of malformed input."""

    intervals: tuple[StageInterval, ...] = ()
    warnings: tuple[LifecycleRepairWarning, ...] = ()
    trustworthy_intervals: tuple[StageInterval, ...] = ()
    reconstructed_from_legacy: bool = False

    @property
    def is_valid(self) -> bool:
        """Whether the history is safe to use for lifecycle facts."""
        return not self.warnings and bool(self.intervals)


@dataclass(frozen=True, slots=True)
class LifetimeStageDays:
    """Cumulative completed and current days for every canonical stage."""

    seedling: int = 0
    clone: int = 0
    mother: int = 0
    veg: int = 0
    flower: int = 0
    dry: int = 0
    cure: int = 0

    def for_stage(self, stage: LifecycleStage | str) -> int:
        """Return lifetime days for ``stage``; Unknown has no accumulated days."""
        parsed = _stage_or_unknown(stage)
        if parsed is LifecycleStage.UNKNOWN:
            return 0
        return int(getattr(self, parsed.value))

    def as_dict(self) -> dict[str, int]:
        """Return a wire-friendly copy keyed by canonical stage."""
        return {stage.value: self.for_stage(stage) for stage in KNOWN_STAGES}


class CultivationBandId(StrEnum):
    """Stable reported identities for lifecycle cultivation bands."""

    UNKNOWN = "unknown"
    ACCLIMATING_SEEDLING = "acclimating_seedling"
    ESTABLISHED_SEEDLING = "established_seedling"
    ACCLIMATING_CLONE = "acclimating_clone"
    ESTABLISHED_CLONE = "established_clone"
    VEGETATIVE = "vegetative"
    MOTHER = "mother"
    EARLY_FLOWER = "early_flower"
    MID_FLOWER = "mid_flower"
    LATE_FLOWER = "late_flower"
    DRYING = "drying"
    CURING = "curing"


@dataclass(frozen=True, slots=True)
class BandInterpolation:
    """Optional blend toward the next band without changing band identity."""

    adjacent_band: CultivationBandId
    factor: float


@dataclass(frozen=True, slots=True)
class CultivationBand:
    """Reported band and, near a boundary, its separate interpolation hint."""

    identity: CultivationBandId
    interpolation: BandInterpolation | None = None

    def interpolate(self, band_value: float, adjacent_value: float) -> float:
        """Blend numeric settings while leaving :attr:`identity` unchanged."""
        if self.interpolation is None:
            return band_value
        factor = self.interpolation.factor
        return band_value + (adjacent_value - band_value) * factor


@dataclass(frozen=True, slots=True)
class LifecycleFacts:
    """One internally consistent lifecycle snapshot evaluated on one date."""

    on: date
    current_stage: LifecycleStage
    current_stage_age: int | None
    lifetime_stage_days: LifetimeStageDays
    cultivation_band: CultivationBand
    warnings: tuple[LifecycleRepairWarning, ...] = ()


@dataclass(frozen=True, slots=True)
class CompatibilityData:
    """Projection consumed by the legacy Plant fields and Stage History shape."""

    stage: str
    stage_history: tuple[StageInterval, ...]
    seedling_start: str | None = None
    clone_start: str | None = None
    mother_start: str | None = None
    veg_start: str | None = None
    flower_start: str | None = None
    dry_start: str | None = None
    cure_start: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return fresh mutable containers suitable for the existing Plant model."""
        return {
            "stage": self.stage,
            "stage_history": [item.as_history_item() for item in self.stage_history],
            **{
                f"{stage.value}_start": getattr(self, f"{stage.value}_start")
                for stage in KNOWN_STAGES
            },
        }


@dataclass(frozen=True, slots=True)
class LifecycleValues:
    """The lifecycle-owned values before or after a proposal."""

    current_stage: LifecycleStage
    current_stage_started_on: date | None
    stage_history: tuple[StageInterval, ...]


@dataclass(frozen=True, slots=True)
class LifecycleRepairEventDraft:
    """Side-effect-free event payload drafted for a correction commit shell."""

    corrected_on: date
    reason: str
    previous_stage: LifecycleStage
    corrected_stage: LifecycleStage
    corrected_stage_started_on: date
    discarded_interval_count: int
    warning_codes: tuple[RepairWarningCode, ...]


class DecisionStatus(StrEnum):
    """Stable decision vocabulary for callers that do not use ``isinstance``."""

    APPLIED = "applied"
    NO_CHANGE = "no_change"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class LifecycleDecision:
    """Common immutable output of a lifecycle transition request."""

    lifecycle: PlantLifecycle
    before: LifecycleValues
    after: LifecycleValues
    before_facts: LifecycleFacts
    after_facts: LifecycleFacts
    compatibility_data: CompatibilityData
    repair_event: LifecycleRepairEventDraft | None = None
    reason: str | None = None
    status: DecisionStatus = field(init=False)


@dataclass(frozen=True, slots=True)
class Applied(LifecycleDecision):
    """A valid transition proposal with a new lifecycle value."""

    status: DecisionStatus = field(default=DecisionStatus.APPLIED, init=False)


@dataclass(frozen=True, slots=True)
class NoChange(LifecycleDecision):
    """A valid request that already matches the current stage."""

    status: DecisionStatus = field(default=DecisionStatus.NO_CHANGE, init=False)


@dataclass(frozen=True, slots=True)
class Rejected(LifecycleDecision):
    """A request rejected without changing any lifecycle value."""

    status: DecisionStatus = field(default=DecisionStatus.REJECTED, init=False)


@dataclass(frozen=True, slots=True)
class LifecycleCorrection:
    """Immutable proposal produced by :meth:`PlantLifecycle.repair_current`."""

    lifecycle: PlantLifecycle
    before: LifecycleValues
    after: LifecycleValues
    before_facts: LifecycleFacts
    after_facts: LifecycleFacts
    compatibility_data: CompatibilityData
    repair_event: LifecycleRepairEventDraft


@dataclass(frozen=True, slots=True)
class PlantLifecycle:
    """The pure owner of a Plant's stage history and derived lifecycle facts."""

    history: StageHistory

    @classmethod
    def from_data(
        cls,
        stage_history: HistoryInput | None,
        *,
        observed_on: DateInput,
        legacy_dates: Mapping[str, DateInput | None] | None = None,
        current_stage: LifecycleStage | str | None = None,
    ) -> PlantLifecycle:
        """Parse present history or reconstruct absent history from legacy dates.

        ``None`` means Stage History is absent and activates the one-time legacy
        reconstruction path.  A present empty or malformed history is never
        replaced silently by legacy values.
        """
        observed = _coerce_date(observed_on)
        if observed is None:
            raise ValueError("observed_on must be a valid date")

        if stage_history is None:
            return cls(
                _reconstruct_history(
                    legacy_dates or {}, observed, current_stage=current_stage
                )
            )
        return cls(_parse_history(stage_history, observed, current_stage=current_stage))

    @classmethod
    def from_history(
        cls,
        stage_history: HistoryInput,
        *,
        observed_on: DateInput,
        current_stage: LifecycleStage | str | None = None,
    ) -> PlantLifecycle:
        """Explicit parsing alias for callers that always have Stage History."""
        return cls.from_data(
            stage_history,
            observed_on=observed_on,
            current_stage=current_stage,
        )

    @property
    def warnings(self) -> tuple[LifecycleRepairWarning, ...]:
        """Expose repair warnings without leaking parsing implementation."""
        return self.history.warnings

    @property
    def current_stage(self) -> LifecycleStage:
        """Return the trusted current stage or Unknown for invalid history."""
        if not self.history.is_valid:
            return LifecycleStage.UNKNOWN
        return self.history.intervals[-1].stage

    @property
    def compatibility_data(self) -> CompatibilityData:
        """Return the legacy projection of trusted lifecycle-owned values."""
        if not self.history.is_valid:
            return CompatibilityData(
                stage=LifecycleStage.UNKNOWN.value, stage_history=()
            )
        return _compatibility_for(self.history.intervals)

    def values(self) -> LifecycleValues:
        """Return lifecycle-owned values as one immutable record."""
        if not self.history.is_valid:
            return LifecycleValues(LifecycleStage.UNKNOWN, None, ())
        current = self.history.intervals[-1]
        return LifecycleValues(
            current.stage, current.started_on, self.history.intervals
        )

    def facts(self, *, on: DateInput) -> LifecycleFacts:
        """Return Current Stage, age, lifetime days, and band on one date."""
        on_date = _coerce_date(on)
        if on_date is None:
            raise ValueError("on must be a valid date")
        if not self.history.is_valid:
            return _unknown_facts(on_date, self.history.warnings)

        interval = _interval_on(self.history.intervals, on_date)
        if interval is None:
            warning = LifecycleRepairWarning(
                RepairWarningCode.FUTURE_DATE,
                "No lifecycle interval contains the requested snapshot date",
            )
            return _unknown_facts(on_date, (*self.history.warnings, warning))

        days = {stage.value: 0 for stage in KNOWN_STAGES}
        for item in self.history.intervals:
            if item.started_on > on_date:
                break
            end = min(item.ended_on or on_date, on_date)
            if end >= item.started_on:
                days[item.stage.value] += (end - item.started_on).days

        age = (on_date - interval.started_on).days
        lifetime = LifetimeStageDays(**days)
        return LifecycleFacts(
            on=on_date,
            current_stage=interval.stage,
            current_stage_age=age,
            lifetime_stage_days=lifetime,
            cultivation_band=cultivation_band_for(interval.stage, age),
        )

    def transition(
        self,
        target_stage: LifecycleStage | str,
        effective_on: DateInput,
        observed_on: DateInput,
    ) -> Applied | NoChange | Rejected:
        """Propose a graph-valid transition without mutating this lifecycle."""
        target = _stage_or_unknown(target_stage)
        effective = _coerce_date(effective_on)
        observed = _coerce_date(observed_on)
        before = self.values()
        before_facts = self.facts(on=observed) if observed else _unknown_facts(date.min)

        reason: str | None = None
        if effective is None or observed is None:
            reason = "effective_on and observed_on must be valid dates"
        elif target is LifecycleStage.UNKNOWN:
            reason = f"Unknown target stage: {target_stage}"
        elif not self.history.is_valid:
            reason = "Lifecycle history requires repair before a transition"
        elif effective > observed:
            reason = "Future-dated transitions are not allowed"
        else:
            current = self.history.intervals[-1]
            if effective < current.started_on:
                reason = "Transition cannot predate the open interval"
            elif target is current.stage:
                return NoChange(
                    lifecycle=self,
                    before=before,
                    after=before,
                    before_facts=before_facts,
                    after_facts=before_facts,
                    compatibility_data=self.compatibility_data,
                )
            elif target not in TRANSITION_GRAPH[current.stage]:
                reason = (
                    f"Transition {current.stage.value}->{target.value} is not allowed"
                )

        if reason is not None:
            return Rejected(
                lifecycle=self,
                before=before,
                after=before,
                before_facts=before_facts,
                after_facts=before_facts,
                compatibility_data=self.compatibility_data,
                reason=reason,
            )

        # The guards above establish these values for the type checker and reader.
        assert effective is not None
        assert observed is not None
        current = self.history.intervals[-1]
        intervals = (
            *self.history.intervals[:-1],
            StageInterval(current.stage, current.started_on, effective),
            StageInterval(target, effective),
        )
        lifecycle = PlantLifecycle(
            StageHistory(intervals=intervals, trustworthy_intervals=intervals)
        )
        return Applied(
            lifecycle=lifecycle,
            before=before,
            after=lifecycle.values(),
            before_facts=before_facts,
            after_facts=lifecycle.facts(on=observed),
            compatibility_data=lifecycle.compatibility_data,
        )

    def repair_current(
        self,
        current_stage: LifecycleStage | str,
        started_on: DateInput,
        corrected_on: DateInput,
        reason: str,
    ) -> LifecycleCorrection:
        """Correct the current interval while retaining a maximal trusted prefix."""
        corrected_stage = _stage_or_unknown(current_stage)
        start = _coerce_date(started_on)
        corrected = _coerce_date(corrected_on)
        if corrected_stage is LifecycleStage.UNKNOWN:
            raise ValueError(f"Unknown current stage: {current_stage}")
        if start is None or corrected is None:
            raise ValueError("started_on and corrected_on must be valid dates")
        if start > corrected:
            raise ValueError("started_on cannot be after corrected_on")
        if not reason.strip():
            raise ValueError("reason must not be empty")

        preserved = [
            item
            for item in self.history.trustworthy_intervals
            if item.ended_on is not None and item.ended_on <= start
        ]
        while (
            preserved and corrected_stage not in TRANSITION_GRAPH[preserved[-1].stage]
        ):
            preserved.pop()

        intervals = (*preserved, StageInterval(corrected_stage, start))
        lifecycle = PlantLifecycle(
            StageHistory(intervals=intervals, trustworthy_intervals=intervals)
        )
        previous_stage = self.current_stage
        raw_count = len(self.history.intervals)
        discarded_count = max(raw_count - len(preserved), 0)
        event = LifecycleRepairEventDraft(
            corrected_on=corrected,
            reason=reason.strip(),
            previous_stage=previous_stage,
            corrected_stage=corrected_stage,
            corrected_stage_started_on=start,
            discarded_interval_count=discarded_count,
            warning_codes=tuple(warning.code for warning in self.history.warnings),
        )
        return LifecycleCorrection(
            lifecycle=lifecycle,
            before=self.values(),
            after=lifecycle.values(),
            before_facts=self.facts(on=corrected),
            after_facts=lifecycle.facts(on=corrected),
            compatibility_data=lifecycle.compatibility_data,
            repair_event=event,
        )


def cultivation_band_for(stage: LifecycleStage | str, age: int) -> CultivationBand:
    """Classify a stage age and expose a separate three-day boundary blend."""
    parsed = _stage_or_unknown(stage)
    if parsed is LifecycleStage.UNKNOWN or age < 0:
        return CultivationBand(CultivationBandId.UNKNOWN)
    if parsed is LifecycleStage.SEEDLING:
        return _two_band(
            age,
            boundary=7,
            lower=CultivationBandId.ACCLIMATING_SEEDLING,
            upper=CultivationBandId.ESTABLISHED_SEEDLING,
        )
    if parsed is LifecycleStage.CLONE:
        return _two_band(
            age,
            boundary=7,
            lower=CultivationBandId.ACCLIMATING_CLONE,
            upper=CultivationBandId.ESTABLISHED_CLONE,
        )
    if parsed is LifecycleStage.FLOWER:
        if age < 21:
            return _lower_band_with_interpolation(
                age,
                boundary=21,
                lower=CultivationBandId.EARLY_FLOWER,
                upper=CultivationBandId.MID_FLOWER,
            )
        if age < 42:
            return _lower_band_with_interpolation(
                age,
                boundary=42,
                lower=CultivationBandId.MID_FLOWER,
                upper=CultivationBandId.LATE_FLOWER,
            )
        return CultivationBand(CultivationBandId.LATE_FLOWER)

    identity = {
        LifecycleStage.VEG: CultivationBandId.VEGETATIVE,
        LifecycleStage.MOTHER: CultivationBandId.MOTHER,
        LifecycleStage.DRY: CultivationBandId.DRYING,
        LifecycleStage.CURE: CultivationBandId.CURING,
    }[parsed]
    return CultivationBand(identity)


def _two_band(
    age: int,
    *,
    boundary: int,
    lower: CultivationBandId,
    upper: CultivationBandId,
) -> CultivationBand:
    if age < boundary:
        return _lower_band_with_interpolation(
            age, boundary=boundary, lower=lower, upper=upper
        )
    return CultivationBand(upper)


def _lower_band_with_interpolation(
    age: int,
    *,
    boundary: int,
    lower: CultivationBandId,
    upper: CultivationBandId,
) -> CultivationBand:
    window_start = boundary - 3
    if age < window_start:
        return CultivationBand(lower)
    factor = round((age - window_start) / 3, 2)
    return CultivationBand(lower, BandInterpolation(upper, factor))


def _coerce_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    try:
        if "T" in candidate or " " in candidate:
            return datetime.fromisoformat(candidate).date()
        return date.fromisoformat(candidate)
    except ValueError:
        return None


def _stage_or_unknown(value: LifecycleStage | str | None) -> LifecycleStage:
    try:
        return LifecycleStage(value) if value is not None else LifecycleStage.UNKNOWN
    except TypeError, ValueError:
        return LifecycleStage.UNKNOWN


def _parse_history(
    raw_history: HistoryInput,
    observed_on: date,
    *,
    current_stage: LifecycleStage | str | None,
    reconstructed: bool = False,
) -> StageHistory:
    if not raw_history:
        warning = LifecycleRepairWarning(
            RepairWarningCode.EMPTY_HISTORY,
            "Stage History is present but empty",
        )
        return StageHistory(
            warnings=(warning,), reconstructed_from_legacy=reconstructed
        )

    intervals: list[StageInterval] = []
    warnings: list[LifecycleRepairWarning] = []
    for index, raw in enumerate(raw_history):
        if isinstance(raw, StageInterval):
            interval = raw
        elif isinstance(raw, Mapping):
            stage = _stage_or_unknown(raw.get("stage"))
            start = _coerce_date(raw.get("start", raw.get("started_on")))
            end_value = raw.get("end", raw.get("ended_on"))
            end = _coerce_date(end_value) if end_value is not None else None
            if stage is LifecycleStage.UNKNOWN:
                warnings.append(
                    LifecycleRepairWarning(
                        RepairWarningCode.UNKNOWN_STAGE,
                        f"History item {index} has an unknown stage",
                        index,
                    )
                )
                break
            if start is None or (end_value is not None and end is None):
                warnings.append(
                    LifecycleRepairWarning(
                        RepairWarningCode.INVALID_DATE,
                        f"History item {index} has an invalid date",
                        index,
                    )
                )
                break
            interval = StageInterval(stage, start, end)
        else:
            warnings.append(
                LifecycleRepairWarning(
                    RepairWarningCode.MALFORMED_ITEM,
                    f"History item {index} is not a mapping",
                    index,
                )
            )
            break
        intervals.append(interval)

    trusted_count = len(intervals) if not warnings else max(len(intervals), 0)
    validation_warnings, validation_trusted = _validate_intervals(
        intervals, observed_on, current_stage=current_stage
    )
    warnings.extend(validation_warnings)
    trusted_count = min(trusted_count, validation_trusted)
    trusted = tuple(intervals[:trusted_count])
    return StageHistory(
        intervals=tuple(intervals),
        warnings=tuple(warnings),
        trustworthy_intervals=trusted,
        reconstructed_from_legacy=reconstructed,
    )


def _validate_intervals(
    intervals: Sequence[StageInterval],
    observed_on: date,
    *,
    current_stage: LifecycleStage | str | None,
) -> tuple[list[LifecycleRepairWarning], int]:
    warnings: list[LifecycleRepairWarning] = []
    trusted_count = 0
    for index, interval in enumerate(intervals):
        if interval.stage is LifecycleStage.UNKNOWN:
            warnings.append(
                LifecycleRepairWarning(
                    RepairWarningCode.UNKNOWN_STAGE,
                    f"History item {index} has an unknown stage",
                    index,
                )
            )
            break
        if interval.started_on > observed_on or (
            interval.ended_on is not None and interval.ended_on > observed_on
        ):
            warnings.append(
                LifecycleRepairWarning(
                    RepairWarningCode.FUTURE_DATE,
                    f"History item {index} contains a future date",
                    index,
                )
            )
            break
        if interval.ended_on is not None and interval.ended_on < interval.started_on:
            warnings.append(
                LifecycleRepairWarning(
                    RepairWarningCode.NEGATIVE_INTERVAL,
                    f"History item {index} ends before it starts",
                    index,
                )
            )
            break
        if interval.ended_on is None and index != len(intervals) - 1:
            warnings.append(
                LifecycleRepairWarning(
                    RepairWarningCode.OPEN_INTERVAL_NOT_LAST,
                    f"Open history item {index} has a later interval",
                    index,
                )
            )
            break
        if index:
            previous = intervals[index - 1]
            if interval.started_on < previous.started_on:
                warnings.append(
                    LifecycleRepairWarning(
                        RepairWarningCode.NONCHRONOLOGICAL,
                        f"History item {index} starts before its predecessor",
                        index,
                    )
                )
                break
            if (
                previous.ended_on is not None
                and previous.ended_on > interval.started_on
            ):
                warnings.append(
                    LifecycleRepairWarning(
                        RepairWarningCode.OVERLAPPING_INTERVALS,
                        f"History item {index} overlaps its predecessor",
                        index,
                    )
                )
                break
            if interval.stage not in TRANSITION_GRAPH[previous.stage]:
                warnings.append(
                    LifecycleRepairWarning(
                        RepairWarningCode.GRAPH_INVALID,
                        f"History contains invalid transition {previous.stage.value}->{interval.stage.value}",
                        index,
                    )
                )
                break
        trusted_count = index + 1

    if not warnings and intervals and intervals[-1].ended_on is not None:
        warnings.append(
            LifecycleRepairWarning(
                RepairWarningCode.NO_OPEN_INTERVAL,
                "Stage History has no current open interval",
                len(intervals) - 1,
            )
        )
        trusted_count = len(intervals)

    expected = _stage_or_unknown(current_stage)
    if (
        not warnings
        and expected is not LifecycleStage.UNKNOWN
        and intervals[-1].stage is not expected
    ):
        warnings.append(
            LifecycleRepairWarning(
                RepairWarningCode.CURRENT_STAGE_MISMATCH,
                "Legacy current stage does not match Stage History",
                len(intervals) - 1,
            )
        )
        trusted_count = len(intervals) - 1

    return warnings, trusted_count


def _reconstruct_history(
    legacy_dates: Mapping[str, DateInput | None],
    observed_on: date,
    *,
    current_stage: LifecycleStage | str | None,
) -> StageHistory:
    raw: list[dict[str, str | None]] = []
    invalid_warning: LifecycleRepairWarning | None = None
    for stage in KNOWN_STAGES:
        value = legacy_dates.get(f"{stage.value}_start", legacy_dates.get(stage.value))
        if value is None:
            continue
        parsed = _coerce_date(value)
        if parsed is None:
            invalid_warning = LifecycleRepairWarning(
                RepairWarningCode.INVALID_DATE,
                f"Legacy {stage.value}_start has an invalid date",
            )
            break
        raw.append({"stage": stage.value, "start": parsed.isoformat(), "end": None})

    if invalid_warning is not None:
        return StageHistory(warnings=(invalid_warning,), reconstructed_from_legacy=True)
    raw.sort(key=lambda item: str(item["start"]))
    for index in range(len(raw) - 1):
        raw[index]["end"] = raw[index + 1]["start"]
    return _parse_history(
        raw,
        observed_on,
        current_stage=current_stage,
        reconstructed=True,
    )


def _interval_on(intervals: Sequence[StageInterval], on: date) -> StageInterval | None:
    for interval in reversed(intervals):
        if interval.started_on <= on and (
            interval.ended_on is None or on < interval.ended_on
        ):
            return interval
    return None


def _compatibility_for(intervals: tuple[StageInterval, ...]) -> CompatibilityData:
    starts: dict[str, str | None] = {
        f"{stage.value}_start": None for stage in KNOWN_STAGES
    }
    for interval in intervals:
        starts[f"{interval.stage.value}_start"] = interval.started_on.isoformat()
    return CompatibilityData(
        stage=intervals[-1].stage.value,
        stage_history=intervals,
        **starts,
    )


def _unknown_facts(
    on: date, warnings: tuple[LifecycleRepairWarning, ...] = ()
) -> LifecycleFacts:
    return LifecycleFacts(
        on=on,
        current_stage=LifecycleStage.UNKNOWN,
        current_stage_age=None,
        lifetime_stage_days=LifetimeStageDays(),
        cultivation_band=CultivationBand(CultivationBandId.UNKNOWN),
        warnings=warnings,
    )


__all__ = [
    "KNOWN_STAGES",
    "TRANSITION_GRAPH",
    "Applied",
    "BandInterpolation",
    "CompatibilityData",
    "CultivationBand",
    "CultivationBandId",
    "DecisionStatus",
    "LifecycleCorrection",
    "LifecycleDecision",
    "LifecycleFacts",
    "LifecycleRepairEventDraft",
    "LifecycleRepairWarning",
    "LifecycleStage",
    "LifecycleValues",
    "LifetimeStageDays",
    "NoChange",
    "PlantLifecycle",
    "Rejected",
    "RepairWarningCode",
    "StageHistory",
    "StageInterval",
    "cultivation_band_for",
]
