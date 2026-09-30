"""Grow Runs: one Growspace's bounded operating episodes (#668, ADR-0033…0038).

A Growspace owns a **Run Ledger**: its Runs, the next Run Sequence Number and
the Run Revision. The ledger is the unit every lifecycle command is checked and
committed against, because the rule it guards -- zero or one Active Run -- is a
rule about the collection, not about any one Run. A command names the revision
it was decided on; a ledger that has moved since refuses it and says where it
is now, so a second tab or a stale automation can never start a second Run.

A Completed Run is **finalized** into a Run Finalization Snapshot (#673): the
identity, boundaries, Participant Identity Snapshots, counts, Strains, Harvest
Window and versioned metrics it will be compared and exported on, copied out
of everything they were derived from so that no later change to a Plant, a
Strain or the Growspace can reach them. A missing fact stays missing in it.

Two Finalized Runs of one Growspace are set side by side in a **Run
Comparison** (#675). Only their frozen metrics are compared, and a row gets a
Comparison Direction only when both values exist under the same Metric
Definition Version; an improvement judgment needs an agreed goal besides.

A Finalized Run is corrected by **Run Reopening** (#917): an administrator
returns it to Completed with a reason, the boundaries stay where they were, and
the snapshot it held is kept as superseded rather than overwritten, so the
next finalization lands beside it under a new Run Revision. An Active Run that
has recorded nothing can instead be **discarded**: it leaves the ledger, its
Sequence Number is never reused, and its audit trail stays behind.

This module is pure. It decides and records; persistence, Home Assistant state
and authorization belong to the shells around it.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime
from enum import StrEnum
import math
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

CODE_NOT_ACTIVE = "grow_run.not_active"
CODE_IRRIGATION_DELIVERING = "grow_run.irrigation_delivering"
CODE_ACKNOWLEDGEMENT_REQUIRED = "grow_run.acknowledgement_required"
CODE_NOT_FOUND = "grow_run.not_found"
CODE_NOT_COMPLETED = "grow_run.not_completed"
CODE_NOT_FINALIZED = "grow_run.not_finalized"
CODE_INSUFFICIENT_HISTORY = "grow_run.insufficient_history"
CODE_SAME_RUN = "grow_run.same_run"
CODE_REASON_REQUIRED = "grow_run.reason_required"
CODE_HAS_ACTIVITY = "grow_run.has_activity"

# Why an Active Run is not activity-free, and so cannot be discarded. A
# refusal lists every one that applies, in this order.
#: A Plant moved into, out of or within the Growspace under the Run.
ACTIVITY_FACTS = "activity_facts"
#: A Participant joined after the start, or one of the opening set left.
PARTICIPANTS_CHANGED = "participants_changed"
#: A Plant entered dry with this Run as its Harvest Source Run.
HARVEST_OUTCOMES = "harvest_outcomes"

# Run Completion Preview warnings. Each one names a Plant or outcome at risk; a
# completion must acknowledge every warning the preview holds when it commits.
WARNING_PLANTS_PRESENT = "plants_present"
WARNING_MISSING_OUTCOMES = "missing_outcomes"
WARNING_ATTRIBUTION_GAPS = "attribution_gaps"

#: The one finalization warning: the snapshot would freeze with facts missing.
WARNING_INCOMPLETE_SNAPSHOT = "incomplete_snapshot"

#: The Run Finalization Snapshot's own layout, apart from any metric's rules.
SNAPSHOT_FORMAT = 1

#: Metric Definition Versions. A change to how a metric is calculated takes a
#: new version, so values frozen under different rules are never compared.
METRIC_DEFINITIONS = {
    "yield": 1,
    "yield_per_harvest_source_plant": 1,
    "water_applied": 1,
    "water_productivity": 1,
}

#: The goal a Run Comparison judges each metric against. A Comparison
#: Direction receives an improvement judgment only for an agreed monotonic
#: goal; ``neutral`` metrics -- totals, and a per-plant Yield no goal has been
#: agreed for -- say only which way they moved. A metric not listed is neutral.
METRIC_GOALS: dict[str, str] = {
    "yield": "neutral",
    "yield_per_harvest_source_plant": "neutral",
    "water_applied": "neutral",
    "water_productivity": "higher",
}


class RunStatus(StrEnum):
    """The Grow Run State Graph's states; all but ``voided`` are reachable."""

    ACTIVE = "active"
    COMPLETED = "completed"
    FINALIZED = "finalized"
    VOIDED = "voided"


class RunCommand(StrEnum):
    """The lifecycle commands a Run Audit Entry can record."""

    START = "start"
    COMPLETE = "complete"
    FINALIZE = "finalize"
    EDIT_METADATA = "edit_metadata"
    REOPEN = "reopen"
    DISCARD = "discard"


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
        reasons: tuple[str, ...] = (),
    ) -> None:
        """Keep the ledger's position beside the refusal."""
        super().__init__(message)
        self.current_revision = current_revision
        self.active_run = active_run
        self.boundary = boundary
        #: Machine-readable causes, for a refusal that has more than one.
        self.reasons = reasons


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


class RunNotActive(GrowRunRefused):
    """The command names a Run that is not the Growspace's Active Run."""

    code = CODE_NOT_ACTIVE


class RunIrrigationDelivering(GrowRunRefused):
    """Integration-controlled irrigation is delivering water at the boundary."""

    code = CODE_IRRIGATION_DELIVERING


class RunAcknowledgementRequired(GrowRunRefused):
    """The command did not acknowledge every warning its preview holds now."""

    code = CODE_ACKNOWLEDGEMENT_REQUIRED


class RunNotFound(GrowRunRefused):
    """The command names a Run this Growspace's ledger does not hold."""

    code = CODE_NOT_FOUND


class RunNotCompleted(GrowRunRefused):
    """Only a Completed Run can be finalized."""

    code = CODE_NOT_COMPLETED


class RunNotFinalized(GrowRunRefused):
    """Only a Finalized Run is reopened or compared: nothing else has frozen facts."""

    code = CODE_NOT_FINALIZED


class RunInsufficientHistory(GrowRunRefused):
    """A Run Comparison needs two Finalized Runs and the Growspace has fewer."""

    code = CODE_INSUFFICIENT_HISTORY


class RunSameRun(GrowRunRefused):
    """A Run Comparison names one Run twice."""

    code = CODE_SAME_RUN


class RunReasonRequired(GrowRunRefused):
    """The command must say why, and said nothing."""

    code = CODE_REASON_REQUIRED


class RunHasActivity(GrowRunRefused):
    """The Active Run recorded something, so it cannot be discarded.

    ``reasons`` names each kind of activity it holds.
    """

    code = CODE_HAS_ACTIVITY


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


def _opt_int(value: Any, name: str) -> int | None:
    return None if value is None else _int(value, name, 0)


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
    #: When the Plant entered dry: what the Harvest Window is drawn from.
    #: Absent on a snapshot taken before #673, and then unknown, not guessed.
    entered_dry_at: datetime | None = None

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
            "entered_dry_at": (
                self.entered_dry_at.isoformat() if self.entered_dry_at else None
            ),
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
            entered_dry_at=_opt_moment(value.get("entered_dry_at"), "outcome.dry"),
        )


