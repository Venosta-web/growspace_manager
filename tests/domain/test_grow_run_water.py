"""Run water facts keep one source per application and never reward gaps."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.growspace_manager.domain.grow_run import (
    GrowRun,
    HarvestOutcome,
    RunLedger,
    RunStatus,
    WaterApplication,
    build_snapshot,
    compare_runs,
    discard_blockers,
    provisional_metrics,
    water_coverage,
)

START = datetime(2026, 1, 1, tzinfo=UTC)


def _run(sequence: int, liters: float | None, *, covered: bool = True) -> GrowRun:
    start = START + timedelta(days=30 * sequence)
    application = WaterApplication(
        f"watering-{sequence}",
        start + timedelta(days=1),
        "manual" if liters is not None else "unknown",
        liters,
    )
    return GrowRun(
        run_id=f"run-{sequence}",
        growspace_id="tent",
        sequence_number=sequence,
        status=RunStatus.COMPLETED,
        timezone="UTC",
        started_at=start,
        completed_at=start + timedelta(days=10),
        water_coverage_started_at=start if covered else None,
        water_applications=(application,),
        harvest_outcomes=(
            HarvestOutcome(
                plant_id=f"plant-{sequence}",
                strain="A",
                phenotype="B",
                source_growspace_id="tent",
                state="recorded",
                reason=None,
                metrics={"dry_weight": 100.0},
                quality_score=None,
                entered_dry_at=start + timedelta(days=8),
            ),
        ),
    )


def _metric(run: GrowRun, name: str):
    return next(row for row in provisional_metrics(run) if row.metric == name)


def test_water_applications_are_deduplicated_and_boundary_scoped() -> None:
    run = _run(1, 2)
    ledger = RunLedger("tent", runs=(run,))
    new = WaterApplication(
        "pump-1", run.started_at + timedelta(hours=1), "pump_estimate", 3
    )
    updated = ledger.project_water(new)
    assert updated.project_water(new) == updated
    assert len(updated.runs[0].water_applications) == 2
    assert _metric(updated.runs[0], "water_applied").value == 5
    assert (
        updated.project_water(
            WaterApplication("too-late", run.completed_at, "manual", 1)
        )
        == updated
    )


def test_unknown_volume_and_missing_coverage_suppress_both_metrics() -> None:
    unknown = _run(1, None)
    assert _metric(unknown, "water_applied").value is None
    assert _metric(unknown, "water_productivity").value is None
    assert _metric(unknown, "water_applied").missing[0].kind == "water_volume"
    uncovered = _run(2, 4, covered=False)
    assert _metric(uncovered, "water_applied").value is None
    assert _metric(uncovered, "water_applied").missing[0].kind == "water_coverage"


def test_partial_application_coverage_is_explicit_and_can_be_lost() -> None:
    run = _run(1, 2)
    run = replace(
        run,
        water_applications=(
            *run.water_applications,
            WaterApplication("unconfirmed", run.started_at, "unknown", None),
        ),
    )
    assert water_coverage(run)[0].coverage_percent == 50
    ledger = RunLedger("tent", runs=(run,))
    incomplete = ledger.mark_water_incomplete()
    assert incomplete != ledger
    assert incomplete.mark_water_incomplete() == incomplete
    assert water_coverage(incomplete.runs[0])[0].coverage_percent == 0


def test_zero_denominator_is_visible_but_has_no_productivity() -> None:
    run = replace(_run(1, 2), water_applications=())
    assert _metric(run, "water_applied").value == 0
    assert _metric(run, "water_productivity").value is None
    assert _metric(run, "water_productivity").missing == (
        _metric(run, "water_productivity").missing[0],
    )
    assert (
        _metric(run, "water_productivity").missing[0].kind == "positive_water_applied"
    )


def test_finalized_comparison_judges_productivity_but_not_water_total() -> None:
    earlier = _run(1, 5)
    later = _run(2, 4)
    earlier = replace(
        earlier,
        status=RunStatus.FINALIZED,
        snapshot=build_snapshot(
            earlier, finalized_at=earlier.completed_at, growspace_name="Tent"
        ),
    )
    later = replace(
        later,
        status=RunStatus.FINALIZED,
        snapshot=build_snapshot(
            later, finalized_at=later.completed_at, growspace_name="Tent"
        ),
    )
    comparison = compare_runs(RunLedger("tent", runs=(earlier, later)))
    rows = {row.metric: row for row in comparison.metrics}
    assert rows["water_applied"].direction == "decrease"
    assert rows["water_applied"].judgment is None
    assert rows["water_productivity"].direction == "increase"
    assert rows["water_productivity"].judgment == "better"
    assert later.snapshot is not None
    assert later.snapshot.water_applications[0].source == "manual"
    assert later.snapshot.coverage[0].coverage_percent == 100


@pytest.mark.parametrize(
    "liters,source",
    [
        (None, "manual"),
        (1, "unknown"),
        (-1, "manual"),
        (float("inf"), "manual"),
        (True, "manual"),
    ],
)
def test_water_application_rejects_inconsistent_evidence(liters, source) -> None:
    with pytest.raises(ValueError):
        WaterApplication("bad", START, source, liters)


def test_water_application_round_trip_rejects_malformed_volume() -> None:
    application = WaterApplication("manual-1", START, "manual", 1.25)
    assert WaterApplication.from_dict(application.as_dict()) == application
    with pytest.raises(TypeError):
        WaterApplication.from_dict({**application.as_dict(), "liters": True})
    with pytest.raises(ValueError):
        WaterApplication("", START, "manual", 1.0)
    with pytest.raises(ValueError):
        WaterApplication("bad-source", START, "tank", 1.0)
    with pytest.raises(ValueError):
        WaterApplication("naive", START.replace(tzinfo=None), "manual", 1.0)


def test_stored_duplicate_water_fact_is_refused_and_it_blocks_discard() -> None:
    run = _run(1, 2)
    assert "activity_facts" in discard_blockers(run)
    raw = run.as_dict()
    raw["water_applications"].append(raw["water_applications"][0])
    with pytest.raises(ValueError, match="water application appears twice"):
        GrowRun.from_dict(raw)
