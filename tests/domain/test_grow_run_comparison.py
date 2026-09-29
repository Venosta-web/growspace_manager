"""Comparing two Finalized Runs, and the metrics each Run status shows (#675)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.growspace_manager.domain.grow_run import (
    CODE_INSUFFICIENT_HISTORY,
    CODE_NOT_FINALIZED,
    CODE_NOT_FOUND,
    CODE_SAME_RUN,
    COMPARISON_COMPARABLE,
    COMPARISON_INCOMPATIBLE,
    COMPARISON_MISSING,
    COMPARISON_UNAVAILABLE,
    FrozenMetric,
    GrowRun,
    HarvestOutcome,
    MetricComparison,
    MissingFact,
    ParticipantIdentity,
    RunInsufficientHistory,
    RunLedger,
    RunNotFinalized,
    RunNotFound,
    RunParticipation,
    RunSameRun,
    RunStatus,
    build_snapshot,
    compare_runs,
    finalized_runs,
    provisional_metrics,
    run_details,
)

STARTED = datetime(2026, 1, 5, 20, 0, tzinfo=UTC)


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
        entered_dry_at=None,
    )


def _run(
    sequence: int,
    status: RunStatus,
    weights: tuple[float | None, ...] = (100.0, 120.0),
) -> GrowRun:
    """Run #``sequence``, ninety days after the one before it."""
    started = STARTED + timedelta(days=90 * (sequence - 1))
    ended = None if status is RunStatus.ACTIVE else started + timedelta(days=70)
    plants = tuple(f"r{sequence}p{index}" for index in range(len(weights)))
    run = GrowRun(
        run_id=f"run-{sequence}",
        growspace_id="tent",
        sequence_number=sequence,
        status=status,
        timezone="Europe/Berlin",
        started_at=started,
        completed_at=ended,
        participations=tuple(
            RunParticipation(plant, started, ended) for plant in plants
        ),
        harvest_outcomes=tuple(
            _outcome(plant, weight)
            for plant, weight in zip(plants, weights, strict=True)
        ),
        participant_identities=tuple(
            ParticipantIdentity(plant, f"Plant {plant}", 7, "OG Kush", 1, "A")
            for plant in plants
        ),
    )
    if status is not RunStatus.FINALIZED:
        return run
    assert ended is not None
    return replace(
        run,
        snapshot=build_snapshot(
            run, finalized_at=ended + timedelta(days=14), growspace_name="Tent"
        ),
    )


def _ledger(*runs: GrowRun) -> RunLedger:
    return RunLedger("tent", revision=9, next_sequence=len(runs) + 1, runs=tuple(runs))


def _row(comparison, name: str) -> MetricComparison:
    return next(row for row in comparison.metrics if row.metric == name)


def _metric(value: float | None, version: int = 1, unit: str = "g") -> FrozenMetric:
    missing = () if value is not None else (MissingFact("dry_weight", "p1"),)
    return FrozenMetric("yield", unit, version, value, missing)


# ---------------------------------------------------------------------------
# Which two Runs
# ---------------------------------------------------------------------------


def test_the_default_pair_is_the_newest_finalized_run_and_its_predecessor() -> None:
    ledger = _ledger(
        _run(1, RunStatus.FINALIZED),
        _run(2, RunStatus.VOIDED),
        _run(3, RunStatus.FINALIZED),
        _run(4, RunStatus.FINALIZED, (150.0, 150.0)),
        _run(5, RunStatus.COMPLETED),
        _run(6, RunStatus.ACTIVE),
    )

    comparison = compare_runs(ledger)

    assert comparison.earlier.sequence_number == 3
    assert comparison.later.sequence_number == 4
    assert [run.sequence_number for run in finalized_runs(ledger)] == [4, 3, 1]


