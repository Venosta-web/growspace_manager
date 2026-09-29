"""Reopening a Finalized Run and discarding an empty Active Run (#917)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path
from typing import Any

import pytest

from custom_components.growspace_manager.domain.grow_run import (
    ACTIVITY_FACTS,
    CODE_HAS_ACTIVITY,
    CODE_NOT_ACTIVE,
    CODE_NOT_FINALIZED,
    CODE_REASON_REQUIRED,
    HARVEST_OUTCOMES,
    PARTICIPANTS_CHANGED,
    ClaimedHistory,
    DailySummary,
    DiscardedRun,
    GrowRun,
    HarvestOutcome,
    OpeningBaseline,
    ParticipantIdentity,
    PlantMovementFact,
    RunAuditEntry,
    RunBackdate,
    RunCommand,
    RunHasActivity,
    RunLedger,
    RunMetadata,
    RunNotActive,
    RunNotFinalized,
    RunNotFound,
    RunParticipation,
    RunReasonRequired,
    RunRevisionConflict,
    RunStatus,
    SupersededSnapshot,
    discard_blockers,
    preview_finalization,
    run_details,
    run_summary,
)
from custom_components.growspace_manager.domain.unattributed_activity import (
    UnattributedActivity,
)
from custom_components.growspace_manager.websocket.grow_runs import (
    discard_result,
    refusal_result,
)

STARTED = datetime(2026, 7, 24, 20, 30, tzinfo=UTC)
ENDED = STARTED + timedelta(days=70)
FINALIZED = ENDED + timedelta(days=21)
REOPENED = FINALIZED + timedelta(days=2)
COVERED = STARTED - timedelta(days=10)
CONTRACT = Path(__file__).parents[1] / "fixtures" / "contract"
REGENERATE = (
    ".venv/bin/pytest tests/domain/test_grow_run_correction.py "
    "--regenerate-contract-fixture"
)


def _outcome(plant_id: str, dry_weight: float | None) -> HarvestOutcome:
    return HarvestOutcome(
        plant_id=plant_id,
        strain="OG Kush",
        phenotype="A",
        source_growspace_id="tent",
        state="recorded" if dry_weight is not None else "pending",
        reason=None,
        metrics={"dry_weight": dry_weight},
        quality_score=None,
        entered_dry_at=STARTED + timedelta(days=63),
    )


def _active(plants: tuple[str, ...] = ("p1", "p2")) -> RunLedger:
    ledger, _ = RunLedger("tent").start(
        expected_revision=0,
        run_id="run-1",
        command_id="cmd-start",
        now=STARTED,
        timezone="Europe/Berlin",
        metadata=RunMetadata.create(label="Autumn"),
        baseline=OpeningBaseline(),
        plant_ids=plants,
        actor_user_id="user-1",
        prior_coverage=COVERED,
    )
    return ledger


def _finalized(dry_weight: float | None = None) -> RunLedger:
    """One Finalized Run whose p1 was harvested; p1's weight as given."""
    ledger = _active().refresh_identities(
        {
            plant: ParticipantIdentity(plant, f"Plant {plant}", 7, "OG Kush", 1, "A")
            for plant in ("p1", "p2")
        }
    )
    ledger = ledger.project_harvest_outcome("run-1", _outcome("p1", dry_weight))
    run = ledger.runs[0]
    completed = replace(
        run,
        status=RunStatus.COMPLETED,
        completed_at=ENDED,
        participations=tuple(
            replace(row, closed_at=ENDED) for row in run.participations
        ),
    )
    ledger = replace(ledger, revision=2, runs=(completed,))
    return _finalize(ledger, FINALIZED)[0]


def _finalize(ledger: RunLedger, now: datetime) -> tuple[RunLedger, GrowRun]:
    preview = preview_finalization(ledger, "run-1", now=now, growspace_name="Tent")
    return ledger.finalize(
        expected_revision=ledger.revision,
        run_id="run-1",
        preview=preview,
        acknowledged=preview.warnings,
        command_id=f"cmd-finalize-{ledger.revision}",
        actor_user_id="user-1",
    )


def _reopen(
    ledger: RunLedger,
    *,
    reason: str | None = "p1 was weighed wet",
    expected: int | None = None,
    run_id: str = "run-1",
) -> tuple[RunLedger, GrowRun]:
    return ledger.reopen(
        expected_revision=ledger.revision if expected is None else expected,
        run_id=run_id,
        reason=reason,
        command_id=f"cmd-reopen-{ledger.revision}",
        actor_user_id="admin-1",
        now=REOPENED,
    )