@dataclass(frozen=True, slots=True)
class ParticipantIdentity:
    """A Participant Identity Snapshot: who a Run Participant was.

    Refreshed from the live Plant while the Run is Active or Completed, so a
    correction before finalization reaches it, and kept when the Plant is
    deleted, so a Participant never becomes a bare ID.
    """

    plant_id: str
    plant_name: str
    strain_id: int | None
    strain_name: str
    phenotype_id: int | None
    phenotype_name: str

    def as_dict(self) -> dict[str, Any]:
        """Return the durable and wire form."""
        return {
            "plant_id": self.plant_id,
            "plant_name": self.plant_name,
            "strain_id": self.strain_id,
            "strain_name": self.strain_name,
            "phenotype_id": self.phenotype_id,
            "phenotype_name": self.phenotype_name,
        }

    @classmethod
    def from_dict(cls, value: Any) -> ParticipantIdentity:
        """Read the durable form back."""
        value = _dict(value, "participant identity")
        return cls(
            plant_id=_str(value.get("plant_id"), "identity.plant_id"),
            plant_name=_opt_str(value.get("plant_name"), "identity.plant_name") or "",
            strain_id=_opt_int(value.get("strain_id"), "identity.strain_id"),
            strain_name=_opt_str(value.get("strain_name"), "identity.strain") or "",
            phenotype_id=_opt_int(value.get("phenotype_id"), "identity.phenotype_id"),
            phenotype_name=(
                _opt_str(value.get("phenotype_name"), "identity.phenotype") or ""
            ),
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
    #: The Run Metadata fields an ``edit_metadata`` command changed.
    changed_fields: tuple[str, ...] = ()
    #: Why, for a command that is given one: required to reopen.
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return the durable and wire form."""
        return {
            "at": self.at.isoformat(),
            "command": self.command.value,
            "command_id": self.command_id,
            "actor_user_id": self.actor_user_id,
            "prior_revision": self.prior_revision,
            "resulting_revision": self.resulting_revision,
            "changed_fields": list(self.changed_fields),
            "reason": self.reason,
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
            changed_fields=tuple(
                _str(name, "audit.changed_fields[]")
                for name in _list(value.get("changed_fields", []), "audit.fields")
            ),
            reason=_opt_str(value.get("reason"), "audit.reason"),
        )


# ---------------------------------------------------------------------------
# The Run Finalization Snapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MissingFact:
    """A fact a snapshot needed and did not have, and whose it was.

    ``dry_weight``: a Harvest Source Plant still waiting for one.
    ``outcome_incomplete``: one recorded as never going to have one.
    ``entered_dry_at``: an outcome that does not say when its Plant entered dry.
    ``participant_identity``: a Participant no identity was ever captured for.
    ``harvest_source_plants``: a Run nothing was harvested from.
    ``yield``: a metric derived from a Yield that is itself incomplete.
    """

    kind: str
    plant_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return the durable and wire form."""
        return {"kind": self.kind, "plant_id": self.plant_id}

    @classmethod
    def from_dict(cls, value: Any) -> MissingFact:
        """Read the durable form back."""
        value = _dict(value, "missing fact")
        return cls(
            kind=_str(value.get("kind"), "missing.kind"),
            plant_id=_opt_str(value.get("plant_id"), "missing.plant_id"),
        )


@dataclass(frozen=True, slots=True)
class FrozenMetric:
    """One comparison metric as finalization froze it.

    ``value`` is absent whenever ``missing`` is not empty: an incomplete metric
    has no number, never a partial one standing in for the whole.
    """

    metric: str
    unit: str
    definition_version: int
    value: float | None
    missing: tuple[MissingFact, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        """Return the durable and wire form."""
        return {
            "metric": self.metric,
            "unit": self.unit,
            "definition_version": self.definition_version,
            "value": self.value,
            "complete": self.value is not None,
            "missing": [row.as_dict() for row in self.missing],
        }

    @classmethod
    def from_dict(cls, value: Any) -> FrozenMetric:
        """Read the durable form back; a value beside a missing fact is refused."""
        value = _dict(value, "frozen metric")
        number = value.get("value")
        if number is not None and (
            isinstance(number, bool) or not isinstance(number, (int, float))
        ):
            raise TypeError("metric.value is not numeric")
        metric = cls(
            metric=_str(value.get("metric"), "metric.metric"),
            unit=_str(value.get("unit"), "metric.unit"),
            definition_version=_int(
                value.get("definition_version"), "metric.definition_version", 1
            ),
            value=number,
            missing=tuple(
                MissingFact.from_dict(row)
                for row in _list(value.get("missing"), "metric.missing")
            ),
        )
        if (metric.value is None) == (not metric.missing):
            raise ValueError("a metric is either valued or missing a fact")
        return metric


@dataclass(frozen=True, slots=True)
class MetricCoverage:
    """How much of one metric's required interval valid data supported."""

    metric: str
    coverage_percent: float

    def as_dict(self) -> dict[str, Any]:
        """Return the durable and wire form."""
        return {"metric": self.metric, "coverage_percent": self.coverage_percent}

    @classmethod
    def from_dict(cls, value: Any) -> MetricCoverage:
        """Read the durable form back."""
        value = _dict(value, "coverage")
        percent = value.get("coverage_percent")
        if (
            isinstance(percent, bool)
            or not isinstance(percent, (int, float))
            or not 0 <= percent <= 100
        ):
            raise ValueError("coverage.coverage_percent is not a percentage")
        return cls(_str(value.get("metric"), "coverage.metric"), percent)


@dataclass(frozen=True, slots=True)
class StrainCount:
    """One Strain among a Run's Participants, as it was named then."""

    strain_id: int | None
    strain_name: str
    participants: int
    harvest_source_plants: int

    def as_dict(self) -> dict[str, Any]:
        """Return the durable and wire form."""
        return {
            "strain_id": self.strain_id,
            "strain_name": self.strain_name,
            "participants": self.participants,
            "harvest_source_plants": self.harvest_source_plants,
        }

    @classmethod
    def from_dict(cls, value: Any) -> StrainCount:
        """Read the durable form back."""
        value = _dict(value, "strain count")
        return cls(
            strain_id=_opt_int(value.get("strain_id"), "strain.strain_id"),
            strain_name=_opt_str(value.get("strain_name"), "strain.name") or "",
            participants=_int(value.get("participants"), "strain.participants", 0),
            harvest_source_plants=_int(
                value.get("harvest_source_plants"), "strain.harvest_sources", 0
            ),
        )


#: The counts a snapshot freezes, in the order the wire form lists them.
SNAPSHOT_COUNTS = (
    "participants",
    "harvest_source_plants",
    "recorded",
    "no_usable_yield",
    "missing_outcomes",
)


@dataclass(frozen=True, slots=True)
class RunSnapshot:
    """The Run Finalization Snapshot: a Run's facts, frozen and self-contained.

    Everything a comparison or an export reads of a Finalized Run is here or on
    the Run's own frozen records, so neither ever looks at a live Plant, Strain
    or Growspace again. ``missing`` is every fact the snapshot lacked, which is
    what made its finalization need acknowledging.
    """

    finalized_at: datetime
    run_id: str
    growspace_id: str
    growspace_name: str
    sequence_number: int
    timezone: str
    started_at: datetime
    completed_at: datetime
    duration_days: int
    harvest_window: tuple[date, date] | None
    participants: tuple[ParticipantIdentity, ...]
    counts: dict[str, int]
    strains: tuple[StrainCount, ...]
    metrics: tuple[FrozenMetric, ...]
    water_applications: tuple[WaterApplication, ...] = ()
    coverage: tuple[MetricCoverage, ...] = ()
    uncovered_gaps: tuple[CoverageGap, ...] = ()
    missing: tuple[MissingFact, ...] = ()
    format: int = SNAPSHOT_FORMAT
    metadata: RunMetadata | None = None
    harvest_outcomes: tuple[HarvestOutcome, ...] | None = None

    @property
    def complete(self) -> bool:
        """Whether nothing the snapshot needed was missing."""
        return not self.missing

    def as_dict(self) -> dict[str, Any]:
        """Return the durable and wire form."""
        window = self.harvest_window
        return {
            "metadata": None if self.metadata is None else self.metadata.as_dict(),
            "harvest_outcomes": (
                None
                if self.harvest_outcomes is None
                else [row.as_dict() for row in self.harvest_outcomes]
            ),
            "format": self.format,
            "finalized_at": self.finalized_at.isoformat(),
            "run_id": self.run_id,
            "growspace_id": self.growspace_id,
            "growspace_name": self.growspace_name,
            "sequence_number": self.sequence_number,
            "timezone": self.timezone,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "duration_days": self.duration_days,
            "harvest_window": (
                None
                if window is None
                else {"first": window[0].isoformat(), "last": window[1].isoformat()}
            ),
            "participants": [row.as_dict() for row in self.participants],
            "counts": {name: self.counts[name] for name in SNAPSHOT_COUNTS},
            "strains": [row.as_dict() for row in self.strains],
            "metrics": [row.as_dict() for row in self.metrics],
            "water_applications": [row.as_dict() for row in self.water_applications],
            "coverage": [row.as_dict() for row in self.coverage],
            "uncovered_gaps": [row.as_dict() for row in self.uncovered_gaps],
            "missing": [row.as_dict() for row in self.missing],
            "complete": self.complete,
        }

    @classmethod
    def from_dict(cls, value: Any) -> RunSnapshot:
        """Read the durable form back, refusing a snapshot of a later format."""
        value = _dict(value, "snapshot")
        if _int(value.get("format"), "snapshot.format", 1) != SNAPSHOT_FORMAT:
            raise ValueError("the snapshot was written by a later format")
        raw_window = value.get("harvest_window")
        window = None
        if raw_window is not None:
            raw_window = _dict(raw_window, "snapshot.harvest_window")
            window = (
                _date(raw_window.get("first"), "harvest_window.first"),
                _date(raw_window.get("last"), "harvest_window.last"),
            )
            if window[1] < window[0]:
                raise ValueError("the Harvest Window ends before it begins")
        counts = _dict(value.get("counts"), "snapshot.counts")
        snapshot = cls(
            metadata=(
                None
                if value.get("metadata") is None
                else RunMetadata.from_dict(value["metadata"])
            ),
            harvest_outcomes=(
                None
                if value.get("harvest_outcomes") is None
                else tuple(
                    HarvestOutcome.from_dict(row)
                    for row in _list(
                        value["harvest_outcomes"], "snapshot.harvest_outcomes"
                    )
                )
            ),
            finalized_at=_moment(value.get("finalized_at"), "snapshot.finalized_at"),
            run_id=_str(value.get("run_id"), "snapshot.run_id"),
            growspace_id=_str(value.get("growspace_id"), "snapshot.growspace_id"),
            growspace_name=_str(value.get("growspace_name"), "snapshot.growspace"),
            sequence_number=_int(value.get("sequence_number"), "snapshot.seq", 1),
            timezone=_zone(value.get("timezone"), "snapshot.timezone"),
            started_at=_moment(value.get("started_at"), "snapshot.started_at"),
            completed_at=_moment(value.get("completed_at"), "snapshot.completed_at"),
            duration_days=_int(value.get("duration_days"), "snapshot.duration", 0),
            harvest_window=window,
            participants=tuple(
                ParticipantIdentity.from_dict(row)
                for row in _list(value.get("participants"), "snapshot.participants")
            ),
            counts={
                name: _int(counts.get(name), f"snapshot.counts.{name}", 0)
                for name in SNAPSHOT_COUNTS
            },
            strains=tuple(
                StrainCount.from_dict(row)
                for row in _list(value.get("strains"), "snapshot.strains")
            ),
            metrics=tuple(
                FrozenMetric.from_dict(row)
                for row in _list(value.get("metrics"), "snapshot.metrics")
            ),
            water_applications=tuple(
                WaterApplication.from_dict(row)
                for row in _list(
                    value.get("water_applications", []), "snapshot.water_applications"
                )
            ),
            coverage=tuple(
                MetricCoverage.from_dict(row)
                for row in _list(value.get("coverage"), "snapshot.coverage")
            ),
            uncovered_gaps=tuple(
                CoverageGap.from_dict(row)
                for row in _list(value.get("uncovered_gaps"), "snapshot.gaps")
            ),
            missing=tuple(
                MissingFact.from_dict(row)
                for row in _list(value.get("missing"), "snapshot.missing")
            ),
        )
        if snapshot.completed_at < snapshot.started_at:
            raise ValueError("the snapshot ends before it starts")
        return snapshot


def _yield_gap(outcome: HarvestOutcome) -> str | None:
    """Why an outcome leaves Yield unknown, or None when its dry weight counts."""
    if outcome.state == "incomplete":
        return "outcome_incomplete"
    if outcome.state == "pending" or outcome.metrics.get("dry_weight") is None:
        return "dry_weight"
    return None


def _yield_metrics(
    outcomes: tuple[HarvestOutcome, ...],
) -> tuple[FrozenMetric, FrozenMetric]:
    """Yield and Yield per Harvest Source Plant from a Run's outcomes.

    The one definition both a frozen snapshot and the provisional metrics of an
    Active or Completed Run are drawn from, so Live, Pending and Final values
    of the same Run differ only in the facts that have arrived.
    """
    yield_missing = [
        MissingFact(gap, row.plant_id)
        for row in outcomes
        if (gap := _yield_gap(row)) is not None
    ]
    if not outcomes:
        yield_missing.append(MissingFact("harvest_source_plants"))
    total = (
        None
        if yield_missing
        else round(sum(float(row.metrics["dry_weight"]) for row in outcomes), 3)
    )
    return (
        FrozenMetric(
            "yield", "g", METRIC_DEFINITIONS["yield"], total, tuple(yield_missing)
        ),
        FrozenMetric(
            "yield_per_harvest_source_plant",
            "g",
            METRIC_DEFINITIONS["yield_per_harvest_source_plant"],
            None if total is None else round(total / len(outcomes), 3),
            () if total is not None else (MissingFact("yield"),),
        ),
    )


def _water_metrics(
    run: GrowRun, yield_metric: FrozenMetric
) -> tuple[FrozenMetric, FrozenMetric]:
    """Compute complete water use and dry yield per liter from run facts."""
    missing: list[MissingFact] = []
    if (
        run.backdate is not None
        or run.water_coverage_started_at is None
        or (run.water_coverage_started_at > run.started_at)
    ):
        missing.append(MissingFact("water_coverage"))
    missing.extend(
        MissingFact("water_volume", row.application_id)
        for row in run.water_applications
        if row.liters is None
    )
    applied = FrozenMetric(
        "water_applied",
        "L",
        METRIC_DEFINITIONS["water_applied"],
        None
        if missing
        else round(sum(row.liters or 0 for row in run.water_applications), 3),
        tuple(missing),
    )
    productivity_missing = list(missing)
    if yield_metric.value is None:
        productivity_missing.append(MissingFact("yield"))
    if applied.value == 0:
        productivity_missing.append(MissingFact("positive_water_applied"))
    productivity_value = None
    if not productivity_missing and yield_metric.value is not None and applied.value:
        productivity_value = round(yield_metric.value / applied.value, 3)
    productivity = FrozenMetric(
        "water_productivity",
        "g/L",
        METRIC_DEFINITIONS["water_productivity"],
        productivity_value,
        tuple(productivity_missing),
    )
    return applied, productivity


def water_coverage(run: GrowRun) -> tuple[MetricCoverage, MetricCoverage]:
    """Report application coverage, with unobserved run history at zero."""
    if (
        run.backdate is not None
        or run.water_coverage_started_at is None
        or run.water_coverage_started_at > run.started_at
    ):
        applied = 0.0
    elif not run.water_applications:
        applied = 100.0
    else:
        applied = round(
            100
            * sum(row.liters is not None for row in run.water_applications)
            / len(run.water_applications),
            1,
        )
    productivity = (
        applied
        if applied == 100
        and (metrics := provisional_metrics(run))[0].value is not None
        and metrics[2].value is not None
        and metrics[2].value > 0
        else 0.0
    )
    return (
        MetricCoverage("water_applied", applied),
        MetricCoverage("water_productivity", productivity),
    )


def provisional_metrics(run: GrowRun) -> tuple[FrozenMetric, ...]:
    """The metrics a Run's status gives it, as its records stand now.

    Live Run Metrics while Active and Pending Run Metrics once Completed are
    drawn from the harvest outcomes that have arrived; a Finalized Run's are
    its frozen ones; a Voided Run has none. Only the frozen ones are compared.
    """
    if run.status is RunStatus.FINALIZED and run.snapshot is not None:
        return run.snapshot.metrics
    if run.status is RunStatus.VOIDED:
        return ()
    yield_metrics = _yield_metrics(
        tuple(sorted(run.harvest_outcomes, key=lambda r: r.plant_id))
    )
    return (*yield_metrics, *_water_metrics(run, yield_metrics[0]))


def build_snapshot(
    run: GrowRun, *, finalized_at: datetime, growspace_name: str
) -> RunSnapshot:
    """Freeze a Completed Run's facts as they stand at ``finalized_at``.

    Only the Run's own records are read, never a live Plant: its Participant
    Identity Snapshots, its Harvest Outcomes and its participation. Whatever
    those lack is listed in ``missing`` and left out of every value it would
    have fed, rather than counted as zero.
    """
    if run.completed_at is None:
        raise ValueError("only a Completed Run has a snapshot")
    zone = ZoneInfo(run.timezone)
    outcomes = tuple(sorted(run.harvest_outcomes, key=lambda row: row.plant_id))
    sources = {row.plant_id: row for row in outcomes}
    identities = {row.plant_id: row for row in run.participant_identities}
    missing: list[MissingFact] = []

    participants: list[ParticipantIdentity] = []
    for plant_id in dict.fromkeys(row.plant_id for row in run.participations):
        identity = identities.get(plant_id)
        if identity is None:
            # Nothing ever named this Plant: keep what its outcome, if any,
            # recorded of its genetics, and say the rest is unknown.
            outcome = sources.get(plant_id)
            identity = ParticipantIdentity(
                plant_id,
                "",
                None,
                outcome.strain if outcome else "",
                None,
                outcome.phenotype if outcome else "",
            )
            missing.append(MissingFact("participant_identity", plant_id))
        participants.append(identity)

    days = [
        row.entered_dry_at.astimezone(zone).date()
        for row in outcomes
        if row.entered_dry_at is not None
    ]
    undated = [row.plant_id for row in outcomes if row.entered_dry_at is None]
    missing.extend(MissingFact("entered_dry_at", plant_id) for plant_id in undated)
    window = (min(days), max(days)) if days and not undated else None

    yield_metrics = _yield_metrics(outcomes)
    metrics = (*yield_metrics, *_water_metrics(run, yield_metrics[0]))
    missing.extend(metrics[0].missing)
    missing.extend(metrics[2].missing)

    strains: dict[tuple[int | None, str], list[int]] = {}
    for identity in participants:
        tally = strains.setdefault((identity.strain_id, identity.strain_name), [0, 0])
        tally[0] += 1
        tally[1] += identity.plant_id in sources
    states = [row.state for row in outcomes]
    return RunSnapshot(
        metadata=run.metadata,
        harvest_outcomes=tuple(
            replace(row, metrics=dict(row.metrics)) for row in outcomes
        ),
        finalized_at=finalized_at,
        run_id=run.run_id,
        growspace_id=run.growspace_id,
        growspace_name=growspace_name,
        sequence_number=run.sequence_number,
        timezone=run.timezone,
        started_at=run.started_at,
        completed_at=run.completed_at,
        duration_days=run.local_days(run.completed_at),
        harvest_window=window,
        participants=tuple(participants),
        counts={
            "participants": len(participants),
            "harvest_source_plants": len(outcomes),
            "recorded": states.count("recorded"),
            "no_usable_yield": states.count("no_usable_yield"),
            "missing_outcomes": sum(
                state in MISSING_OUTCOME_STATES for state in states
            ),
        },
        strains=tuple(
            StrainCount(strain_id, name, tally[0], tally[1])
            for (strain_id, name), tally in sorted(
                strains.items(), key=lambda item: (item[0][1], item[0][0] or 0)
            )
        ),
        metrics=metrics,
        water_applications=run.water_applications,
        coverage=water_coverage(run),
        uncovered_gaps=run.backdate.gaps if run.backdate else (),
        missing=tuple(dict.fromkeys(missing)),
    )


@dataclass(frozen=True, slots=True)
class SupersededSnapshot:
    """A Run Finalization Snapshot that Run Reopening set aside, kept whole.

    ``finalized_revision`` is the Run Revision its finalization produced, and
    ``superseded_revision`` the one the reopening did; the Run Audit Entry at
    that revision says who reopened it and why.
    """

    snapshot: RunSnapshot
    finalized_revision: int
    superseded_revision: int

    def as_dict(self) -> dict[str, Any]:
        """Return the durable and wire form."""
        return {
            "finalized_revision": self.finalized_revision,
            "superseded_revision": self.superseded_revision,
            "snapshot": self.snapshot.as_dict(),
        }

    @classmethod
    def from_dict(cls, value: Any) -> SupersededSnapshot:
        """Read the durable form back."""
        value = _dict(value, "superseded snapshot")
        superseded = cls(
            snapshot=RunSnapshot.from_dict(value.get("snapshot")),
            finalized_revision=_int(
                value.get("finalized_revision"), "superseded.finalized_revision", 1
            ),
            superseded_revision=_int(
                value.get("superseded_revision"), "superseded.superseded_revision", 1
            ),
        )
        if superseded.superseded_revision <= superseded.finalized_revision:
            raise ValueError("a snapshot is superseded before it was finalized")
        return superseded


@dataclass(frozen=True, slots=True)
class WaterApplication:
    """One reported or controlled irrigation, with one measurement source.

    A missing volume remains a fact: omitting it would make a partial total look
    complete. ``application_id`` is the durable watering or delivery attempt ID.
    """

    application_id: str
    at: datetime
    source: str
    liters: float | None

    def __post_init__(self) -> None:
        """Refuse a contradictory or unbounded measurement."""
        if not self.application_id:
            raise ValueError("water application has no id")
        if self.source not in {"manual", "pump_estimate", "metered", "unknown"}:
            raise ValueError("water application has an unknown source")
        if (self.source == "unknown") != (self.liters is None):
            raise ValueError("water application has inconsistent volume evidence")
        if self.liters is not None and (
            isinstance(self.liters, bool)
            or not isinstance(self.liters, (int, float))
            or self.liters < 0
            or not math.isfinite(self.liters)
        ):
            raise ValueError("water application has an invalid volume")
        if self.at.tzinfo is None:
            raise ValueError("water application has no timezone")

    def as_dict(self) -> dict[str, Any]:
        """Return the durable and wire form."""
        return {
            "application_id": self.application_id,
            "at": self.at.isoformat(),
            "source": self.source,
            "liters": self.liters,
        }

    @classmethod
    def from_dict(cls, value: Any) -> WaterApplication:
        """Read one application without coercing a malformed volume."""
        value = _dict(value, "water application")
        liters = value.get("liters")
        if liters is not None and (
            isinstance(liters, bool) or not isinstance(liters, (int, float))
        ):
            raise TypeError("water application volume is not numeric")
        return cls(
            _str(value.get("application_id"), "water.application_id"),
            _moment(value.get("at"), "water.at"),
            _str(value.get("source"), "water.source"),
            liters,
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
    water_applications: tuple[WaterApplication, ...] = ()
    water_coverage_started_at: datetime | None = None
    harvest_outcomes: tuple[HarvestOutcome, ...] = ()
    audit: tuple[RunAuditEntry, ...] = ()
    daily_summaries: tuple[DailySummary, ...] = ()
    backdate: RunBackdate | None = None
    #: The end of the half-open operating interval; absent while Active.
    completed_at: datetime | None = None
    #: Who each Participant is, kept current until finalization freezes it.
    participant_identities: tuple[ParticipantIdentity, ...] = ()
    #: The Run Finalization Snapshot; present exactly when Finalized.
    snapshot: RunSnapshot | None = None
    #: Every earlier snapshot Run Reopening set aside, oldest first.
    superseded_snapshots: tuple[SupersededSnapshot, ...] = ()
    #: When the Growspace's Unattributed Activity coverage began before this
    #: Run's start ended it; what a discard gives back. Absent when nothing
    #: covered it then, and on a Run started before #917.
    prior_coverage: datetime | None = None

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
            "water_applications": [row.as_dict() for row in self.water_applications],
            "water_coverage_started_at": (
                self.water_coverage_started_at.isoformat()
                if self.water_coverage_started_at
                else None
            ),
            "harvest_outcomes": [row.as_dict() for row in self.harvest_outcomes],
            "audit": [row.as_dict() for row in self.audit],
            "daily_summaries": [row.as_dict() for row in self.daily_summaries],
            "backdate": self.backdate.as_dict() if self.backdate else None,
            "participant_identities": [
                row.as_dict() for row in self.participant_identities
            ],
            "snapshot": self.snapshot.as_dict() if self.snapshot else None,
            "superseded_snapshots": [
                row.as_dict() for row in self.superseded_snapshots
            ],
            "prior_coverage": (
                self.prior_coverage.isoformat() if self.prior_coverage else None
            ),
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
            water_applications=tuple(
                WaterApplication.from_dict(row)
                for row in _list(
                    value.get("water_applications", []), "run.water_applications"
                )
            ),
            water_coverage_started_at=_opt_moment(
                value.get("water_coverage_started_at"), "run.water_coverage_started_at"
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
            participant_identities=tuple(
                ParticipantIdentity.from_dict(row)
                for row in _list(
                    value.get("participant_identities", []), "run.identities"
                )
            ),
            snapshot=(
                None
                if value.get("snapshot") is None
                else RunSnapshot.from_dict(value.get("snapshot"))
            ),
            superseded_snapshots=tuple(
                SupersededSnapshot.from_dict(row)
                for row in _list(
                    value.get("superseded_snapshots", []), "run.superseded_snapshots"
                )
            ),
            prior_coverage=_opt_moment(
                value.get("prior_coverage"), "run.prior_coverage"
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
        water_ids = [row.application_id for row in run.water_applications]
        if len(water_ids) != len(set(water_ids)):
            raise ValueError("a water application appears twice in one Run")
        outcome_ids = [row.plant_id for row in run.harvest_outcomes]
        if len(outcome_ids) != len(set(outcome_ids)):
            raise ValueError("a Plant has more than one harvest outcome in one Run")
        if run.status is RunStatus.ACTIVE and run.completed_at is not None:
            raise ValueError("an Active Run has a completion boundary")
        if run.status in (RunStatus.COMPLETED, RunStatus.FINALIZED):
            if run.completed_at is None or run.completed_at < run.started_at:
                raise ValueError("a Completed Run has no valid completion boundary")
            if open_plants:
                raise ValueError("a Completed Run still has open participation")
        if (run.status is RunStatus.FINALIZED) != (run.snapshot is not None):
            raise ValueError("a snapshot belongs to a Finalized Run, and only there")
        if any(
            row.run_id != run.run_id
            for row in (
                *((run.snapshot,) if run.snapshot else ()),
                *(row.snapshot for row in run.superseded_snapshots),
            )
        ):
            raise ValueError("a Run holds another Run's snapshot")
        identity_ids = [row.plant_id for row in run.participant_identities]
        if len(identity_ids) != len(set(identity_ids)):
            raise ValueError("a Participant has two identities in one Run")
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


#: Harvest outcome states that leave the Run's Yield incomplete: ``pending``
#: may still receive a dry weight while the Run is Completed; ``incomplete``
#: was chosen when its Plant was deleted and never will.
MISSING_OUTCOME_STATES = ("pending", "incomplete")


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
    missing_outcomes: tuple[HarvestOutcome, ...] = ()
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
            "missing_outcomes": [
                {
                    "plant_id": row.plant_id,
                    "strain": row.strain,
                    "phenotype": row.phenotype,
                    "state": row.state,
                }
                for row in self.missing_outcomes
            ],
            # Metric Coverage, one ``{"metric", "coverage_percent"}`` row per
            # water metric. A zero-volume Run has complete Water Applied
            # coverage but no Water Productivity denominator.
            "coverage": [row.as_dict() for row in water_coverage(self.run)],
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
    pending_facts: list[PlantMovementFact] | tuple[PlantMovementFact, ...],
    delivering_outputs: list[str] | tuple[str, ...],
    retrospective_note: str | None,
) -> CompletionPreview:
    """Preview completing the ledger's Active Run at ``now``.

    Missing outcomes are the Run's own Harvest Outcome snapshots still pending
    a dry weight or recorded as incomplete. ``pending_facts`` are the Plant
    outbox's unprojected facts, of any Growspace.
    """
    run = ledger.active_run
    if run is None:
        raise RunNotActive(
            "This growspace has no Active Run to complete",
            current_revision=ledger.revision,
        )
    missing = tuple(
        sorted(
            (
                row
                for row in run.harvest_outcomes
                if row.state in MISSING_OUTCOME_STATES
            ),
            key=lambda row: row.plant_id,
        )
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
class FinalizationPreview:
    """What finalizing a Completed Run now would freeze, and what it lacks.

    Like the Run Completion Preview it is built again at commit, so the
    acknowledgement a finalization carries answers the snapshot that lands.
    """

    run: GrowRun
    revision: int
    snapshot: RunSnapshot

    @property
    def warnings(self) -> tuple[str, ...]:
        """The one warning an incomplete snapshot needs acknowledged."""
        return () if self.snapshot.complete else (WARNING_INCOMPLETE_SNAPSHOT,)

    def as_dict(self) -> dict[str, Any]:
        """Return the wire form the finalization dialog is drawn from."""
        return {
            "run": run_summary(self.run, self.revision),
            "snapshot": self.snapshot.as_dict(),
            "warnings": list(self.warnings),
        }


def preview_finalization(
    ledger: RunLedger, run_id: str, *, now: datetime, growspace_name: str
) -> FinalizationPreview:
    """Preview freezing the named Completed Run at ``now``."""
    run = ledger.find(run_id)
    if run.status is not RunStatus.COMPLETED:
        raise RunNotCompleted(
            f"Run #{run.sequence_number} is {run.status.value}; only a Completed "
            "Run can be finalized",
            current_revision=ledger.revision,
            active_run=ledger.active_run,
        )
    return FinalizationPreview(
        run=run,
        revision=ledger.revision,
        snapshot=build_snapshot(run, finalized_at=now, growspace_name=growspace_name),
    )


def discard_blockers(
    run: GrowRun,
    *,
    pending_facts: list[PlantMovementFact] | tuple[PlantMovementFact, ...] = (),
    harvest_source_plant_ids: list[str] | tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Every kind of activity that keeps an Active Run from being discarded.

    ``pending_facts`` are the Plant outbox's facts, projected or not: one still
    naming this Run is activity it has not received yet, and discarding under
    it would leave a fact pointing at a Run that no longer exists. The same
    holds for ``harvest_source_plant_ids``, the live Plants that name this Run
    as their Harvest Source Run.
    """
    opening = run.backdate.covered_from if run.backdate else run.started_at
    blockers: list[str] = []
    if (
        run.movement_history
        or run.water_applications
        or any(
            run.run_id in (fact.source_run_id, fact.target_run_id)
            for fact in pending_facts
        )
    ):
        blockers.append(ACTIVITY_FACTS)
    if any(
        row.opened_at != opening or row.closed_at is not None
        for row in run.participations
    ):
        blockers.append(PARTICIPANTS_CHANGED)
    if run.harvest_outcomes or harvest_source_plant_ids:
        blockers.append(HARVEST_OUTCOMES)
    return tuple(blockers)


@dataclass(frozen=True, slots=True)
class DiscardedRun:
    """What the ledger keeps of a discarded Run: who it was and its audit.

    Its Sequence Number stays allocated, so no later Run is ever given it, and
    the last audit entry is the discard itself.
    """

    run_id: str
    sequence_number: int
    started_at: datetime
    audit: tuple[RunAuditEntry, ...]

    def as_dict(self) -> dict[str, Any]:
        """Return the durable form."""
        return {
            "run_id": self.run_id,
            "sequence_number": self.sequence_number,
            "started_at": self.started_at.isoformat(),
            "audit": [row.as_dict() for row in self.audit],
        }

    @classmethod
    def from_dict(cls, value: Any) -> DiscardedRun:
        """Read the durable form back; a discard with no audit is refused."""
        value = _dict(value, "discarded run")
        discarded = cls(
            run_id=_str(value.get("run_id"), "discarded.run_id"),
            sequence_number=_int(value.get("sequence_number"), "discarded.seq", 1),
            started_at=_moment(value.get("started_at"), "discarded.started_at"),
            audit=tuple(
                RunAuditEntry.from_dict(row)
                for row in _list(value.get("audit"), "discarded.audit")
            ),
        )
        if not discarded.audit or discarded.audit[-1].command is not RunCommand.DISCARD:
            raise ValueError("a discarded Run's audit does not end in its discard")
        return discarded


@dataclass(frozen=True, slots=True)
class RunLedger:
    """One Growspace's Runs, its next Sequence Number, and its Run Revision."""

    growspace_id: str
    revision: int = 0
    next_sequence: int = 1
    runs: tuple[GrowRun, ...] = ()
    #: Runs discarded before recording anything, oldest first.
    discarded: tuple[DiscardedRun, ...] = ()

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

    def find(self, run_id: str) -> GrowRun:
        """The named Run, or a refusal saying this Growspace holds no such Run."""
        run = next((row for row in self.runs if row.run_id == run_id), None)
        if run is None:
            raise RunNotFound(
                "This growspace holds no such Run",
                current_revision=self.revision,
                active_run=self.active_run,
            )
        return run

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

    def project_water(self, application: WaterApplication) -> RunLedger:
        """Place one irrigation in its operating interval, once by durable ID."""
        runs = tuple(
            replace(run, water_applications=(*run.water_applications, application))
            if run.status in (RunStatus.ACTIVE, RunStatus.COMPLETED)
            and run.covers(application.at)
            and not any(
                row.application_id == application.application_id
                for row in run.water_applications
            )
            else run
            for run in self.runs
        )
        return replace(self, runs=runs) if runs != self.runs else self

    def mark_water_incomplete(self) -> RunLedger:
        """Keep an unreadable delivery interval from becoming a complete total."""
        runs = tuple(
            replace(run, water_coverage_started_at=None)
            if run.status in (RunStatus.ACTIVE, RunStatus.COMPLETED)
            and run.water_coverage_started_at is not None
            else run
            for run in self.runs
        )
        return replace(self, runs=runs) if runs != self.runs else self

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

    def refresh_identities(
        self, identities: dict[str, ParticipantIdentity]
    ) -> RunLedger:
        """Bring each still-mutable Run's Participant identities up to date.

        A Plant with no live identity keeps the last one captured, which is how
        a Participant deleted before finalization is still named in it.
        """
        runs: list[GrowRun] = []
        for run in self.runs:
            if run.status not in (RunStatus.ACTIVE, RunStatus.COMPLETED):
                runs.append(run)
                continue
            kept = {row.plant_id: row for row in run.participant_identities}
            for plant_id in dict.fromkeys(row.plant_id for row in run.participations):
                if plant_id in identities:
                    kept[plant_id] = identities[plant_id]
            refreshed = tuple(kept.values())
            runs.append(
                run
                if refreshed == run.participant_identities
                else replace(run, participant_identities=refreshed)
            )
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
        prior_coverage: datetime | None = None,
    ) -> tuple[RunLedger, GrowRun]:
        """Start a Run; return the advanced ledger and the Run it holds.

        The Plants present become Participants from this boundary. None is a
        valid answer: an empty Growspace can start a Run.

        With a ``claim`` the Run starts in the past instead: its boundary,
        Participants and movement history are the claimed Unattributed
        Activity, now attributed to it, and ``plant_ids`` is unused. The
        audit entry still records when the start was committed.

        ``prior_coverage`` is when the Growspace's Unattributed Activity
        coverage began, which the start ends; it is kept so a discard can
        give it back.
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
            water_coverage_started_at=now if claim is None else None,
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
            prior_coverage=prior_coverage,
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

    def finalize(
        self,
        *,
        expected_revision: int,
        run_id: str,
        preview: FinalizationPreview,
        acknowledged: list[str] | tuple[str, ...] | set[str],
        command_id: str,
        actor_user_id: str | None,
    ) -> tuple[RunLedger, GrowRun]:
        """Freeze a Completed Run into its snapshot; return the new ledger.

        An incomplete snapshot finalizes only when the grower acknowledged it,
        and what it lacks stays listed in it rather than being filled in.
        """
        self.require_revision(expected_revision)
        run = self.find(run_id)
        if run.status is not RunStatus.COMPLETED or preview.run.run_id != run_id:
            raise RunNotCompleted(
                f"Run #{run.sequence_number} is {run.status.value}; only a "
                "Completed Run can be finalized",
                current_revision=self.revision,
                active_run=self.active_run,
            )
        if unacknowledged := [
            code for code in preview.warnings if code not in set(acknowledged)
        ]:
            raise RunAcknowledgementRequired(
                f"Finalizing Run #{run.sequence_number} needs acknowledgement "
                f"of: {', '.join(unacknowledged)}",
                current_revision=self.revision,
                active_run=self.active_run,
            )
        resulting = self.revision + 1
        finalized = replace(
            run,
            status=RunStatus.FINALIZED,
            snapshot=preview.snapshot,
            audit=(
                *run.audit,
                RunAuditEntry(
                    at=preview.snapshot.finalized_at,
                    command=RunCommand.FINALIZE,
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
            runs=tuple(finalized if row is run else row for row in self.runs),
        )
        return ledger, finalized

    def update_metadata(
        self,
        *,
        expected_revision: int,
        run_id: str,
        metadata: RunMetadata,
        command_id: str,
        actor_user_id: str | None,
        now: datetime,
    ) -> tuple[RunLedger, GrowRun]:
        """Replace a Run's descriptive metadata, audited, in any status.

        Run Metadata is not a fact of the Run, so a Finalized Run takes the
        edit without Reopening and its snapshot does not move. An edit that
        changes nothing is not a command: nothing is audited or advanced.
        """
        self.require_revision(expected_revision)
        run = self.find(run_id)
        changed = tuple(
            name
            for name in ("label", "tags", "goals", "notes")
            if getattr(run.metadata, name) != getattr(metadata, name)
        )
        if not changed:
            return self, run
        resulting = self.revision + 1
        edited = replace(
            run,
            metadata=metadata,
            audit=(
                *run.audit,
                RunAuditEntry(
                    at=now,
                    command=RunCommand.EDIT_METADATA,
                    command_id=command_id,
                    actor_user_id=actor_user_id,
                    prior_revision=self.revision,
                    resulting_revision=resulting,
                    changed_fields=changed,
                ),
            ),
        )
        ledger = replace(
            self,
            revision=resulting,
            runs=tuple(edited if row is run else row for row in self.runs),
        )
        return ledger, edited

    def reopen(
        self,
        *,
        expected_revision: int,
        run_id: str,
        reason: str | None,
        command_id: str,
        actor_user_id: str | None,
        now: datetime,
    ) -> tuple[RunLedger, GrowRun]:
        """Return a Finalized Run to Completed so its facts can be corrected.

        The operating interval does not reopen: the boundary, the closed
        participation and the Run Timezone are exactly as completion left
        them. The snapshot is set aside whole, beside the revision that froze
        it, and the next finalization freezes a new one instead of editing it.
        """
        self.require_revision(expected_revision)
        run = self.find(run_id)
        if run.status is not RunStatus.FINALIZED or run.snapshot is None:
            raise RunNotFinalized(
                f"Run #{run.sequence_number} is {run.status.value}; only a "
                "Finalized Run can be reopened",
                current_revision=self.revision,
                active_run=self.active_run,
            )
        if (why := _text(reason, MAX_TEXT_LENGTH)) is None:
            raise RunReasonRequired(
                f"Say why Run #{run.sequence_number} is being reopened",
                current_revision=self.revision,
                active_run=self.active_run,
            )
        resulting = self.revision + 1
        finalized_revision = next(
            entry.resulting_revision
            for entry in reversed(run.audit)
            if entry.command is RunCommand.FINALIZE
        )
        reopened = replace(
            run,
            status=RunStatus.COMPLETED,
            snapshot=None,
            superseded_snapshots=(
                *run.superseded_snapshots,
                SupersededSnapshot(run.snapshot, finalized_revision, resulting),
            ),
            audit=(
                *run.audit,
                RunAuditEntry(
                    at=now,
                    command=RunCommand.REOPEN,
                    command_id=command_id,
                    actor_user_id=actor_user_id,
                    prior_revision=self.revision,
                    resulting_revision=resulting,
                    reason=why,
                ),
            ),
        )
        ledger = replace(
            self,
            revision=resulting,
            runs=tuple(reopened if row is run else row for row in self.runs),
        )
        return ledger, reopened

    def discard(
        self,
        *,
        expected_revision: int,
        run_id: str,
        reason: str | None,
        command_id: str,
        actor_user_id: str | None,
        now: datetime,
        pending_facts: list[PlantMovementFact] | tuple[PlantMovementFact, ...] = (),
        harvest_source_plant_ids: list[str] | tuple[str, ...] = (),
    ) -> tuple[RunLedger, DiscardedRun]:
        """Remove an activity-free Active Run as though it never started.

        Only the Active Run can go, and only while it holds nothing but the
        Participants it opened with: a movement fact, a later Participant or a
        harvest outcome is history, and history is corrected, never erased.
        The Sequence Number stays allocated and the audit trail stays in the
        ledger.
        """
        self.require_revision(expected_revision)
        run = self.find(run_id)
        if run.status is not RunStatus.ACTIVE:
            raise RunNotActive(
                f"Run #{run.sequence_number} is {run.status.value}; only an "
                "Active Run can be discarded",
                current_revision=self.revision,
                active_run=self.active_run,
            )
        if blockers := discard_blockers(
            run,
            pending_facts=pending_facts,
            harvest_source_plant_ids=harvest_source_plant_ids,
        ):
            raise RunHasActivity(
                f"Run #{run.sequence_number} has recorded activity "
                f"({', '.join(blockers)}); complete it instead",
                current_revision=self.revision,
                active_run=run,
                reasons=blockers,
            )
        resulting = self.revision + 1
        discarded = DiscardedRun(
            run_id=run.run_id,
            sequence_number=run.sequence_number,
            started_at=run.started_at,
            audit=(
                *run.audit,
                RunAuditEntry(
                    at=now,
                    command=RunCommand.DISCARD,
                    command_id=command_id,
                    actor_user_id=actor_user_id,
                    prior_revision=self.revision,
                    resulting_revision=resulting,
                    reason=_text(reason, MAX_TEXT_LENGTH),
                ),
            ),
        )
        ledger = replace(
            self,
            revision=resulting,
            runs=tuple(row for row in self.runs if row is not run),
            discarded=(*self.discarded, discarded),
        )
        return ledger, discarded

    def as_dict(self) -> dict[str, Any]:
        """Return the durable form."""
        return {
            "growspace_id": self.growspace_id,
            "revision": self.revision,
            "next_sequence": self.next_sequence,
            "runs": [run.as_dict() for run in self.runs],
            "discarded": [row.as_dict() for row in self.discarded],
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
            discarded=tuple(
                DiscardedRun.from_dict(row)
                for row in _list(value.get("discarded", []), "ledger.discarded")
            ),
        )
        held = [(run.run_id, run.sequence_number) for run in ledger.runs]
        held += [(row.run_id, row.sequence_number) for row in ledger.discarded]
        run_ids = [run_id for run_id, _ in held]
        sequences = [number for _, number in held]
        if len(set(run_ids)) != len(run_ids):
            raise ValueError("a Run ID appears twice in one ledger")
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
    """The selected Run's Participants, movement history and frozen snapshot.

    A Finalized Run's snapshot is read from the Run alone, so it is served the
    same after its Plants or its Growspace are gone.
    """
    return {
        "outcome": "found",
        "run": {
            **run_summary(run, revision),
            "notes": run.metadata.notes,
            "participations": [row.as_dict() for row in run.participations],
            "movement_history": [row.as_dict() for row in run.movement_history],
            "water_applications": [row.as_dict() for row in run.water_applications],
            "harvest_outcomes": [row.as_dict() for row in run.harvest_outcomes],
            "tags": list(run.metadata.tags),
            "goals": run.metadata.goals,
            "audit": [row.as_dict() for row in run.audit],
            "snapshot": run.snapshot.as_dict() if run.snapshot else None,
            # The Grow Run View's Participants and Performance (#675): who
            # took part as named now, and the metrics ``metrics_state`` marks.
            "participant_identities": [
                row.as_dict() for row in run.participant_identities
            ],
            "metrics": [row.as_dict() for row in provisional_metrics(run)],
            "coverage": [row.as_dict() for row in water_coverage(run)],
            "superseded_snapshots": [row.as_dict() for row in run.superseded_snapshots],
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


# ---------------------------------------------------------------------------
# The Run Comparison (#675)
# ---------------------------------------------------------------------------

#: Why a metric row does or does not receive a Comparison Direction.
COMPARISON_COMPARABLE = "comparable"
COMPARISON_MISSING = "missing"
COMPARISON_INCOMPATIBLE = "incompatible"
COMPARISON_UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class MetricComparison:
    """One metric of two Finalized Runs, side by side.

    A direction exists only between two values frozen under the same Metric
    Definition Version and unit: a missing value is never zero, and values
    calculated by different rules are never set against each other. ``earlier``
    or ``later`` is None when that Run's snapshot does not hold the metric at
    all, which is what a metric introduced after one of them was finalized is.
    """

    metric: str
    goal: str
    earlier: FrozenMetric | None
    later: FrozenMetric | None

    @property
    def state(self) -> str:
        """``comparable``, or why this row has no direction."""
        if self.earlier is None or self.later is None:
            return COMPARISON_UNAVAILABLE
        if (
            self.earlier.definition_version != self.later.definition_version
            or self.earlier.unit != self.later.unit
        ):
            return COMPARISON_INCOMPATIBLE
        if self.earlier.value is None or self.later.value is None:
            return COMPARISON_MISSING
        return COMPARISON_COMPARABLE

    @property
    def delta(self) -> float | None:
        """The later value less the earlier one, when the two are comparable."""
        if self.state != COMPARISON_COMPARABLE:
            return None
        assert self.earlier is not None and self.later is not None
        assert self.earlier.value is not None and self.later.value is not None
        return round(self.later.value - self.earlier.value, 3)

    @property
    def direction(self) -> str | None:
        """How the later Run moved relative to the earlier: the neutral fact."""
        delta = self.delta
        if delta is None:
            return None
        if delta == 0:
            return "equal"
        return "increase" if delta > 0 else "decrease"

    @property
    def judgment(self) -> str | None:
        """Better, worse or the same -- only against an agreed monotonic goal."""
        direction = self.direction
        if direction is None or self.goal not in ("higher", "lower"):
            return None
        if direction == "equal":
            return "same"
        return (
            "better"
            if (direction == "increase") == (self.goal == "higher")
            else "worse"
        )

    def as_dict(self) -> dict[str, Any]:
        """Return the wire form of one comparison row."""
        return {
            "metric": self.metric,
            "goal": self.goal,
            "state": self.state,
            "earlier": self.earlier.as_dict() if self.earlier else None,
            "later": self.later.as_dict() if self.later else None,
            "delta": self.delta,
            "direction": self.direction,
            "judgment": self.judgment,
        }


def _frozen(run: GrowRun) -> RunSnapshot:
    """A Finalized Run's snapshot, which the Run's own reader guarantees."""
    assert run.snapshot is not None
    return run.snapshot


@dataclass(frozen=True, slots=True)
class RunComparison:
    """Two Finalized Runs of one Growspace, earlier and later by sequence.

    Direction is always the later Run relative to the earlier one, whichever
    order the grower picked them in. Everything beyond the metric rows --
    Participants, Strains, Harvest Source Plants, duration, coverage and loss
    -- is context, and travels as each Run's own frozen snapshot.
    """

    earlier: GrowRun
    later: GrowRun
    revision: int

    @property
    def metrics(self) -> tuple[MetricComparison, ...]:
        """One row per metric either snapshot froze, the later Run's first."""
        earlier = {row.metric: row for row in _frozen(self.earlier).metrics}
        later = {row.metric: row for row in _frozen(self.later).metrics}
        names = dict.fromkeys([*later, *earlier])
        return tuple(
            MetricComparison(
                name,
                METRIC_GOALS.get(name, "neutral"),
                earlier.get(name),
                later.get(name),
            )
            for name in names
        )

    def as_dict(self) -> dict[str, Any]:
        """Return the two-column wire form the Grow Run View draws."""
        return {
            "earlier": {
                "run": run_summary(self.earlier, self.revision),
                "snapshot": _frozen(self.earlier).as_dict(),
            },
            "later": {
                "run": run_summary(self.later, self.revision),
                "snapshot": _frozen(self.later).as_dict(),
            },
            "metrics": [row.as_dict() for row in self.metrics],
        }


def finalized_runs(ledger: RunLedger) -> tuple[GrowRun, ...]:
    """The Growspace's Finalized Runs, newest first by Run Sequence Number."""
    return tuple(
        sorted(
            (run for run in ledger.runs if run.status is RunStatus.FINALIZED),
            key=lambda run: -run.sequence_number,
        )
    )


def compare_runs(
    ledger: RunLedger, run_ids: tuple[str, str] | None = None
) -> RunComparison:
    """Compare two Finalized Runs of this ledger's Growspace.

    Without ``run_ids`` it is the newest Finalized Run and its predecessor.
    A ledger holds one Growspace's Runs, so a Run of another Growspace is
    simply not found here: cross-growspace comparison cannot be asked for.
    """
    if run_ids is None:
        finalized = finalized_runs(ledger)
        if len(finalized) < 2:
            raise RunInsufficientHistory(
                "A Run Comparison needs two Finalized Runs; this growspace has "
                f"{len(finalized)}",
                current_revision=ledger.revision,
                active_run=ledger.active_run,
            )
        return RunComparison(finalized[1], finalized[0], ledger.revision)
    first, second = run_ids
    if first == second:
        raise RunSameRun(
            "A Run Comparison needs two different Runs",
            current_revision=ledger.revision,
            active_run=ledger.active_run,
        )
    runs = sorted(
        (ledger.find(first), ledger.find(second)), key=lambda run: run.sequence_number
    )
    for run in runs:
        if run.status is not RunStatus.FINALIZED:
            raise RunNotFinalized(
                f"Run #{run.sequence_number} is {run.status.value}; only Finalized "
                "Runs are compared",
                current_revision=ledger.revision,
                active_run=ledger.active_run,
            )
    return RunComparison(runs[0], runs[1], ledger.revision)


def export_run(ledger: RunLedger, run_id: str) -> dict[str, Any]:
    """Export only the selected Finalized Run's frozen facts (#683)."""
    run = ledger.find(run_id)
    if run.status is not RunStatus.FINALIZED:
        raise RunNotFinalized(
            f"Run #{run.sequence_number} is {run.status.value}; only Finalized "
            "Runs can be exported",
            current_revision=ledger.revision,
            active_run=ledger.active_run,
        )
    return {
        "format": "growspace_manager.grow_run",
        "version": 1,
        "status": RunStatus.FINALIZED.value,
        "snapshot": _frozen(run).as_dict(),
    }
