"""Grow Runs: one Growspace's bounded operating episodes (#668, ADR-0033…0038).

A Growspace owns a **Run Ledger**: its Runs, the next Run Sequence Number and
the Run Revision. The ledger is the unit every lifecycle command is checked and
committed against, because the rule it guards -- zero or one Active Run -- is a
rule about the collection, not about any one Run. A command names the revision
it was decided on; a ledger that has moved since refuses it and says where it
is now, so a second tab or a stale automation can never start a second Run.

This module is pure. It decides and records; persistence, Home Assistant state
and authorization belong to the shells around it.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_LABEL_LENGTH = 80
MAX_TAGS = 20
MAX_TAG_LENGTH = 40
MAX_TEXT_LENGTH = 2000

# Refusal codes. Every refusal travels with the ledger's current revision, so
# the caller can re-decide on what is really there.
CODE_REVISION_CONFLICT = "grow_run.revision_conflict"
CODE_ALREADY_ACTIVE = "grow_run.already_active"
CODE_NOT_AUTHORIZED = "grow_run.not_authorized"
CODE_STORE_UNREADABLE = "grow_run.store_unreadable"
CODE_BEYOND_RETENTION = "grow_run.beyond_retention"
CODE_BOUNDARY_CONFLICT = "grow_run.boundary_conflict"


class RunStatus(StrEnum):
    """The Grow Run State Graph's states. Only ``active`` is reachable yet."""

    ACTIVE = "active"
    COMPLETED = "completed"
    FINALIZED = "finalized"
    VOIDED = "voided"


class RunCommand(StrEnum):
    """The lifecycle commands a Run Audit Entry can record."""

    START = "start"


class GrowRunRefused(Exception):
    """A lifecycle command the ledger would not take, and where it stands."""

    code: str = "grow_run.refused"

    def __init__(
        self,
        message: str,
        *,
        current_revision: int | None,
        active_run: GrowRun | None = None,
        boundary: datetime | None = None,
    ) -> None:
        """Keep the ledger's position beside the refusal."""
        super().__init__(message)
        self.current_revision = current_revision
        self.active_run = active_run
        self.boundary = boundary


class RunRevisionConflict(GrowRunRefused):
    """The command was decided on a revision the ledger has moved past."""

    code = CODE_REVISION_CONFLICT


class RunAlreadyActive(GrowRunRefused):
    """The Growspace already has its one Active Run."""

    code = CODE_ALREADY_ACTIVE


class RunNotAuthorized(GrowRunRefused):
    """The acting user may not run this command on this Growspace."""

    code = CODE_NOT_AUTHORIZED


class RunStoreUnreadable(GrowRunRefused):
    """The stored Run history could not be read; nothing may be written over it."""

    code = CODE_STORE_UNREADABLE


class RunBeyondRetention(GrowRunRefused):
    """A backdated start older than the Unattributed Activity Ledger keeps.

    Nothing is inferred for it; ``boundary`` is the retention horizon, and the
    only honest record of such history is an Imported Run.
    """

    code = CODE_BEYOND_RETENTION


class RunBoundaryConflict(GrowRunRefused):
    """A backdated start that would overlap another Run or lie in the future.

    ``boundary`` is the moment the requested start may not reach.
    """

    code = CODE_BOUNDARY_CONFLICT


# ---------------------------------------------------------------------------
# Readers for stored documents. A malformed record is refused whole.
# ---------------------------------------------------------------------------


def _str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"{name} is not a non-empty string")
    return value


def _opt_str(value: Any, name: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise TypeError(f"{name} is not a string")
    return value


def _int(value: Any, name: str, minimum: int) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} is not an integer of at least {minimum}")
    return value


def _moment(value: Any, name: str) -> datetime:
    moment = datetime.fromisoformat(_str(value, name))
    if moment.tzinfo is None:
        raise ValueError(f"{name} has no timezone")
    return moment


