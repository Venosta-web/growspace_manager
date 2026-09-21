"""One batch on paper, watched while it prints.

A batch preflight is reviewed in one request; printing it is not a request at
all. Every attempt waits on a physical printer, a batch of twenty labels in two
copies takes minutes, and a WebSocket command that answered only at the end
would leave the card with nothing to show but a spinner -- and nothing at all
if the answer were lost on the way back. A **Batch Job** is therefore started,
held here, and read back: each attempt's outcome lands on the job the moment
the printer answers, in plan order, and the card polls it.

A job never re-derives what it prints. It carries the held
:class:`~.batch.BatchPreflight` by reference, and a retry is a second job over
the same preflight, selecting the first job's failed attempts only -- which is
the one property the domain guarantees and this module must not lose.

Nothing here is persisted, for the same reason approvals are not: a restart
forgets the job, and the operator looks at the labels on the bench before
deciding what to print again.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
import logging
from typing import Any

from homeassistant.core import HomeAssistant

from ..const import DOMAIN
from .approvals import ApprovalHolder
from .batch import AttemptStatus, BatchAttemptResult, BatchPreflight, BatchPrintResult
from .printing import PrintRefused

_LOGGER = logging.getLogger(__name__)

#: A job outlives its printing by long enough to read the result, retry the
#: failures and look again; it never needs to outlive a working session.
JOB_TTL = timedelta(hours=1)

#: How many jobs one config entry keeps. A batch is a deliberate act, rarely
#: repeated more than a few times in a row; the oldest go first.
JOB_LIMIT = 8

#: Where the job holders live on `hass.data`, one per config entry.
_HOLDERS = "label_batch_jobs"

#: The one kind this holder keeps.
BATCH_JOB = "batch_job"


class JobState(StrEnum):
    """Where one job is."""

    #: Attempts are still being sent; some are pending.
    RUNNING = "running"
    #: Every selected attempt has an outcome, printed or failed.
    FINISHED = "finished"
    #: A whole-batch gate refused after the job started and nothing printed.
    REFUSED = "refused"


@dataclass(slots=True)
class BatchJob:
    """One print or retry over a held preflight, updated as it runs."""

    id: str
    preflight_id: str
    preflight: BatchPreflight
    #: The job this one retries, or `None` for the first print.
    retry_of: str | None
    #: Every original attempt, in plan order, with its latest outcome.
    attempts: list[BatchAttemptResult]
    #: The attempts this job sends, in plan order.
    selected: tuple[str, ...]
    state: JobState = JobState.RUNNING
    refusal: PrintRefused | None = None
    _positions: dict[str, int] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        """Index attempts by ID once, for the listener."""
        self._positions = {
            item.attempt.id: index for index, item in enumerate(self.attempts)
        }

    def record(self, result: BatchAttemptResult) -> None:
        """Take one attempt's outcome as soon as the printer answered."""
        self.attempts[self._positions[result.attempt.id]] = result

    def result(self) -> BatchPrintResult:
        """The job as the domain's result, which is what a retry consumes."""
        return BatchPrintResult(
            preflight=self.preflight,
            attempts=tuple(self.attempts),
            attempted_ids=self.selected,
        )

    @property
    def failed(self) -> tuple[str, ...]:
        """The attempts a retry would send, in plan order."""
        return tuple(
            item.attempt.id
            for item in self.attempts
            if item.status is AttemptStatus.FAILED
        )

    def as_dict(self) -> dict[str, Any]:
        """Return the job and every attempt, compactly enough to poll.

        An attempt carries the identities of what reached paper rather than
        the printed raster: the card already holds every record's raster from
        the preflight, and sending each one back on every poll would make
        watching a batch the heaviest thing the card does.
        """
        return {
            "id": self.id,
            "preflight_id": self.preflight_id,
            "preflight_identity": self.preflight.identity,
            "retry_of": self.retry_of,
            "state": str(self.state),
            "selected": list(self.selected),
            "attempts": [_attempt(item) for item in self.attempts],
            "refusal": None
            if self.refusal is None
            else {
                "operation": self.refusal.operation,
                "blocked_by": list(self.refusal.blockers),
                "reason": str(self.refusal),
                # Every gate that refuses a started job is about the review
                # no longer matching the printer, so the answer is one.
                "recovery": "preflight_again",
            },
        }