def test_named_runs_compare_the_later_against_the_earlier_whatever_the_order() -> None:
    ledger = _ledger(
        _run(1, RunStatus.FINALIZED, (100.0,)),
        _run(2, RunStatus.FINALIZED, (80.0,)),
        _run(3, RunStatus.FINALIZED, (140.0,)),
    )

    comparison = compare_runs(ledger, ("run-3", "run-1"))

    assert (comparison.earlier.run_id, comparison.later.run_id) == ("run-1", "run-3")
    row = _row(comparison, "yield")
    assert (row.delta, row.direction) == (40.0, "increase")


@pytest.mark.parametrize(
    ("runs", "run_ids", "refusal", "code"),
    [
        ((), None, RunInsufficientHistory, CODE_INSUFFICIENT_HISTORY),
        (
            (RunStatus.FINALIZED, RunStatus.COMPLETED),
            None,
            RunInsufficientHistory,
            CODE_INSUFFICIENT_HISTORY,
        ),
        (
            (RunStatus.FINALIZED, RunStatus.FINALIZED),
            ("run-1", "run-1"),
            RunSameRun,
            CODE_SAME_RUN,
        ),
        (
            (RunStatus.FINALIZED, RunStatus.COMPLETED),
            ("run-1", "run-2"),
            RunNotFinalized,
            CODE_NOT_FINALIZED,
        ),
        (
            (RunStatus.FINALIZED, RunStatus.ACTIVE),
            ("run-2", "run-1"),
            RunNotFinalized,
            CODE_NOT_FINALIZED,
        ),
        # Another growspace's Run is not in this ledger at all.
        (
            (RunStatus.FINALIZED, RunStatus.FINALIZED),
            ("run-1", "elsewhere"),
            RunNotFound,
            CODE_NOT_FOUND,
        ),
    ],
)
def test_a_comparison_refuses_anything_but_two_finalized_runs(
    runs, run_ids, refusal, code
) -> None:
    ledger = _ledger(
        *(_run(index, status) for index, status in enumerate(runs, start=1))
    )

    with pytest.raises(refusal) as raised:
        compare_runs(ledger, run_ids)

    assert raised.value.code == code
    assert raised.value.current_revision == 9


# ---------------------------------------------------------------------------
# One metric row
# ---------------------------------------------------------------------------


def test_yield_is_neutral_it_moves_but_is_never_judged() -> None:
    ledger = _ledger(
        _run(1, RunStatus.FINALIZED, (100.0, 120.0)),
        _run(2, RunStatus.FINALIZED, (90.0, 110.0)),
    )

    rows = {row.metric: row.as_dict() for row in compare_runs(ledger).metrics}

    assert rows["yield"] == {
        "metric": "yield",
        "goal": "neutral",
        "state": COMPARISON_COMPARABLE,
        "earlier": {
            "metric": "yield",
            "unit": "g",
            "definition_version": 1,
            "value": 220.0,
            "complete": True,
            "missing": [],
        },
        "later": {
            "metric": "yield",
            "unit": "g",
            "definition_version": 1,
            "value": 200.0,
            "complete": True,
            "missing": [],
        },
        "delta": -20.0,
        "direction": "decrease",
        "judgment": None,
    }
    assert rows["yield_per_harvest_source_plant"]["direction"] == "decrease"
    assert rows["yield_per_harvest_source_plant"]["judgment"] is None


def test_a_missing_value_leaves_the_row_without_a_direction() -> None:
    ledger = _ledger(
        _run(1, RunStatus.FINALIZED, (100.0, None)),
        _run(2, RunStatus.FINALIZED, (90.0, 110.0)),
    )

    row = _row(compare_runs(ledger), "yield")

    assert row.state == COMPARISON_MISSING
    assert (row.delta, row.direction, row.judgment) == (None, None, None)
    assert row.earlier is not None and row.earlier.value is None


@pytest.mark.parametrize(
    ("earlier", "later"),
    [
        (_metric(100.0, version=1), _metric(120.0, version=2)),
        (_metric(100.0, unit="g"), _metric(120.0, unit="kg")),
        # Different rules outrank a missing value: the pair is never comparable.
        (_metric(None, version=1), _metric(120.0, version=2)),
    ],
)
def test_values_frozen_under_different_rules_are_incompatible(
    earlier: FrozenMetric, later: FrozenMetric
) -> None:
    row = MetricComparison("yield", "neutral", earlier, later)

    assert row.state == COMPARISON_INCOMPATIBLE
    assert row.direction is None


