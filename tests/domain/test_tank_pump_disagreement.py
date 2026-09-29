"""The Tank–Pump Disagreement, the calibration signal ADR-0054 asked for (ADR-0064 item 9)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from custom_components.growspace_manager.domain.delivery_attempt import (
    AttemptTrigger,
    DeliveryAttempt,
)
from custom_components.growspace_manager.domain.tank_pump_disagreement import (
    DAYS_KEPT,
    DayComparison,
    DayVerdict,
    DisagreementState,
    TankPumpDisagreement,
    Transition,
    compare_day,
    disagrees,
    hand_watered_from_tank_l,
    pump_delivered_l,
    qualifying_tanks,
    tank_consumed_l,
)
from custom_components.growspace_manager.models import IrrigationTank

TODAY = date(2026, 9, 29)
TANK = "sensor.tank"


def _day(offset: int) -> date:
    """Return the day ``offset`` days before today."""
    return TODAY - timedelta(days=offset)


def _judged(day: date, verdict: DayVerdict) -> DayComparison:
    return DayComparison(day, verdict, 10.0, 0.0, 5.0)


def _watching() -> TankPumpDisagreement:
    record, _ = TankPumpDisagreement().watching([TANK], _day(10))
    return record


def _run(
    record: TankPumpDisagreement, *verdicts: DayVerdict
) -> tuple[TankPumpDisagreement, list[Transition | None]]:
    """Judge one day per verdict, the oldest first, ending yesterday."""
    transitions: list[Transition | None] = []
    for offset, verdict in zip(range(len(verdicts), 0, -1), verdicts, strict=True):
        record, transition = record.judged(_judged(_day(offset), verdict))
        transitions.append(transition)
    return record, transitions


AGREES, DISAGREES = DayVerdict.AGREES, DayVerdict.DISAGREES
NO_ATTEMPT, TANK_UNKNOWN = DayVerdict.NO_ATTEMPT, DayVerdict.TANK_UNKNOWN


# ── The threshold ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("tank_l", "pump_l", "expected"),
    [
        # Exactly 25% of the larger figure is not more than 25%.
        (8.0, 6.0, False),
        (8.0, 5.99, True),
        # The same edge with the pump the larger figure.
        (6.0, 8.0, False),
        (5.99, 8.0, True),
        # More than 25% but exactly 1 L apart is not more than 1 L.
        (3.0, 2.0, False),
        (3.01, 2.0, True),
        (2.0, 3.01, True),
        # Tiny tents: a large share of nothing is still inside the floor.
        (0.9, 0.0, False),
        (0.0, 0.0, False),
        (10.0, 10.0, False),
    ],
)
def test_a_day_disagrees_past_a_quarter_of_the_larger_figure_and_a_litre(
    tank_l: float, pump_l: float, expected: bool
) -> None:
    """Both conditions must hold, and each is strict."""
    assert disagrees(tank_l, pump_l) is expected


def test_hand_watering_from_the_tank_is_taken_off_the_drop() -> None:
    """The jug left through the tank, not the pump."""
    comparison = compare_day(
        _day(1),
        tank_drop_l=12.0,
        hand_watering_l=4.0,
        pump_l=8.0,
        actuated=True,
        tank_unknown=False,
    )

    assert comparison.verdict is DayVerdict.AGREES
    assert comparison.tank_l == 8.0


def test_a_hand_report_larger_than_the_drop_leaves_nothing_for_the_pump() -> None:
    """The pump is then compared against no tank water at all."""
    comparison = compare_day(
        _day(1),
        tank_drop_l=2.0,
        hand_watering_l=5.0,
        pump_l=3.0,
        actuated=True,
        tank_unknown=False,
    )

    assert comparison.tank_l == 0.0
    assert comparison.verdict is DayVerdict.DISAGREES


@pytest.mark.parametrize(
    ("actuated", "tank_unknown", "expected"),
    [
        (False, False, DayVerdict.NO_ATTEMPT),
        (False, True, DayVerdict.NO_ATTEMPT),
        (True, True, DayVerdict.TANK_UNKNOWN),
        (True, False, DayVerdict.DISAGREES),
    ],
)
def test_a_day_without_an_attempt_or_with_an_unknown_tank_is_not_judged(
    actuated: bool, tank_unknown: bool, expected: DayVerdict
) -> None:
    """Either one makes the day count neither way, however far apart it looks."""
    comparison = compare_day(
        _day(1),
        tank_drop_l=20.0,
        hand_watering_l=0.0,
        pump_l=0.0 if not actuated else 5.0,
        actuated=actuated,
        tank_unknown=tank_unknown,
    )

    assert comparison.verdict is expected
    assert comparison.counts is (expected is DayVerdict.DISAGREES)


def test_the_figures_are_kept_to_the_centilitre() -> None:
    """What is shown and stored is rounded; the verdict is not."""
    comparison = compare_day(
        _day(1),
        tank_drop_l=4.004,
        hand_watering_l=0.0,
        pump_l=3.0,
        actuated=True,
        tank_unknown=False,
    )

    assert comparison.tank_drop_l == 4.0
    assert comparison.verdict is DayVerdict.DISAGREES


# ── Persistence: raised after two, cleared after two ───────────────────────


def test_two_disagreeing_days_raise_the_signal() -> None:
    """The first disagreeing day is only a streak; the second raises."""
    record, transitions = _run(_watching(), DISAGREES, DISAGREES)

    assert transitions == [None, Transition.RAISED]
    assert record.state is DisagreementState.RAISED
    assert record.raised_on == _day(1)
    assert record.streak == 0


def test_an_agreeing_day_breaks_the_run_toward_raising() -> None:
    """Consecutive means consecutive among the days that count."""
    record, transitions = _run(_watching(), DISAGREES, AGREES, DISAGREES)

    assert transitions == [None, None, None]
    assert record.state is DisagreementState.CLEAR
    assert record.streak == 1


@pytest.mark.parametrize("skipped", [NO_ATTEMPT, TANK_UNKNOWN])
def test_a_skipped_day_neither_advances_nor_breaks_a_run(skipped: DayVerdict) -> None:
    """A day off between two disagreeing days still raises on the second."""
    record, transitions = _run(_watching(), DISAGREES, skipped, skipped, DISAGREES)

    assert transitions == [None, None, None, Transition.RAISED]
    assert record.state is DisagreementState.RAISED


def test_two_agreeing_days_clear_the_signal() -> None:
    """Once raised, it takes two agreeing days to clear it."""
    raised, _ = _run(_watching(), DISAGREES, DISAGREES)

    record, transitions = _run(raised, AGREES, AGREES)

    assert transitions == [None, Transition.CLEARED]
    assert record.state is DisagreementState.CLEAR
    assert record.raised_on is None
    assert record.streak == 0


def test_a_disagreeing_day_breaks_the_run_toward_clearing() -> None:
    """Raised, an agreeing day followed by a disagreeing one clears nothing."""
    raised, _ = _run(_watching(), DISAGREES, DISAGREES)

    record, transitions = _run(raised, AGREES, DISAGREES, AGREES, NO_ATTEMPT)

    assert transitions == [None, None, None, None]
    assert record.state is DisagreementState.RAISED
    assert record.streak == 1


def test_only_the_last_days_are_kept() -> None:
    """The view shows the last days, as many as a missed evaluation reaches."""
    record, _ = _run(_watching(), *[AGREES] * (DAYS_KEPT + 3))

    assert len(record.days) == DAYS_KEPT
    assert record.days[-1].day == _day(1)
    assert record.evaluated_through == _day(1)


# ── Which tanks, and which days ────────────────────────────────────────────


def test_no_measured_tank_means_nothing_to_compare() -> None:
    """A growspace without a tank in litres has no Tank–Pump Disagreement."""
    record, transition = TankPumpDisagreement().watching([], TODAY)

    assert transition is None
    assert record.state is DisagreementState.NO_TANK
    assert record.due_days(TODAY) == []
    assert record.tank_unknown_on(TODAY) is record


def test_a_new_tank_is_compared_from_the_next_whole_day() -> None:
    """The day it was added holds only part of that day's drop."""
    record, transition = TankPumpDisagreement().watching([TANK], TODAY)

    assert transition is None
    assert record.state is DisagreementState.CLEAR
    assert record.first_day == TODAY + timedelta(days=1)
    assert record.due_days(TODAY) == []
    assert record.due_days(TODAY + timedelta(days=1)) == []
    assert record.due_days(TODAY + timedelta(days=2)) == [TODAY + timedelta(days=1)]