def _attempt(item: BatchAttemptResult) -> dict[str, Any]:
    """One attempt's plan identity and latest outcome."""
    return {
        **item.attempt.as_dict(),
        "status": str(item.status),
        "error": item.error,
        "raster_identity": item.outcome.raster_identity if item.outcome else None,
        "raster_input_digest": item.outcome.raster_input_digest
        if item.outcome
        else None,
    }


def start_batch_job(
    hass: HomeAssistant,
    holder: ApprovalHolder,
    *,
    preflight_id: str,
    preflight: BatchPreflight,
    previous: BatchJob | None,
    run: Callable[
        [Callable[[BatchAttemptResult], None]],
        Coroutine[Any, Any, BatchPrintResult],
    ],
) -> BatchJob:
    """Hold a new job and print it in the background.

    `run` is the domain call, handed the listener that lands each outcome on
    the job. A first job starts with every attempt pending; a retry starts
    from the previous job's outcomes with only the failed attempts pending
    again, so what the card shows is what is about to happen.
    """
    if previous is None:
        attempts = [
            BatchAttemptResult(attempt=item, status=AttemptStatus.PENDING)
            for item in preflight.attempts
        ]
        selected = tuple(item.id for item in preflight.attempts)
    else:
        selected = previous.failed
        attempts = [
            BatchAttemptResult(attempt=item.attempt, status=AttemptStatus.PENDING)
            if item.attempt.id in selected
            else item
            for item in previous.attempts
        ]
    job = BatchJob(
        id="",
        preflight_id=preflight_id,
        preflight=preflight,
        retry_of=None if previous is None else previous.id,
        attempts=attempts,
        selected=selected,
    )
    job.id = holder.hold(BATCH_JOB, job)
    hass.async_create_background_task(
        _async_run(job, run), name=f"{DOMAIN} label batch {job.id}"
    )
    return job


async def _async_run(
    job: BatchJob,
    run: Callable[
        [Callable[[BatchAttemptResult], None]],
        Coroutine[Any, Any, BatchPrintResult],
    ],
) -> None:
    """Print the job, and leave it in a state that says what happened."""
    try:
        await run(job.record)
    except PrintRefused as refused:
        # A whole-batch gate: calibration moved after the review, or consent
        # no longer matches. The domain refuses before the first attempt.
        job.refusal = refused
        job.state = JobState.REFUSED
        return
    except Exception:
        # Anything else stopped the loop part-way. What printed is recorded;
        # what did not is failed rather than left pending forever, so a retry
        # can send it.
        _LOGGER.exception("Label batch %s stopped unexpectedly", job.id)
        for item in list(job.attempts):
            if item.attempt.id in job.selected and item.status is AttemptStatus.PENDING:
                job.record(
                    BatchAttemptResult(
                        attempt=item.attempt,
                        status=AttemptStatus.FAILED,
                        error="The batch stopped before this label was sent.",
                    )
                )
    job.state = JobState.FINISHED


def batch_job_holder(hass: HomeAssistant, entry_id: str) -> ApprovalHolder:
    """Return one config entry's job holder, creating it the first time."""
    holders: dict[str, ApprovalHolder] = hass.data.setdefault(DOMAIN, {}).setdefault(
        _HOLDERS, {}
    )
    holder = holders.get(entry_id)
    if holder is None:
        holder = ApprovalHolder(ttl=JOB_TTL, limit=JOB_LIMIT)
        holders[entry_id] = holder
    return holder


def running_job_for(holder: ApprovalHolder, preflight_id: str) -> BatchJob | None:
    """Return a job still printing this preflight, if there is one."""
    jobs: list[BatchJob] = holder.values(BATCH_JOB)
    for job in jobs:
        if job.preflight_id == preflight_id and job.state is JobState.RUNNING:
            return job
    return None


__all__ = [
    "BATCH_JOB",
    "BatchJob",
    "JobState",
    "batch_job_holder",
    "running_job_for",
    "start_batch_job",
]
