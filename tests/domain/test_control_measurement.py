"""One baseline, honest provenance and confirmed-shot response evidence."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.growspace_manager.domain.control_measurement import (
    ControlMeasurement,
    ProbeResponseWatch,
    WitnessSubstitution,
    control_measurement,
)
from custom_components.growspace_manager.domain.sensor_validity import (
    Invalidity,
    SensorReading,
)

AT = datetime(2026, 9, 30, 12, tzinfo=UTC)
PROBES = [
    {
        "entity_id": "sensor.witness",
        "quantity": "moisture",
        "role": "witness",
        "cell": None,
        "name": "Edge",
    },
    {
        "entity_id": "sensor.control",
        "quantity": "moisture",
        "role": "control",
        "cell": [1, 2],
        "name": "Middle",
    },
]


@pytest.mark.parametrize(
    "cause", [None, Invalidity.STALE, Invalidity.IMPLAUSIBLE, Invalidity.UNAVAILABLE]
)
@pytest.mark.parametrize("unresponsive", [False, True])
def test_measurement_preserves_validator_and_elected_provenance(cause, unresponsive):
    reading = SensorReading(40 if cause is None else None, cause, AT if cause else None)
    measurement = control_measurement(
        PROBES,
        reading,
        observed_at=AT,
        window=timedelta(minutes=15),
        unresponsive_since=AT if unresponsive else None,
    )
    expected = cause or (Invalidity.UNRESPONSIVE if unresponsive else None)
    assert measurement.cause == expected
    assert measurement.value == (None if expected else 40)
    assert measurement.as_dict() == {
        "value": None if expected else 40,
        "observed_at": AT.isoformat(),
        "cause": expected.value if expected else None,
        "invalid_since": AT.isoformat() if expected else None,
        "validity_window_seconds": 900,
        "probe": PROBES[1],
        "substitute_for": None,
    }


def test_without_elected_probe_witnesses_cannot_fill_the_gap():
    measurement = control_measurement(
        PROBES[:1], SensorReading(10, None, None), observed_at=None, window=None
    )
    assert measurement.value is None
    assert measurement.as_dict()["validity_window_seconds"] is None
    assert measurement.as_dict()["observed_at"] is None
    assert measurement.as_dict()["probe"] is None
    assert measurement.cause is Invalidity.UNAVAILABLE


def test_three_consecutive_flat_shots_and_one_rise_recovers():
    watch = ProbeResponseWatch()
    watch.observe(0, AT, settled=True)  # No confirmed shot, no evidence.
    for count in range(1, 4):
        watch.confirmed_shot(30, AT, near_saturation=False)
        watch.observe(30, AT, settled=True)  # Never judge the pre-shot report.
        watch.observe(30, AT + timedelta(minutes=1), settled=False)
        watch.observe(
            30.05, AT + timedelta(minutes=2), settled=True
        )  # Below the deadband is flat.
        watch.observe(30, AT + timedelta(minutes=3), settled=True)  # Count once.
        assert watch.failures == count
        assert (watch.unresponsive_since is not None) == (count == 3)
    watch.observe(35, AT + timedelta(minutes=4), settled=False)
    assert watch.failures == 0
    assert watch.unresponsive_since is None
    assert watch.before is None


def test_an_excluded_shot_cannot_count_and_a_rise_breaks_the_streak():
    watch = ProbeResponseWatch()
    watch.confirmed_shot(30, AT, near_saturation=False)
    watch.observe(30, AT + timedelta(minutes=2), settled=True)
    watch.confirmed_shot(50, AT, near_saturation=True)
    watch.observe(50, AT + timedelta(minutes=2), settled=True)
    assert watch.failures == 1
    watch.confirmed_shot(30, AT, near_saturation=False)
    watch.abandon()  # Manual watering destroys the response attribution.
    watch.observe(30, AT + timedelta(minutes=2), settled=True)
    assert watch.failures == 1
    watch.confirmed_shot(30, AT, near_saturation=False)
    watch.observe(32, AT + timedelta(minutes=2), settled=True)
    assert watch.failures == 0


def _measurement(value, *, probe=PROBES[1], at=AT, cause=None):
    return ControlMeasurement(
        value, at, cause, at if cause else None, timedelta(minutes=15), probe
    )


def test_learned_median_deduplicates_reports_and_hands_back_immediately():
    state = WitnessSubstitution()
    for minute, delta in enumerate([4, 6, 40]):
        at = AT + timedelta(minutes=minute)
        control = _measurement(50, at=at)
        peer = _measurement(50 - delta, probe=PROBES[0], at=at)
        assert state.resolve(control, [peer], at) is control
        for _ in range(10):
            state.resolve(control, [peer], at)
    failed = _measurement(None, cause=Invalidity.UNAVAILABLE)
    at = AT + timedelta(minutes=3)
    substitute = state.resolve(failed, [_measurement(42, probe=PROBES[0], at=at)], at)
    assert substitute.value == 48
    assert substitute.substitute_for == "sensor.control"
    assert substitute.as_dict()["substitute_for"] == "sensor.control"
    assert substitute.probe == PROBES[0]
    assert substitute.cause is None
    assert state.active == {
        "entity_id": "sensor.witness",
        "offset": 6,
        "since": at.isoformat(),
    }
    recovered = _measurement(49, at=at)
    assert (
        state.resolve(recovered, [_measurement(42, probe=PROBES[0], at=at)], at)
        is recovered
    )
    assert state.active is None


@pytest.mark.parametrize("cause", list(Invalidity))
def test_invalid_control_can_substitute_but_invalid_witness_cannot(cause):
    state = WitnessSubstitution()
    peer = _measurement(34, probe=PROBES[0])
    state.resolve(_measurement(40), [peer], AT)
    failed = _measurement(None, cause=cause)
    assert state.resolve(failed, [peer], AT).value == 40
    invalid_peer = _measurement(None, probe=PROBES[0], cause=cause)
    assert state.resolve(failed, [invalid_peer], AT) is failed
    assert state.active is None


def test_no_history_expired_history_and_removed_witness_cannot_substitute():
    state = WitnessSubstitution()
    control = _measurement(40)
    peer = _measurement(34, probe=PROBES[0])
    failed = _measurement(None, cause=Invalidity.STALE)
    assert state.resolve(failed, [peer], AT) is failed
    state.resolve(control, [peer], AT)
    assert state.resolve(failed, [peer], AT).value == 40
    later = AT + timedelta(hours=24)
    assert (
        state.resolve(failed, [_measurement(34, probe=PROBES[0], at=later)], later)
        is failed
    )
    # Reading an old pair again must not rejuvenate its history.
    assert state.resolve(control, [peer], later) is control
    assert state.resolve(failed, [peer], later) is failed
    state.resolve(control, [peer], AT)
    assert state.resolve(failed, [], AT) is failed
    assert state.history == {}
    assert state.pairs == {}


def test_active_witness_is_stable_until_it_fails_then_an_eligible_peer_takes_over():
    state = WitnessSubstitution()
    second = dict(PROBES[0], entity_id="sensor.second")
    peers = [_measurement(34, probe=PROBES[0]), _measurement(42, probe=second)]
    state.resolve(_measurement(40), peers, AT)
    failed = _measurement(None, cause=Invalidity.UNRESPONSIVE)
    assert state.resolve(failed, peers, AT).probe == PROBES[0]
    assert state.resolve(failed, peers[::-1], AT).probe == PROBES[0]
    bad = _measurement(None, probe=PROBES[0], cause=Invalidity.IMPLAUSIBLE)
    assert state.resolve(failed, [bad, peers[1]], AT).probe == second
    assert state.active["offset"] == -2
    assert state.resolve(failed, [bad, peers[1]], AT + timedelta(seconds=1)).value == 40
    assert state.active["since"] == AT.isoformat()


def test_no_control_never_substitutes_and_corrected_values_must_be_plausible():
    state = WitnessSubstitution()
    assert state.resolve(_measurement(None, probe=None), [], AT).probe is None
    state.resolve(_measurement(90), [_measurement(10, probe=PROBES[0])], AT)
    failed = _measurement(None, cause=Invalidity.UNAVAILABLE)
    assert state.resolve(failed, [_measurement(60, probe=PROBES[0])], AT) is failed
    assert state.active is None
    # A document without probe provenance cannot supply a baseline.
    assert state.resolve(failed, [_measurement(60, probe=None)], AT) is failed


def test_pair_without_timestamp_cannot_train():
    state = WitnessSubstitution()
    control = _measurement(40, at=None)
    peer = _measurement(34, probe=PROBES[0])
    state.resolve(control, [peer], AT)
    assert state.history["sensor.witness"] == []


def test_substitution_offset_uses_only_pairs_still_inside_the_rolling_window():
    state = WitnessSubstitution()
    for hour, offset in [(0, 4), (1, 6), (2, 40)]:
        at = AT + timedelta(hours=hour)
        state.resolve(
            _measurement(50, at=at),
            [_measurement(50 - offset, probe=PROBES[0], at=at)],
            at,
        )
    failed = _measurement(None, cause=Invalidity.UNAVAILABLE)
    start = AT + timedelta(hours=3)
    peer = _measurement(20, probe=PROBES[0], at=start)
    assert state.resolve(failed, [peer], start).value == 26
    since = state.active["since"]
    # At the boundary the oldest offset (4) is no longer part of the median.
    later = AT + timedelta(hours=24)
    peer = _measurement(20, probe=PROBES[0], at=later)
    assert state.resolve(failed, [peer], later).value == 43
    assert state.active["offset"] == 23
    assert state.active["since"] == since