def test_the_same_tanks_in_any_order_keep_the_evidence() -> None:
    """Watching the set already watched changes nothing."""
    record, _ = TankPumpDisagreement().watching(["sensor.b", "sensor.a"], TODAY)

    again, transition = record.watching(["sensor.a", "sensor.b", "sensor.a"], TODAY)

    assert again is record
    assert transition is None


def test_changed_tanks_start_the_comparison_again() -> None:
    """A raised signal about the old tanks is reported restarted, not dropped."""
    raised, _ = _run(_watching(), DISAGREES, DISAGREES)

    record, transition = raised.watching([TANK, "sensor.second"], TODAY)

    assert transition is Transition.RESTARTED
    assert record.state is DisagreementState.CLEAR
    assert record.days == ()
    assert record.first_day == TODAY + timedelta(days=1)


def test_changed_tanks_under_a_clear_signal_restart_quietly() -> None:
    """Nothing was raised, so there is nothing to report."""
    _, transition = _watching().watching([], TODAY)

    assert transition is None


def test_yesterday_is_due_once() -> None:
    """After it is judged, nothing is due until the next midnight."""
    record = _watching()

    assert record.due_days(TODAY)[-1] == _day(1)
    judged, _ = record.judged(_judged(_day(1), AGREES))
    assert judged.due_days(TODAY) == []


