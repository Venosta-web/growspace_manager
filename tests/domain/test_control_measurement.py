"""One baseline, honest provenance and confirmed-shot response evidence."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.growspace_manager.domain.control_measurement import (
    ProbeResponseWatch,
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
