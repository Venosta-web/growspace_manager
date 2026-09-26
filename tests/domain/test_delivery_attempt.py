"""Delivery Attempts and the Dispensed Volume the daily caps enforce (ADR-0054/0055)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from custom_components.growspace_manager.domain.delivery_attempt import (
    RETENTION,
    ROW_LIMIT,
    AttemptOutcome,
    AttemptTrigger,
    DeliveryAttempt,
    DispensedVolume,
    attempt_trigger,
    dispensed_volume,
    retained,
)

ON = datetime(2026, 9, 26, 14, 30, tzinfo=UTC)
TODAY = date(2026, 9, 26)


def _attempt(**overrides: Any) -> DeliveryAttempt:
    fields: dict[str, Any] = {
        "attempt_id": "a1",
        "growspace_id": "gs1",
        "output": "switch.pump",
        "trigger": AttemptTrigger.SCHEDULE,
        "planned_s": 60,
        "flow_rate_ml_per_sec": 10.0,
        "on_commanded_at": ON - timedelta(seconds=2),
        "on_confirmed_at": ON,
        "charge_date": TODAY,
    }
    fields.update(overrides)
    return DeliveryAttempt.actuated(**fields)


def test_an_actuated_attempt_is_charged_its_plan() -> None:
    """60 s at 10 ml/s is charged 0.6 L the moment the pump confirms ON."""
    attempt = _attempt()

    assert attempt.charged_l == pytest.approx(0.6)
    assert attempt.is_open
    assert attempt.estimated_l is None


def test_an_attempt_without_a_flow_rate_charges_a_cycle_and_no_litres() -> None:
    """No flow rate: the cycle limit still counts it, the volume cap cannot."""
    attempt = _attempt(flow_rate_ml_per_sec=None)

    assert attempt.charged_l == 0.0
    assert dispensed_volume([attempt], TODAY) == DispensedVolume(cycles=1, liters=0.0)


def test_an_aborted_shot_costs_the_cap_its_plan_and_shows_what_ran() -> None:
    """An aborted 5 s shot out of a 60 s plan: the cap keeps 60 s, the water is 5 s."""
    closed = _attempt().closed(
        off_commanded_at=ON + timedelta(seconds=5), abort_cause="cancel"
    )

    assert closed.outcome is AttemptOutcome.ABORTED
    assert closed.abort_cause == "cancel"
    assert closed.charged_l == pytest.approx(0.6)
    assert closed.estimated_l == pytest.approx(0.05)
    assert not closed.is_open


def test_a_shot_that_overran_its_plan_is_topped_up() -> None:
    """A late wake-up ran the pump 63 s: the cap is charged what really ran."""
    closed = _attempt().closed(off_commanded_at=ON + timedelta(seconds=63))

    assert closed.outcome is AttemptOutcome.COMPLETED
    assert closed.charged_l == pytest.approx(0.63)
    assert closed.estimated_l == pytest.approx(0.63)


def test_reading_back_off_is_recorded_on_the_close() -> None:
    """Whether OFF was read back travels with the attempt."""
    closed = _attempt().closed(off_commanded_at=ON + timedelta(seconds=60))
    assert not closed.off_confirmed

    confirmed = closed.read_back_off(ON + timedelta(seconds=61))

    assert confirmed.off_confirmed
    assert confirmed.off_confirmed_at == ON + timedelta(seconds=61)


@pytest.mark.parametrize(
    ("event_data", "trigger"),
    [
        ({"manual": True}, AttemptTrigger.MANUAL),
        ({"phase": "P1"}, AttemptTrigger.STEERING),
        ({"time": "10:00:00"}, AttemptTrigger.SCHEDULE),
        ({}, AttemptTrigger.SCHEDULE),
    ],
)
def test_the_trigger_is_read_from_the_request(
    event_data: dict[str, Any], trigger: AttemptTrigger
) -> None:
    """Manual wins over a phase; anything else was scheduled."""
    assert attempt_trigger(event_data) is trigger


def test_dispensed_volume_sums_only_the_day_asked_for() -> None:
    """Yesterday's charges never count toward today's caps."""
    attempts = [
        _attempt(attempt_id="y", charge_date=TODAY - timedelta(days=1)),
        _attempt(attempt_id="t1"),
        _attempt(attempt_id="t2", planned_s=30),
    ]

    assert dispensed_volume(attempts, TODAY) == DispensedVolume(
        cycles=2, liters=pytest.approx(0.9)
    )
    assert dispensed_volume([], TODAY) == DispensedVolume()


def test_retention_drops_attempts_older_than_a_week() -> None:
    """Seven days are kept; an eighth-day row goes."""
    now = ON
    old = _attempt(
        attempt_id="old",
        on_confirmed_at=now - RETENTION - timedelta(minutes=1),
        charge_date=TODAY - timedelta(days=8),
    )
    recent = _attempt(
        attempt_id="recent",
        on_confirmed_at=now - timedelta(days=6),
        charge_date=TODAY - timedelta(days=6),
    )

    kept = retained([old, recent], now=now, today=TODAY)

    assert [attempt.attempt_id for attempt in kept] == ["recent"]


def test_retention_never_drops_a_charge_dated_today() -> None:
    """A clock that jumped forward still cannot evict today's charges."""
    charged_today = _attempt(on_confirmed_at=ON - timedelta(days=30))

    assert retained([charged_today], now=ON, today=TODAY) == [charged_today]


