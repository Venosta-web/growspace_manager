"""Reference recipes are measured days, never synthetic demand."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from custom_components.growspace_manager.domain.delivery_attempt import (
    AttemptTrigger,
    DeliveryAttempt,
    TriggerEvidence,
    attempt_trigger,
    trigger_evidence,
)
from custom_components.growspace_manager.domain.replay_fallback import (
    choose_reference_day,
    layout_replay,
    reference_shots,
    watch_reference_window,
)
from custom_components.growspace_manager.domain.steering_phase import (
    phase_boundary_times,
)
from custom_components.growspace_manager.models import IrrigationStrategy
from custom_components.growspace_manager.models.irrigation_zone import IrrigationZone

TODAY = date(2026, 9, 30)
REF = {"day": "2026-09-29", "day_hours": 12, "lights_on": "2026-09-29T08:00:00+00:00"}
STRATEGY = IrrigationStrategy(
    lights_on_time="08:00:00",
    p0_duration_minutes=60,
    p2_stop_before_lights_off_minutes=120,
)
BOUNDS = phase_boundary_times(STRATEGY, 12, TODAY, UTC)


def attempt(hour=10, **values):
    at = datetime(2026, 9, 29, hour, tzinfo=UTC)
    return replace(
        DeliveryAttempt.requested(
            attempt_id=f"shot-{hour}",
            growspace_id="g",
            zone_id="default",
            output="switch.pump",
            trigger=AttemptTrigger.STEERING,
            planned_s=10,
            flow_rate_ml_per_sec=2,
            requested_at=at,
        )
        .commanded(at)
        .confirmed_on(at, at.date()),
        **values,
    )


def test_selection_is_latest_compatible_retained_zone_day():
    shots = [attempt()]
    days = [
        REF,
        {**REF, "day": "2026-09-30"},
        {**REF, "day": "2026-09-28", "day_hours": 18},
    ]
    assert (
        choose_reference_day(days, shots, zone_id="default", today=TODAY, day_hours=12)
        == REF
    )
    assert (
        choose_reference_day(days, shots, zone_id="other", today=TODAY, day_hours=12)
        is None
    )
    assert (
        choose_reference_day([REF], [], zone_id="default", today=TODAY, day_hours=12)
        is None
    )
    assert (
        choose_reference_day(
            [REF], shots, zone_id="default", today=date(2026, 10, 6), day_hours=12
        )
        is None
    )
    assert (
        reference_shots(
            [attempt(trigger=AttemptTrigger.FALLBACK)], "default", date(2026, 9, 29)
        )
        == []
    )


def test_layout_uses_offsets_never_catches_up_or_crosses_phase_bounds():
    shots = [
        attempt(8),
        attempt(9),
        attempt(10),
        attempt(11),
        attempt(18),
        attempt(19),
        attempt(12, on_confirmed_at=None),
    ]
    plan = layout_replay(
        REF,
        shots,
        boundaries=BOUNDS,
        started_at=BOUNDS.lights_on + timedelta(hours=2),
        max_cycle_seconds=6,
    )
    assert [s.at.hour for s in plan] == [11]
    assert plan[0].as_dict() == {
        "at": "2026-09-30T11:00:00+00:00",
        "planned_s": 6,
        "reference_day": REF["day"],
        "reference_attempt_id": "shot-11",
    }
    plan = layout_replay(
        REF,
        [attempt()],
        boundaries=BOUNDS,
        started_at=BOUNDS.lights_on,
        max_cycle_seconds=100,
    )
    assert plan[0].planned_s == 8


@pytest.mark.parametrize(
    "invalid,disabled,gap",
    [
        (True, False, False),
        (False, True, False),
        (False, False, True),
        (False, False, False),
    ],
)
def test_window_needs_unbroken_own_valid_control(invalid, disabled, gap):
    delay = timedelta(minutes=15)
    window = {}
    at = BOUNDS.lights_on
    while at <= BOUNDS.lights_off:
        window, qualifies = watch_reference_window(
            window,
            at=at,
            boundaries=BOUNDS,
            own_control_valid=not (invalid and at.hour == 12),
            enabled=not (disabled and at.hour == 12),
            delay=delay,
        )
        at += timedelta(minutes=20 if gap else 10)
    assert qualifies is (not invalid and not disabled and not gap)
    _, qualifies = watch_reference_window(
        window,
        at=at,
        boundaries=BOUNDS,
        own_control_valid=True,
        enabled=True,
        delay=delay,
    )
    assert not qualifies


def test_late_start_and_dark_invalidity():
    delay = timedelta(minutes=15)
    window, _ = watch_reference_window(
        {},
        at=BOUNDS.lights_on - timedelta(minutes=5),
        boundaries=BOUNDS,
        own_control_valid=True,
        enabled=True,
        delay=delay,
    )
    assert window["last_seen"] == BOUNDS.lights_on.isoformat()
    window, _ = watch_reference_window(
        window,
        at=BOUNDS.lights_on + timedelta(hours=1),
        boundaries=BOUNDS,
        own_control_valid=True,
        enabled=True,
        delay=delay,
    )
    assert not window["clean"]
    window = {
        "lights_on": BOUNDS.lights_on.isoformat(),
        "last_seen": BOUNDS.lights_off.isoformat(),
        "clean": True,
    }
    _, qualifies = watch_reference_window(
        window,
        at=BOUNDS.lights_off,
        boundaries=BOUNDS,
        own_control_valid=False,
        enabled=True,
        delay=delay,
    )
    assert qualifies  # A failure after the lit window cannot dirty it retroactively.


def test_fallback_wire_round_trip_and_safe_upgrade_default():
    data = {
        "fallback": True,
        "reference_day": REF["day"],
        "reference_attempt_id": "shot-10",
    }
    assert attempt_trigger(data) is AttemptTrigger.FALLBACK
    evidence = trigger_evidence(data)
    assert TriggerEvidence.from_dict(evidence.as_dict()) == evidence
    row = attempt(trigger=AttemptTrigger.FALLBACK, trigger_evidence=evidence)
    assert DeliveryAttempt.from_dict(row.as_dict()) == row
    zone = IrrigationZone.from_dict({"id": "default"})
    assert zone.degraded_fallback == "hold"
    assert zone.substrate_history.reference_days == []


def test_immediate_alerts_do_not_make_the_regular_minute_loop_an_unwatched_gap():
    window = {}
    at = BOUNDS.lights_on
    while at <= BOUNDS.lights_off:
        window, qualifies = watch_reference_window(
            window,
            at=at,
            boundaries=BOUNDS,
            own_control_valid=True,
            enabled=True,
            delay=timedelta(0),
        )
        at += timedelta(minutes=1)
    assert qualifies
