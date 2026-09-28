"""Delivery Attempts and the Dispensed Volume the daily caps enforce (ADR-0054/0055)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from custom_components.growspace_manager.domain.delivery_attempt import (
    RETENTION,
    ROW_LIMIT,
    AttemptOutcome,
    AttemptState,
    AttemptTrigger,
    DeliveryAttempt,
    DispensedVolume,
    TriggerEvidence,
    attempt_trigger,
    dispensed_volume,
    retained,
    trigger_evidence,
    with_suppression,
)

ON = datetime(2026, 9, 26, 14, 30, tzinfo=UTC)
TODAY = date(2026, 9, 26)


def _requested(**overrides: Any) -> DeliveryAttempt:
    fields: dict[str, Any] = {
        "attempt_id": "a1",
        "growspace_id": "gs1",
        "output": "switch.pump",
        "trigger": AttemptTrigger.SCHEDULE,
        "trigger_evidence": TriggerEvidence(slot="14:30:00"),
        "planned_s": 60,
        "flow_rate_ml_per_sec": 10.0,
        "requested_at": ON - timedelta(seconds=3),
    }
    fields.update(overrides)
    return DeliveryAttempt.requested(**fields)


def _attempt(
    *,
    on_confirmed_at: datetime = ON,
    charge_date: date = TODAY,
    **overrides: Any,
) -> DeliveryAttempt:
    """An actuated attempt, commanded 2 s before its pump confirmed ON."""
    overrides.setdefault("requested_at", on_confirmed_at - timedelta(seconds=3))
    return (
        _requested(**overrides)
        .commanded(on_confirmed_at - timedelta(seconds=2))
        .confirmed_on(on_confirmed_at, charge_date)
    )


def _suppressed(
    reason: str = "cap_reached", at: datetime = ON, **overrides: Any
) -> DeliveryAttempt:
    overrides.setdefault("trigger_evidence", None)
    return _requested(
        attempt_id=f"s-{at.isoformat()}-{reason}", requested_at=at, **overrides
    ).refused(reason)


def test_a_requested_attempt_is_open_and_charges_nothing() -> None:
    """Written before the ON command, it is on record but not yet charged."""
    attempt = _requested()

    assert attempt.state is AttemptState.REQUESTED
    assert attempt.is_open
    assert not attempt.is_actuated
    assert attempt.charged_l == 0.0
    assert attempt.charge_date is None
    assert dispensed_volume([attempt], TODAY) == DispensedVolume()


def test_an_actuated_attempt_is_charged_its_plan() -> None:
    """60 s at 10 ml/s is charged 0.6 L the moment the pump confirms ON."""
    attempt = _attempt()

    assert attempt.state is AttemptState.ACTUATED
    assert attempt.charged_l == pytest.approx(0.6)
    assert attempt.is_open
    assert attempt.estimated_l is None
    assert attempt.on_commanded_at == ON - timedelta(seconds=2)
    assert attempt.requested_at == ON - timedelta(seconds=3)


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
    assert closed.state is AttemptState.CLOSED


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


def test_a_pump_that_never_confirmed_on_is_not_delivered_and_charges_nothing() -> None:
    """Commanded, never read ON: closed with the reason, no charge."""
    closed = (
        _requested()
        .commanded(ON)
        .unconfirmed(
            off_commanded_at=ON + timedelta(seconds=10), reason="on_unconfirmed"
        )
    )

    assert closed.outcome is AttemptOutcome.NOT_DELIVERED
    assert closed.reason == "on_unconfirmed"
    assert closed.abort_cause is None
    assert closed.charged_l == 0.0
    assert dispensed_volume([closed], TODAY) == DispensedVolume()


def test_a_request_stopped_before_confirm_on_is_aborted_uncharged() -> None:
    """Cancelled during the ON wait: aborted by what stopped it, still uncharged."""
    closed = _requested().unconfirmed(
        off_commanded_at=None, abort_cause="watchdog", reason="on_unconfirmed"
    )

    assert closed.outcome is AttemptOutcome.ABORTED
    assert closed.abort_cause == "watchdog"
    assert closed.reason is None
    assert closed.charge_date is None


def test_an_unconfirmed_close_needs_a_cause_or_a_reason() -> None:
    """Nothing closes without saying why."""
    with pytest.raises(ValueError, match="cause or a reason"):
        _requested().unconfirmed(off_commanded_at=None)


def test_a_commanded_request_is_never_suppressed() -> None:
    """Once the ON command went out, a refusal is too late to be one."""
    with pytest.raises(ValueError, match="reached the pump"):
        _requested().commanded(ON).refused("dark")


@pytest.mark.parametrize(
    "step",
    [
        lambda a: a.refused("dark"),
        lambda a: a.commanded(ON),
        lambda a: a.confirmed_on(ON, TODAY),
        lambda a: a.unconfirmed(off_commanded_at=ON, reason="on_unconfirmed"),
    ],
    ids=["refused", "commanded", "confirmed-on", "unconfirmed"],
)
def test_an_actuated_attempt_cannot_step_back(step: Any) -> None:
    """Requested → Actuated → Closed, and never backwards."""
    with pytest.raises(ValueError, match="actuated, not requested"):
        step(_attempt())


def test_only_an_actuated_attempt_closes_on_its_on_time() -> None:
    """A request with no confirm-ON has no ON time to measure."""
    with pytest.raises(ValueError, match="requested, not actuated"):
        _requested().closed(off_commanded_at=ON)


def test_a_suppressed_request_is_closed_uncharged_with_its_reason() -> None:
    """Refused by the gate: one closed row, counted once, charging nothing."""
    attempt = _suppressed("low_tank")

    assert attempt.state is AttemptState.CLOSED
    assert attempt.outcome is AttemptOutcome.SUPPRESSED
    assert attempt.reason == "low_tank"
    assert attempt.suppressed_count == 1
    assert attempt.requested_at == attempt.last_requested_at == ON
    assert attempt.on_commanded_at is None
    assert dispensed_volume([attempt], TODAY) == DispensedVolume()


def test_consecutive_suppressions_with_one_reason_merge_into_one_row() -> None:
    """Three cap refusals are one row: a count, and the first and last times."""
    rows: list[DeliveryAttempt] = []
    for minutes in (0, 5, 10):
        rows = with_suppression(rows, _suppressed(at=ON + timedelta(minutes=minutes)))

    (row,) = rows
    assert row.suppressed_count == 3
    assert row.requested_at == ON
    assert row.last_requested_at == ON + timedelta(minutes=10)
    assert row.attempt_id == _suppressed(at=ON).attempt_id


def test_a_different_reason_starts_a_new_row() -> None:
    """A cap refusal then a dark one are two runs."""
    rows = with_suppression([], _suppressed("cap_reached"))
    rows = with_suppression(rows, _suppressed("dark", ON + timedelta(minutes=1)))

    assert [row.reason for row in rows] == ["cap_reached", "dark"]


def test_an_attempt_between_suppressions_ends_the_run() -> None:
    """A shot that fired on the same output makes the next refusal a new row."""
    rows = with_suppression([], _suppressed(at=ON - timedelta(hours=2)))
    rows.append(_attempt(attempt_id="shot", on_confirmed_at=ON - timedelta(hours=1)))
    rows = with_suppression(rows, _suppressed(at=ON))

    assert [row.attempt_id for row in rows] == [
        _suppressed(at=ON - timedelta(hours=2)).attempt_id,
        "shot",
        _suppressed(at=ON).attempt_id,
    ]
    assert rows[0].suppressed_count == rows[2].suppressed_count == 1


def test_another_outputs_attempt_does_not_end_the_run() -> None:
    """Consecutive is per output: a drain pump firing leaves the run whole."""
    rows = with_suppression([], _suppressed(at=ON - timedelta(hours=2)))
    rows.append(_attempt(attempt_id="other", output="switch.other"))
    rows = with_suppression(rows, _suppressed(at=ON))

    assert [row.attempt_id for row in rows] == [rows[0].attempt_id, "other"]
    assert rows[0].suppressed_count == 2


def test_a_different_trigger_does_not_merge() -> None:
    """A refused manual run is not folded into a run of refused schedules."""
    rows = with_suppression([], _suppressed())
    rows = with_suppression(
        rows,
        _suppressed(
            at=ON + timedelta(minutes=1),
            trigger=AttemptTrigger.MANUAL,
            trigger_evidence=TriggerEvidence(user_id="u1"),
        ),
    )

    assert len(rows) == 2
    assert rows[1].trigger_evidence.user_id == "u1"
    with pytest.raises(ValueError, match="only a run"):
        rows[0].merged(rows[1])


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


@pytest.mark.parametrize(
    ("event_data", "evidence"),
    [
        (
            {"time": "10:00:00", "duration": 30},
            {"slot": "10:00:00"},
        ),
        (
            {
                "phase": "p2",
                "vwc": 41.5,
                "base_seconds": 20,
                "vwc_factor": 1.1,
                "ec_factor": 0.9,
            },
            {
                "phase": "p2",
                "vwc": 41.5,
                "base_s": 20.0,
                "vwc_factor": 1.1,
                "ec_factor": 0.9,
            },
        ),
        ({"manual": True, "user_id": "abc123"}, {"user_id": "abc123"}),
        ({"manual": True, "user_id": None}, {}),
        ({}, {}),
    ],
    ids=["schedule", "steering", "manual", "manual-no-user", "no-slot"],
)
def test_each_trigger_records_its_own_evidence(
    event_data: dict[str, Any], evidence: dict[str, Any]
) -> None:
    """The slot, the steering decision, or the person — and nothing else."""
    assert trigger_evidence(event_data).as_dict() == evidence


def test_dispensed_volume_sums_only_the_day_asked_for() -> None:
    """Yesterday's charges never count toward today's caps."""
    attempts = [
        _attempt(attempt_id="y", charge_date=TODAY - timedelta(days=1)),
        _attempt(attempt_id="t1"),
        _attempt(attempt_id="t2", planned_s=30),
        _suppressed(),
        _requested(attempt_id="r"),
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


def test_a_merged_run_is_aged_by_its_last_suppression() -> None:
    """A run that began eight days ago and is still going is kept."""
    rows = with_suppression([], _suppressed(at=ON - timedelta(days=8)))
    rows = with_suppression(rows, _suppressed(at=ON - timedelta(days=1)))

    assert retained(rows, now=ON, today=TODAY) == rows


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


def test_the_row_limit_evicts_uncharged_rows_of_today_before_any_charge() -> None:
    """Today's suppressions are history, not charges: they can go; charges cannot."""
    charged = [
        _attempt(attempt_id=f"c{index}", on_confirmed_at=ON - timedelta(hours=10))
        for index in range(ROW_LIMIT)
    ]
    refused = _suppressed(at=ON - timedelta(hours=1))

    kept = retained([refused, *charged], now=ON, today=TODAY)

    assert kept == charged


