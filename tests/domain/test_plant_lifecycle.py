"""Unit tests for the pure Plant Lifecycle domain module."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date, datetime
from pathlib import Path

import pytest

from custom_components.growspace_manager.domain.plant_lifecycle import (
    Applied,
    CultivationBandId,
    DecisionStatus,
    LifecycleStage,
    LifetimeStageDays,
    NoChange,
    PlantLifecycle,
    Rejected,
    RepairWarningCode,
    StageInterval,
    cultivation_band_for,
)

TODAY = date(2026, 8, 22)


def history(*items: tuple[str, str, str | None]) -> list[dict[str, str | None]]:
    """Build persisted Stage History input."""
    return [{"stage": stage, "start": start, "end": end} for stage, start, end in items]


def lifecycle_for(*items: tuple[str, str, str | None]) -> PlantLifecycle:
    """Build a lifecycle observed on the shared test date."""
    return PlantLifecycle.from_data(history(*items), observed_on=TODAY)


def test_module_has_no_home_assistant_dependency() -> None:
    """The domain module can never grow a Home Assistant import."""
    source = Path(
        "custom_components/growspace_manager/domain/plant_lifecycle.py"
    ).read_text()
    assert "from homeassistant" not in source
    assert "import homeassistant" not in source


def test_small_value_helpers_cover_open_and_unknown_values() -> None:
    """Open durations and Unknown lifetime lookups have explicit neutral values."""
    interval = StageInterval(LifecycleStage.VEG, date(2026, 8, 1))

    assert interval.days is None
    assert LifetimeStageDays(veg=4).for_stage("unknown") == 0


def test_public_date_seams_reject_invalid_values() -> None:
    """Bad caller-supplied dates fail at the public seam, not deep in arithmetic."""
    with pytest.raises(ValueError, match="observed_on"):
        PlantLifecycle.from_data([], observed_on=object())  # type: ignore[arg-type]

    lifecycle = lifecycle_for(("veg", "2026-08-01", None))
    with pytest.raises(ValueError, match="on must"):
        lifecycle.facts(on="not-a-date")


def test_from_history_alias_accepts_datetime_observation() -> None:
    """The explicit parsing alias accepts a datetime and reasons by calendar day."""
    lifecycle = PlantLifecycle.from_history(
        history(("veg", "2026-08-01", None)),
        observed_on=datetime(2026, 8, 22, 14, 30),
    )

    assert lifecycle.current_stage is LifecycleStage.VEG


def test_facts_are_one_consistent_snapshot_with_reveg_lifetime_days() -> None:
    """Facts use one explicit date for stage, age, lifetime totals, and band."""
    lifecycle = lifecycle_for(
        ("seedling", "2026-05-01", "2026-05-08"),
        ("veg", "2026-05-08", "2026-06-01"),
        ("flower", "2026-06-01", "2026-07-15"),
        ("veg", "2026-07-15", "2026-08-01"),
        ("flower", "2026-08-01", None),
    )

    facts = lifecycle.facts(on=TODAY)

    assert facts.current_stage is LifecycleStage.FLOWER
    assert facts.current_stage_age == 21
    assert facts.lifetime_stage_days.as_dict() == {
        "seedling": 7,
        "clone": 0,
        "mother": 0,
        "veg": 41,
        "flower": 65,
        "dry": 0,
        "cure": 0,
    }
    assert facts.cultivation_band.identity is CultivationBandId.MID_FLOWER
    assert facts.warnings == ()


def test_facts_support_a_historical_snapshot() -> None:
    """An earlier explicit date resolves its then-current interval and totals."""
    lifecycle = lifecycle_for(
        ("seedling", "2026-01-01", "2026-01-08"),
        ("veg", "2026-01-08", "2026-02-01"),
        ("flower", "2026-02-01", None),
    )

    facts = lifecycle.facts(on="2026-01-20")

    assert facts.current_stage is LifecycleStage.VEG
    assert facts.current_stage_age == 12
    assert facts.lifetime_stage_days.seedling == 7
    assert facts.lifetime_stage_days.veg == 12
    assert facts.lifetime_stage_days.flower == 0


@pytest.mark.parametrize(
    ("stage", "age", "expected"),
    [
        ("seedling", 0, CultivationBandId.ACCLIMATING_SEEDLING),
        ("seedling", 6, CultivationBandId.ACCLIMATING_SEEDLING),
        ("seedling", 7, CultivationBandId.ESTABLISHED_SEEDLING),
        ("clone", 0, CultivationBandId.ACCLIMATING_CLONE),
        ("clone", 6, CultivationBandId.ACCLIMATING_CLONE),
        ("clone", 7, CultivationBandId.ESTABLISHED_CLONE),
        ("flower", 0, CultivationBandId.EARLY_FLOWER),
        ("flower", 20, CultivationBandId.EARLY_FLOWER),
        ("flower", 21, CultivationBandId.MID_FLOWER),
        ("flower", 41, CultivationBandId.MID_FLOWER),
        ("flower", 42, CultivationBandId.LATE_FLOWER),
        ("flower", 200, CultivationBandId.LATE_FLOWER),
    ],
)
def test_cultivation_band_thresholds(
    stage: str, age: int, expected: CultivationBandId
) -> None:
    """Reported identity changes only on the agreed exact boundary."""
    assert cultivation_band_for(stage, age).identity is expected


def test_adjacent_band_interpolation_does_not_change_identity() -> None:
    """Boundary blending is separate from the stable reported band."""
    early = cultivation_band_for("flower", 20)
    mid = cultivation_band_for("flower", 41)
    seedling = cultivation_band_for("seedling", 6)

    assert early.identity is CultivationBandId.EARLY_FLOWER
    assert early.interpolation is not None
    assert early.interpolation.adjacent_band is CultivationBandId.MID_FLOWER
    assert early.interpolation.factor == 0.67
    assert mid.identity is CultivationBandId.MID_FLOWER
    assert mid.interpolation is not None
    assert mid.interpolation.adjacent_band is CultivationBandId.LATE_FLOWER
    assert seedling.identity is CultivationBandId.ACCLIMATING_SEEDLING
    assert seedling.interpolation is not None
    assert (
        seedling.interpolation.adjacent_band is CultivationBandId.ESTABLISHED_SEEDLING
    )
    assert early.interpolate(10.0, 20.0) == pytest.approx(16.7)
    assert cultivation_band_for("flower", 10).interpolate(10.0, 20.0) == 10.0


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("seedling", "veg"),
        ("clone", "veg"),
        ("veg", "mother"),
        ("veg", "flower"),
        ("mother", "veg"),
        ("mother", "flower"),
        ("flower", "dry"),
        ("flower", "veg"),
        ("dry", "cure"),
    ],
)
def test_every_allowed_graph_edge_is_applied(source: str, target: str) -> None:
    """Every branch in the seed, clone, mother, and reveg graph is reachable."""
    lifecycle = lifecycle_for((source, "2026-08-01", None))

    result = lifecycle.transition(target, "2026-08-20", TODAY)

    assert isinstance(result, Applied)
    assert result.status is DecisionStatus.APPLIED
    assert result.before.current_stage.value == source
    assert result.after.current_stage.value == target
    assert result.lifecycle is not lifecycle
    assert lifecycle.current_stage.value == source
    assert result.after_facts.current_stage.value == target
    assert result.compatibility_data.stage == target
    assert result.repair_event is None


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("seedling", "flower"),
        ("clone", "mother"),
        ("veg", "dry"),
        ("mother", "dry"),
        ("flower", "cure"),
        ("dry", "veg"),
        ("cure", "veg"),
    ],
)
def test_invalid_graph_edges_are_rejected(source: str, target: str) -> None:
    """Invalid skips and Cure exits never alter lifecycle values."""
    lifecycle = lifecycle_for((source, "2026-08-01", None))

    result = lifecycle.transition(target, "2026-08-20", TODAY)

    assert isinstance(result, Rejected)
    assert result.status is DecisionStatus.REJECTED
    assert result.lifecycle is lifecycle
    assert result.before == result.after
    assert "not allowed" in (result.reason or "")


def test_same_stage_request_is_no_change_and_immutable() -> None:
    """A same-stage request produces an explicit NoChange proposal."""
    lifecycle = lifecycle_for(("veg", "2026-08-01", None))

    result = lifecycle.transition("veg", "2026-08-20", TODAY)

    assert isinstance(result, NoChange)
    assert result.status is DecisionStatus.NO_CHANGE
    assert result.lifecycle is lifecycle
    assert result.before == result.after
    with pytest.raises(FrozenInstanceError):
        result.reason = "changed"  # type: ignore[misc]


def test_future_transition_is_rejected_even_when_same_stage() -> None:
    """The no-future rule is checked before same-stage idempotence."""
    lifecycle = lifecycle_for(("veg", "2026-08-01", None))

    result = lifecycle.transition("veg", "2026-08-23", TODAY)

    assert isinstance(result, Rejected)
    assert "Future-dated" in (result.reason or "")


@pytest.mark.parametrize(
    ("target", "effective", "observed", "reason"),
    [
        ("flower", "bad", TODAY, "valid dates"),
        ("flower", TODAY, "bad", "valid dates"),
        ("mystery", TODAY, TODAY, "Unknown target stage"),
    ],
)
def test_transition_rejects_invalid_request_vocabulary(
    target: str,
    effective: str | date,
    observed: str | date,
    reason: str,
) -> None:
    """Invalid explicit dates and target stages return Rejected proposals."""
    lifecycle = lifecycle_for(("veg", "2026-08-01", None))

    result = lifecycle.transition(target, effective, observed)

    assert isinstance(result, Rejected)
    assert reason in (result.reason or "")


def test_backdated_transition_at_open_start_creates_zero_day_interval() -> None:
    """The inclusive lower bound deliberately permits a zero-day close."""
    lifecycle = lifecycle_for(("veg", "2026-08-10", None))

    result = lifecycle.transition("flower", "2026-08-10", TODAY)

    assert isinstance(result, Applied)
    assert result.after.stage_history[0].days == 0
    assert result.after.stage_history[1].started_on == date(2026, 8, 10)
    assert result.after_facts.current_stage_age == 12


def test_backdated_transition_before_open_start_is_rejected() -> None:
    """A backdate cannot rewrite already-closed history."""
    lifecycle = lifecycle_for(("veg", "2026-08-10", None))

    result = lifecycle.transition("flower", "2026-08-09", TODAY)

    assert isinstance(result, Rejected)
    assert "predate" in (result.reason or "")


def test_compatibility_data_uses_latest_start_for_revisited_stage() -> None:
    """Legacy start fields mirror the most recent transition into each stage."""
    lifecycle = lifecycle_for(
        ("veg", "2026-01-01", "2026-02-01"),
        ("flower", "2026-02-01", "2026-03-01"),
        ("veg", "2026-03-01", None),
    )

    data = lifecycle.compatibility_data.as_dict()

    assert data["stage"] == "veg"
    assert data["veg_start"] == "2026-03-01"
    assert data["flower_start"] == "2026-02-01"
    assert data["stage_history"][0] == {
        "stage": "veg",
        "start": "2026-01-01",
        "end": "2026-02-01",
    }


def test_absent_history_reconstructs_once_from_legacy_dates() -> None:
    """Only an absent history activates sorted legacy reconstruction."""
    lifecycle = PlantLifecycle.from_data(
        None,
        observed_on=TODAY,
        current_stage="flower",
        legacy_dates={
            "flower_start": "2026-08-01T12:30:00+02:00",
            "seedling_start": "2026-06-01T08:00:00+02:00",
            "veg_start": "2026-06-08T08:00:00+02:00",
        },
    )

    assert lifecycle.history.reconstructed_from_legacy is True
    assert lifecycle.history.is_valid is True
    assert [item.stage.value for item in lifecycle.history.intervals] == [
        "seedling",
        "veg",
        "flower",
    ]
    assert lifecycle.current_stage is LifecycleStage.FLOWER
    assert lifecycle.compatibility_data.flower_start == "2026-08-01"


def test_present_empty_history_never_falls_back_to_legacy_dates() -> None:
    """Present bad history becomes Unknown instead of hiding damage."""
    lifecycle = PlantLifecycle.from_data(
        [],
        observed_on=TODAY,
        current_stage="veg",
        legacy_dates={"veg_start": "2026-08-01"},
    )

    assert lifecycle.current_stage is LifecycleStage.UNKNOWN
    assert lifecycle.history.reconstructed_from_legacy is False
    assert lifecycle.warnings[0].code is RepairWarningCode.EMPTY_HISTORY
    assert lifecycle.compatibility_data.stage == "unknown"
    assert lifecycle.compatibility_data.stage_history == ()


def test_malformed_non_mapping_and_unknown_interval_fail_closed() -> None:
    """The untrusted storage seam diagnoses arbitrary objects and Unknown values."""
    malformed = PlantLifecycle.from_data([42], observed_on=TODAY)
    unknown = PlantLifecycle.from_data(
        [StageInterval(LifecycleStage.UNKNOWN, date(2026, 8, 1))],
        observed_on=TODAY,
    )

    assert malformed.warnings[0].code is RepairWarningCode.MALFORMED_ITEM
    assert unknown.warnings[0].code is RepairWarningCode.UNKNOWN_STAGE


def test_closed_only_history_and_invalid_legacy_date_fail_closed() -> None:
    """A current open interval and parseable legacy dates are both mandatory."""
    closed = lifecycle_for(("veg", "2026-08-01", "2026-08-10"))
    legacy = PlantLifecycle.from_data(
        None,
        observed_on=TODAY,
        legacy_dates={"veg_start": "not-a-date"},
    )

    assert closed.warnings[0].code is RepairWarningCode.NO_OPEN_INTERVAL
    assert legacy.history.reconstructed_from_legacy
    assert legacy.warnings[0].code is RepairWarningCode.INVALID_DATE


def test_snapshot_before_first_interval_is_unknown() -> None:
    """Facts never invent a stage for a date not covered by Stage History."""
    lifecycle = lifecycle_for(("veg", "2026-08-01", None))

    facts = lifecycle.facts(on="2026-07-31")

    assert facts.current_stage is LifecycleStage.UNKNOWN
    assert facts.warnings[-1].code is RepairWarningCode.FUTURE_DATE


@pytest.mark.parametrize(
    ("items", "expected"),
    [
        (
            [("mystery", "2026-08-01", None)],
            RepairWarningCode.UNKNOWN_STAGE,
        ),
        (
            [("veg", "not-a-date", None)],
            RepairWarningCode.INVALID_DATE,
        ),
        (
            [("veg", "2026-08-23", None)],
            RepairWarningCode.FUTURE_DATE,
        ),
        (
            [
                ("veg", "2026-08-10", "2026-08-20"),
                ("flower", "2026-08-01", None),
            ],
            RepairWarningCode.NONCHRONOLOGICAL,
        ),
        (
            [
                ("veg", "2026-08-01", "2026-08-20"),
                ("flower", "2026-08-10", None),
            ],
            RepairWarningCode.OVERLAPPING_INTERVALS,
        ),
        (
            [
                ("veg", "2026-08-01", None),
                ("flower", "2026-08-10", None),
            ],
            RepairWarningCode.OPEN_INTERVAL_NOT_LAST,
        ),
        (
            [
                ("seedling", "2026-08-01", "2026-08-10"),
                ("flower", "2026-08-10", None),
            ],
            RepairWarningCode.GRAPH_INVALID,
        ),
        (
            [("veg", "2026-08-10", "2026-08-01")],
            RepairWarningCode.NEGATIVE_INTERVAL,
        ),
    ],
)
def test_malformed_history_produces_unknown_with_repair_warning(
    items: list[tuple[str, str, str | None]], expected: RepairWarningCode
) -> None:
    """Every specified corruption class fails closed as Unknown Stage."""
    lifecycle = PlantLifecycle.from_data(
        history(*items),
        observed_on=TODAY,
        legacy_dates={"veg_start": "2026-08-01"},
    )

    assert lifecycle.current_stage is LifecycleStage.UNKNOWN
    assert expected in {warning.code for warning in lifecycle.warnings}
    facts = lifecycle.facts(on=TODAY)
    assert facts.current_stage is LifecycleStage.UNKNOWN
    assert facts.current_stage_age is None
    assert facts.lifetime_stage_days.as_dict() == dict.fromkeys(
        ("seedling", "clone", "mother", "veg", "flower", "dry", "cure"), 0
    )
    assert isinstance(lifecycle.transition("flower", TODAY, TODAY), Rejected)


def test_current_stage_mismatch_is_unknown() -> None:
    """A present history that disagrees with the shadow stage needs repair."""
    lifecycle = PlantLifecycle.from_data(
        history(("veg", "2026-08-01", None)),
        observed_on=TODAY,
        current_stage="flower",
    )

    assert lifecycle.current_stage is LifecycleStage.UNKNOWN
    assert lifecycle.warnings[0].code is RepairWarningCode.CURRENT_STAGE_MISMATCH


def test_repair_preserves_trustworthy_prefix_and_discards_ambiguous_tail() -> None:
    """Correction retains closed good history and replaces damaged current data."""
    lifecycle = PlantLifecycle.from_data(
        history(
            ("seedling", "2026-05-01", "2026-05-08"),
            ("veg", "2026-05-08", "2026-07-01"),
            ("flower", "2026-06-20", None),
        ),
        observed_on=TODAY,
    )
    assert lifecycle.current_stage is LifecycleStage.UNKNOWN

    correction = lifecycle.repair_current(
        "flower",
        started_on="2026-07-01",
        corrected_on=TODAY,
        reason="Grower confirmed flip date",
    )

    assert correction.before.current_stage is LifecycleStage.UNKNOWN
    assert correction.after.current_stage is LifecycleStage.FLOWER
    assert [item.stage.value for item in correction.after.stage_history] == [
        "seedling",
        "veg",
        "flower",
    ]
    assert correction.after_facts.current_stage_age == 52
    assert correction.compatibility_data.stage == "flower"
    assert correction.compatibility_data.flower_start == "2026-07-01"
    assert correction.repair_event.reason == "Grower confirmed flip date"
    assert correction.repair_event.previous_stage is LifecycleStage.UNKNOWN
    assert correction.repair_event.discarded_interval_count == 1
    assert RepairWarningCode.OVERLAPPING_INTERVALS in (
        correction.repair_event.warning_codes
    )
    assert correction.lifecycle.warnings == ()


def test_repair_discards_incompatible_prefix_until_graph_is_valid() -> None:
    """The corrected history remains graph-valid even after a radical correction."""
    lifecycle = lifecycle_for(
        ("seedling", "2026-06-01", "2026-06-08"),
        ("veg", "2026-06-08", None),
    )

    correction = lifecycle.repair_current(
        "clone", "2026-08-01", TODAY, "Plant was misidentified"
    )

    assert correction.after.stage_history == (correction.after.stage_history[-1],)
    assert correction.after.current_stage is LifecycleStage.CLONE
    assert correction.lifecycle.history.is_valid


@pytest.mark.parametrize(
    ("stage", "start", "corrected", "reason", "message"),
    [
        ("mystery", "2026-08-01", TODAY, "reason", "Unknown current stage"),
        ("veg", "bad", TODAY, "reason", "valid dates"),
        ("veg", "2026-08-23", TODAY, "reason", "cannot be after"),
        ("veg", "2026-08-01", TODAY, "   ", "must not be empty"),
    ],
)
def test_repair_rejects_invalid_correction_inputs(
    stage: str,
    start: str,
    corrected: date,
    reason: str,
    message: str,
) -> None:
    """Corrections must themselves be authoritative, dated, and explained."""
    lifecycle = lifecycle_for(("veg", "2026-07-01", None))

    with pytest.raises(ValueError, match=message):
        lifecycle.repair_current(stage, start, corrected, reason)


def test_reschedule_moves_several_boundaries_and_retains_the_rest() -> None:
    """A multi-date correction rewrites only the stages the grower named."""
    lifecycle = lifecycle_for(
        ("seedling", "2026-05-01", "2026-05-08"),
        ("veg", "2026-05-08", "2026-07-01"),
        ("flower", "2026-07-01", None),
    )

    correction = lifecycle.reschedule(
        {"veg": "2026-05-06", "flower": "2026-06-28"},
        TODAY,
        "Grower corrected both flip dates",
    )

    assert [
        (item.stage.value, item.started_on.isoformat(), item.ended_on)
        for item in correction.after.stage_history
    ] == [
        ("seedling", "2026-05-01", date(2026, 5, 6)),
        ("veg", "2026-05-06", date(2026, 6, 28)),
        ("flower", "2026-06-28", None),
    ]
    assert correction.after.current_stage is LifecycleStage.FLOWER
    assert correction.compatibility_data.seedling_start == "2026-05-01"
    assert correction.compatibility_data.veg_start == "2026-05-06"
    assert correction.compatibility_data.flower_start == "2026-06-28"
    assert correction.lifecycle.history.is_valid
    assert correction.repair_event.discarded_interval_count == 0
    assert correction.repair_event.corrected_starts == (
        (LifecycleStage.VEG, date(2026, 5, 6)),
        (LifecycleStage.FLOWER, date(2026, 6, 28)),
    )


def test_reschedule_inserts_a_stage_the_plant_has_never_been_in() -> None:
    """A date for an unrecorded stage joins the history where it belongs."""
    lifecycle = lifecycle_for(("veg", "2026-06-01", None))

    correction = lifecycle.reschedule(
        {"seedling": "2026-05-20", "veg": "2026-05-28"},
        TODAY,
        "Grower recorded the seedling start",
    )

    assert [item.stage.value for item in correction.after.stage_history] == [
        "seedling",
        "veg",
    ]
    assert correction.after.current_stage is LifecycleStage.VEG
    assert correction.after.current_stage_started_on == date(2026, 5, 28)


def test_reschedule_can_advance_the_current_stage() -> None:
    """The latest supplied start owns the open interval once boundaries move."""
    lifecycle = lifecycle_for(("veg", "2026-06-01", None))

    correction = lifecycle.reschedule(
        {"veg": "2026-05-28", "flower": "2026-07-10"},
        TODAY,
        "Grower recorded the flip",
    )

    assert correction.before.current_stage is LifecycleStage.VEG
    assert correction.after.current_stage is LifecycleStage.FLOWER
    assert correction.repair_event.previous_stage is LifecycleStage.VEG
    assert correction.repair_event.corrected_stage is LifecycleStage.FLOWER


def test_reschedule_retargets_only_the_latest_interval_of_a_stage() -> None:
    """After a Reveg, ``veg_start`` names the newer veg interval, not the first."""
    lifecycle = lifecycle_for(
        ("veg", "2026-04-01", "2026-05-01"),
        ("flower", "2026-05-01", "2026-06-01"),
        ("veg", "2026-06-01", None),
    )

    correction = lifecycle.reschedule(
        {"flower": "2026-05-04", "veg": "2026-06-05"},
        TODAY,
        "Grower corrected the reveg",
    )

    assert [
        (item.stage.value, item.started_on.isoformat())
        for item in correction.after.stage_history
    ] == [("veg", "2026-04-01"), ("flower", "2026-05-04"), ("veg", "2026-06-05")]


def test_reschedule_rebuilds_untrustworthy_history_from_the_supplied_starts() -> None:
    """History the parser cannot trust is rebuilt, and the loss is counted."""
    lifecycle = lifecycle_for(
        ("veg", "2026-05-08", "2026-07-01"),
        ("flower", "2026-06-20", None),
    )
    assert lifecycle.current_stage is LifecycleStage.UNKNOWN

    correction = lifecycle.reschedule(
        {"veg": "2026-05-08", "flower": "2026-07-01"},
        TODAY,
        "Grower re-entered both dates",
    )

    assert correction.lifecycle.history.is_valid
    assert correction.after.current_stage is LifecycleStage.FLOWER
    assert correction.repair_event.discarded_interval_count == 1
    assert RepairWarningCode.OVERLAPPING_INTERVALS in (
        correction.repair_event.warning_codes
    )


@pytest.mark.parametrize(
    ("starts", "message"),
    [
        (
            {"veg": "2026-07-05", "flower": "2026-07-01"},
            "veg start 2026-07-05 is after flower start 2026-07-01",
        ),
        (
            {"veg": "2026-05-08", "flower": "2026-09-01"},
            "flower start 2026-09-01 is in the future",
        ),
        (
            {"veg": "2026-05-08", "cure": "2026-07-10"},
            "Stage order flower->cure is not allowed",
        ),
        ({"veg": "2026-05-08", "mystery": "2026-07-01"}, "Unknown stage"),
        ({"veg": "2026-05-08", "flower": "not-a-date"}, "not a valid date"),
        ({}, "must supply a stage start"),
    ],
)
def test_reschedule_refuses_a_contradictory_set_by_name(
    starts: dict[str, str], message: str
) -> None:
    """Every refusal names the stages that conflict, never a single-stage rule."""
    lifecycle = lifecycle_for(
        ("seedling", "2026-05-01", "2026-05-08"),
        ("veg", "2026-05-08", "2026-07-01"),
        ("flower", "2026-07-01", None),
    )

    with pytest.raises(ValueError, match=message):
        lifecycle.reschedule(starts, TODAY, "Grower corrected the dates")


def test_reschedule_refuses_a_retained_interval_dated_after_the_correction() -> None:
    """The rebuilt history is re-validated, so a retained future start refuses too."""
    lifecycle = lifecycle_for(
        ("veg", "2026-08-01", "2026-08-10"),
        ("flower", "2026-08-10", None),
    )

    with pytest.raises(ValueError, match="future date"):
        lifecycle.reschedule(
            {"veg": "2026-07-01"},
            date(2026, 8, 5),
            "Grower corrected the veg start",
        )


@pytest.mark.parametrize(
    ("corrected_on", "message"),
    [("not-a-date", "corrected_on must be a valid date"), (None, "valid date")],
)
def test_reschedule_requires_a_correction_date(
    corrected_on: str | None, message: str
) -> None:
    """A reschedule is dated, like every other correction."""
    lifecycle = lifecycle_for(("veg", "2026-07-01", None))

    with pytest.raises(ValueError, match=message):
        lifecycle.reschedule({"veg": "2026-06-01"}, corrected_on, "Grower corrected it")


def test_reschedule_requires_a_reason() -> None:
    """A correction stays explainable however many boundaries it moves."""
    lifecycle = lifecycle_for(("veg", "2026-07-01", None))

    with pytest.raises(ValueError, match="must not be empty"):
        lifecycle.reschedule({"veg": "2026-06-01"}, TODAY, "   ")


def test_unknown_and_negative_age_have_unknown_cultivation_band() -> None:
    """Band classification has an explicit fail-closed identity."""
    assert cultivation_band_for("unknown", 1).identity is CultivationBandId.UNKNOWN
    assert cultivation_band_for("veg", -1).identity is CultivationBandId.UNKNOWN