def test_the_row_limit_evicts_the_oldest_rows_not_charged_today() -> None:
    """Over the limit, earlier days go oldest first and today's all stay."""
    yesterday = TODAY - timedelta(days=1)
    earlier = [
        _attempt(
            attempt_id=f"y{index}",
            on_confirmed_at=ON - timedelta(days=1, seconds=ROW_LIMIT - index),
            charge_date=yesterday,
        )
        for index in range(ROW_LIMIT)
    ]
    today = [_attempt(attempt_id=f"t{index}") for index in range(3)]

    kept = retained([*today, *earlier], now=ON, today=TODAY)

    assert len(kept) == ROW_LIMIT
    ids = {attempt.attempt_id for attempt in kept}
    assert {"t0", "t1", "t2"} <= ids
    assert {"y0", "y1", "y2"}.isdisjoint(ids)
    assert f"y{ROW_LIMIT - 1}" in ids


@pytest.mark.parametrize(
    "attempt",
    [
        _attempt(),
        _attempt(trigger=AttemptTrigger.MANUAL)
        .closed(off_commanded_at=ON + timedelta(seconds=5), abort_cause="e_stop")
        .read_back_off(ON + timedelta(seconds=6)),
    ],
    ids=["open", "closed"],
)
def test_the_wire_form_round_trips(attempt: DeliveryAttempt) -> None:
    """What is stored is exactly what is read back."""
    wire = attempt.as_dict()

    assert DeliveryAttempt.from_dict(wire) == attempt
    assert wire["evidence"] == "estimated"
    assert wire["state"] == ("actuated" if attempt.is_open else "closed")


def test_the_wire_form_names_every_field() -> None:
    """The stored shape, field by field."""
    wire = (
        _attempt()
        .closed(off_commanded_at=ON + timedelta(seconds=60))
        .read_back_off(ON + timedelta(seconds=61))
        .as_dict()
    )

    assert wire == {
        "attempt_id": "a1",
        "growspace_id": "gs1",
        "output": "switch.pump",
        "trigger": "schedule",
        "planned_s": 60.0,
        "flow_rate_ml_per_sec": 10.0,
        "on_commanded_at": "2026-09-26T14:29:58+00:00",
        "on_confirmed_at": "2026-09-26T14:30:00+00:00",
        "charge_date": "2026-09-26",
        "charged_l": pytest.approx(0.6),
        "state": "closed",
        "outcome": "completed",
        "abort_cause": None,
        "off_commanded_at": "2026-09-26T14:31:00+00:00",
        "off_confirmed_at": "2026-09-26T14:31:01+00:00",
        "estimated_l": pytest.approx(0.6),
        "evidence": "estimated",
    }


def _wire(**changes: Any) -> dict[str, Any]:
    wire = _attempt().as_dict()
    for key, value in changes.items():
        if value is _DROP:
            wire.pop(key)
        else:
            wire[key] = value
    return wire


_DROP = object()


@pytest.mark.parametrize(
    ("value", "error"),
    [
        ("not an object", TypeError),
        (_wire(attempt_id=""), ValueError),
        (_wire(growspace_id=None), ValueError),
        (_wire(output=_DROP), ValueError),
        (_wire(planned_s=-1), ValueError),
        (_wire(charged_l=True), ValueError),
        (_wire(flow_rate_ml_per_sec=float("nan")), ValueError),
        (_wire(charged_l=float("inf")), ValueError),
        (_wire(estimated_l="0.5"), ValueError),
        (_wire(abort_cause=3), ValueError),
        (_wire(trigger="sprinkler"), ValueError),
        (_wire(trigger=None), TypeError),
        (_wire(on_confirmed_at="2026-09-26T14:30:00"), ValueError),
        (_wire(on_commanded_at=_DROP), TypeError),
        (_wire(charge_date=20260926), TypeError),
        (_wire(outcome="exploded"), ValueError),
        (_wire(state="closed"), ValueError),
        (_wire(charged_l=0.1), ValueError),
    ],
    ids=[
        "not-object",
        "empty-id",
        "no-growspace",
        "no-output",
        "negative-plan",
        "bool-charge",
        "nan-flow",
        "infinite-charge",
        "text-estimate",
        "numeric-abort-cause",
        "unknown-trigger",
        "no-trigger",
        "naive-timestamp",
        "no-timestamp",
        "numeric-date",
        "unknown-outcome",
        "state-disagrees",
        "charged-below-plan",
    ],
)
def test_a_malformed_record_is_refused_whole(
    value: Any, error: type[Exception]
) -> None:
    """A record that is not whole fails closed rather than under-counting."""
    with pytest.raises(error):
        DeliveryAttempt.from_dict(value)