def test_missed_days_are_caught_up_as_far_as_the_attempts_reach() -> None:
    """A restart after a long sleep judges only days whose attempts are kept."""
    record = replace(_watching(), evaluated_through=_day(9))

    assert record.due_days(TODAY) == [
        _day(offset) for offset in range(DAYS_KEPT, 0, -1)
    ]


def test_an_unknown_tank_is_remembered_until_its_day_is_judged() -> None:
    """Marked once, whatever the tick count, and dropped once judged."""
    record = _watching().tank_unknown_on(_day(1))

    assert record.tank_unknown_on(_day(1)) is record
    assert _day(1) in record.unknown_days
    record = record.tank_unknown_on(TODAY)
    judged, _ = record.judged(_judged(_day(1), TANK_UNKNOWN))
    assert judged.unknown_days == frozenset({TODAY})


def test_qualifying_tanks_are_those_measured_in_litres() -> None:
    """A tank without ``volume_liters`` reads percent, not water."""
    measured = IrrigationTank(sensor_entity="sensor.a", name="A", volume_liters=100.0)
    percent = IrrigationTank(sensor_entity="sensor.b", name="B")

    assert qualifying_tanks([measured, percent]) == [measured]


# ── The two sides ──────────────────────────────────────────────────────────


def _attempt(attempt_id: str, **fields: Any) -> DeliveryAttempt:
    confirmed = datetime(2026, 9, 28, 8, tzinfo=UTC)
    values: dict[str, Any] = {
        "attempt_id": attempt_id,
        "growspace_id": "gs1",
        "output": "switch.pump",
        "trigger": AttemptTrigger.SCHEDULE,
        "planned_s": 60.0,
        "flow_rate_ml_per_sec": 10.0,
        "requested_at": confirmed,
        "on_commanded_at": confirmed,
        "on_confirmed_at": confirmed,
        "charge_date": _day(1),
        "charged_l": 0.6,
        "estimated_l": 0.5,
    }
    values.update(fields)
    return DeliveryAttempt(**values)


def test_the_pump_side_is_the_day_s_actuated_attempts() -> None:
    """Drains, other days and unconfirmed requests are not delivered water."""
    attempts = [
        _attempt("shot"),
        _attempt("aborted", estimated_l=0.25),
        _attempt("still_open", estimated_l=None),
        _attempt("other_day", charge_date=_day(2)),
        _attempt(
            "drain",
            trigger=AttemptTrigger.DRAIN,
            charge_date=None,
            charged_l=0.0,
            estimated_l=None,
        ),
        _attempt(
            "never_on",
            on_confirmed_at=None,
            charge_date=None,
            charged_l=0.0,
            estimated_l=None,
        ),
    ]

    assert pump_delivered_l(attempts, _day(1)) == (0.75, True)


