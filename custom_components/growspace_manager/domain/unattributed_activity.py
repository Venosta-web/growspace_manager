"""The Unattributed Activity Ledger, and claiming it for a backdated Run (#670).

A Growspace keeps doing things while no Grow Run is active: Plants arrive,
move, leave. ADR-0036 keeps that activity -- the same movement facts a Run
records, plus one daily summary per local day -- for a bounded retention
(365 days by default), so a grower who starts a Run late can start it in the
recent past and have the Run own what really happened since.

Nothing here is inferred. The ledger knows only what it recorded:

- **Coverage** begins when the ledger first observed the Growspace without an
  Active Run (``covered_since``). A backdated start before that is allowed, but
  the stretch before coverage is an *uncovered gap*, and Plants standing there
  become Participants from the coverage start, not from the day asked for.
- **A day with no summary** is a day Home Assistant never observed the
  Growspace; it is reported as a gap too, because a later metric cannot count
  what nothing measured.
- **History older than retention** is not backdated at all. It can only be
  recorded as an Imported Run.

Claiming is one transaction with the start: the claimed facts leave this
ledger in the same write that gives them to the Run, so no fact can belong to
two Runs, and a failed write leaves both where they were.

Pure, like `domain.grow_run`: the store and the services decide when.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .grow_run import (
    ClaimedHistory,
    CoverageGap,
    DailySummary,
    GapReason,
    GrowRunRefused,
    PlantMovementFact,
    RunAlreadyActive,
    RunBackdate,
    RunBeyondRetention,
    RunBoundaryConflict,
    RunLedger,
    RunParticipation,
    _dict,
    _list,
    _opt_moment,
    _str,
)

DEFAULT_RETENTION_DAYS = 365
MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 3650


def _side_run(fact: PlantMovementFact, growspace_id: str) -> tuple[bool, str | None]:
    """Whether the fact touches this Growspace, and the Run on that side."""
    if fact.target_growspace_id == growspace_id:
        return True, fact.target_run_id
    if fact.source_growspace_id == growspace_id:
        return True, fact.source_run_id
    return False, None


def _enters(fact: PlantMovementFact, growspace_id: str) -> bool:
    return (
        fact.target_growspace_id == growspace_id
        and fact.source_growspace_id != growspace_id
    )


def _exits(fact: PlantMovementFact, growspace_id: str) -> bool:
    return (
        fact.source_growspace_id == growspace_id
        and fact.target_growspace_id != growspace_id
    )


def _local_day(moment: datetime, zone: ZoneInfo) -> date:
    return moment.astimezone(zone).date()


def _day_start(day: date, zone: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=zone).astimezone(UTC)


@dataclass(frozen=True, slots=True)
class UnattributedActivity:
    """One Growspace's retained activity from while it had no Active Run."""

    growspace_id: str
    covered_since: datetime | None = None
    facts: tuple[PlantMovementFact, ...] = ()
    days: tuple[DailySummary, ...] = ()

    def _day(self, day: date) -> DailySummary:
        return next((row for row in self.days if row.day == day), DailySummary(day))

    def _put(self, summary: DailySummary) -> tuple[DailySummary, ...]:
        rows = [row for row in self.days if row.day != summary.day]
        rows.append(summary)
        return tuple(sorted(rows, key=lambda row: row.day))

    def record(self, fact: PlantMovementFact, timezone: str) -> UnattributedActivity:
        """Keep a fact that no Run owns on this Growspace's side; once only."""
        touches, run_id = _side_run(fact, self.growspace_id)
        if (
            not touches
            or run_id is not None
            or any(row.fact_id == fact.fact_id for row in self.facts)
        ):
            return self
        summary = self._day(_local_day(fact.at, ZoneInfo(timezone)))
        summary = replace(
            summary,
            plant_ids=tuple(sorted({*summary.plant_ids, fact.plant_id})),
            entries=summary.entries + _enters(fact, self.growspace_id),
            exits=summary.exits + _exits(fact, self.growspace_id),
        )
        facts = sorted(
            (*self.facts, replace(fact, projected=True)),
            key=lambda row: (row.at, row.fact_id),
        )
        return replace(self, facts=tuple(facts), days=self._put(summary))

    def observe(
        self, now: datetime, timezone: str, plant_ids: list[str] | tuple[str, ...]
    ) -> UnattributedActivity:
        """Note that the Growspace was seen today, and who stood in it.

        Opens coverage the first time. Returns ``self`` when nothing changed,
        so a caller can skip the write.
        """
        summary = self._day(_local_day(now, ZoneInfo(timezone)))
        plants = tuple(sorted({*summary.plant_ids, *plant_ids}))
        known = any(row.day == summary.day for row in self.days)
        if self.covered_since is not None and known and plants == summary.plant_ids:
            return self
        return replace(
            self,
            covered_since=self.covered_since or now,
            days=self._put(replace(summary, plant_ids=plants)),
        )

    def prune(
        self, now: datetime, timezone: str, retention_days: int
    ) -> UnattributedActivity:
        """Forget what is older than retention; coverage starts no earlier."""
        horizon = now - timedelta(days=retention_days)
        horizon_day = _local_day(horizon, ZoneInfo(timezone))
        pruned = replace(
            self,
            covered_since=(
                max(self.covered_since, horizon) if self.covered_since else None
            ),
            facts=tuple(row for row in self.facts if row.at >= horizon),
            days=tuple(row for row in self.days if row.day >= horizon_day),
        )
        return self if pruned == self else pruned

    def close(self) -> UnattributedActivity:
        """A Run is active: coverage ends until the Growspace is Run-free again."""
        return self if self.covered_since is None else replace(self, covered_since=None)

    def as_dict(self) -> dict[str, Any]:
        """Return the durable form."""
        return {
            "growspace_id": self.growspace_id,
            "covered_since": (
                self.covered_since.isoformat() if self.covered_since else None
            ),
            "facts": [row.as_dict() for row in self.facts],
            "days": [row.as_dict() for row in self.days],
        }

    @classmethod
    def from_dict(cls, value: Any) -> UnattributedActivity:
        """Read the durable form back and hold it to the ledger's invariants."""
        value = _dict(value, "unattributed activity")
        activity = cls(
            growspace_id=_str(value.get("growspace_id"), "unattributed.growspace"),
            covered_since=_opt_moment(
                value.get("covered_since"), "unattributed.covered_since"
            ),
            facts=tuple(
                PlantMovementFact.from_dict(row)
                for row in _list(value.get("facts"), "unattributed.facts")
            ),
            days=tuple(
                DailySummary.from_dict(row)
                for row in _list(value.get("days"), "unattributed.days")
            ),
        )
        if len({row.fact_id for row in activity.facts}) != len(activity.facts):
            raise ValueError("an unattributed fact appears twice")
        if len({row.day for row in activity.days}) != len(activity.days):
            raise ValueError("an unattributed day is summarised twice")
        return activity


