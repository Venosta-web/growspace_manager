"""Write-through persistence of every Growspace's Run Ledger (#668).

Grow Runs are domain records, not entities (ADR-0035), and their history must
survive restarts, Recorder purges and source deletion (ADR-0033/0034). They
therefore live in a store of their own, apart from the debounced configuration
writes: a lifecycle command is decided, persisted and only then published, and
the lock around those three steps is what makes zero-or-one Active Run a rule
rather than a race.

The same document holds each Growspace's Unattributed Activity Ledger (#670,
ADR-0036), so a backdated start can take facts out of it and give them to the
new Run in one write: no fact is ever in both, and a failed write leaves both
where they were.

A file that exists but cannot be read is never written over. Every command is
refused until someone repairs it, because the alternative -- starting afresh --
would reissue Sequence Numbers and silently erase the history it failed to read.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
import logging
from os.path import exists
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, EVENT_GROWSPACE_LOG_ENTRY
from .domain.date_logic import parse_date_field
from .domain.grow_run import (
    DiscardedRun,
    GrowRun,
    HarvestOutcome,
    ParticipantIdentity,
    PlantMovementFact,
    RunAuditEntry,
    RunCommand,
    RunLedger,
    RunStatus,
    RunStoreUnreadable,
    SafetyFact,
    WaterApplication,
)
from .domain.unattributed_activity import DEFAULT_RETENTION_DAYS, UnattributedActivity
from .models.plant import Plant

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1

#: The Grow Run Lifecycle Event: one per committed lifecycle command.
EVENT_GROW_RUN_LIFECYCLE = f"{DOMAIN}_grow_run_lifecycle"

#: The logbook category a lifecycle command is written under.
CATEGORY_GROW_RUN = "grow_run"

_PAST_TENSE = {
    RunCommand.START: "started",
    RunCommand.COMPLETE: "completed",
    RunCommand.FINALIZE: "finalized",
    RunCommand.EDIT_METADATA: "described",
    RunCommand.REOPEN: "reopened",
    RunCommand.DISCARD: "discarded",
}

#: The status a lifecycle event reports for a Run that has left the ledger.
STATUS_DISCARDED = "discarded"


class GrowRunStore:
    """Hold each Growspace's Run Ledger and commit changes to it atomically."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        *,
        retention_days: int = DEFAULT_RETENTION_DAYS,
    ) -> None:
        """Keep Run history separate from the debounced configuration store."""
        self._hass = hass
        self._key = f"growspace_manager.grow_runs_{entry_id}"
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, self._key)
        self._ledgers: dict[str, RunLedger] = {}
        self._unattributed: dict[str, UnattributedActivity] = {}
        self.retention_days = retention_days
        self.lock = asyncio.Lock()
        self.unreadable = False

    async def async_load(self) -> None:
        """Read every ledger, or fail closed on a file that cannot be trusted."""
        try:
            data = await self._store.async_load()
            if data is None:
                path = self._hass.config.path(".storage", self._key)
                self.unreadable = await self._hass.async_add_executor_job(exists, path)
                return
            self._ledgers, self._unattributed = self._decode(data)
        except Exception:
            _LOGGER.exception("Grow Run history is unreadable; every Run command held")
            self.unreadable = True
            self._ledgers = {}
            self._unattributed = {}

    @staticmethod
    def _decode(
        data: Any,
    ) -> tuple[dict[str, RunLedger], dict[str, UnattributedActivity]]:
        """Validate the whole document before accepting any ledger in it.

        A document written before #670 has no Unattributed Activity map; that
        is no coverage yet, never a reason to refuse the Runs beside it.
        """
        if not isinstance(data, dict) or not isinstance(data.get("ledgers"), dict):
            raise TypeError("Grow Run store has no ledger map")
        ledgers: dict[str, RunLedger] = {}
        for growspace_id, raw in data["ledgers"].items():
            ledger = RunLedger.from_dict(raw)
            if ledger.growspace_id != growspace_id:
                raise ValueError("a ledger is filed under another Growspace")
            ledgers[growspace_id] = ledger
        raw_activity = data.get("unattributed", {})
        if not isinstance(raw_activity, dict):
            raise TypeError("Grow Run store has no Unattributed Activity map")
        activities: dict[str, UnattributedActivity] = {}
        for growspace_id, raw in raw_activity.items():
            activity = UnattributedActivity.from_dict(raw)
            if activity.growspace_id != growspace_id:
                raise ValueError(
                    "unattributed activity is filed under another Growspace"
                )
            activities[growspace_id] = activity
        return ledgers, activities

    def ledger(self, growspace_id: str) -> RunLedger:
        """Return a Growspace's ledger; one that never started a Run is empty."""
        if self.unreadable:
            raise RunStoreUnreadable(
                "Grow Run history could not be read; no Run command is accepted "
                "until it is repaired",
                current_revision=None,
            )
        return self._ledgers.get(growspace_id) or RunLedger(growspace_id)

    def unattributed(self, growspace_id: str) -> UnattributedActivity:
        """Return a Growspace's Unattributed Activity Ledger; empty if none yet."""
        self.ledger(growspace_id)  # refuses while the history is unreadable
        return self._unattributed.get(growspace_id) or UnattributedActivity(
            growspace_id
        )

    def active_run(self, growspace_id: str) -> GrowRun | None:
        """The Growspace's Active Run, or None -- also when the store is unreadable."""
        if self.unreadable:
            return None
        return self.ledger(growspace_id).active_run

    async def async_begin_safety_coverage(self, now: datetime) -> None:
        """Mark Runs already active at upgrade as having partial coverage."""
        if self.unreadable:
            return
        async with self.lock:
            for ledger in tuple(self._ledgers.values()):
                runs = tuple(
                    replace(run, safety_coverage_started_at=now)
                    if run.status is RunStatus.ACTIVE
                    and run.safety_coverage_started_at is None
                    else run
                    for run in ledger.runs
                )
                if runs != ledger.runs:
                    await self.async_commit(replace(ledger, runs=runs))

    async def async_commit(
        self,
        ledger: RunLedger | None = None,
        *,
        activities: tuple[UnattributedActivity, ...] = (),
    ) -> None:
        """Persist a ledger and any Unattributed Activity in one write.

        Must be called holding :attr:`lock`. A failed write leaves the
        in-memory state exactly as it was, so nothing unsaved is ever visible.
        """
        if self.unreadable:
            raise RunStoreUnreadable(
                "Grow Run history could not be read", current_revision=None
            )
        ledgers = dict(self._ledgers)
        if ledger is not None:
            ledgers[ledger.growspace_id] = ledger
        unattributed = {
            **self._unattributed,
            **{activity.growspace_id: activity for activity in activities},
        }
        await self._store.async_save(
            {
                "ledgers": {key: value.as_dict() for key, value in ledgers.items()},
                "unattributed": {
                    key: value.as_dict() for key, value in unattributed.items()
                },
            }
        )
        self._ledgers = ledgers
        self._unattributed = unattributed

    async def async_project_movement(self, fact: PlantMovementFact) -> None:
        """Project into every referenced Run; replay after partial writes is safe."""
        growspace_ids = {
            growspace_id
            for growspace_id in (
                fact.source_growspace_id,
                fact.target_growspace_id,
            )
            if growspace_id is not None
        }
        async with self.lock:
            for growspace_id in sorted(growspace_ids):
                ledger = self.ledger(growspace_id)
                # If history was unreadable when the Plant committed, the fact
                # still survived in the Plant document. Attribute it now using
                # the Run whose operating interval holds the fact's timestamp,
                # which may since have completed.
                owner = ledger.run_at(fact.at)
                if owner is not None:
                    if (
                        growspace_id == fact.source_growspace_id
                        and fact.source_run_id is None
                    ):
                        fact = replace(fact, source_run_id=owner.run_id)
                    if (
                        growspace_id == fact.target_growspace_id
                        and fact.target_run_id is None
                    ):
                        fact = replace(fact, target_run_id=owner.run_id)
                expected = {
                    run_id
                    for location, run_id in (
                        (fact.source_growspace_id, fact.source_run_id),
                        (fact.target_growspace_id, fact.target_run_id),
                    )
                    if location == growspace_id and run_id is not None
                }
                if expected - {run.run_id for run in ledger.runs}:
                    raise ValueError(
                        f"Activity fact {fact.fact_id} references a missing Run"
                    )
                updated = ledger.project_movement(fact)
                activity = self.unattributed(growspace_id)
                recorded = activity.record(fact, self._hass.config.time_zone)
                if updated != ledger or recorded != activity:
                    await self.async_commit(
                        updated if updated != ledger else None,
                        activities=(recorded,) if recorded != activity else (),
                    )

    async def async_project_water(
        self, growspace_id: str, application: WaterApplication
    ) -> None:
        """Copy an irrigation fact into its Run once, before source retention."""
        async with self.lock:
            ledger = self.ledger(growspace_id)
            updated = ledger.project_water(application)
            if updated is not ledger:
                await self.async_commit(updated)

    async def async_project_safety(self, fact: SafetyFact) -> None:
        """Attribute one durable safety fact, replaying safely by its ID."""
        async with self.lock:
            ledger = self.ledger(fact.growspace_id)
            activity = self.unattributed(fact.growspace_id)
            if any(
                row.fact_id == fact.fact_id
                for run in ledger.runs
                for row in run.safety_facts
            ):
                return
            owner = ledger.run_at(fact.at)
            if owner is not None:
                updated = ledger.project_safety(fact)
                if updated != ledger:
                    await self.async_commit(updated)
            else:
                updated_activity = activity.record_safety(fact)
                if updated_activity != activity:
                    await self.async_commit(activities=(updated_activity,))

    async def async_mark_water_incomplete(self, growspace_id: str) -> None:
        """Persist loss of delivery coverage when its source cannot be read."""
        async with self.lock:
            ledger = self.ledger(growspace_id)
            updated = ledger.mark_water_incomplete()
            if updated is not ledger:
                await self.async_commit(updated)

    async def async_observe(
        self, now: datetime, occupancy: dict[str, list[str]]
    ) -> None:
        """Keep each Run-free Growspace's ledger covering today, within retention.

        ``occupancy`` maps every Growspace to the Plants standing in it. A
        Growspace with an Active Run stops accruing coverage; one without
        opens or extends it. Writes only when something changed, which is at
        most once a day per Growspace plus whenever a Plant first appears.
        """
        if self.unreadable:
            return
        zone = self._hass.config.time_zone
        async with self.lock:
            changed: list[UnattributedActivity] = []
            for growspace_id, plant_ids in occupancy.items():
                activity = self.unattributed(growspace_id)
                if self.active_run(growspace_id) is None:
                    observed = activity.observe(now, zone, plant_ids)
                else:
                    observed = activity.close()
                observed = observed.prune(now, zone, self.retention_days)
                if observed != activity:
                    changed.append(observed)
            if changed:
                await self.async_commit(activities=tuple(changed))

    async def async_project_harvest_outcomes(self, plants: list[Plant]) -> None:
        """Copy committed Plant outcomes into their source Runs.

        Replaying all live Plants after startup or a failed projection is safe;
        snapshots for deleted Plants remain in the Run ledger.
        """
        async with self.lock:
            for plant in plants:
                run_id = plant.harvest_source_run_id
                source = plant.harvest_source_growspace_id
                if run_id is None or source is None:
                    continue
                ledger = self.ledger(source)
                if not any(run.run_id == run_id for run in ledger.runs):
                    raise ValueError(f"Harvest source Run {run_id} is missing")
                metrics = plant.harvest_metrics.to_dict()
                state = plant.harvest_outcome_state
                if state == "pending" and metrics.get("dry_weight") is not None:
                    state = "recorded"
                outcome = HarvestOutcome(
                    plant_id=plant.plant_id,
                    strain=plant.strain,
                    phenotype=plant.phenotype,
                    source_growspace_id=source,
                    state=state,
                    reason=plant.harvest_outcome_reason,
                    metrics=metrics,
                    quality_score=plant.phenotype_score.total_score,
                    entered_dry_at=parse_date_field(plant.dry_start),
                )
                updated = ledger.project_harvest_outcome(run_id, outcome)
                if updated != ledger:
                    await self.async_commit(updated)

    async def async_project_identities(
        self, identities: dict[str, ParticipantIdentity]
    ) -> None:
        """Refresh every mutable Run's Participant Identity Snapshots.

        ``identities`` holds the live Plants only. A Participant whose Plant
        is gone keeps the identity last copied here, and a Finalized Run is
        never touched: its Participants are in its snapshot.
        """
        async with self.lock:
            for growspace_id in sorted(self._ledgers):
                ledger = self.ledger(growspace_id)
                updated = ledger.refresh_identities(identities)
                if updated is not ledger:
                    await self.async_commit(updated)

    def announce(self, run: GrowRun) -> None:
        """Emit the lifecycle event and logbook line for the Run's last command.

        The Run Audit Entry just committed is the whole description: which
        command, who, when, why when it was asked, and the revision it produced.
        """
        self._announce(
            run.growspace_id,
            run.run_id,
            run.sequence_number,
            run.status.value,
            run.audit[-1],
        )

    def announce_discard(self, growspace_id: str, discarded: DiscardedRun) -> None:
        """Announce a discard: the Run is gone, so its status reads ``discarded``."""
        self._announce(
            growspace_id,
            discarded.run_id,
            discarded.sequence_number,
            STATUS_DISCARDED,
            discarded.audit[-1],
        )

    def _announce(
        self,
        growspace_id: str,
        run_id: str,
        sequence_number: int,
        status: str,
        entry: RunAuditEntry,
    ) -> None:
        user_id = entry.actor_user_id
        actor = f"HA user {user_id}" if user_id else "the system"
        message = f"Run #{sequence_number} {_PAST_TENSE[entry.command]} by {actor}"
        if entry.reason:
            message = f"{message}: {entry.reason}"
        self._hass.bus.async_fire(
            EVENT_GROW_RUN_LIFECYCLE,
            {
                "growspace_id": growspace_id,
                "run_id": run_id,
                "sequence_number": sequence_number,
                "command": entry.command.value,
                "command_id": entry.command_id,
                "status": status,
                "at": entry.at.isoformat(),
                "user_id": user_id,
                "revision": entry.resulting_revision,
                "reason": entry.reason,
            },
        )
        self._hass.bus.async_fire(
            EVENT_GROWSPACE_LOG_ENTRY,
            {
                "growspace_id": growspace_id,
                "category": CATEGORY_GROW_RUN,
                "message": message,
                "timestamp": entry.at.isoformat(),
                "user_id": user_id,
            },
        )