def test_a_day_of_drains_alone_is_a_day_without_an_attempt() -> None:
    """A drain moves water out of the pots and never counts."""
    drain = _attempt(
        "drain",
        trigger=AttemptTrigger.DRAIN,
        charge_date=None,
        charged_l=0.0,
        estimated_l=None,
    )

    assert pump_delivered_l([drain], _day(1)) == (0.0, False)


def test_the_tank_side_is_the_local_day_s_consumption() -> None:
    """Events are dated in the local zone; refills and malformed ones are left out."""
    zone = ZoneInfo("America/Los_Angeles")
    day = date(2026, 9, 28)
    events = [
        # 00:30 local on the day, 07:30 UTC.
        {
            "timestamp": "2026-09-28T07:30:00+00:00",
            "event_type": "consumption",
            "liters": 2.0,
        },
        # 23:30 local on the day, 06:30 UTC the next.
        {
            "timestamp": "2026-09-29T06:30:00+00:00",
            "event_type": "consumption",
            "liters": 1.5,
        },
        # 00:30 local the next day.
        {
            "timestamp": "2026-09-29T07:30:00+00:00",
            "event_type": "consumption",
            "liters": 9.0,
        },
        # 23:30 local the day before, although it is the day in UTC.
        {
            "timestamp": "2026-09-28T06:30:00+00:00",
            "event_type": "consumption",
            "liters": 9.0,
        },
        # Without a zone it was written in UTC: 12:00 UTC is 05:00 local.
        {
            "timestamp": "2026-09-28T12:00:00",
            "event_type": "consumption",
            "liters": 0.5,
        },
        {
            "timestamp": "2026-09-28T12:00:00+00:00",
            "event_type": "refill",
            "liters": 40.0,
        },
        {"timestamp": "not a time", "event_type": "consumption", "liters": 9.0},
        {"event_type": "consumption", "liters": 9.0},
    ]

    assert tank_consumed_l(events, day, zone) == 4.0


def test_only_hand_watering_from_the_tank_is_taken_off() -> None:
    """A jug filled elsewhere never passed through the tank."""
    readings = [
        {"date": "2026-09-28", "liters": 1.5, "from_monitored_tank": True},
        {"date": "2026-09-28", "liters": 0.5, "from_monitored_tank": True},
        {"date": "2026-09-28", "liters": 4.0, "from_monitored_tank": False},
        {"date": "2026-09-28", "liters": 3.0, "source": "pump_estimate"},
        {"date": "2026-09-27", "liters": 9.0, "from_monitored_tank": True},
    ]

    assert hand_watered_from_tank_l(readings, date(2026, 9, 28)) == 2.0


# ── Wording ────────────────────────────────────────────────────────────────


def test_the_sentence_for_a_pump_that_delivered_less() -> None:
    """ADR-0064's own example."""
    day = DayComparison(_day(1), DISAGREES, 12.4, 0.0, 8.1)

    assert day.sentence(TODAY) == (
        "The tank dropped 12.4 L yesterday; the pump delivered 8.1 L (35% less)."
        " A flow rate set too low, a leak, or water drawn from the tank can cause"
        " this."
    )


def test_the_sentence_for_a_pump_that_delivered_more_on_an_earlier_day() -> None:
    """The share is of the tank figure, and an older day is named by its date."""
    day = DayComparison(date(2026, 9, 26), DISAGREES, 10.0, 2.0, 12.0)

    assert day.sentence(TODAY) == (
        "The tank dropped 8.0 L on 26 September beyond 2.0 L of Hand Watering from"
        " it; the pump delivered 12.0 L (50% more). A flow rate set too high, a"
        " pump or line delivering less than it should, or water added to the tank"
        " can cause this."
    )


def test_the_sentence_when_the_tank_did_not_drop() -> None:
    """A share of nothing is not given."""
    day = DayComparison(_day(1), DISAGREES, 0.0, 0.0, 3.0)

    assert day.sentence(TODAY).startswith(
        "The tank dropped 0.0 L yesterday; the pump delivered 3.0 L. "
    )