def test_a_metric_only_one_snapshot_froze_is_unavailable() -> None:
    first = _run(1, RunStatus.FINALIZED)
    second = _run(2, RunStatus.FINALIZED)
    assert second.snapshot is not None
    newer = FrozenMetric("energy_productivity", "g/kWh", 1, 1.4)
    second = replace(
        second,
        snapshot=replace(second.snapshot, metrics=(*second.snapshot.metrics, newer)),
    )

    comparison = compare_runs(_ledger(first, second))

    row = _row(comparison, "energy_productivity")
    assert row.state == COMPARISON_UNAVAILABLE
    assert row.earlier is None
    assert row.as_dict()["earlier"] is None
    assert row.goal == "neutral"  # nothing agreed for it here
    assert [row.metric for row in comparison.metrics] == [
        "yield",
        "yield_per_harvest_source_plant",
        "water_applied",
        "water_productivity",
        "energy_productivity",
    ]


@pytest.mark.parametrize(
    ("goal", "earlier", "later", "judgment"),
    [
        ("higher", 1.0, 2.0, "better"),
        ("higher", 2.0, 1.0, "worse"),
        ("lower", 1.0, 2.0, "worse"),
        ("lower", 2.0, 1.0, "better"),
        ("higher", 2.0, 2.0, "same"),
        ("neutral", 2.0, 2.0, None),
    ],
)
def test_only_an_agreed_goal_turns_a_direction_into_a_judgment(
    goal: str, earlier: float, later: float, judgment: str | None
) -> None:
    row = MetricComparison("yield", goal, _metric(earlier), _metric(later))

    assert row.judgment == judgment
    assert row.direction == (
        "equal" if earlier == later else "increase" if later > earlier else "decrease"
    )


# ---------------------------------------------------------------------------
# The wire form
# ---------------------------------------------------------------------------


def test_the_comparison_carries_both_runs_and_their_frozen_context() -> None:
    ledger = _ledger(_run(1, RunStatus.FINALIZED), _run(2, RunStatus.FINALIZED))

    wire = compare_runs(ledger).as_dict()

    assert set(wire) == {"earlier", "later", "metrics"}
    for side, run in (("earlier", ledger.runs[0]), ("later", ledger.runs[1])):
        assert wire[side]["run"]["run_id"] == run.run_id
        assert wire[side]["run"]["run_revision"] == 9
        assert wire[side]["snapshot"] == run.snapshot.as_dict()


# ---------------------------------------------------------------------------
# Live, Pending and Final metrics
# ---------------------------------------------------------------------------


def test_each_status_shows_the_metrics_it_has() -> None:
    active = _run(1, RunStatus.ACTIVE, (100.0, None))
    completed = _run(2, RunStatus.COMPLETED, (100.0, 50.0))
    finalized = _run(3, RunStatus.FINALIZED)
    voided = _run(4, RunStatus.VOIDED)

    live = provisional_metrics(active)
    assert live[0].value is None
    assert live[0].missing == (MissingFact("dry_weight", "r1p1"),)
    assert [row.value for row in provisional_metrics(completed)] == [
        150.0,
        75.0,
        None,
        None,
    ]
    assert finalized.snapshot is not None
    assert provisional_metrics(finalized) == finalized.snapshot.metrics
    assert provisional_metrics(voided) == ()


def test_details_carry_the_metrics_and_who_took_part() -> None:
    run = _run(1, RunStatus.COMPLETED, (100.0,))

    details = run_details(run, 4)["run"]

    assert details["metrics_state"] == "pending"
    assert details["metrics"][0]["value"] == 100.0
    assert details["participant_identities"] == [
        {
            "plant_id": "r1p0",
            "plant_name": "Plant r1p0",
            "strain_id": 7,
            "strain_name": "OG Kush",
            "phenotype_id": 1,
            "phenotype_name": "A",
        }
    ]