def _discard(
    ledger: RunLedger,
    *,
    expected: int | None = None,
    run_id: str = "run-1",
    reason: str | None = "Started by mistake",
    **activity: Any,
) -> tuple[RunLedger, DiscardedRun]:
    return ledger.discard(
        expected_revision=ledger.revision if expected is None else expected,
        run_id=run_id,
        reason=reason,
        command_id="cmd-discard",
        actor_user_id="user-2",
        now=STARTED + timedelta(hours=3),
        **activity,
    )


def _movement(fact_id: str, **fields: Any) -> PlantMovementFact:
    return PlantMovementFact(
        **{
            "fact_id": fact_id,
            "plant_id": "p3",
            "at": STARTED + timedelta(hours=1),
            "kind": "entry",
            "source_growspace_id": None,
            "target_growspace_id": "tent",
            "source_run_id": None,
            "target_run_id": "run-1",
            **fields,
        }
    )


# ---------------------------------------------------------------------------
# Run Reopening
# ---------------------------------------------------------------------------


def test_reopening_returns_a_finalized_run_to_completed_without_resuming_it() -> None:
    finalized = _finalized()
    before = finalized.runs[0]
    assert before.snapshot is not None

    ledger, run = _reopen(finalized, reason="  p1 was weighed wet  ")

    assert ledger.revision == finalized.revision + 1 == 4
    assert run.status is RunStatus.COMPLETED
    assert run.snapshot is None
    # The operating interval stays closed exactly where completion closed it.
    assert run.completed_at == ENDED
    assert run.participations == before.participations
    assert run.superseded_snapshots == (
        SupersededSnapshot(
            before.snapshot, finalized_revision=3, superseded_revision=4
        ),
    )
    assert run.audit[-1] == RunAuditEntry(
        at=REOPENED,
        command=RunCommand.REOPEN,
        command_id="cmd-reopen-3",
        actor_user_id="admin-1",
        prior_revision=3,
        resulting_revision=4,
        reason="p1 was weighed wet",
    )
    assert run_summary(run, ledger.revision)["metrics_state"] == "pending"


def test_a_reopened_run_takes_corrections_and_freezes_a_new_snapshot_beside_the_old() -> (
    None
):
    reopened, _ = _reopen(_finalized(dry_weight=None))

    # While Finalized nothing reaches the Run; reopened, the correction does.
    corrected = reopened.project_harvest_outcome("run-1", _outcome("p1", 88.0))
    corrected = corrected.refresh_identities(
        {"p2": ParticipantIdentity("p2", "Mother Ann", 7, "OG Kush", 1, "A")}
    )
    refinalized, run = _finalize(corrected, REOPENED + timedelta(hours=1))

    assert refinalized.revision == 5
    assert run.status is RunStatus.FINALIZED
    assert run.snapshot is not None
    assert run.snapshot.complete
    assert run.snapshot.metrics[0].value == 88.0
    assert {row.plant_name for row in run.snapshot.participants} == {
        "Plant p1",
        "Mother Ann",
    }
    # The first snapshot is still there, whole, and still incomplete.
    (old,) = run.superseded_snapshots
    assert old.snapshot.metrics[0].value is None
    assert (old.finalized_revision, old.superseded_revision) == (3, 4)
    assert [entry.command for entry in run.audit] == [
        RunCommand.START,
        RunCommand.FINALIZE,
        RunCommand.REOPEN,
        RunCommand.FINALIZE,
    ]

    # Reopened again, both earlier snapshots are kept, oldest first.
    again, run = _reopen(refinalized, reason="Second look")
    assert [row.finalized_revision for row in run.superseded_snapshots] == [3, 5]
    assert [row.superseded_revision for row in run.superseded_snapshots] == [4, 6]
    assert GrowRun.from_dict(run.as_dict()) == run
    assert RunLedger.from_dict(again.as_dict()) == again


@pytest.mark.parametrize("reason", [None, "", "   \n"])
def test_reopening_needs_a_reason(reason: str | None) -> None:
    finalized = _finalized()
    with pytest.raises(RunReasonRequired) as refused:
        _reopen(finalized, reason=reason)
    assert refused.value.code == CODE_REASON_REQUIRED
    assert refused.value.current_revision == 3


def test_reopening_refuses_a_stale_revision_an_unknown_run_and_a_mutable_run() -> None:
    finalized = _finalized()
    with pytest.raises(RunRevisionConflict):
        _reopen(finalized, expected=2)
    with pytest.raises(RunNotFound):
        _reopen(finalized, run_id="nope")

    reopened, _ = _reopen(finalized)
    with pytest.raises(RunNotFinalized) as completed:
        _reopen(reopened)
    assert completed.value.code == CODE_NOT_FINALIZED
    assert "is completed" in str(completed.value)

    with pytest.raises(RunNotFinalized) as active:
        _reopen(_active())
    assert active.value.active_run is not None