@pytest.mark.parametrize(
    "attempt",
    [
        _requested(),
        _requested().commanded(ON - timedelta(seconds=1)),
        _attempt(),
        _attempt(
            trigger=AttemptTrigger.MANUAL,
            trigger_evidence=TriggerEvidence(user_id="u1"),
        )
        .closed(off_commanded_at=ON + timedelta(seconds=5), abort_cause="e_stop")
        .read_back_off(ON + timedelta(seconds=6)),
        _requested()
        .commanded(ON)
        .unconfirmed(
            off_commanded_at=ON + timedelta(seconds=10), reason="on_unconfirmed"
        )
        .read_back_off(ON + timedelta(seconds=11)),
        with_suppression(
            [_suppressed(trigger=AttemptTrigger.STEERING)],
            _suppressed(at=ON + timedelta(minutes=1), trigger=AttemptTrigger.STEERING),
        )[0],
    ],
    ids=["requested", "commanded", "actuated", "closed", "not-delivered", "suppressed"],
)
def test_the_wire_form_round_trips(attempt: DeliveryAttempt) -> None:
    """What is stored is exactly what is read back."""
    wire = attempt.as_dict()

    assert DeliveryAttempt.from_dict(wire) == attempt
    assert wire["state"] == attempt.state.value
    assert wire["evidence"] == (
        "estimated" if attempt.estimated_l is not None else None
    )