def _opt_moment(value: Any, name: str) -> datetime | None:
    return None if value is None else _moment(value, name)


def _date(value: Any, name: str) -> date:
    return date.fromisoformat(_str(value, name))


def _zone(value: Any, name: str) -> str:
    """Accept only an IANA timezone this interpreter can resolve."""
    zone = _str(value, name)
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError) as err:
        raise ValueError(f"{name} is not a known timezone") from err
    return zone


def _list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"{name} is not a list")
    return value


def _dict(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{name} is not an object")
    return value


def _text(value: str | None, limit: int) -> str | None:
    """Normalise a grower's free text: trimmed, and absent rather than blank."""
    if value is None:
        return None
    value = value.strip()
    if len(value) > limit:
        raise ValueError(f"text longer than {limit} characters")
    return value or None


# ---------------------------------------------------------------------------
# The records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunMetadata:
    """The editable description of a Run: label, tags, goals, notes."""

    label: str | None = None
    tags: tuple[str, ...] = ()
    goals: str | None = None
    notes: str | None = None

    @classmethod
    def create(
        cls,
        *,
        label: str | None = None,
        tags: list[str] | tuple[str, ...] = (),
        goals: str | None = None,
        notes: str | None = None,
    ) -> RunMetadata:
        """Normalise a grower's input; refuse what exceeds the bounds."""
        cleaned: list[str] = []
        for tag in tags:
            text = _text(tag, MAX_TAG_LENGTH)
            if text and text not in cleaned:
                cleaned.append(text)
        if len(cleaned) > MAX_TAGS:
            raise ValueError(f"a Run has at most {MAX_TAGS} tags")
        return cls(
            label=_text(label, MAX_LABEL_LENGTH),
            tags=tuple(cleaned),
            goals=_text(goals, MAX_TEXT_LENGTH),
            notes=_text(notes, MAX_TEXT_LENGTH),
        )

    def as_dict(self) -> dict[str, Any]:
        """Return the durable form."""
        return {
            "label": self.label,
            "tags": list(self.tags),
            "goals": self.goals,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, value: Any) -> RunMetadata:
        """Read the durable form back."""
        value = _dict(value, "metadata")
        tags = _list(value.get("tags"), "metadata.tags")
        return cls(
            label=_opt_str(value.get("label"), "metadata.label"),
            tags=tuple(_str(tag, "metadata.tags[]") for tag in tags),
            goals=_opt_str(value.get("goals"), "metadata.goals"),
            notes=_opt_str(value.get("notes"), "metadata.notes"),
        )


@dataclass(frozen=True, slots=True)
class BaselineState:
    """One condition or output as it stood when the Run started."""

    entity_id: str
    key: str
    state: str

    def as_dict(self) -> dict[str, Any]:
        """Return the durable form."""
        return {"entity_id": self.entity_id, "key": self.key, "state": self.state}

    @classmethod
    def from_dict(cls, value: Any) -> BaselineState:
        """Read the durable form back."""
        value = _dict(value, "baseline state")
        return cls(
            entity_id=_str(value.get("entity_id"), "baseline.entity_id"),
            key=_str(value.get("key"), "baseline.key"),
            state=_str(value.get("state"), "baseline.state"),
        )


@dataclass(frozen=True, slots=True)
class OpeningBaseline:
    """The Run Opening Baseline: conditions and equipment at the start boundary.

    A condition already active here is carried-in context; only a later
    clear-to-active transition is an episode of this Run.
    """

    conditions: tuple[BaselineState, ...] = ()
    equipment: tuple[BaselineState, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        """Return the durable form."""
        return {
            "conditions": [state.as_dict() for state in self.conditions],
            "equipment": [state.as_dict() for state in self.equipment],
        }

    @classmethod
    def from_dict(cls, value: Any) -> OpeningBaseline:
        """Read the durable form back."""
        value = _dict(value, "baseline")
        return cls(
            conditions=tuple(
                BaselineState.from_dict(row)
                for row in _list(value.get("conditions"), "baseline.conditions")
            ),
            equipment=tuple(
                BaselineState.from_dict(row)
                for row in _list(value.get("equipment"), "baseline.equipment")
            ),
        )


@dataclass(frozen=True, slots=True)
class RunParticipation:
    """One half-open interval of a Plant in the Run's Growspace."""

    plant_id: str
    opened_at: datetime
    closed_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return the durable form."""
        return {
            "plant_id": self.plant_id,
            "opened_at": self.opened_at.isoformat(),
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
        }

    @classmethod
    def from_dict(cls, value: Any) -> RunParticipation:
        """Read the durable form back."""
        value = _dict(value, "participation")
        interval = cls(
            plant_id=_str(value.get("plant_id"), "participation.plant_id"),
            opened_at=_moment(value.get("opened_at"), "participation.opened_at"),
            closed_at=_opt_moment(value.get("closed_at"), "participation.closed_at"),
        )
        if interval.closed_at is not None and interval.closed_at < interval.opened_at:
            raise ValueError("Participation closes before it opens")
        return interval


@dataclass(frozen=True, slots=True)
class PlantMovementFact:
    """A durable observation of a successful Plant location mutation."""

    fact_id: str
    plant_id: str
    at: datetime
    kind: str
    source_growspace_id: str | None
    target_growspace_id: str | None
    source_run_id: str | None
    target_run_id: str | None
    projected: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Return the durable and wire form of the fact."""
        return {
            "fact_id": self.fact_id,
            "plant_id": self.plant_id,
            "at": self.at.isoformat(),
            "kind": self.kind,
            "source_growspace_id": self.source_growspace_id,
            "target_growspace_id": self.target_growspace_id,
            "source_run_id": self.source_run_id,
            "target_run_id": self.target_run_id,
            "projected": self.projected,
        }

    @classmethod
    def from_dict(cls, value: Any) -> PlantMovementFact:
        """Validate one fact read from the Plant outbox."""
        value = _dict(value, "activity fact")
        projected = value.get("projected", False)
        if not isinstance(projected, bool):
            raise TypeError("fact.projected is not boolean")
        return cls(
            fact_id=_str(value.get("fact_id"), "fact.id"),
            plant_id=_str(value.get("plant_id"), "fact.plant_id"),
            at=_moment(value.get("at"), "fact.at"),
            kind=_str(value.get("kind"), "fact.kind"),
            source_growspace_id=_opt_str(
                value.get("source_growspace_id"), "fact.source"
            ),
            target_growspace_id=_opt_str(
                value.get("target_growspace_id"), "fact.target"
            ),
            source_run_id=_opt_str(value.get("source_run_id"), "fact.source_run"),
            target_run_id=_opt_str(value.get("target_run_id"), "fact.target_run"),
            projected=projected,
        )


@dataclass(frozen=True, slots=True)
class DailySummary:
    """One local day of a Growspace's activity: who stood in it, who came and went.

    Kept by the Unattributed Activity Ledger while no Run is active, and handed
    whole to the Run that claims that day. A day with no summary is a day Home
    Assistant never observed the Growspace.
    """

    day: date
    plant_ids: tuple[str, ...] = ()
    entries: int = 0
    exits: int = 0

    def as_dict(self) -> dict[str, Any]:
        """Return the durable and wire form."""
        return {
            "date": self.day.isoformat(),
            "plant_ids": list(self.plant_ids),
            "entries": self.entries,
            "exits": self.exits,
        }

    @classmethod
    def from_dict(cls, value: Any) -> DailySummary:
        """Read the durable form back."""
        value = _dict(value, "daily summary")
        plant_ids = _list(value.get("plant_ids"), "day.plant_ids")
        return cls(
            day=_date(value.get("date"), "day.date"),
            plant_ids=tuple(_str(plant, "day.plant_ids[]") for plant in plant_ids),
            entries=_int(value.get("entries"), "day.entries", 0),
            exits=_int(value.get("exits"), "day.exits", 0),
        )


class GapReason(StrEnum):
    """Why part of a backdated Run's interval has no activity to claim."""

    #: Before the Unattributed Activity Ledger began covering the Growspace.
    BEFORE_RECORDING = "before_recording"
    #: A whole local day on which Home Assistant never observed the Growspace.
    NOT_OBSERVED = "not_observed"


@dataclass(frozen=True, slots=True)
class CoverageGap:
    """A half-open interval of a backdated Run with nothing recorded for it."""

    start: datetime
    end: datetime
    reason: GapReason

    def as_dict(self) -> dict[str, Any]:
        """Return the durable and wire form."""
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "reason": self.reason.value,
        }

    @classmethod
    def from_dict(cls, value: Any) -> CoverageGap:
        """Read the durable form back."""
        value = _dict(value, "coverage gap")
        gap = cls(
            start=_moment(value.get("start"), "gap.start"),
            end=_moment(value.get("end"), "gap.end"),
            reason=GapReason(value.get("reason")),
        )
        if gap.end <= gap.start:
            raise ValueError("a coverage gap ends before it starts")
        return gap


@dataclass(frozen=True, slots=True)
class RunBackdate:
    """How a Run started in the past: the day asked for and what it could not see.

    ``covered_from`` is where claimed activity begins; anything between the
    start and it, and every day listed in ``gaps``, is uncovered rather than
    inferred.
    """

    started_on: date
    covered_from: datetime
    claimed_facts: int
    gaps: tuple[CoverageGap, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        """Return the durable form."""
        return {
            "started_on": self.started_on.isoformat(),
            "covered_from": self.covered_from.isoformat(),
            "claimed_facts": self.claimed_facts,
            "gaps": [gap.as_dict() for gap in self.gaps],
        }

    @classmethod
    def from_dict(cls, value: Any) -> RunBackdate:
        """Read the durable form back."""
        value = _dict(value, "backdate")
        return cls(
            started_on=_date(value.get("started_on"), "backdate.started_on"),
            covered_from=_moment(value.get("covered_from"), "backdate.covered_from"),
            claimed_facts=_int(value.get("claimed_facts"), "backdate.claimed", 0),
            gaps=tuple(
                CoverageGap.from_dict(row)
                for row in _list(value.get("gaps"), "backdate.gaps")
            ),
        )


@dataclass(frozen=True, slots=True)
class HarvestOutcome:
    """Last committed harvest facts for a source Run, independent of the Plant."""

    plant_id: str
    strain: str
    phenotype: str
    source_growspace_id: str
    state: str
    reason: str | None
    metrics: dict[str, Any]
    quality_score: float | None

    def as_dict(self) -> dict[str, Any]:
        """Return the durable and wire snapshot."""
        return {
            "plant_id": self.plant_id,
            "strain": self.strain,
            "phenotype": self.phenotype,
            "source_growspace_id": self.source_growspace_id,
            "state": self.state,
            "reason": self.reason,
            "metrics": dict(self.metrics),
            "quality_score": self.quality_score,
        }

    @classmethod
    def from_dict(cls, value: Any) -> HarvestOutcome:
        """Read a stored snapshot without inventing a missing outcome."""
        value = _dict(value, "harvest outcome")
        state = _str(value.get("state"), "outcome.state")
        if state not in {"pending", "recorded", "no_usable_yield", "incomplete"}:
            raise ValueError("unknown harvest outcome state")
        reason = _opt_str(value.get("reason"), "outcome.reason")
        if state == "no_usable_yield" and not (reason and reason.strip()):
            raise ValueError("No Usable Yield needs a reason")
        metrics = _dict(value.get("metrics"), "outcome.metrics")
        dry_weight = metrics.get("dry_weight")
        if dry_weight is not None and (
            isinstance(dry_weight, bool)
            or not isinstance(dry_weight, (int, float))
            or dry_weight < 0
        ):
            raise ValueError("outcome.dry_weight is invalid")
        if state == "no_usable_yield" and dry_weight != 0:
            raise ValueError("No Usable Yield must record zero dry weight")
        if state == "incomplete" and dry_weight is not None:
            raise ValueError("an incomplete outcome cannot have a dry weight")
        quality = value.get("quality_score")
        if quality is not None and (
            isinstance(quality, bool) or not isinstance(quality, (int, float))
        ):
            raise TypeError("outcome.quality_score is not numeric")
        return cls(
            plant_id=_str(value.get("plant_id"), "outcome.plant_id"),
            strain=_opt_str(value.get("strain"), "outcome.strain") or "",
            phenotype=_opt_str(value.get("phenotype"), "outcome.phenotype") or "",
            source_growspace_id=_str(
                value.get("source_growspace_id"), "outcome.source"
            ),
            state=state,
            reason=reason,
            metrics=metrics,
            quality_score=quality,
        )


@dataclass(frozen=True, slots=True)
class ClaimedHistory:
    """Everything a backdated start takes from the Unattributed Activity Ledger.

    Built by `domain.unattributed_activity.plan_claim`; the facts are still
    unattributed here and become the Run's when the start commits.
    """

    started_at: datetime
    backdate: RunBackdate
    participations: tuple[RunParticipation, ...]
    facts: tuple[PlantMovementFact, ...]
    days: tuple[DailySummary, ...]


@dataclass(frozen=True, slots=True)
class RunAuditEntry:
    """The immutable record of one lifecycle command."""

    at: datetime
    command: RunCommand
    command_id: str
    actor_user_id: str | None
    prior_revision: int
    resulting_revision: int

    def as_dict(self) -> dict[str, Any]:
        """Return the durable form."""
        return {
            "at": self.at.isoformat(),
            "command": self.command.value,
            "command_id": self.command_id,
            "actor_user_id": self.actor_user_id,
            "prior_revision": self.prior_revision,
            "resulting_revision": self.resulting_revision,
        }

    @classmethod
    def from_dict(cls, value: Any) -> RunAuditEntry:
        """Read the durable form back."""
        value = _dict(value, "audit entry")
        return cls(
            at=_moment(value.get("at"), "audit.at"),
            command=RunCommand(value.get("command")),
            command_id=_str(value.get("command_id"), "audit.command_id"),
            actor_user_id=_opt_str(value.get("actor_user_id"), "audit.actor_user_id"),
            prior_revision=_int(value.get("prior_revision"), "audit.prior", 0),
            resulting_revision=_int(
                value.get("resulting_revision"), "audit.resulting", 1
            ),
        )


@dataclass(frozen=True, slots=True)
class GrowRun:
    """One Grow Run of one Growspace."""

    run_id: str
    growspace_id: str
    sequence_number: int
    status: RunStatus
    timezone: str
    started_at: datetime
    metadata: RunMetadata = field(default_factory=RunMetadata)
    baseline: OpeningBaseline = field(default_factory=OpeningBaseline)
    participations: tuple[RunParticipation, ...] = ()
    movement_history: tuple[PlantMovementFact, ...] = ()
    harvest_outcomes: tuple[HarvestOutcome, ...] = ()
    audit: tuple[RunAuditEntry, ...] = ()
    daily_summaries: tuple[DailySummary, ...] = ()
    backdate: RunBackdate | None = None

    @property
    def participant_count(self) -> int:
        """Each Plant counts once, however many intervals it has."""
        return len({row.plant_id for row in self.participations})

    def local_days(self, now: datetime) -> int:
        """Whole local days since the start, in the Run Timezone."""
        zone = ZoneInfo(self.timezone)
        return (
            now.astimezone(zone).date() - self.started_at.astimezone(zone).date()
        ).days

    def as_dict(self) -> dict[str, Any]:
        """Return the durable form."""
        return {
            "run_id": self.run_id,
            "growspace_id": self.growspace_id,
            "sequence_number": self.sequence_number,
            "status": self.status.value,
            "timezone": self.timezone,
            "started_at": self.started_at.isoformat(),
            "metadata": self.metadata.as_dict(),
            "baseline": self.baseline.as_dict(),
            "participations": [row.as_dict() for row in self.participations],
            "movement_history": [row.as_dict() for row in self.movement_history],
            "harvest_outcomes": [row.as_dict() for row in self.harvest_outcomes],
            "audit": [row.as_dict() for row in self.audit],
            "daily_summaries": [row.as_dict() for row in self.daily_summaries],
            "backdate": self.backdate.as_dict() if self.backdate else None,
        }

    @classmethod
    def from_dict(cls, value: Any) -> GrowRun:
        """Read the durable form back, refusing anything incomplete."""
        value = _dict(value, "run")
        run = cls(
            run_id=_str(value.get("run_id"), "run.run_id"),
            growspace_id=_str(value.get("growspace_id"), "run.growspace_id"),
            sequence_number=_int(value.get("sequence_number"), "run.sequence", 1),
            status=RunStatus(value.get("status")),
            timezone=_zone(value.get("timezone"), "run.timezone"),
            started_at=_moment(value.get("started_at"), "run.started_at"),
            metadata=RunMetadata.from_dict(value.get("metadata")),
            baseline=OpeningBaseline.from_dict(value.get("baseline")),
            participations=tuple(
                RunParticipation.from_dict(row)
                for row in _list(value.get("participations"), "run.participations")
            ),
            movement_history=tuple(
                PlantMovementFact.from_dict(row)
                for row in _list(
                    value.get("movement_history", []), "run.movement_history"
                )
            ),
            harvest_outcomes=tuple(
                HarvestOutcome.from_dict(row)
                for row in _list(
                    value.get("harvest_outcomes", []), "run.harvest_outcomes"
                )
            ),
            audit=tuple(
                RunAuditEntry.from_dict(row)
                for row in _list(value.get("audit"), "run.audit")
            ),
            daily_summaries=tuple(
                DailySummary.from_dict(row)
                for row in _list(value.get("daily_summaries", []), "run.days")
            ),
            backdate=(
                None
                if value.get("backdate") is None
                else RunBackdate.from_dict(value.get("backdate"))
            ),
        )
        open_plants = [
            row.plant_id for row in run.participations if row.closed_at is None
        ]
        if len(open_plants) != len(set(open_plants)):
            raise ValueError("a Plant has more than one open Run Participation")
        fact_ids = [row.fact_id for row in run.movement_history]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("a movement fact appears twice in one Run")
        outcome_ids = [row.plant_id for row in run.harvest_outcomes]
        if len(outcome_ids) != len(set(outcome_ids)):
            raise ValueError("a Plant has more than one harvest outcome in one Run")
        return run


@dataclass(frozen=True, slots=True)
class RunLedger:
    """One Growspace's Runs, its next Sequence Number, and its Run Revision."""

    growspace_id: str
    revision: int = 0
    next_sequence: int = 1
    runs: tuple[GrowRun, ...] = ()

    @property
    def active_run(self) -> GrowRun | None:
        """The one Active Run, if there is one."""
        return next((r for r in self.runs if r.status is RunStatus.ACTIVE), None)

    def require_revision(self, expected: int) -> None:
        """Refuse a command decided on any revision but this one."""
        if expected != self.revision:
            raise RunRevisionConflict(
                f"The Run Revision is {self.revision}, not {expected}; "
                "reload and decide again",
                current_revision=self.revision,
                active_run=self.active_run,
            )

    def project_movement(self, fact: PlantMovementFact) -> RunLedger:
        """Apply one fact once, closing and opening half-open intervals."""
        run_ids = {fact.source_run_id, fact.target_run_id} - {None}
        changed = False
        runs: list[GrowRun] = []
        for run in self.runs:
            if run.run_id not in run_ids or any(
                row.fact_id == fact.fact_id for row in run.movement_history
            ):
                runs.append(run)
                continue
            intervals = list(run.participations)
            exits = fact.source_run_id == run.run_id and (
                fact.target_run_id != run.run_id or fact.target_growspace_id is None
            )
            enters = fact.target_run_id == run.run_id and (
                fact.source_run_id != run.run_id or fact.source_growspace_id is None
            )
            if exits:
                for index in range(len(intervals) - 1, -1, -1):
                    interval = intervals[index]
                    if (
                        interval.plant_id == fact.plant_id
                        and interval.closed_at is None
                    ):
                        intervals[index] = replace(interval, closed_at=fact.at)
                        break
            if enters and not any(
                row.plant_id == fact.plant_id and row.closed_at is None
                for row in intervals
            ):
                intervals.append(RunParticipation(fact.plant_id, fact.at))
            runs.append(
                replace(
                    run,
                    participations=tuple(intervals),
                    movement_history=(
                        *run.movement_history,
                        replace(fact, projected=True),
                    ),
                )
            )
            changed = True
        return replace(self, runs=tuple(runs)) if changed else self

    def project_harvest_outcome(
        self, run_id: str, outcome: HarvestOutcome
    ) -> RunLedger:
        """Refresh a source snapshot while the Run is still editable."""
        runs: list[GrowRun] = []
        for run in self.runs:
            if run.run_id != run_id:
                runs.append(run)
                continue
            if run.status in {RunStatus.FINALIZED, RunStatus.VOIDED}:
                return self
            existing = tuple(
                row for row in run.harvest_outcomes if row.plant_id != outcome.plant_id
            )
            runs.append(replace(run, harvest_outcomes=(*existing, outcome)))
        return replace(self, runs=tuple(runs)) if tuple(runs) != self.runs else self

    def start(
        self,
        *,
        expected_revision: int,
        run_id: str,
        command_id: str,
        now: datetime,
        timezone: str,
        metadata: RunMetadata,
        baseline: OpeningBaseline,
        plant_ids: list[str] | tuple[str, ...],
        actor_user_id: str | None,
        claim: ClaimedHistory | None = None,
    ) -> tuple[RunLedger, GrowRun]:
        """Start a Run; return the advanced ledger and the Run it holds.

        The Plants present become Participants from this boundary. None is a
        valid answer: an empty Growspace can start a Run.

        With a ``claim`` the Run starts in the past instead: its boundary,
        Participants and movement history are the claimed Unattributed
        Activity, now attributed to it, and ``plant_ids`` is unused. The
        audit entry still records when the start was committed.
        """
        self.require_revision(expected_revision)
        if (active := self.active_run) is not None:
            raise RunAlreadyActive(
                f"Run #{active.sequence_number} is already active",
                current_revision=self.revision,
                active_run=active,
            )
        _zone(timezone, "timezone")
        resulting = self.revision + 1
        if claim is None:
            started_at = now
            participations = tuple(
                RunParticipation(plant_id, now) for plant_id in dict.fromkeys(plant_ids)
            )
        else:
            started_at = claim.started_at
            participations = claim.participations
        run = GrowRun(
            run_id=run_id,
            growspace_id=self.growspace_id,
            sequence_number=self.next_sequence,
            status=RunStatus.ACTIVE,
            timezone=timezone,
            started_at=started_at,
            metadata=metadata,
            baseline=baseline,
            participations=participations,
            movement_history=(
                ()
                if claim is None
                else tuple(
                    _attribute(fact, self.growspace_id, run_id) for fact in claim.facts
                )
            ),
            daily_summaries=() if claim is None else claim.days,
            backdate=None if claim is None else claim.backdate,
            audit=(
                RunAuditEntry(
                    at=now,
                    command=RunCommand.START,
                    command_id=command_id,
                    actor_user_id=actor_user_id,
                    prior_revision=self.revision,
                    resulting_revision=resulting,
                ),
            ),
        )
        ledger = replace(
            self,
            revision=resulting,
            next_sequence=self.next_sequence + 1,
            runs=(*self.runs, run),
        )
        return ledger, run

    def as_dict(self) -> dict[str, Any]:
        """Return the durable form."""
        return {
            "growspace_id": self.growspace_id,
            "revision": self.revision,
            "next_sequence": self.next_sequence,
            "runs": [run.as_dict() for run in self.runs],
        }

    @classmethod
    def from_dict(cls, value: Any) -> RunLedger:
        """Read the durable form back and hold it to the ledger's invariants."""
        value = _dict(value, "ledger")
        ledger = cls(
            growspace_id=_str(value.get("growspace_id"), "ledger.growspace_id"),
            revision=_int(value.get("revision"), "ledger.revision", 0),
            next_sequence=_int(value.get("next_sequence"), "ledger.next_sequence", 1),
            runs=tuple(
                GrowRun.from_dict(row)
                for row in _list(value.get("runs"), "ledger.runs")
            ),
        )
        sequences = [run.sequence_number for run in ledger.runs]
        if len(set(sequences)) != len(sequences) or any(
            number >= ledger.next_sequence for number in sequences
        ):
            raise ValueError("Run Sequence Numbers are reused or ahead of the ledger")
        if any(run.growspace_id != ledger.growspace_id for run in ledger.runs):
            raise ValueError("a Run is filed under another Growspace")
        if sum(run.status is RunStatus.ACTIVE for run in ledger.runs) > 1:
            raise ValueError("more than one Active Run")
        return ledger


def _attribute(
    fact: PlantMovementFact, growspace_id: str, run_id: str
) -> PlantMovementFact:
    """Name the claiming Run on whichever side of the fact is this Growspace."""
    return replace(
        fact,
        source_run_id=(
            run_id if fact.source_growspace_id == growspace_id else fact.source_run_id
        ),
        target_run_id=(
            run_id if fact.target_growspace_id == growspace_id else fact.target_run_id
        ),
        projected=True,
    )


def run_summary(run: GrowRun, revision: int) -> dict[str, Any]:
    """The compact wire form of one Run at one Run Revision."""
    return {
        "run_id": run.run_id,
        "sequence_number": run.sequence_number,
        "label": run.metadata.label,
        "started_at": run.started_at.isoformat(),
        "timezone": run.timezone,
        "participant_count": run.participant_count,
        "run_revision": revision,
    }


def run_details(run: GrowRun, revision: int) -> dict[str, Any]:
    """The selected Run's Participants and chronological movement history."""
    return {
        "outcome": "found",
        "run": {
            **run_summary(run, revision),
            "participations": [row.as_dict() for row in run.participations],
            "movement_history": [row.as_dict() for row in run.movement_history],
            "harvest_outcomes": [row.as_dict() for row in run.harvest_outcomes],
        },
    }


def sensor_state(ledger: RunLedger, now: datetime) -> tuple[int | str, dict[str, Any]]:
    """The Active Run Sensor: sequence number or ``none``, and compact attributes.

    The key set is fixed so the sensor reads the same shape whether a Run is
    active or not; only the Run Revision is meaningful without one, and it is
    the one value a Start needs.
    """
    run = ledger.active_run
    if run is None:
        return "none", {
            "run_id": None,
            "label": None,
            "started_at": None,
            "duration_days": None,
            "participant_count": None,
            "run_revision": ledger.revision,
        }
    return run.sequence_number, {
        "run_id": run.run_id,
        "label": run.metadata.label,
        "started_at": run.started_at.isoformat(),
        "duration_days": run.local_days(now),
        "participant_count": run.participant_count,
        "run_revision": ledger.revision,
    }
