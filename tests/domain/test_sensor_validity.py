"""Zero-mock table tests for sensor validity (#789, tank slice for #790)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import math

import pytest

from custom_components.growspace_manager.domain.sensor_validity import (
    TANK_LEVEL_RANGE,
    Invalidity,
    PlausibleRange,
    SensorReading,
    parse_numeric_state,
    validate_reading,
)

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
CHANGED = NOW - timedelta(minutes=30)
MAX_AGE = timedelta(minutes=120)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("42", 42.0),
        ("42.5", 42.5),
        ("50.0 %", 50.0),
        ("50,5 %", 50.5),
        (" 7 ", 7.0),
        ("unknown", None),
        ("unavailable", None),
        ("", None),
        (None, None),
        ("full", None),
    ],
)
def test_parse_numeric_state(raw: str | None, expected: float | None) -> None:
    assert parse_numeric_state(raw) == expected


def test_parse_numeric_state_keeps_nan_for_the_plausibility_check() -> None:
    value = parse_numeric_state("nan")
    assert value is not None
    assert math.isnan(value)


def _validate(
    raw: str | None, *, reported_ago: timedelta = timedelta(minutes=1)
) -> SensorReading:
    return validate_reading(
        raw,
        changed_at=CHANGED,
        reported_at=NOW - reported_ago,
        now=NOW,
        max_age=MAX_AGE,
        plausible=TANK_LEVEL_RANGE,
    )


@pytest.mark.parametrize(
    ("raw", "reported_ago", "value", "invalidity", "invalid_since"),
    [
        # A fresh, in-range reading is valid.
        ("55", timedelta(minutes=1), 55.0, None, None),
        # 0 % is a real, empty tank — valid, so the gate reads it as low.
        ("0", timedelta(minutes=1), 0.0, None, None),
        ("100", timedelta(minutes=1), 100.0, None, None),
        # A steady sensor whose last_reported still moves is not stale.
        ("55", MAX_AGE, 55.0, None, None),
        # Unavailable since the state changed to it.
        ("unavailable", timedelta(minutes=1), None, Invalidity.UNAVAILABLE, CHANGED),
        ("unknown", timedelta(minutes=1), None, Invalidity.UNAVAILABLE, CHANGED),
        ("full", timedelta(minutes=1), None, Invalidity.UNAVAILABLE, CHANGED),
        (None, timedelta(minutes=1), None, Invalidity.UNAVAILABLE, CHANGED),
        # Outside the plausible range, never clamped.
        ("-5", timedelta(minutes=1), None, Invalidity.IMPLAUSIBLE, CHANGED),
        ("150", timedelta(minutes=1), None, Invalidity.IMPLAUSIBLE, CHANGED),
        ("nan", timedelta(minutes=1), None, Invalidity.IMPLAUSIBLE, CHANGED),
        ("inf", timedelta(minutes=1), None, Invalidity.IMPLAUSIBLE, CHANGED),
        # Stale from the moment the window ran out, not from the last report.
        (
            "55",
            MAX_AGE + timedelta(minutes=5),
            None,
            Invalidity.STALE,
            NOW - timedelta(minutes=5),
        ),
        # Implausible outranks stale: it says more about what is wrong.
        ("150", MAX_AGE * 2, None, Invalidity.IMPLAUSIBLE, CHANGED),
    ],
)
def test_validate_reading(
    raw: str | None,
    reported_ago: timedelta,
    value: float | None,
    invalidity: Invalidity | None,
    invalid_since: datetime | None,
) -> None:
    reading = _validate(raw, reported_ago=reported_ago)
    assert reading == SensorReading(value, invalidity, invalid_since)
    assert reading.valid is (invalidity is None)


def test_a_missing_entity_is_unavailable_and_undated() -> None:
    reading = validate_reading(
        None,
        changed_at=None,
        reported_at=None,
        now=NOW,
        max_age=MAX_AGE,
        plausible=TANK_LEVEL_RANGE,
    )
    assert reading == SensorReading(None, Invalidity.UNAVAILABLE, None)


def test_plausible_range_is_inclusive() -> None:
    band = PlausibleRange(0.0, 20.0)
    assert band.contains(0.0)
    assert band.contains(20.0)
    assert not band.contains(20.01)
    assert not band.contains(float("nan"))
