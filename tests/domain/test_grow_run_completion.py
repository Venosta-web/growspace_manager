"""Completing a Grow Run, with plain values only (#671)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json

import pytest

from custom_components.growspace_manager.domain.grow_run import (
    CODE_ACKNOWLEDGEMENT_REQUIRED,
    CODE_IRRIGATION_DELIVERING,
    CODE_NOT_ACTIVE,
    WARNING_ATTRIBUTION_GAPS,
    WARNING_MISSING_OUTCOMES,
    WARNING_PLANTS_PRESENT,
    CompletionPreview,
    GrowRun,
    HarvestOutcome,
    OpeningBaseline,
    PlantMovementFact,
    PresentPlant,
    RunAcknowledgementRequired,
    RunCommand,
    RunIrrigationDelivering,
    RunLedger,
    RunMetadata,
    RunNotActive,
    RunRevisionConflict,
    RunStatus,
    preview_completion,
    run_summary,
    sensor_state,
)

STARTED = datetime(2026, 7, 24, 20, 30, tzinfo=UTC)
ENDED = STARTED + timedelta(days=70)
EVERY_WARNING = [
    WARNING_PLANTS_PRESENT,
    WARNING_MISSING_OUTCOMES,
    WARNING_ATTRIBUTION_GAPS,
]


def _active(plants: tuple[str, ...] = ("p1", "p2")) -> tuple[RunLedger, GrowRun]:
    return RunLedger("tent").start(
        expected_revision=0,
        run_id="run-1",
        command_id="cmd-start",
        now=STARTED,
        timezone="Europe/Berlin",
        metadata=RunMetadata.create(label="Autumn", notes="Started strong"),
        baseline=OpeningBaseline(),
        plant_ids=plants,
        actor_user_id="user-1",
    )


def _fact(
    fact_id: str,
    plant_id: str,
    at: datetime,
    *,
    kind: str = "transplant",
    source: str | None = "tent",
    target: str | None = "dry-room",
    source_run: str | None = "run-1",
    target_run: str | None = None,
    projected: bool = False,
) -> PlantMovementFact:
    return PlantMovementFact(
        fact_id=fact_id,
        plant_id=plant_id,
        at=at,
        kind=kind,
        source_growspace_id=source,
        target_growspace_id=target,
        source_run_id=source_run,
        target_run_id=target_run,
        projected=projected,
    )


def _present(*plant_ids: str) -> list[PresentPlant]:
    return [PresentPlant(plant_id, "OG Kush", "#1", "flower") for plant_id in plant_ids]


def _preview(
    ledger: RunLedger,
    *,
    now: datetime = ENDED,
    present: tuple[str, ...] = (),
    pending: tuple[PlantMovementFact, ...] = (),
    delivering: tuple[str, ...] = (),
    note: str | None = None,
) -> CompletionPreview:
    return preview_completion(
        ledger,
        now=now,
        plants_present=_present(*present),
        pending_facts=pending,
        delivering_outputs=delivering,
        retrospective_note=note,
    )


def _complete(
    ledger: RunLedger,
    preview: CompletionPreview,
    acknowledged: list[str] | None = None,
    expected: int | None = None,
    run_id: str = "run-1",
) -> tuple[RunLedger, GrowRun]:
    return ledger.complete(
        expected_revision=ledger.revision if expected is None else expected,
        run_id=run_id,
        preview=preview,
        acknowledged=acknowledged or [],
        command_id="cmd-complete",
        actor_user_id="user-2",
    )


# ---------------------------------------------------------------------------
# The preview
# ---------------------------------------------------------------------------


def test_a_clean_empty_run_previews_without_warnings() -> None:
    ledger, run = _active(plants=())
    preview = _preview(ledger, note="  Good run  ")
    wire = preview.as_dict()
    assert preview.warnings == ()
    assert preview.blockers == ()
    assert wire["completed_at"] == ENDED.isoformat()
    assert wire["duration_days"] == 70
    assert wire["closing_participations"] == []
    assert wire["coverage"] == []
    assert wire["retrospective_note"] == "Good run"
    assert wire["run"] == run_summary(run, 1)


def test_plants_still_present_warn_and_their_intervals_are_listed() -> None:
    ledger, _ = _active()
    preview = _preview(ledger, present=("p2", "p1"))
    assert preview.warnings == (WARNING_PLANTS_PRESENT,)
    assert [row.plant_id for row in preview.plants_present] == ["p1", "p2"]
    assert [row["plant_id"] for row in preview.as_dict()["closing_participations"]] == [
        "p1",
        "p2",
    ]
    assert preview.as_dict()["plants_present"][0] == {
        "plant_id": "p1",
        "strain_name": "OG Kush",
        "phenotype_name": "#1",
        "stage": "flower",
    }


def _outcome(plant_id: str, state: str, dry_weight: float | None) -> HarvestOutcome:
    return HarvestOutcome(
        plant_id=plant_id,
        strain="OG Kush",
        phenotype="#1",
        source_growspace_id="tent",
        state=state,
        reason="Hermie" if state == "no_usable_yield" else None,
        metrics={"dry_weight": dry_weight},
        quality_score=None,
    )


def test_pending_and_incomplete_harvest_outcomes_are_missing() -> None:
    """Recorded and No Usable Yield outcomes are complete; the rest are at risk."""
    ledger, _ = _active(plants=("p1", "p2", "p3", "p4"))
    for outcome in (
        _outcome("p3", "incomplete", None),
        _outcome("p1", "recorded", 55.0),
        _outcome("p2", "pending", None),
        _outcome("p4", "no_usable_yield", 0),
    ):
        ledger = ledger.project_harvest_outcome("run-1", outcome)
    preview = _preview(ledger)
    assert [(row.plant_id, row.state) for row in preview.missing_outcomes] == [
        ("p2", "pending"),
        ("p3", "incomplete"),
    ]
    assert preview.warnings == (WARNING_MISSING_OUTCOMES,)
    assert preview.as_dict()["missing_outcomes"][0] == {
        "plant_id": "p2",
        "strain": "OG Kush",
        "phenotype": "#1",
        "state": "pending",
    }


def test_a_run_without_harvest_outcomes_misses_none() -> None:
    ledger, _ = _active(plants=("p1",))
    ledger = ledger.project_movement(_fact("f1", "p1", STARTED + timedelta(days=3)))
    assert _preview(ledger).missing_outcomes == ()


def test_a_completed_run_still_receives_its_outcomes() -> None:
    """Completion does not close the Run to late harvest outcomes (#672)."""
    ledger, _ = _active(plants=())
    ledger, _ = _complete(ledger, _preview(ledger))
    ledger = ledger.project_harvest_outcome("run-1", _outcome("p1", "recorded", 40.0))
    assert ledger.runs[0].harvest_outcomes[0].state == "recorded"


def test_attribution_gaps_name_pending_facts_and_unrecorded_presence() -> None:
    ledger, _ = _active(plants=("p1",))
    pending = (
        _fact("f-in", "p2", STARTED + timedelta(days=5), source=None, target="tent"),
        _fact("f-done", "p9", STARTED + timedelta(days=5), projected=True),
        _fact("f-else", "p8", STARTED + timedelta(days=5), source="other"),
        _fact("f-before", "p7", STARTED - timedelta(days=1)),
    )
    preview = _preview(ledger, present=("p1", "p2", "p3"), pending=pending)
    assert [(g.kind, g.plant_id, g.fact_id) for g in preview.attribution_gaps] == [
        ("pending_fact", "p2", "f-in"),
        ("unrecorded_presence", "p3", None),
    ]
    assert preview.warnings == (WARNING_PLANTS_PRESENT, WARNING_ATTRIBUTION_GAPS)
    assert preview.as_dict()["attribution_gaps"][1] == {
        "kind": "unrecorded_presence",
        "plant_id": "p3",
        "fact_id": None,
        "at": None,
    }


def test_delivering_irrigation_is_a_blocker_not_a_warning() -> None:
    ledger, _ = _active(plants=())
    preview = _preview(ledger, delivering=("switch.pump", "switch.pump", "switch.a"))
    assert preview.delivering_outputs == ("switch.a", "switch.pump")
    assert preview.warnings == ()
    assert preview.blockers == (CODE_IRRIGATION_DELIVERING,)


def test_there_is_nothing_to_preview_without_an_active_run() -> None:
    with pytest.raises(RunNotActive) as refused:
        _preview(RunLedger("tent", revision=4, next_sequence=3))
    assert refused.value.code == CODE_NOT_ACTIVE
    assert refused.value.current_revision == 4


def test_a_retrospective_note_past_its_bound_is_refused() -> None:
    ledger, _ = _active(plants=())
    with pytest.raises(ValueError):
        _preview(ledger, note="x" * 2001)


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------


def test_completion_closes_participation_and_records_the_boundary() -> None:
    ledger, _ = _active()
    ledger = ledger.project_movement(_fact("f1", "p1", STARTED + timedelta(days=3)))
    preview = _preview(ledger, present=("p2",), note="Dense buds")

    completed_ledger, run = _complete(ledger, preview, [WARNING_PLANTS_PRESENT])

    assert run.status is RunStatus.COMPLETED
    assert run.completed_at == ENDED
    assert run.metadata.notes == "Dense buds"
    assert [(p.plant_id, p.closed_at) for p in run.participations] == [
        ("p1", STARTED + timedelta(days=3)),
        ("p2", ENDED),
    ]
    audit = run.audit[-1]
    assert (audit.command, audit.at, audit.actor_user_id) == (
        RunCommand.COMPLETE,
        ENDED,
        "user-2",
    )
    assert (audit.prior_revision, audit.resulting_revision) == (1, 2)
    assert completed_ledger.revision == 2
    assert completed_ledger.next_sequence == 2
    assert completed_ledger.active_run is None
    assert run_summary(run, 2)["metrics_state"] == "pending"
    assert run_summary(run, 2)["completed_at"] == ENDED.isoformat()


def test_a_completed_ledger_clears_the_sensor_and_starts_the_next_run() -> None:
    ledger, _ = _active(plants=())
    ledger, _ = _complete(ledger, _preview(ledger))
    state, attributes = sensor_state(ledger, ENDED)
    assert (state, attributes["run_id"], attributes["run_revision"]) == (
        "none",
        None,
        2,
    )

    ledger, second = ledger.start(
        expected_revision=2,
        run_id="run-2",
        command_id="cmd-2",
        now=ENDED,
        timezone="Europe/Berlin",
        metadata=RunMetadata(),
        baseline=OpeningBaseline(),
        plant_ids=(),
        actor_user_id=None,
    )
    assert second.sequence_number == 2
    assert [run.status for run in ledger.runs] == [
        RunStatus.COMPLETED,
        RunStatus.ACTIVE,
    ]


def test_an_unacknowledged_warning_refuses_and_names_it() -> None:
    ledger, run = _active()
    preview = _preview(ledger, present=("p1",))
    with pytest.raises(RunAcknowledgementRequired) as refused:
        _complete(ledger, preview, [WARNING_MISSING_OUTCOMES])
    assert refused.value.code == CODE_ACKNOWLEDGEMENT_REQUIRED
    assert "plants_present" in str(refused.value)
    assert (refused.value.current_revision, refused.value.active_run) == (1, run)


def test_acknowledging_more_than_is_warned_is_harmless() -> None:
    ledger, _ = _active(plants=())
    _, run = _complete(ledger, _preview(ledger), EVERY_WARNING)
    assert run.status is RunStatus.COMPLETED


def test_delivering_irrigation_refuses_even_when_everything_is_acknowledged() -> None:
    ledger, run = _active(plants=())
    preview = _preview(ledger, delivering=("switch.pump",))
    with pytest.raises(RunIrrigationDelivering) as refused:
        _complete(ledger, preview, EVERY_WARNING)
    assert refused.value.code == CODE_IRRIGATION_DELIVERING
    assert "switch.pump" in str(refused.value)
    assert refused.value.active_run == run


def test_a_stale_revision_is_refused_before_anything_else() -> None:
    ledger, _ = _active(plants=())
    with pytest.raises(RunRevisionConflict):
        _complete(ledger, _preview(ledger), expected=0)


@pytest.mark.parametrize("run_id", ["run-9", "run-1"])
def test_only_the_active_run_can_complete(run_id: str) -> None:
    ledger, _ = _active(plants=())
    preview = _preview(ledger)
    if run_id == "run-1":
        ledger, _ = _complete(ledger, preview)
    with pytest.raises(RunNotActive):
        _complete(ledger, preview, run_id=run_id)


def test_a_boundary_before_the_start_is_impossible() -> None:
    ledger, _ = _active(plants=())
    with pytest.raises(ValueError, match="before it started"):
        _complete(ledger, _preview(ledger, now=STARTED - timedelta(seconds=1)))


# ---------------------------------------------------------------------------
# The boundary: facts that arrive after completion
# ---------------------------------------------------------------------------


def _completed(plants: tuple[str, ...] = ("p1",)) -> RunLedger:
    ledger, _ = _active(plants=plants)
    ledger, _ = _complete(ledger, _preview(ledger), EVERY_WARNING)
    return ledger


def test_a_late_exit_inside_the_run_closes_its_interval_earlier() -> None:
    ledger = _completed()
    exit_at = ENDED - timedelta(hours=1)
    ledger = ledger.project_movement(_fact("late", "p1", exit_at))
    (run,) = ledger.runs
    assert [(p.plant_id, p.closed_at) for p in run.participations] == [("p1", exit_at)]
    assert [row.fact_id for row in run.movement_history] == ["late"]
    assert ledger.project_movement(_fact("late", "p1", exit_at)) == ledger


def test_a_late_entry_inside_the_run_ends_at_the_boundary() -> None:
    ledger = _completed(plants=())
    entry_at = ENDED - timedelta(days=1)
    ledger = ledger.project_movement(
        _fact("late", "p5", entry_at, source=None, target="tent", source_run=None,
              target_run="run-1")
    )  # fmt: skip
    (run,) = ledger.runs
    assert [(p.plant_id, p.opened_at, p.closed_at) for p in run.participations] == [
        ("p5", entry_at, ENDED)
    ]
    assert run.participant_count == 1


@pytest.mark.parametrize("offset", [timedelta(0), timedelta(minutes=1)])
def test_a_fact_at_or_after_the_boundary_is_outside_the_run(offset: timedelta) -> None:
    ledger = _completed()
    assert ledger.project_movement(_fact("after", "p1", ENDED + offset)) == ledger


def test_a_fact_is_attributed_to_the_run_whose_interval_holds_it() -> None:
    ledger = _completed()
    assert ledger.run_at(STARTED) is ledger.runs[0]
    assert ledger.run_at(ENDED - timedelta(seconds=1)) is ledger.runs[0]
    assert ledger.run_at(ENDED) is None
    assert ledger.run_at(STARTED - timedelta(seconds=1)) is None


# ---------------------------------------------------------------------------
# Durable form
# ---------------------------------------------------------------------------


def test_a_completed_ledger_survives_its_durable_form() -> None:
    ledger = _completed()
    assert RunLedger.from_dict(json.loads(json.dumps(ledger.as_dict()))) == ledger


def test_a_run_stored_before_completion_existed_reads_as_active() -> None:
    ledger, run = _active()
    document = json.loads(json.dumps(ledger.as_dict()))
    del document["runs"][0]["completed_at"]
    assert RunLedger.from_dict(document).active_run == run


@pytest.mark.parametrize(
    ("status", "completed_at", "close", "match"),
    [
        ("active", ENDED, True, "Active Run has a completion"),
        ("completed", None, True, "no valid completion"),
        ("completed", STARTED - timedelta(days=1), True, "no valid completion"),
        ("completed", ENDED, False, "still has open participation"),
    ],
)
def test_an_inconsistent_completion_is_refused_whole(
    status: str, completed_at: datetime | None, close: bool, match: str
) -> None:
    ledger, _ = _active(plants=("p1",))
    document = json.loads(json.dumps(ledger.as_dict()))
    run = document["runs"][0]
    run["status"] = status
    run["completed_at"] = completed_at.isoformat() if completed_at else None
    if close:
        run["participations"][0]["closed_at"] = STARTED.isoformat()
    with pytest.raises(ValueError, match=match):
        RunLedger.from_dict(document)