# ---------------------------------------------------------------------------
# Activity-free discard
# ---------------------------------------------------------------------------


def test_an_empty_active_run_is_discarded_and_its_number_never_reused() -> None:
    active = _active()
    ledger, discarded = _discard(active)

    assert ledger.runs == ()
    assert ledger.active_run is None
    assert ledger.revision == 2
    assert ledger.next_sequence == 2
    assert (discarded.run_id, discarded.sequence_number) == ("run-1", 1)
    assert discarded.started_at == STARTED
    assert discarded.audit[0] == active.runs[0].audit[0]
    assert discarded.audit[-1] == RunAuditEntry(
        at=STARTED + timedelta(hours=3),
        command=RunCommand.DISCARD,
        command_id="cmd-discard",
        actor_user_id="user-2",
        prior_revision=1,
        resulting_revision=2,
        reason="Started by mistake",
    )
    assert ledger.discarded == (discarded,)
    assert RunLedger.from_dict(ledger.as_dict()) == ledger

    restarted, run = ledger.start(
        expected_revision=2,
        run_id="run-2",
        command_id="cmd-start-2",
        now=STARTED + timedelta(days=1),
        timezone="Europe/Berlin",
        metadata=RunMetadata(),
        baseline=OpeningBaseline(),
        plant_ids=(),
        actor_user_id="user-1",
    )
    assert run.sequence_number == 2
    assert restarted.discarded == (discarded,)


def test_a_discard_without_a_reason_records_none() -> None:
    _, discarded = _discard(_active(), reason="   ")
    assert discarded.audit[-1].reason is None


@pytest.mark.parametrize(
    ("activity", "reasons"),
    [
        pytest.param(
            {"pending_facts": [_movement("f-1", projected=True)]},
            (ACTIVITY_FACTS,),
            id="a fact naming the Run is still in the Plant outbox",
        ),
        pytest.param(
            {"pending_facts": [_movement("f-2", source_run_id="run-1")]},
            (ACTIVITY_FACTS,),
            id="a fact leaving the Run",
        ),
        pytest.param(
            {"harvest_source_plant_ids": ["p1"]},
            (HARVEST_OUTCOMES,),
            id="a live Plant names the Run as its Harvest Source Run",
        ),
    ],
)
def test_activity_the_run_has_not_received_yet_still_refuses_a_discard(
    activity: dict[str, Any], reasons: tuple[str, ...]
) -> None:
    active = _active()
    with pytest.raises(RunHasActivity) as refused:
        _discard(active, **activity)
    assert refused.value.reasons == reasons
    assert refused.value.code == CODE_HAS_ACTIVITY


def test_every_kind_of_recorded_activity_is_named_in_the_refusal() -> None:
    active = _active()
    # p3 joined and p1 left: two facts, a later Participant and a closed one.
    moved = active.project_movement(_movement("f-in")).project_movement(
        _movement(
            "f-out",
            plant_id="p1",
            kind="removal",
            source_growspace_id="tent",
            target_growspace_id=None,
            source_run_id="run-1",
            target_run_id=None,
        )
    )
    harvested = moved.project_harvest_outcome("run-1", _outcome("p2", None))
    with pytest.raises(RunHasActivity) as refused:
        _discard(harvested)

    assert refused.value.reasons == (
        ACTIVITY_FACTS,
        PARTICIPANTS_CHANGED,
        HARVEST_OUTCOMES,
    )
    assert refused.value.active_run == harvested.active_run
    wire = refusal_result(refused.value)
    assert wire["refusal"]["reasons"] == [
        "activity_facts",
        "participants_changed",
        "harvest_outcomes",
    ]
    assert wire["refusal"]["active_run"]["run_id"] == "run-1"
    assert "complete it instead" in wire["refusal"]["message"]


def test_a_participant_changed_without_a_fact_still_counts() -> None:
    """The rule reads the participation itself, not only how it got there."""
    active = _active()
    run = active.runs[0]
    late = replace(
        run,
        participations=(
            *run.participations,
            RunParticipation("p3", STARTED + timedelta(hours=1)),
        ),
    )
    assert discard_blockers(late) == (PARTICIPANTS_CHANGED,)
    closed = replace(
        run,
        participations=(replace(run.participations[0], closed_at=STARTED),),
    )
    assert discard_blockers(closed) == (PARTICIPANTS_CHANGED,)