@dataclass(frozen=True, slots=True)
class ClaimPlan:
    """What a backdated start would claim, and whether it may.

    The same plan is the grower's preview and the confirmed start's input, so
    what was shown is what is committed -- recomputed under the lock, on the
    ledger as it stands then.
    """

    started_on: date
    timezone: str
    retention_days: int
    horizon: datetime
    covered_since: datetime | None
    history: ClaimedHistory
    conflict: GrowRunRefused | None

    def remaining(self, activity: UnattributedActivity) -> UnattributedActivity:
        """The ledger once the claim commits: claimed facts and days leave it."""
        claimed_facts = {row.fact_id for row in self.history.facts}
        claimed_days = {row.day for row in self.history.days}
        return replace(
            activity,
            covered_since=None,
            facts=tuple(r for r in activity.facts if r.fact_id not in claimed_facts),
            days=tuple(r for r in activity.days if r.day not in claimed_days),
        )


def _conflict(
    ledger: RunLedger, *, started_at: datetime, now: datetime, horizon: datetime
) -> GrowRunRefused | None:
    """The first boundary the requested start runs into, if any."""
    refusal: type[GrowRunRefused]
    latest = max(ledger.runs, key=lambda run: run.started_at, default=None)
    if (active := ledger.active_run) is not None:
        refusal, boundary = RunAlreadyActive, active.started_at
        message = f"Run #{active.sequence_number} is already active"
    elif started_at > now:
        refusal, boundary = RunBoundaryConflict, now
        message = "A Run cannot start in the future"
    elif started_at < horizon:
        refusal, boundary = RunBeyondRetention, horizon
        message = (
            "Activity that old is no longer kept, so nothing can be claimed "
            "for it; record that history as an Imported Run instead"
        )
    elif latest is not None and started_at <= latest.started_at:
        refusal, boundary = RunBoundaryConflict, latest.started_at
        message = f"Run #{latest.sequence_number} started later; Runs never overlap"
    else:
        return None
    return refusal(
        message,
        current_revision=ledger.revision,
        active_run=ledger.active_run,
        boundary=boundary,
    )


def _gaps(
    days: tuple[DailySummary, ...],
    *,
    started_at: datetime,
    covered_from: datetime,
    now: datetime,
    zone: ZoneInfo,
) -> tuple[CoverageGap, ...]:
    """Before coverage, and every whole past local day nothing observed."""
    gaps: list[CoverageGap] = []
    if covered_from > started_at:
        gaps.append(CoverageGap(started_at, covered_from, GapReason.BEFORE_RECORDING))
    observed = {row.day for row in days}
    day = _local_day(covered_from, zone)
    today = _local_day(now, zone)
    while day < today:
        if day not in observed:
            start = max(_day_start(day, zone), covered_from)
            end = _day_start(day + timedelta(days=1), zone)
            previous = gaps[-1] if gaps else None
            if (
                previous is not None
                and previous.reason is GapReason.NOT_OBSERVED
                and previous.end == start
            ):
                gaps[-1] = replace(previous, end=end)
            else:
                gaps.append(CoverageGap(start, end, GapReason.NOT_OBSERVED))
        day += timedelta(days=1)
    return tuple(gaps)


