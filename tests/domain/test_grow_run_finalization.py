"""Finalizing a Completed Run into a frozen Run Finalization Snapshot (#673)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from custom_components.growspace_manager.domain.grow_run import (
    CODE_NOT_COMPLETED,
    CODE_NOT_FOUND,
    WARNING_INCOMPLETE_SNAPSHOT,
    CoverageGap,
    FrozenMetric,
    GapReason,
    GrowRun,
    HarvestOutcome,
    MetricCoverage,
    MissingFact,
    OpeningBaseline,
    ParticipantIdentity,
    PlantMovementFact,
    RunAcknowledgementRequired,
    RunBackdate,
    RunCommand,
    RunLedger,
    RunMetadata,
    RunNotCompleted,
    RunNotFound,
    RunRevisionConflict,
    RunSnapshot,
    RunStatus,
    build_snapshot,
    preview_finalization,
    run_details,
)

STARTED = datetime(2026, 7, 24, 20, 30, tzinfo=UTC)
ENDED = STARTED + timedelta(days=70)
FINALIZED = ENDED + timedelta(days=21)


def _identity(plant_id: str, strain: str = "OG Kush", strain_id: int = 7):
    return ParticipantIdentity(
        plant_id, f"{strain} ({plant_id})", strain_id, strain, 1, "A"
    )


def _outcome(
    plant_id: str,
    state: str = "recorded",
    dry_weight: float | None = 100.0,
    *,
    entered_dry_at: datetime | None = STARTED + timedelta(days=63),
    reason: str | None = None,
) -> HarvestOutcome:
    return HarvestOutcome(
        plant_id=plant_id,
        strain="OG Kush",
        phenotype="A",
        source_growspace_id="tent",
        state=state,
        reason=reason,
        metrics={"dry_weight": dry_weight},
        quality_score=None,
        entered_dry_at=entered_dry_at,
    )


def _completed(
    plants: tuple[str, ...] = ("p1", "p2"),
    outcomes: tuple[HarvestOutcome, ...] = (),
    *,
    identities: bool = True,
) -> RunLedger:
    """A ledger holding one Completed Run with the given facts."""
    ledger, _ = RunLedger("tent").start(
        expected_revision=0,
        run_id="run-1",
        command_id="cmd-start",
        now=STARTED,
        timezone="Europe/Berlin",
        metadata=RunMetadata.create(label="Autumn", tags=["organic"]),
        baseline=OpeningBaseline(),
        plant_ids=plants,
        actor_user_id="user-1",
    )
    for outcome in outcomes:
        ledger = ledger.project_harvest_outcome("run-1", outcome)
    if identities:
        ledger = ledger.refresh_identities({p: _identity(p) for p in plants})
    run = ledger.runs[0]
    completed = replace(
        run,
        status=RunStatus.COMPLETED,
        completed_at=ENDED,
        participations=tuple(
            replace(row, closed_at=ENDED) for row in run.participations
        ),
    )
    return replace(ledger, revision=2, runs=(completed,))


def _finalize(
    ledger: RunLedger, acknowledged: tuple[str, ...] = ()
) -> tuple[RunLedger, GrowRun]:
    preview = preview_finalization(
        ledger, "run-1", now=FINALIZED, growspace_name="Tent"
    )
    return ledger.finalize(
        expected_revision=ledger.revision,
        run_id="run-1",
        preview=preview,
        acknowledged=acknowledged,
        command_id="cmd-finalize",
        actor_user_id="user-1",
    )


def _metric(snapshot: RunSnapshot, name: str) -> FrozenMetric:
    return next(row for row in snapshot.metrics if row.metric == name)


# ---------------------------------------------------------------------------
# What the snapshot freezes
# ---------------------------------------------------------------------------


def test_a_complete_run_freezes_every_fact_without_asking() -> None:
    ledger = _completed(
        outcomes=(
            _outcome("p1", dry_weight=100.25),
            _outcome(
                "p2",
                "no_usable_yield",
                0,
                reason="Botrytis",
                entered_dry_at=STARTED + timedelta(days=66),
            ),
        )
    )
    preview = preview_finalization(
        ledger, "run-1", now=FINALIZED, growspace_name="Tent"
    )
    assert preview.warnings == ()

    finalized_ledger, run = _finalize(ledger)
    snapshot = run.snapshot
    assert snapshot is not None
    assert run.status is RunStatus.FINALIZED
    assert finalized_ledger.revision == 3
    assert run.audit[-1].command is RunCommand.FINALIZE
    assert run.audit[-1].at == FINALIZED
    assert (run.audit[-1].prior_revision, run.audit[-1].resulting_revision) == (2, 3)

    assert snapshot.complete
    assert (snapshot.run_id, snapshot.growspace_id, snapshot.growspace_name) == (
        "run-1",
        "tent",
        "Tent",
    )
    assert snapshot.sequence_number == 1
    assert snapshot.timezone == "Europe/Berlin"
    assert (snapshot.started_at, snapshot.completed_at) == (STARTED, ENDED)
    assert snapshot.duration_days == 70
    # Local dates in the Run Timezone: 20:30 UTC is already the next day.
    assert snapshot.harvest_window == (date(2026, 9, 25), date(2026, 9, 28))
    assert [row.plant_id for row in snapshot.participants] == ["p1", "p2"]
    assert snapshot.counts == {
        "participants": 2,
        "harvest_source_plants": 2,
        "recorded": 1,
        "no_usable_yield": 1,
        "missing_outcomes": 0,
    }
    assert [row.as_dict() for row in snapshot.strains] == [
        {
            "strain_id": 7,
            "strain_name": "OG Kush",
            "participants": 2,
            "harvest_source_plants": 2,
        }
    ]
    assert _metric(snapshot, "yield").value == 100.25
    assert _metric(snapshot, "yield_per_harvest_source_plant").value == 50.125
    assert {row.metric: row.definition_version for row in snapshot.metrics} == {
        "yield": 1,
        "yield_per_harvest_source_plant": 1,
    }


def test_a_pending_dry_weight_is_missing_never_zero() -> None:
    ledger = _completed(outcomes=(_outcome("p1"), _outcome("p2", "pending", None)))
    preview = preview_finalization(
        ledger, "run-1", now=FINALIZED, growspace_name="Tent"
    )

    assert preview.warnings == (WARNING_INCOMPLETE_SNAPSHOT,)
    total = _metric(preview.snapshot, "yield")
    assert total.value is None
    assert total.missing == (MissingFact("dry_weight", "p2"),)
    per_plant = _metric(preview.snapshot, "yield_per_harvest_source_plant")
    assert per_plant.value is None
    assert per_plant.missing == (MissingFact("yield"),)
    assert preview.snapshot.counts["missing_outcomes"] == 1


def test_an_incomplete_snapshot_needs_acknowledging_and_keeps_its_gaps() -> None:
    ledger = _completed(outcomes=(_outcome("p1", "incomplete", None),))

    with pytest.raises(RunAcknowledgementRequired) as refused:
        _finalize(ledger)
    assert refused.value.current_revision == 2

    _, run = _finalize(ledger, (WARNING_INCOMPLETE_SNAPSHOT,))
    assert run.snapshot is not None
    assert not run.snapshot.complete
    assert MissingFact("outcome_incomplete", "p1") in run.snapshot.missing
    assert _metric(run.snapshot, "yield").value is None


def test_a_recorded_outcome_without_a_weight_is_still_missing_one() -> None:
    snapshot = build_snapshot(
        _completed(outcomes=(_outcome("p1", "recorded", None),)).runs[0],
        finalized_at=FINALIZED,
        growspace_name="Tent",
    )
    assert _metric(snapshot, "yield").missing == (MissingFact("dry_weight", "p1"),)


def test_a_run_nothing_was_harvested_from_has_no_yield_and_no_window() -> None:
    snapshot = build_snapshot(
        _completed().runs[0], finalized_at=FINALIZED, growspace_name="Tent"
    )
    assert snapshot.harvest_window is None
    assert _metric(snapshot, "yield").missing == (MissingFact("harvest_source_plants"),)
    assert snapshot.counts["harvest_source_plants"] == 0


def test_an_undated_outcome_leaves_the_harvest_window_unknown() -> None:
    snapshot = build_snapshot(
        _completed(outcomes=(_outcome("p1"), _outcome("p2", entered_dry_at=None))).runs[
            0
        ],
        finalized_at=FINALIZED,
        growspace_name="Tent",
    )
    assert snapshot.harvest_window is None
    assert MissingFact("entered_dry_at", "p2") in snapshot.missing
    # The Yield itself does not need the date.
    assert _metric(snapshot, "yield").value == 200.0


def test_a_participant_never_named_keeps_what_its_outcome_recorded() -> None:
    snapshot = build_snapshot(
        _completed(outcomes=(_outcome("p1"),), identities=False).runs[0],
        finalized_at=FINALIZED,
        growspace_name="Tent",
    )
    first, second = snapshot.participants
    assert (first.strain_name, first.phenotype_name, first.plant_name) == (
        "OG Kush",
        "A",
        "",
    )
    assert (second.strain_name, second.strain_id) == ("", None)
    assert MissingFact("participant_identity", "p1") in snapshot.missing
    assert MissingFact("participant_identity", "p2") in snapshot.missing


def test_strains_are_counted_by_identity_as_named_then() -> None:
    ledger = _completed(("p1", "p2", "p3"), outcomes=(_outcome("p3"),))
    ledger = ledger.refresh_identities(
        {
            "p1": _identity("p1", "Amnesia", 2),
            "p2": _identity("p2", "OG Kush", 7),
            "p3": _identity("p3", "Amnesia", 2),
        }
    )
    snapshot = build_snapshot(
        ledger.runs[0], finalized_at=FINALIZED, growspace_name="Tent"
    )
    assert [
        (row.strain_name, row.participants, row.harvest_source_plants)
        for row in snapshot.strains
    ] == [("Amnesia", 2, 1), ("OG Kush", 1, 0)]


def test_a_backdated_runs_uncovered_gaps_are_frozen_as_coverage() -> None:
    gap = CoverageGap(STARTED, STARTED + timedelta(hours=4), GapReason.NOT_OBSERVED)
    ledger = _completed(outcomes=(_outcome("p1"), _outcome("p2")))
    run = replace(
        ledger.runs[0],
        backdate=RunBackdate(STARTED.date(), STARTED, 0, (gap,)),
    )
    snapshot = build_snapshot(run, finalized_at=FINALIZED, growspace_name="Tent")
    assert snapshot.uncovered_gaps == (gap,)
    assert snapshot.coverage == ()


def test_only_a_completed_run_has_a_snapshot() -> None:
    active = _completed().runs[0]
    with pytest.raises(ValueError, match="Completed"):
        build_snapshot(
            replace(active, status=RunStatus.ACTIVE, completed_at=None),
            finalized_at=FINALIZED,
            growspace_name="Tent",
        )


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_an_unknown_run_is_not_found() -> None:
    with pytest.raises(RunNotFound) as refused:
        preview_finalization(_completed(), "nope", now=FINALIZED, growspace_name="T")
    assert refused.value.code == CODE_NOT_FOUND
    assert refused.value.current_revision == 2


def test_an_active_or_finalized_run_is_not_finalized() -> None:
    ledger = _completed()
    active = replace(
        ledger,
        runs=(replace(ledger.runs[0], status=RunStatus.ACTIVE, completed_at=None),),
    )
    with pytest.raises(RunNotCompleted) as refused:
        preview_finalization(active, "run-1", now=FINALIZED, growspace_name="T")
    assert refused.value.code == CODE_NOT_COMPLETED

    finalized, _ = _finalize(ledger, (WARNING_INCOMPLETE_SNAPSHOT,))
    with pytest.raises(RunNotCompleted):
        preview_finalization(finalized, "run-1", now=FINALIZED, growspace_name="T")


def test_a_finalization_on_a_stale_revision_or_a_second_time_is_refused() -> None:
    ledger = _completed(outcomes=(_outcome("p1"), _outcome("p2")))
    preview = preview_finalization(
        ledger, "run-1", now=FINALIZED, growspace_name="Tent"
    )
    with pytest.raises(RunRevisionConflict):
        ledger.finalize(
            expected_revision=1,
            run_id="run-1",
            preview=preview,
            acknowledged=(),
            command_id="c",
            actor_user_id=None,
        )
    finalized, _ = _finalize(ledger)
    with pytest.raises(RunNotCompleted):
        finalized.finalize(
            expected_revision=finalized.revision,
            run_id="run-1",
            preview=preview,
            acknowledged=(),
            command_id="c",
            actor_user_id=None,
        )


# ---------------------------------------------------------------------------
# Frozen means frozen
# ---------------------------------------------------------------------------


def test_nothing_that_feeds_a_mutable_run_reaches_a_finalized_one() -> None:
    ledger, run = _finalize(_completed(outcomes=(_outcome("p1"), _outcome("p2"))))

    after = (
        ledger.project_harvest_outcome("run-1", _outcome("p1", dry_weight=999.0))
        .refresh_identities({"p1": _identity("p1", "Renamed", 99)})
        .project_movement(
            PlantMovementFact(
                "late",
                "p1",
                STARTED + timedelta(days=3),
                "move",
                "tent",
                "other",
                "run-1",
                None,
            )
        )
    )
    assert after is ledger
    assert after.runs[0].snapshot == run.snapshot


def test_identities_refresh_while_mutable_and_outlive_their_plant() -> None:
    ledger = _completed()
    renamed = ledger.refresh_identities({"p1": _identity("p1", "Renamed", 99)})
    identities = {row.plant_id: row for row in renamed.runs[0].participant_identities}
    assert identities["p1"].strain_name == "Renamed"
    # p2 is gone from the live Plants: its last identity stays.
    assert identities["p2"] == _identity("p2")
    # A Plant that never took part is not adopted, and nothing new is nothing.
    assert renamed.refresh_identities({"stranger": _identity("stranger")}) is renamed


# ---------------------------------------------------------------------------
# Run Metadata stays editable, audited, and outside the snapshot
# ---------------------------------------------------------------------------


def test_metadata_edits_are_audited_and_never_move_the_snapshot() -> None:
    ledger, run = _finalize(_completed(outcomes=(_outcome("p1"), _outcome("p2"))))
    now = FINALIZED + timedelta(hours=1)

    edited_ledger, edited = ledger.update_metadata(
        expected_revision=ledger.revision,
        run_id="run-1",
        metadata=RunMetadata.create(label="Best yet", tags=["organic"], notes="n"),
        command_id="cmd-describe",
        actor_user_id="user-2",
        now=now,
    )
    assert edited.status is RunStatus.FINALIZED
    assert edited.snapshot == run.snapshot
    assert edited.metadata.label == "Best yet"
    assert edited_ledger.revision == ledger.revision + 1
    entry = edited.audit[-1]
    assert entry.command is RunCommand.EDIT_METADATA
    assert entry.changed_fields == ("label", "notes")
    assert (entry.at, entry.actor_user_id) == (now, "user-2")


def test_an_edit_that_changes_nothing_is_not_a_command() -> None:
    ledger = _completed()
    run = ledger.runs[0]
    same, returned = ledger.update_metadata(
        expected_revision=ledger.revision,
        run_id="run-1",
        metadata=run.metadata,
        command_id="c",
        actor_user_id=None,
        now=FINALIZED,
    )
    assert same is ledger
    assert returned is run
    with pytest.raises(RunRevisionConflict):
        ledger.update_metadata(
            expected_revision=0,
            run_id="run-1",
            metadata=run.metadata,
            command_id="c",
            actor_user_id=None,
            now=FINALIZED,
        )
    with pytest.raises(RunNotFound):
        ledger.update_metadata(
            expected_revision=ledger.revision,
            run_id="nope",
            metadata=run.metadata,
            command_id="c",
            actor_user_id=None,
            now=FINALIZED,
        )


# ---------------------------------------------------------------------------
# The durable form survives a restart exactly
# ---------------------------------------------------------------------------


def _finalized_run() -> GrowRun:
    ledger = _completed(outcomes=(_outcome("p1"), _outcome("p2", "pending", None)))
    _, run = _finalize(ledger, (WARNING_INCOMPLETE_SNAPSHOT,))
    return replace(
        run,
        snapshot=replace(
            run.snapshot,
            coverage=(MetricCoverage("water_applied", 87.5),),
            uncovered_gaps=(
                CoverageGap(
                    STARTED, STARTED + timedelta(hours=2), GapReason.BEFORE_RECORDING
                ),
            ),
        ),
    )


def test_a_finalized_run_reads_back_exactly() -> None:
    run = _finalized_run()
    ledger = RunLedger("tent", revision=3, next_sequence=2, runs=(run,))
    assert RunLedger.from_dict(ledger.as_dict()) == ledger
    details = run_details(run, 3)["run"]
    assert details["snapshot"] == run.snapshot.as_dict()
    assert details["audit"][-1]["command"] == "finalize"


def test_a_run_stored_before_673_reads_with_no_identities_or_snapshot() -> None:
    stored = _completed().runs[0].as_dict()
    del stored["participant_identities"]
    del stored["snapshot"]
    for row in stored["audit"]:
        del row["changed_fields"]
    run = GrowRun.from_dict(stored)
    assert run.participant_identities == ()
    assert run.snapshot is None


def _stored(**changes: Any) -> dict[str, Any]:
    stored = _finalized_run().as_dict()
    stored["snapshot"].update(changes)
    return stored


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"format": 2}, "later format"),
        ({"harvest_window": {"first": "2026-09-28", "last": "2026-09-25"}}, "ends"),
        ({"completed_at": "2026-07-01T00:00:00+00:00"}, "ends before"),
        ({"run_id": "run-9"}, "another Run"),
        ({"coverage": [{"metric": "w", "coverage_percent": 101}]}, "percentage"),
        ({"coverage": [{"metric": "w", "coverage_percent": True}]}, "percentage"),
    ],
)
def test_a_malformed_snapshot_is_refused(changes: dict[str, Any], error: str) -> None:
    with pytest.raises(ValueError, match=error):
        GrowRun.from_dict(_stored(**changes))


def test_a_metric_with_both_a_value_and_a_missing_fact_is_refused() -> None:
    stored = _stored()
    stored["snapshot"]["metrics"][0]["value"] = 0
    with pytest.raises(ValueError, match="valued or missing"):
        GrowRun.from_dict(stored)
    stored["snapshot"]["metrics"][0]["value"] = "12"
    with pytest.raises(TypeError, match="numeric"):
        GrowRun.from_dict(stored)


def test_a_snapshot_belongs_to_a_finalized_run_only() -> None:
    finalized = _finalized_run().as_dict()
    without = {**finalized, "snapshot": None}
    with pytest.raises(ValueError, match="snapshot"):
        GrowRun.from_dict(without)
    completed = {**finalized, "status": "completed"}
    with pytest.raises(ValueError, match="snapshot"):
        GrowRun.from_dict(completed)


def test_a_participant_with_two_identities_is_refused() -> None:
    stored = _completed().runs[0].as_dict()
    stored["participant_identities"].append(stored["participant_identities"][0])
    with pytest.raises(ValueError, match="two identities"):
        GrowRun.from_dict(stored)


def test_an_outcome_reads_back_when_its_plant_entered_dry() -> None:
    outcome = _outcome("p1")
    assert HarvestOutcome.from_dict(outcome.as_dict()) == outcome
    naive = {**outcome.as_dict(), "entered_dry_at": "2026-09-25T20:30:00"}
    with pytest.raises(ValueError, match="timezone"):
        HarvestOutcome.from_dict(naive)