def test_the_logbook_lines() -> None:
    """Raised names the day that raised it; the others say why it cleared."""
    raised, _ = _run(_watching(), DISAGREES, DISAGREES)

    assert raised.message(Transition.RAISED, TODAY) == (
        "Tank–Pump Disagreement raised. The tank dropped 10.0 L yesterday; the"
        " pump delivered 5.0 L (50% less). A flow rate set too low, a leak, or"
        " water drawn from the tank can cause this."
    )
    assert raised.message(Transition.CLEARED, TODAY) == (
        "Tank–Pump Disagreement cleared: the tank drop and the pump agreed on 2"
        " days in a row."
    )
    assert "tanks changed" in raised.message(Transition.RESTARTED, TODAY)
    assert _watching().message(Transition.RAISED, TODAY) == (
        "Tank–Pump Disagreement raised."
    )


def test_the_view_of_a_raised_signal() -> None:
    """Its state, the day it was raised, its sentence and its last days."""
    raised, _ = _run(_watching(), AGREES, DISAGREES, DISAGREES)

    view = raised.view(TODAY)

    assert view["state"] == "raised"
    assert view["raised_on"] == _day(1).isoformat()
    assert view["message"] == raised.days[-1].sentence(TODAY)
    assert [day["verdict"] for day in view["days"]] == [
        "agrees",
        "disagrees",
        "disagrees",
    ]
    assert view["days"][-1] == {
        "date": _day(1).isoformat(),
        "verdict": "disagrees",
        "tank_drop_l": 10.0,
        "hand_watering_l": 0.0,
        "pump_l": 5.0,
    }


def test_the_view_of_a_clear_signal_has_no_sentence() -> None:
    """A disagreeing day that raised nothing is shown only in the days."""
    record, _ = _run(_watching(), DISAGREES)

    assert record.view(TODAY) == {
        "state": "clear",
        "raised_on": None,
        "message": None,
        "days": [record.days[0].as_dict()],
    }
    assert TankPumpDisagreement().view(TODAY)["state"] == "no_tank"


# ── The durable form ───────────────────────────────────────────────────────


def test_the_record_survives_its_durable_form() -> None:
    """Everything the signal stands on comes back as it was."""
    record, _ = _run(_watching(), DISAGREES, TANK_UNKNOWN, DISAGREES, AGREES)
    record = record.tank_unknown_on(TODAY)

    assert TankPumpDisagreement.from_dict(record.as_dict()) == record


def _durable(**overrides: Any) -> dict[str, Any]:
    value = _watching().as_dict()
    value["days"] = [_judged(_day(1), AGREES).as_dict()]
    value.update(overrides)
    return value


def _day_with(**overrides: Any) -> dict[str, Any]:
    value = _judged(_day(1), AGREES).as_dict()
    value.update(overrides)
    return value


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("garbage", id="not an object"),
        pytest.param(_durable(tanks="sensor.tank"), id="tanks not a list"),
        pytest.param(_durable(tanks=[""]), id="an empty tank"),
        pytest.param(_durable(streak=-1), id="a negative streak"),
        pytest.param(_durable(streak=True), id="a boolean streak"),
        pytest.param(_durable(unknown_days="2026-09-28"), id="unknown days not a list"),
        pytest.param(_durable(days={}), id="days not a list"),
        pytest.param(_durable(first_day=20260928), id="a day not a string"),
        pytest.param(_durable(raised_on="yesterday"), id="a day not a date"),
        pytest.param(_durable(days=["agrees"]), id="a judged day not an object"),
        pytest.param(_durable(days=[_day_with(pump_l=-1.0)]), id="a negative figure"),
        pytest.param(
            _durable(days=[_day_with(tank_drop_l=float("nan"))]),
            id="a figure not finite",
        ),
        pytest.param(_durable(days=[_day_with(verdict=None)]), id="no verdict"),
        pytest.param(
            _durable(days=[_day_with(verdict="maybe")]), id="an unknown verdict"
        ),
    ],
)
def test_a_record_that_is_not_whole_is_refused(value: Any) -> None:
    """The store starts a refused record afresh rather than trust part of it."""
    with pytest.raises((TypeError, ValueError)):
        TankPumpDisagreement.from_dict(value)