def _participations(
    facts: list[PlantMovementFact],
    *,
    growspace_id: str,
    covered_from: datetime,
    plant_ids: list[str] | tuple[str, ...],
) -> tuple[RunParticipation, ...]:
    """Walk back from who stands here now to who stood here at coverage start.

    Then walk forward, opening and closing half-open intervals on each fact.
    Starting from the present keeps the result consistent with the Plants
    the grower can see, whatever the ledger missed.
    """
    present = set(plant_ids)
    for fact in reversed(facts):
        if _enters(fact, growspace_id):
            present.discard(fact.plant_id)
        elif _exits(fact, growspace_id):
            present.add(fact.plant_id)
    intervals = [RunParticipation(plant, covered_from) for plant in sorted(present)]
    for fact in facts:
        if _exits(fact, growspace_id):
            for index in range(len(intervals) - 1, -1, -1):
                row = intervals[index]
                if row.plant_id == fact.plant_id and row.closed_at is None:
                    intervals[index] = replace(row, closed_at=fact.at)
                    break
        elif _enters(fact, growspace_id) and not any(
            row.plant_id == fact.plant_id and row.closed_at is None for row in intervals
        ):
            intervals.append(RunParticipation(fact.plant_id, fact.at))
    return tuple(intervals)


def plan_claim(
    ledger: RunLedger,
    activity: UnattributedActivity,
    *,
    started_on: date,
    now: datetime,
    timezone: str,
    retention_days: int,
    plant_ids: list[str] | tuple[str, ...],
) -> ClaimPlan:
    """Plan a Run starting at local midnight of ``started_on``.

    ``plant_ids`` are the Plants standing in the Growspace now.
    """
    zone = ZoneInfo(timezone)
    started_at = _day_start(started_on, zone)
    horizon = now - timedelta(days=retention_days)
    covered_from = max(started_at, activity.covered_since or now)
    facts = [row for row in activity.facts if row.at >= covered_from]
    backdate = RunBackdate(
        started_on=started_on,
        covered_from=covered_from,
        claimed_facts=len(facts),
        gaps=_gaps(
            activity.days,
            started_at=started_at,
            covered_from=covered_from,
            now=now,
            zone=zone,
        ),
    )
    return ClaimPlan(
        started_on=started_on,
        timezone=timezone,
        retention_days=retention_days,
        horizon=horizon,
        covered_since=activity.covered_since,
        history=ClaimedHistory(
            started_at=started_at,
            backdate=backdate,
            participations=_participations(
                facts,
                growspace_id=ledger.growspace_id,
                covered_from=covered_from,
                plant_ids=plant_ids,
            ),
            facts=tuple(facts),
            days=tuple(row for row in activity.days if row.day >= started_on),
        ),
        conflict=_conflict(ledger, started_at=started_at, now=now, horizon=horizon),
    )


def claim_preview(
    plan: ClaimPlan, *, revision: int, names: dict[str, str]
) -> dict[str, Any]:
    """The wire form of a plan: everything the grower confirms, before they do.

    ``names`` gives a display name for each Plant still known; a Plant that has
    since been removed is shown by its ID.
    """
    history = plan.history
    conflict = plan.conflict
    return {
        "outcome": "preview",
        "preview": {
            "started_on": plan.started_on.isoformat(),
            "started_at": history.started_at.isoformat(),
            "timezone": plan.timezone,
            "run_revision": revision,
            "retention_days": plan.retention_days,
            "retention_horizon": plan.horizon.isoformat(),
            "covered_since": (
                plan.covered_since.isoformat() if plan.covered_since else None
            ),
            "covered_from": history.backdate.covered_from.isoformat(),
            "participant_count": len({r.plant_id for r in history.participations}),
            "participations": [
                {**row.as_dict(), "name": names.get(row.plant_id)}
                for row in history.participations
            ],
            "claimed_facts": [row.as_dict() for row in history.facts],
            "claimed_days": [row.as_dict() for row in history.days],
            "gaps": [gap.as_dict() for gap in history.backdate.gaps],
            "conflict": (
                None
                if conflict is None
                else {
                    "code": conflict.code,
                    "message": str(conflict),
                    "boundary": (
                        conflict.boundary.isoformat() if conflict.boundary else None
                    ),
                }
            ),
        },
    }