def test_only_the_active_run_can_be_discarded() -> None:
    finalized = _finalized()
    with pytest.raises(RunNotActive) as refused:
        _discard(finalized)
    assert refused.value.code == CODE_NOT_ACTIVE
    assert "only an Active Run can be discarded" in str(refused.value)
    with pytest.raises(RunNotFound):
        _discard(_active(), run_id="nope")
    with pytest.raises(RunRevisionConflict):
        _discard(_active(), expected=0)


def test_a_backdated_run_that_claimed_nothing_is_empty_from_its_coverage_start() -> (
    None
):
    covered_from = STARTED - timedelta(days=2)
    claim = ClaimedHistory(
        started_at=STARTED - timedelta(days=5),
        backdate=RunBackdate(
            started_on=date(2026, 7, 19), covered_from=covered_from, claimed_facts=0
        ),
        participations=(RunParticipation("p1", covered_from),),
        facts=(),
        days=(DailySummary(date(2026, 7, 23), ("p1",)),),
    )
    ledger, run = RunLedger("tent").start(
        expected_revision=0,
        run_id="run-1",
        command_id="cmd-start",
        now=STARTED,
        timezone="Europe/Berlin",
        metadata=RunMetadata(),
        baseline=OpeningBaseline(),
        plant_ids=("ignored",),
        actor_user_id="user-1",
        claim=claim,
        prior_coverage=covered_from,
    )
    assert discard_blockers(run) == ()
    discarded, _ = _discard(ledger)
    assert discarded.runs == ()

    # What the start took from the Unattributed Activity Ledger comes back.
    restored = UnattributedActivity("tent").restore(run)
    assert restored.covered_since == covered_from
    assert restored.days == claim.days


def test_restoring_keeps_coverage_and_days_the_ledger_already_holds() -> None:
    run = replace(
        _active().runs[0],
        daily_summaries=(
            DailySummary(date(2026, 7, 20), ("p9",)),
            DailySummary(date(2026, 7, 22), ("p1",)),
        ),
    )
    held = UnattributedActivity(
        "tent",
        covered_since=STARTED,
        days=(DailySummary(date(2026, 7, 22), ("p1", "p2"), entries=1),),
    )
    restored = held.restore(run)
    assert restored.covered_since == STARTED
    assert [row.day.isoformat() for row in restored.days] == [
        "2026-07-20",
        "2026-07-22",
    ]
    assert restored.days[1] == held.days[0]
    # A Run from before #917 recorded no prior coverage: nothing to give back.
    assert UnattributedActivity("tent").restore(
        replace(run, prior_coverage=None, daily_summaries=())
    ) == UnattributedActivity("tent")


# ---------------------------------------------------------------------------
# Stored documents
# ---------------------------------------------------------------------------


def _document() -> dict[str, Any]:
    reopened, _ = _reopen(_finalized())
    ledger, _ = _finalize(reopened, REOPENED)
    return ledger.as_dict()


def test_a_document_from_before_917_reads_with_nothing_superseded_or_discarded() -> (
    None
):
    document = _document()
    del document["discarded"]
    run = document["runs"][0]
    del run["superseded_snapshots"], run["prior_coverage"]
    for entry in run["audit"]:
        del entry["reason"]
    ledger = RunLedger.from_dict(document)
    assert ledger.discarded == ()
    assert ledger.runs[0].superseded_snapshots == ()
    assert ledger.runs[0].prior_coverage is None
    assert {entry.reason for entry in ledger.runs[0].audit} == {None}


def _superseded(document: dict[str, Any]) -> dict[str, Any]:
    return document["runs"][0]["superseded_snapshots"][0]


def _discarded(document: dict[str, Any]) -> dict[str, Any]:
    ledger = RunLedger.from_dict(document)
    run = GrowRun(
        run_id="run-0",
        growspace_id="tent",
        sequence_number=2,
        status=RunStatus.ACTIVE,
        timezone="Europe/Berlin",
        started_at=STARTED,
    )
    ledger = replace(ledger, next_sequence=3, runs=(*ledger.runs, run))
    return _discard(ledger, run_id="run-0")[0].as_dict()


def _corrupt(change: Any) -> Any:
    def corrupted() -> dict[str, Any]:
        document = _document()
        change(document)
        return document

    return corrupted


