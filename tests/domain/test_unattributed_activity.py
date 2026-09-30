"""The Unattributed Activity Ledger and backdated claims, plain values only (#670)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path
from typing import Any

import pytest

from custom_components.growspace_manager.domain.grow_run import (
    CODE_ALREADY_ACTIVE,
    CODE_BEYOND_RETENTION,
    CODE_BOUNDARY_CONFLICT,
    CoverageGap,
    DailySummary,
    GapReason,
    GrowRun,
    OpeningBaseline,
    PlantMovementFact,
    RunBackdate,
    RunLedger,
    RunMetadata,
    RunStatus,
    SafetyFact,
)
from custom_components.growspace_manager.domain.unattributed_activity import (
    ClaimPlan,
    UnattributedActivity,
    claim_preview,
    plan_claim,
)
from custom_components.growspace_manager.websocket.grow_runs import refusal_result

ZONE = "Europe/Berlin"
# Midnight in Berlin (CEST, UTC+2) on each day of August 2026.
DAY = {n: datetime(2026, 8, n, tzinfo=UTC) - timedelta(hours=2) for n in range(1, 32)}
COVERED = DAY[1] + timedelta(hours=9)
NOW = DAY[10] + timedelta(hours=12)
CONTRACT = Path(__file__).parents[1] / "fixtures" / "contract"
REGENERATE = (
    ".venv/bin/pytest tests/domain/test_unattributed_activity.py "
    "--regenerate-contract-fixture"
)


def _fact(
    fact_id: str,
    plant_id: str,
    at: datetime,
    source: str | None,
    target: str | None,
    *,
    source_run: str | None = None,
    target_run: str | None = None,
    kind: str = "transplant",
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
    )


def _observed(*days: int, plants: tuple[str, ...] = ()) -> UnattributedActivity:
    """A tent covered since the 1st, observed on the given days."""
    activity = UnattributedActivity("tent")
    for day in days:
        activity = activity.observe(
            COVERED if day == 1 else DAY[day] + timedelta(hours=1), ZONE, plants
        )
    return activity


def _history() -> UnattributedActivity:
    """p1 stood in the tent throughout; p2 arrived on the 3rd; p1 left and came back."""
    activity = _observed(*range(1, 11), plants=("p1",))
    for fact in (
        _fact("f-entry", "p2", DAY[3] + timedelta(hours=8), None, "tent", kind="entry"),
        _fact("f-out", "p1", DAY[4] + timedelta(hours=8), "tent", "veg"),
        _fact("f-back", "p1", DAY[6] + timedelta(hours=8), "veg", "tent"),
        _fact("f-move", "p2", DAY[7] + timedelta(hours=8), "tent", "tent", kind="move"),
    ):
        activity = activity.record(fact, ZONE)
    return activity


def _plan(
    started_on: date,
    *,
    ledger: RunLedger | None = None,
    activity: UnattributedActivity | None = None,
    retention_days: int = 365,
    plants: tuple[str, ...] = ("p1", "p2"),
) -> ClaimPlan:
    return plan_claim(
        ledger or RunLedger("tent", revision=2, next_sequence=3),
        activity if activity is not None else _history(),
        started_on=started_on,
        now=NOW,
        timezone=ZONE,
        retention_days=retention_days,
        plant_ids=plants,
    )


# ---------------------------------------------------------------------------
# Keeping the ledger
# ---------------------------------------------------------------------------


def test_an_unattributed_fact_is_kept_once_and_summarised_on_its_local_day() -> None:
    fact = _fact("f1", "p1", DAY[3] + timedelta(minutes=30), "veg", "tent")
    activity = UnattributedActivity("tent").record(fact, ZONE)
    assert activity.record(fact, ZONE) is activity
    assert activity.facts == (replace(fact, projected=True),)
    # 22:30 UTC on the 2nd is 00:30 on the 3rd in Berlin.
    assert activity.days == (DailySummary(date(2026, 8, 3), ("p1",), 1, 0),)


def test_safety_fact_is_claimed_once_by_a_backdated_run() -> None:
    fact = SafetyFact("stop-1", "tent", DAY[3], "emergency_stop")
    activity = _observed(*range(1, 11)).record_safety(fact)
    assert activity.record_safety(fact) is activity
    assert UnattributedActivity.from_dict(activity.as_dict()) == activity
    plan = _plan(date(2026, 8, 2), activity=activity, plants=())
    assert plan.history.safety_facts == (fact,)
    remaining = plan.remaining(activity)
    assert remaining.safety_facts == ()
    ledger, run = RunLedger("tent", revision=2, next_sequence=3).start(
        expected_revision=2,
        run_id="run-3",
        command_id="start-3",
        now=NOW,
        timezone=ZONE,
        metadata=RunMetadata(),
        baseline=OpeningBaseline(),
        plant_ids=(),
        actor_user_id="user",
        claim=plan.history,
    )
    assert ledger.find(run.run_id).safety_facts == (fact,)
    assert activity.prune(NOW, ZONE, 5).safety_facts == ()
    with pytest.raises(ValueError, match="safety fact appears twice"):
        UnattributedActivity.from_dict(
            {**activity.as_dict(), "safety_facts": [fact.as_dict(), fact.as_dict()]}
        )


def test_leaving_counts_an_exit_and_a_move_inside_counts_neither() -> None:
    activity = (
        UnattributedActivity("tent")
        .record(_fact("f1", "p1", DAY[3], "tent", None, kind="removal"), ZONE)
        .record(_fact("f2", "p2", DAY[3], "tent", "tent", kind="move"), ZONE)
    )
    assert activity.days == (DailySummary(date(2026, 8, 3), ("p1", "p2"), 0, 1),)


def test_a_fact_a_run_owns_here_or_elsewhere_is_not_unattributed_here() -> None:
    empty = UnattributedActivity("tent")
    owned = _fact("f1", "p1", DAY[3], "veg", "tent", target_run="run-1")
    unrelated = _fact("f2", "p1", DAY[3], "veg", "flower")
    assert empty.record(owned, ZONE) is empty
    assert empty.record(unrelated, ZONE) is empty
    # The source side's Run does not own the tent's side.
    leaving_a_run = _fact("f3", "p1", DAY[3], "veg", "tent", source_run="run-9")
    assert empty.record(leaving_a_run, ZONE).facts[0].fact_id == "f3"


def test_observing_opens_coverage_once_and_writes_only_on_change() -> None:
    first = UnattributedActivity("tent").observe(COVERED, ZONE, ["p1"])
    assert first.covered_since == COVERED
    assert first.days == (DailySummary(date(2026, 8, 1), ("p1",)),)
    later_same_day = COVERED + timedelta(hours=3)
    assert first.observe(later_same_day, ZONE, ["p1"]) is first
    grown = first.observe(later_same_day, ZONE, ["p2"])
    assert grown.days == (DailySummary(date(2026, 8, 1), ("p1", "p2")),)
    next_day = grown.observe(DAY[2] + timedelta(hours=1), ZONE, [])
    assert next_day.covered_since == COVERED
    assert [row.day.day for row in next_day.days] == [1, 2]


def test_pruning_forgets_what_retention_no_longer_keeps() -> None:
    activity = _history()
    assert activity.prune(NOW, ZONE, 365) is activity
    pruned = activity.prune(NOW, ZONE, 5)
    horizon = NOW - timedelta(days=5)
    assert pruned.covered_since == horizon
    assert [row.fact_id for row in pruned.facts] == ["f-back", "f-move"]
    assert [row.day.day for row in pruned.days] == [5, 6, 7, 8, 9, 10]
    assert UnattributedActivity("tent").prune(NOW, ZONE, 5).covered_since is None


def test_closing_ends_coverage_and_keeps_the_facts() -> None:
    activity = _history()
    closed = activity.close()
    assert closed.covered_since is None
    assert closed.facts == activity.facts
    assert closed.close() is closed


def test_the_ledger_round_trips_and_refuses_duplicates() -> None:
    activity = _history()
    stored = json.loads(json.dumps(activity.as_dict()))
    assert UnattributedActivity.from_dict(stored) == activity

    twice = {**stored, "facts": [stored["facts"][0]] * 2}
    with pytest.raises(ValueError, match="fact appears twice"):
        UnattributedActivity.from_dict(twice)
    twice = {**stored, "days": [stored["days"][0]] * 2}
    with pytest.raises(ValueError, match="summarised twice"):
        UnattributedActivity.from_dict(twice)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("growspace_id", ""),
        ("covered_since", "2026-08-01T09:00:00"),
        ("facts", None),
        ("days", {}),
    ],
)
def test_a_malformed_ledger_is_refused(key: str, value: Any) -> None:
    stored = json.loads(json.dumps(_history().as_dict()))
    with pytest.raises((TypeError, ValueError)):
        UnattributedActivity.from_dict({**stored, key: value})


@pytest.mark.parametrize(
    "day",
    [
        {"date": "2026-08-01", "plant_ids": None, "entries": 0, "exits": 0},
        {"date": "01/08/2026", "plant_ids": [], "entries": 0, "exits": 0},
        {"date": "2026-08-01", "plant_ids": [], "entries": -1, "exits": 0},
    ],
)
def test_a_malformed_day_is_refused(day: dict[str, Any]) -> None:
    with pytest.raises((TypeError, ValueError)):
        DailySummary.from_dict(day)


# ---------------------------------------------------------------------------
# Planning a claim
# ---------------------------------------------------------------------------


def test_a_claim_reconstructs_participation_from_the_recorded_movement() -> None:
    plan = _plan(date(2026, 8, 2))
    history = plan.history
    assert plan.conflict is None
    assert history.started_at == DAY[2]
    assert history.backdate.covered_from == DAY[2]
    assert [
        (row.plant_id, row.opened_at, row.closed_at) for row in history.participations
    ] == [
        ("p1", DAY[2], DAY[4] + timedelta(hours=8)),
        ("p2", DAY[3] + timedelta(hours=8), None),
        ("p1", DAY[6] + timedelta(hours=8), None),
    ]
    assert [row.fact_id for row in history.facts] == [
        "f-entry",
        "f-out",
        "f-back",
        "f-move",
    ]
    assert [row.day.day for row in history.days] == list(range(2, 11))
    assert history.backdate.claimed_facts == 4
    assert history.backdate.gaps == ()


def test_a_plant_that_left_before_today_is_still_a_participant() -> None:
    activity = _observed(*range(1, 11), plants=("p1", "p9")).record(
        _fact("f-gone", "p9", DAY[5], "tent", None, kind="removal"), ZONE
    )
    plan = _plan(date(2026, 8, 2), activity=activity, plants=("p1",))
    assert [
        (row.plant_id, row.opened_at, row.closed_at)
        for row in plan.history.participations
    ] == [("p1", DAY[2], None), ("p9", DAY[2], DAY[5])]


def test_the_stretch_before_coverage_is_a_gap_not_an_inference() -> None:
    plan = _plan(date(2026, 7, 30))
    backdate = plan.history.backdate
    assert plan.conflict is None
    assert plan.history.started_at == DAY[1] - timedelta(days=2)
    assert backdate.covered_from == COVERED
    assert backdate.gaps == (
        CoverageGap(DAY[1] - timedelta(days=2), COVERED, GapReason.BEFORE_RECORDING),
    )
    # Plants standing when coverage began join from coverage, not from the 30th.
    assert plan.history.participations[0].opened_at == COVERED


def test_days_nobody_observed_are_gaps_and_neighbours_merge() -> None:
    activity = _observed(1, 2, 5, 6, 8, 9, 10, plants=("p1",))
    plan = _plan(date(2026, 8, 2), activity=activity, plants=("p1",))
    assert plan.history.backdate.gaps == (
        CoverageGap(DAY[3], DAY[5], GapReason.NOT_OBSERVED),
        CoverageGap(DAY[7], DAY[8], GapReason.NOT_OBSERVED),
    )


def test_without_any_coverage_the_whole_interval_is_uncovered() -> None:
    plan = _plan(date(2026, 8, 9), activity=UnattributedActivity("tent"), plants=())
    assert plan.history.backdate.covered_from == NOW
    assert plan.history.backdate.gaps == (
        CoverageGap(DAY[9], NOW, GapReason.BEFORE_RECORDING),
    )
    assert plan.history.participations == ()


def test_today_is_a_valid_start_and_tomorrow_is_not() -> None:
    assert _plan(date(2026, 8, 10)).conflict is None
    tomorrow = _plan(date(2026, 8, 11)).conflict
    assert tomorrow is not None
    assert tomorrow.code == CODE_BOUNDARY_CONFLICT
    assert tomorrow.boundary == NOW
    assert tomorrow.current_revision == 2


def test_history_older_than_retention_is_directed_to_an_imported_run() -> None:
    conflict = _plan(date(2026, 8, 3), retention_days=7).conflict
    assert conflict is not None
    assert conflict.code == CODE_BEYOND_RETENTION
    assert conflict.boundary == NOW - timedelta(days=7)
    assert "Imported Run" in str(conflict)
    assert _plan(date(2026, 8, 3), retention_days=8).conflict is None


def _run(status: RunStatus, started_at: datetime) -> GrowRun:
    return GrowRun(
        run_id="run-1",
        growspace_id="tent",
        sequence_number=1,
        status=status,
        timezone=ZONE,
        started_at=started_at,
    )


def test_an_active_run_is_the_conflicting_boundary() -> None:
    ledger = RunLedger(
        "tent", revision=1, next_sequence=2, runs=(_run(RunStatus.ACTIVE, DAY[5]),)
    )
    conflict = _plan(date(2026, 8, 2), ledger=ledger).conflict
    assert conflict is not None
    assert conflict.code == CODE_ALREADY_ACTIVE
    assert conflict.boundary == DAY[5]
    assert conflict.active_run == ledger.active_run


def test_a_start_may_not_reach_back_over_an_earlier_run() -> None:
    ledger = RunLedger(
        "tent", revision=3, next_sequence=2, runs=(_run(RunStatus.COMPLETED, DAY[5]),)
    )
    overlapping = _plan(date(2026, 8, 5), ledger=ledger).conflict
    assert overlapping is not None
    assert overlapping.code == CODE_BOUNDARY_CONFLICT
    assert overlapping.boundary == DAY[5]
    assert "never overlap" in str(overlapping)
    assert _plan(date(2026, 8, 6), ledger=ledger).conflict is None


def test_a_committed_claim_leaves_the_ledger_and_belongs_to_the_run() -> None:
    activity = _history()
    plan = _plan(date(2026, 8, 5))
    remaining = plan.remaining(activity)
    assert remaining.covered_since is None
    assert [row.fact_id for row in remaining.facts] == ["f-entry", "f-out"]
    assert [row.day.day for row in remaining.days] == [1, 2, 3, 4]

    ledger, run = RunLedger("tent", revision=2, next_sequence=3).start(
        expected_revision=2,
        run_id="run-3",
        command_id="cmd-3",
        now=NOW,
        timezone=ZONE,
        metadata=RunMetadata(),
        baseline=OpeningBaseline(),
        plant_ids=["ignored"],
        actor_user_id="user-1",
        claim=plan.history,
    )
    assert ledger.revision == 3
    assert run.started_at == DAY[5]
    assert run.audit[0].at == NOW
    assert run.local_days(NOW) == 5
    assert run.backdate == plan.history.backdate
    assert run.daily_summaries == plan.history.days
    assert {
        (r.fact_id, r.target_run_id, r.projected) for r in run.movement_history
    } == {
        ("f-back", "run-3", True),
        ("f-move", "run-3", True),
    }
    # The side that left the tent for veg keeps veg's attribution: none.
    assert run.movement_history[0].source_run_id is None
    assert "ignored" not in {row.plant_id for row in run.participations}
    assert RunLedger.from_dict(json.loads(json.dumps(ledger.as_dict()))) == ledger


def test_an_older_stored_run_has_no_backdate_or_days() -> None:
    stored = _run(RunStatus.ACTIVE, NOW).as_dict()
    del stored["backdate"]
    del stored["daily_summaries"]
    run = GrowRun.from_dict(stored)
    assert (run.backdate, run.daily_summaries) == (None, ())


@pytest.mark.parametrize(
    "gap",
    [
        {"start": DAY[2].isoformat(), "end": DAY[2].isoformat(), "reason": "x"},
        {
            "start": DAY[3].isoformat(),
            "end": DAY[2].isoformat(),
            "reason": "not_observed",
        },
        {"start": DAY[2].isoformat(), "end": DAY[3].isoformat(), "reason": "late"},
    ],
)
def test_a_malformed_backdate_is_refused(gap: dict[str, Any]) -> None:
    backdate = RunBackdate(date(2026, 8, 2), DAY[2], 0).as_dict()
    with pytest.raises((TypeError, ValueError)):
        RunBackdate.from_dict({**backdate, "gaps": [gap]})


# ---------------------------------------------------------------------------
# Wire forms the card parses (contract fixtures)
# ---------------------------------------------------------------------------


def _wire_forms() -> dict[str, Any]:
    names = {"p1": "OG Kush", "p2": "Gelato"}
    clear = _plan(date(2026, 7, 31))
    refused = _plan(date(2026, 8, 3), retention_days=7)
    assert refused.conflict is not None
    return {
        "grow_run_start_preview_v1": {
            "clear": claim_preview(clear, revision=2, names=names),
            "conflict": claim_preview(refused, revision=2, names=names),
        },
        "grow_run_beyond_retention_v1": refusal_result(refused.conflict),
    }


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


def test_the_preview_names_known_plants_and_counts_each_once() -> None:
    preview = _wire_forms()["grow_run_start_preview_v1"]["clear"]["preview"]
    assert preview["participant_count"] == 2
    assert [row["name"] for row in preview["participations"]] == [
        "OG Kush",
        "Gelato",
        "OG Kush",
    ]
    assert preview["conflict"] is None
    assert preview["gaps"][0]["reason"] == "before_recording"
    unnamed = claim_preview(_plan(date(2026, 8, 2)), revision=2, names={})
    assert {row["name"] for row in unnamed["preview"]["participations"]} == {None}
