"""The Calibration Proposal's ratio and unit guard (ADR-0064 item 7, #890)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest

from custom_components.growspace_manager.domain.calibration_proposal import (
    UNIT_MIX_UPS,
    CalibrationProposal,
    tank_evidence_applies,
    tank_ratios,
    tank_sourced_proposal,
    unit_mix_up,
)
from custom_components.growspace_manager.domain.tank_pump_disagreement import (
    DayComparison,
    DayVerdict,
    TankPumpDisagreement,
)

TODAY = date(2026, 9, 29)
TANK = "sensor.reservoir"


def _day(
    offset: int,
    verdict: DayVerdict = DayVerdict.DISAGREES,
    *,
    tank: float = 12.0,
    hand: float = 0.0,
    pump: float = 8.0,
) -> DayComparison:
    return DayComparison(TODAY - timedelta(days=offset), verdict, tank, hand, pump)


def _raised(*days: DayComparison) -> TankPumpDisagreement:
    return TankPumpDisagreement(
        tanks=(TANK,),
        flow_rate_ml_per_sec=10.0,
        first_day=TODAY - timedelta(days=10),
        raised_on=TODAY - timedelta(days=1),
        days=days,
    )


def _propose(
    record: TankPumpDisagreement,
    *,
    rate: float = 10.0,
    zones: int = 1,
    zone_metered: bool = False,
) -> CalibrationProposal | None:
    return tank_sourced_proposal(
        record, configured_ml_per_sec=rate, zones=zones, zone_metered=zone_metered
    )


# ── The ratio ──────────────────────────────────────────────────────────────


def test_the_ratio_is_tank_drop_over_pump_figure_on_disagreeing_days() -> None:
    """Agreeing and uncounted days are not evidence of a wrong rate."""
    days = [
        _day(5, tank=12.0, pump=8.0),
        _day(4, DayVerdict.AGREES, tank=8.0, pump=8.0),
        _day(3, DayVerdict.NO_ATTEMPT, tank=3.0, pump=0.0),
        _day(2, DayVerdict.TANK_UNKNOWN, tank=30.0, pump=8.0),
        _day(1, tank=6.0, pump=10.0),
    ]

    assert tank_ratios(days) == [1.5, 0.6]


def test_the_ratio_is_net_of_hand_watering_from_the_tank() -> None:
    """Water carried out in a jug did not go through the pump."""
    assert tank_ratios([_day(1, tank=14.0, hand=2.0, pump=8.0)]) == [1.5]


@pytest.mark.parametrize(
    "day",
    [
        pytest.param(_day(1, tank=0.0, pump=8.0), id="the tank did not move"),
        pytest.param(_day(1, tank=3.0, hand=5.0, pump=8.0), id="all of it by hand"),
        pytest.param(_day(1, tank=8.0, pump=0.0), id="the pump delivered nothing"),
    ],
)
def test_a_day_with_nothing_on_one_side_is_not_evidence(day: DayComparison) -> None:
    """A zero on either side is not a rate off by some factor."""
    assert tank_ratios([day]) == []


# ── The unit guard ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("ratio", "factor"),
    [
        (3.785, 3.785),
        (3.6, 3.785),
        (3.97, 3.785),
        (0.264, 0.264),
        (0.251, 0.264),
        (0.277, 0.264),
        (1000.0, 1000.0),
        (951.0, 1000.0),
        (1049.0, 1000.0),
        (0.001, 0.001),
        (0.00096, 0.001),
        (0.00104, 0.001),
    ],
)
def test_a_ratio_within_five_percent_of_a_mix_up_is_one(
    ratio: float, factor: float
) -> None:
    """Each common mix-up, at its factor and at either edge of the 5%."""
    mix_up = unit_mix_up(ratio)

    assert mix_up is not None
    assert mix_up.factor == factor


@pytest.mark.parametrize("ratio", [1.0, 1.5, 3.59, 3.98, 0.25, 0.28, 940.0, 0.0011])
def test_a_ratio_outside_every_mix_up_is_a_rate(ratio: float) -> None:
    """Just beyond 5% of a factor, and any ordinary correction, pass."""
    assert unit_mix_up(ratio) is None


def test_every_mix_up_names_its_units() -> None:
    """The issue says which units the grower should look at."""
    assert [(mix_up.factor, mix_up.units) for mix_up in UNIT_MIX_UPS] == [
        (3.785, "gallons and litres"),
        (0.264, "gallons and litres"),
        (1000.0, "litres and cubic metres or millilitres"),
        (0.001, "litres and cubic metres or millilitres"),
    ]


# ── Whether the tank may speak for the zone ────────────────────────────────


@pytest.mark.parametrize(
    ("zones", "zone_metered", "applies"),
    [
        (1, False, True),
        (1, True, False),
        (2, False, False),
        (0, False, False),
    ],
)
def test_the_tank_speaks_only_for_one_unmetered_zone(
    zones: int, zone_metered: bool, applies: bool
) -> None:
    """Two zones cannot be told apart, and a meter outranks the tank."""
    assert tank_evidence_applies(zones=zones, zone_metered=zone_metered) is applies


# ── The proposal ───────────────────────────────────────────────────────────


def test_a_raised_disagreement_proposes_the_rate_times_the_median() -> None:
    """Three disagreeing days: the median ratio, not the mean, corrects it."""
    record = _raised(
        _day(3, tank=12.0, pump=8.0),
        _day(2, tank=16.0, pump=8.0),
        _day(1, tank=10.0, pump=8.0),
    )

    proposal = _propose(record, rate=10.0)

    assert proposal == CalibrationProposal(
        configured_ml_per_sec=10.0,
        median_ratio=1.5,
        evidence_count=3,
        entities=(TANK,),
    )
    assert proposal.proposed_ml_per_sec == 15.0
    assert proposal.applicable
    assert proposal.mix_up is None


def test_the_proposed_rate_is_rounded_to_hundredths() -> None:
    """A rate the grower can read back, not a float artefact."""
    proposal = _propose(_raised(_day(1, tank=10.0, pump=3.0)), rate=7.0)

    assert proposal is not None
    assert proposal.proposed_ml_per_sec == 23.33


def test_a_ratio_like_a_unit_mix_up_offers_no_apply() -> None:
    """Litres read as gallons would rescale every shot by almost four."""
    proposal = _propose(_raised(_day(2, tank=30.3, pump=8.0), _day(1, tank=30.2)))

    assert proposal is not None
    assert proposal.mix_up is not None
    assert proposal.mix_up.factor == 3.785
    assert not proposal.applicable
    assert proposal.entities == (TANK,)


@pytest.mark.parametrize(
    ("record", "rate", "zones", "zone_metered"),
    [
        pytest.param(
            replace(_raised(_day(1)), raised_on=None), 10.0, 1, False, id="not raised"
        ),
        pytest.param(_raised(_day(1)), 10.0, 2, False, id="two zones"),
        pytest.param(_raised(_day(1)), 10.0, 1, True, id="a metered zone"),
        pytest.param(_raised(_day(1)), 0.0, 1, False, id="no rate configured"),
        pytest.param(
            _raised(_day(1, DayVerdict.AGREES)), 10.0, 1, False, id="no disagreeing day"
        ),
        pytest.param(
            _raised(_day(1, tank=0.0, pump=8.0)), 10.0, 1, False, id="no water in it"
        ),
        pytest.param(
            _raised(_day(1, tank=1.001, pump=8000.0)),
            0.01,
            1,
            False,
            id="a rate that rounds to nothing",
        ),
    ],
)
def test_nothing_is_proposed_without_evidence_for_this_zone(
    record: TankPumpDisagreement, rate: float, zones: int, zone_metered: bool
) -> None:
    """Every refusal leaves the growspace with no proposal at all."""
    assert _propose(record, rate=rate, zones=zones, zone_metered=zone_metered) is None
