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
from datetime import datetime
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
CODE_NOT_ACTIVE = "grow_run.not_active"
CODE_IRRIGATION_DELIVERING = "grow_run.irrigation_delivering"
CODE_ACKNOWLEDGEMENT_REQUIRED = "grow_run.acknowledgement_required"

# Run Completion Preview warnings. Each one names a Plant or outcome at risk; a
# completion must acknowledge every warning the preview holds when it commits.
WARNING_PLANTS_PRESENT = "plants_present"
WARNING_MISSING_OUTCOMES = "missing_outcomes"
WARNING_ATTRIBUTION_GAPS = "attribution_gaps"


class RunStatus(StrEnum):
    """The Grow Run State Graph's states. ``active`` and ``completed`` are reachable."""

    ACTIVE = "active"
    COMPLETED = "completed"
    FINALIZED = "finalized"
    VOIDED = "voided"


class RunCommand(StrEnum):
    """The lifecycle commands a Run Audit Entry can record."""

    START = "start"
    COMPLETE = "complete"


class GrowRunRefused(Exception):
    """A lifecycle command the ledger would not take, and where it stands."""

    code: str = "grow_run.refused"

    def __init__(
        self,
        message: str,
        *,
        current_revision: int | None,
        active_run: GrowRun | None = None,
    ) -> None:
        """Keep the ledger's position beside the refusal."""
        super().__init__(message)
        self.current_revision = current_revision
        self.active_run = active_run


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


class RunNotActive(GrowRunRefused):
    """The command names a Run that is not the Growspace's Active Run."""

    code = CODE_NOT_ACTIVE


class RunIrrigationDelivering(GrowRunRefused):
    """Integration-controlled irrigation is delivering water at the boundary."""

    code = CODE_IRRIGATION_DELIVERING


