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
        return cls(
            plant_id=_str(value.get("plant_id"), "participation.plant_id"),
            opened_at=_moment(value.get("opened_at"), "participation.opened_at"),
            closed_at=_opt_moment(value.get("closed_at"), "participation.closed_at"),
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
    audit: tuple[RunAuditEntry, ...] = ()

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
            "audit": [row.as_dict() for row in self.audit],
        }

    @classmethod
    def from_dict(cls, value: Any) -> GrowRun:
        """Read the durable form back, refusing anything incomplete."""
        value = _dict(value, "run")
        return cls(
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
            audit=tuple(
                RunAuditEntry.from_dict(row)
                for row in _list(value.get("audit"), "run.audit")
            ),
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

    def require_revision(self, expected: int) -> None:
        """Refuse a command decided on any revision but this one."""
        if expected != self.revision:
            raise RunRevisionConflict(
                f"The Run Revision is {self.revision}, not {expected}; "
                "reload and decide again",
                current_revision=self.revision,
                active_run=self.active_run,
            )

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