@pytest.mark.parametrize(
    "corrupted",
    [
        pytest.param(
            _corrupt(lambda d: _superseded(d).update(superseded_revision=3)),
            id="superseded before it was finalized",
        ),
        pytest.param(
            _corrupt(lambda d: _superseded(d)["snapshot"].update(run_id="run-9")),
            id="another Run's superseded snapshot",
        ),
        pytest.param(
            lambda: {
                **(document := _discarded(_document())),
                "discarded": [{**document["discarded"][0], "audit": []}],
            },
            id="a discard with no audit",
        ),
        pytest.param(
            lambda: {
                **(document := _discarded(_document())),
                "discarded": [
                    {
                        **document["discarded"][0],
                        "audit": [
                            {
                                **document["discarded"][0]["audit"][-1],
                                "command": "start",
                            }
                        ],
                    }
                ],
            },
            id="a discard whose audit does not end in it",
        ),
        pytest.param(
            lambda: {
                **(document := _discarded(_document())),
                "discarded": [{**document["discarded"][0], "run_id": "run-1"}],
            },
            id="a discarded Run ID still held",
        ),
        pytest.param(
            lambda: {
                **(document := _discarded(_document())),
                "discarded": [{**document["discarded"][0], "sequence_number": 1}],
            },
            id="a discarded Sequence Number reused",
        ),
    ],
)
def test_a_corrupt_correction_record_refuses_the_whole_ledger(corrupted: Any) -> None:
    with pytest.raises((TypeError, ValueError)):
        RunLedger.from_dict(corrupted())


def test_a_ledger_with_a_discard_reads_back_whole() -> None:
    document = _discarded(_document())
    assert RunLedger.from_dict(document).as_dict() == document


# ---------------------------------------------------------------------------
# The wire forms the card parses
# ---------------------------------------------------------------------------


def _wire_forms() -> dict[str, Any]:
    finalized = _finalized(dry_weight=None)
    reopened_ledger, reopened = _reopen(finalized)
    corrected = reopened_ledger.project_harvest_outcome("run-1", _outcome("p1", 88.0))
    refinalized_ledger, refinalized = _finalize(
        corrected, REOPENED + timedelta(hours=1)
    )
    try:
        _reopen(refinalized_ledger, reason=" ")
    except RunReasonRequired as refused:
        reason_required = refusal_result(refused)
    discarded_ledger, discarded = _discard(_active())
    moved = _active().project_movement(_movement("f-in"))
    try:
        _discard(moved)
    except RunHasActivity as refused:
        has_activity = refusal_result(refused)
    return {
        "grow_run_reopened_v1": {
            "outcome": "reopened",
            "run_revision": reopened_ledger.revision,
            "run": run_summary(reopened, reopened_ledger.revision),
        },
        "grow_run_reopen_refused_v1": reason_required,
        "grow_run_refinalized_details_v1": run_details(
            refinalized, refinalized_ledger.revision
        ),
        "grow_run_discarded_v1": discard_result(discarded, discarded_ledger.revision),
        "grow_run_discard_refused_v1": has_activity,
    }


def test_the_wire_forms_say_what_the_grower_needs() -> None:
    forms = _wire_forms()
    assert forms["grow_run_reopened_v1"]["run"]["status"] == "completed"
    assert forms["grow_run_reopen_refused_v1"]["refusal"]["code"] == (
        "grow_run.reason_required"
    )
    details = forms["grow_run_refinalized_details_v1"]["run"]
    assert details["snapshot"]["complete"] is True
    (superseded,) = details["superseded_snapshots"]
    assert superseded["snapshot"]["complete"] is False
    assert details["audit"][2]["reason"] == "p1 was weighed wet"
    assert (
        details["audit"][2]["resulting_revision"] == superseded["superseded_revision"]
    )
    assert forms["grow_run_discarded_v1"] == {
        "outcome": "discarded",
        "run_revision": 2,
        "run_id": "run-1",
        "sequence_number": 1,
    }
    assert forms["grow_run_discard_refused_v1"]["refusal"]["reasons"] == [
        "activity_facts",
        "participants_changed",
    ]


@pytest.mark.parametrize("name", sorted(_wire_forms()))
def test_contract_fixture(name: str, pytestconfig: pytest.Config) -> None:
    """Each wire form the card parses is exactly the committed fixture."""
    wire = _wire_forms()[name]
    path = CONTRACT / f"{name}.json"
    if pytestconfig.getoption("regenerate_contract_fixture"):
        path.write_text(f"{json.dumps(wire, indent=2, sort_keys=True)}\n")
    assert path.exists(), f"{name} is missing; regenerate with: {REGENERATE}"
    assert wire == json.loads(path.read_text()), (
        f"{name} changed; review the diff, then regenerate with: {REGENERATE}"
    )