class RunAcknowledgementRequired(GrowRunRefused):
    """The completion did not acknowledge every warning its preview holds now."""

    code = CODE_ACKNOWLEDGEMENT_REQUIRED


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
    audit: tuple[RunAuditEntry, ...] = ()
    #: The end of the half-open operating interval; absent while Active.
    completed_at: datetime | None = None

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

    def covers(self, moment: datetime) -> bool:
        """Whether ``moment`` falls inside the half-open operating interval."""
        return self.started_at <= moment and (
            self.completed_at is None or moment < self.completed_at
        )

    def as_dict(self) -> dict[str, Any]:
        """Return the durable form."""
        return {
            "run_id": self.run_id,
            "growspace_id": self.growspace_id,
            "sequence_number": self.sequence_number,
            "status": self.status.value,
            "timezone": self.timezone,
            "started_at": self.started_at.isoformat(),
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "metadata": self.metadata.as_dict(),
            "baseline": self.baseline.as_dict(),
            "participations": [row.as_dict() for row in self.participations],
            "movement_history": [row.as_dict() for row in self.movement_history],
            "audit": [row.as_dict() for row in self.audit],
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
            completed_at=_opt_moment(value.get("completed_at"), "run.completed_at"),
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
            audit=tuple(
                RunAuditEntry.from_dict(row)
                for row in _list(value.get("audit"), "run.audit")
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
        if run.status is RunStatus.ACTIVE and run.completed_at is not None:
            raise ValueError("an Active Run has a completion boundary")
        if run.status is RunStatus.COMPLETED:
            if run.completed_at is None or run.completed_at < run.started_at:
                raise ValueError("a Completed Run has no valid completion boundary")
            if open_plants:
                raise ValueError("a Completed Run still has open participation")
        return run


# ---------------------------------------------------------------------------
# The Run Completion Preview
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PresentPlant:
    """A Plant standing in the Growspace as the Run would complete."""

    plant_id: str
    strain_name: str
    phenotype_name: str
    stage: str

    def as_dict(self) -> dict[str, Any]:
        """Return the wire form."""
        return {
            "plant_id": self.plant_id,
            "strain_name": self.strain_name,
            "phenotype_name": self.phenotype_name,
            "stage": self.stage,
        }


@dataclass(frozen=True, slots=True)
class MissingOutcome:
    """A Plant harvested out of the Run whose dry weight is not known.

    ``plant_removed`` is the one that can no longer be recorded against the
    live Plant; ``no_dry_weight`` may still arrive while the Run is Completed.
    """

    plant_id: str
    harvested_at: datetime
    reason: str

    def as_dict(self) -> dict[str, Any]:
        """Return the wire form."""
        return {
            "plant_id": self.plant_id,
            "harvested_at": self.harvested_at.isoformat(),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class AttributionGap:
    """Something the Run's participation history cannot yet account for.

    ``pending_fact``: a movement recorded in this Growspace inside the Run that
    has not been projected. ``unrecorded_presence``: a Plant standing here with
    no open participation. Both mean the Run would complete on an incomplete
    history of who was in it.
    """

    kind: str
    plant_id: str
    fact_id: str | None = None
    at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return the wire form."""
        return {
            "kind": self.kind,
            "plant_id": self.plant_id,
            "fact_id": self.fact_id,
            "at": self.at.isoformat() if self.at else None,
        }


@dataclass(frozen=True, slots=True)
class CompletionPreview:
    """What completing the Active Run at ``completed_at`` would do and risk.

    It is computed afresh at commit as well as for the grower, so the warnings
    a completion must acknowledge are the ones true when it lands, not the ones
    true when the dialog opened.
    """

    run: GrowRun
    revision: int
    completed_at: datetime
    plants_present: tuple[PresentPlant, ...] = ()
    missing_outcomes: tuple[MissingOutcome, ...] = ()
    attribution_gaps: tuple[AttributionGap, ...] = ()
    delivering_outputs: tuple[str, ...] = ()
    retrospective_note: str | None = None

    @property
    def closing(self) -> tuple[RunParticipation, ...]:
        """The participation intervals the boundary will close."""
        return tuple(row for row in self.run.participations if row.closed_at is None)

    @property
    def warnings(self) -> tuple[str, ...]:
        """The risks a completion must acknowledge, in a stable order."""
        return tuple(
            code
            for code, present in (
                (WARNING_PLANTS_PRESENT, self.plants_present),
                (WARNING_MISSING_OUTCOMES, self.missing_outcomes),
                (WARNING_ATTRIBUTION_GAPS, self.attribution_gaps),
            )
            if present
        )

    @property
    def blockers(self) -> tuple[str, ...]:
        """What refuses the completion outright rather than asking."""
        return (CODE_IRRIGATION_DELIVERING,) if self.delivering_outputs else ()

    def as_dict(self) -> dict[str, Any]:
        """Return the wire form the Run Completion Preview is drawn from."""
        return {
            "run": run_summary(self.run, self.revision),
            "completed_at": self.completed_at.isoformat(),
            "duration_days": self.run.local_days(self.completed_at),
            "closing_participations": [row.as_dict() for row in self.closing],
            "plants_present": [row.as_dict() for row in self.plants_present],
            "missing_outcomes": [row.as_dict() for row in self.missing_outcomes],
            # Metric Coverage per Run metric. No Run metric is measured yet
            # (#676-#679 add them), so there is nothing whose coverage could
            # fall short; the key is here so those metrics add rows, not shape.
            "coverage": [],
            "attribution_gaps": [row.as_dict() for row in self.attribution_gaps],
            "retrospective_note": self.retrospective_note,
            "delivering_outputs": list(self.delivering_outputs),
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
        }


def preview_completion(
    ledger: RunLedger,
    *,
    now: datetime,
    plants_present: list[PresentPlant] | tuple[PresentPlant, ...],
    dry_weights: dict[str, float | None],
    pending_facts: list[PlantMovementFact] | tuple[PlantMovementFact, ...],
    delivering_outputs: list[str] | tuple[str, ...],
    retrospective_note: str | None,
) -> CompletionPreview:
    """Preview completing the ledger's Active Run at ``now``.

    ``dry_weights`` holds every Plant that still exists, by ID; a harvested
    Plant missing from it has been removed. ``pending_facts`` are the Plant
    outbox's unprojected facts, of any Growspace.
    """
    run = ledger.active_run
    if run is None:
        raise RunNotActive(
            "This growspace has no Active Run to complete",
            current_revision=ledger.revision,
        )
    harvested: dict[str, datetime] = {}
    for fact in run.movement_history:
        if fact.kind == "harvest" and fact.source_run_id == run.run_id:
            harvested.setdefault(fact.plant_id, fact.at)
    missing = tuple(
        MissingOutcome(
            plant_id,
            at,
            "plant_removed" if plant_id not in dry_weights else "no_dry_weight",
        )
        for plant_id, at in harvested.items()
        if dry_weights.get(plant_id) is None
    )
    open_plants = {row.plant_id for row in run.participations if row.closed_at is None}
    gaps = [
        AttributionGap("pending_fact", fact.plant_id, fact.fact_id, fact.at)
        for fact in pending_facts
        if not fact.projected
        and run.covers(fact.at)
        and run.growspace_id in (fact.source_growspace_id, fact.target_growspace_id)
    ]
    pending_plants = {gap.plant_id for gap in gaps}
    gaps.extend(
        AttributionGap("unrecorded_presence", plant.plant_id)
        for plant in plants_present
        if plant.plant_id not in open_plants and plant.plant_id not in pending_plants
    )
    return CompletionPreview(
        run=run,
        revision=ledger.revision,
        completed_at=now,
        plants_present=tuple(sorted(plants_present, key=lambda row: row.plant_id)),
        missing_outcomes=missing,
        attribution_gaps=tuple(gaps),
        delivering_outputs=tuple(sorted(set(delivering_outputs))),
        retrospective_note=_text(retrospective_note, MAX_TEXT_LENGTH),
    )


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

    def run_at(self, moment: datetime) -> GrowRun | None:
        """The Active or Completed Run whose operating interval holds ``moment``."""
        return next(
            (
                run
                for run in self.runs
                if run.status in (RunStatus.ACTIVE, RunStatus.COMPLETED)
                and run.covers(moment)
            ),
            None,
        )

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
        """Apply one fact once, closing and opening half-open intervals.

        A fact can reach a Run after it completed: it was recorded before the
        boundary but projected after it. Inside the operating interval it still
        counts, against the boundary -- an interval completion closed is the
        one it re-closes earlier, and an entry opens one that ends there. A
        fact at or after the boundary is outside the Run and changes nothing.
        """
        run_ids = {fact.source_run_id, fact.target_run_id} - {None}
        changed = False
        runs: list[GrowRun] = []
        for run in self.runs:
            if (
                run.run_id not in run_ids
                or run.status not in (RunStatus.ACTIVE, RunStatus.COMPLETED)
                or not run.covers(fact.at)
                or any(row.fact_id == fact.fact_id for row in run.movement_history)
            ):
                runs.append(run)
                continue
            # Still open: unclosed while Active, closed only by the boundary once
            # Completed. For an Active Run both read ``closed_at is None``.
            boundary = run.completed_at
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
                        and interval.closed_at == boundary
                        and interval.opened_at <= fact.at
                    ):
                        intervals[index] = replace(interval, closed_at=fact.at)
                        break
            if enters and not any(
                row.plant_id == fact.plant_id and row.closed_at == boundary
                for row in intervals
            ):
                intervals.append(RunParticipation(fact.plant_id, fact.at, boundary))
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
    ) -> tuple[RunLedger, GrowRun]:
        """Start a Run; return the advanced ledger and the Run it holds.

        The Plants present become Participants from this boundary. None is a
        valid answer: an empty Growspace can start a Run.
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
        run = GrowRun(
            run_id=run_id,
            growspace_id=self.growspace_id,
            sequence_number=self.next_sequence,
            status=RunStatus.ACTIVE,
            timezone=timezone,
            started_at=now,
            metadata=metadata,
            baseline=baseline,
            participations=tuple(
                RunParticipation(plant_id, now) for plant_id in dict.fromkeys(plant_ids)
            ),
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

    def complete(
        self,
        *,
        expected_revision: int,
        run_id: str,
        preview: CompletionPreview,
        acknowledged: list[str] | tuple[str, ...] | set[str],
        command_id: str,
        actor_user_id: str | None,
    ) -> tuple[RunLedger, GrowRun]:
        """End the Active Run at the preview's boundary; return the new ledger.

        Every open participation closes at the boundary, the Run becomes
        Completed, and the retrospective note becomes its notes. Irrigation
        delivering water refuses outright; any warning the grower did not
        acknowledge refuses and asks again.
        """
        self.require_revision(expected_revision)
        run = self.active_run
        if run is None or run.run_id != run_id or preview.run.run_id != run_id:
            raise RunNotActive(
                "That Run is not this growspace's Active Run",
                current_revision=self.revision,
                active_run=run,
            )
        if preview.delivering_outputs:
            raise RunIrrigationDelivering(
                "Irrigation is delivering water through "
                f"{', '.join(preview.delivering_outputs)}; complete the run "
                "once it has finished",
                current_revision=self.revision,
                active_run=run,
            )
        if unacknowledged := [
            code for code in preview.warnings if code not in set(acknowledged)
        ]:
            raise RunAcknowledgementRequired(
                f"Completing Run #{run.sequence_number} needs acknowledgement "
                f"of: {', '.join(unacknowledged)}",
                current_revision=self.revision,
                active_run=run,
            )
        boundary = preview.completed_at
        if boundary < run.started_at:
            raise ValueError("a Run cannot complete before it started")
        resulting = self.revision + 1
        completed = replace(
            run,
            status=RunStatus.COMPLETED,
            completed_at=boundary,
            metadata=replace(run.metadata, notes=preview.retrospective_note),
            participations=tuple(
                replace(row, closed_at=boundary) if row.closed_at is None else row
                for row in run.participations
            ),
            audit=(
                *run.audit,
                RunAuditEntry(
                    at=boundary,
                    command=RunCommand.COMPLETE,
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
            runs=tuple(completed if row is run else row for row in self.runs),
        )
        return ledger, completed

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


#: Which metrics a Run's status gives it: Live Run Metrics while Active,
#: Pending Run Metrics once Completed, a frozen Finalization Snapshot after.
METRICS_STATE = {
    RunStatus.ACTIVE: "live",
    RunStatus.COMPLETED: "pending",
    RunStatus.FINALIZED: "frozen",
    RunStatus.VOIDED: "excluded",
}


def run_summary(run: GrowRun, revision: int) -> dict[str, Any]:
    """The compact wire form of one Run at one Run Revision."""
    return {
        "run_id": run.run_id,
        "sequence_number": run.sequence_number,
        "label": run.metadata.label,
        "status": run.status.value,
        "started_at": run.started_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "timezone": run.timezone,
        "participant_count": run.participant_count,
        "metrics_state": METRICS_STATE[run.status],
        "run_revision": revision,
    }


def run_details(run: GrowRun, revision: int) -> dict[str, Any]:
    """The selected Run's Participants and chronological movement history."""
    return {
        "outcome": "found",
        "run": {
            **run_summary(run, revision),
            "notes": run.metadata.notes,
            "participations": [row.as_dict() for row in run.participations],
            "movement_history": [row.as_dict() for row in run.movement_history],
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