def test_the_wire_form_names_every_field() -> None:
    """The stored shape, field by field."""
    wire = (
        _attempt(
            trigger=AttemptTrigger.STEERING,
            trigger_evidence=TriggerEvidence(
                phase="p1", vwc=38.0, base_s=20.0, vwc_factor=1.2, ec_factor=1.0
            ),
        )
        .closed(off_commanded_at=ON + timedelta(seconds=60))
        .read_back_off(ON + timedelta(seconds=61))
        .as_dict()
    )

    assert wire == {
        "attempt_id": "a1",
        "growspace_id": "gs1",
        "output": "switch.pump",
        "trigger": "steering",
        "trigger_evidence": {
            "phase": "p1",
            "vwc": 38.0,
            "base_s": 20.0,
            "vwc_factor": 1.2,
            "ec_factor": 1.0,
        },
        "planned_s": 60.0,
        "flow_rate_ml_per_sec": 10.0,
        "requested_at": "2026-09-26T14:29:57+00:00",
        "on_commanded_at": "2026-09-26T14:29:58+00:00",
        "on_confirmed_at": "2026-09-26T14:30:00+00:00",
        "off_commanded_at": "2026-09-26T14:31:00+00:00",
        "off_confirmed_at": "2026-09-26T14:31:01+00:00",
        "charge_date": "2026-09-26",
        "state": "closed",
        "outcome": "completed",
        "reason": None,
        "abort_cause": None,
        "charged_l": pytest.approx(0.6),
        "estimated_l": pytest.approx(0.6),
        "evidence": "estimated",
        "suppressed_count": 0,
        "last_requested_at": None,
    }


def test_a_row_written_before_attempts_were_requested_still_loads() -> None:
    """#787's rows have no request time or evidence; they are not malformed."""
    legacy = {
        "attempt_id": "old",
        "growspace_id": "gs1",
        "output": "switch.pump",
        "trigger": "schedule",
        "planned_s": 60.0,
        "flow_rate_ml_per_sec": 10.0,
        "on_commanded_at": "2026-09-26T14:29:58+00:00",
        "on_confirmed_at": "2026-09-26T14:30:00+00:00",
        "charge_date": "2026-09-26",
        "charged_l": 0.6,
        "state": "actuated",
        "outcome": None,
        "abort_cause": None,
        "off_commanded_at": None,
        "off_confirmed_at": None,
        "estimated_l": None,
        "evidence": "estimated",
    }

    attempt = DeliveryAttempt.from_dict(legacy)

    assert attempt.requested_at == ON - timedelta(seconds=2)
    assert attempt.trigger_evidence == TriggerEvidence()
    assert attempt.state is AttemptState.ACTUATED
    assert dispensed_volume([attempt], TODAY).cycles == 1


def _wire(base: DeliveryAttempt | None = None, **changes: Any) -> dict[str, Any]:
    wire = (base or _attempt()).as_dict()
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
        (_wire(reason=["dark"]), ValueError),
        (_wire(trigger="sprinkler"), ValueError),
        (_wire(trigger=None), TypeError),
        (_wire(on_confirmed_at="2026-09-26T14:30:00"), ValueError),
        (_wire(requested_at=_DROP, on_commanded_at=None), TypeError),
        (_wire(requested_at=None), TypeError),
        (_wire(charge_date=20260926), TypeError),
        (_wire(outcome="exploded"), ValueError),
        (_wire(state="closed"), ValueError),
        (_wire(charged_l=0.1), ValueError),
        (_wire(charge_date=None), ValueError),
        (_wire(_requested(), charge_date="2026-09-26"), ValueError),
        (_wire(_requested(), charged_l=0.6), ValueError),
        (_wire(trigger_evidence="10:00"), TypeError),
        (_wire(trigger_evidence={"slot": 10}), ValueError),
        (_wire(trigger_evidence={"vwc": "40"}), ValueError),
        (_wire(trigger_evidence={"weather": "sunny"}), ValueError),
        (_wire(suppressed_count=-1), ValueError),
        (_wire(suppressed_count=True), ValueError),
        (_wire(suppressed_count=2), ValueError),
        (_wire(_suppressed(), suppressed_count=0), ValueError),
        (_wire(_suppressed(), last_requested_at=None), ValueError),
        (_wire(_suppressed(), reason=None), ValueError),
        (_wire(_suppressed(), on_commanded_at=ON.isoformat()), ValueError),
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
        "list-reason",
        "unknown-trigger",
        "no-trigger",
        "naive-timestamp",
        "no-timestamp",
        "null-request-time",
        "numeric-date",
        "unknown-outcome",
        "state-disagrees",
        "charged-below-plan",
        "actuated-without-date",
        "requested-with-date",
        "requested-charged",
        "text-evidence",
        "numeric-slot",
        "text-vwc",
        "unknown-evidence",
        "negative-count",
        "bool-count",
        "count-on-a-shot",
        "suppressed-uncounted",
        "suppressed-without-last",
        "suppressed-without-reason",
        "suppressed-commanded",
    ],
)
def test_a_malformed_record_is_refused_whole(
    value: Any, error: type[Exception]
) -> None:
    """A record that is not whole fails closed rather than under-counting."""
    with pytest.raises(error):
        DeliveryAttempt.from_dict(value)
