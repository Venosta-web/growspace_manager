"""Zero-mock table tests for sensor validity (#789; the tank slice came with #790)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import math

import pytest

from custom_components.growspace_manager.domain.sensor_validity import (
    HUMIDITY_RANGE,
    PORE_EC_RANGE,
    REALERT_AFTER,
    SUBSTRATE_MOISTURE_RANGE,
    TANK_LEVEL_RANGE,
    VPD_RANGE,
    WINDOW_FLOOR,
    Invalidity,
    PlausibleRange,
    ReportCadence,
    SensorAlert,
    SensorReading,
    SensorWatch,
    ec_scale,
    inhibit_code,
    inhibit_detail,
    invalid_alert_message,
    parse_numeric_state,
    recovered_alert_message,
    substrate_moisture_range,
    temperature_range,
    validate_reading,
    validity_window,
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


def test_no_window_never_goes_stale() -> None:
    reading = validate_reading(
        "55",
        changed_at=CHANGED,
        reported_at=NOW - timedelta(days=30),
        now=NOW,
        max_age=None,
        plausible=TANK_LEVEL_RANGE,
    )
    assert reading == SensorReading(55.0, None, None)


def test_plausible_range_is_inclusive() -> None:
    band = PlausibleRange(0.0, 20.0)
    assert band.contains(0.0)
    assert band.contains(20.0)
    assert not band.contains(20.01)
    assert not band.contains(float("nan"))


# --- The control-input slice (#789) ------------------------------------------


@pytest.mark.parametrize(
    ("raw", "zero_is_implausible", "valid"),
    [
        ("0", False, True),
        ("0", True, False),
        ("0.1", True, True),
        ("100", True, True),
        ("-5", False, False),
        ("150", False, False),
        ("nan", False, False),
    ],
)
def test_substrate_moisture_range(
    raw: str, zero_is_implausible: bool, valid: bool
) -> None:
    reading = validate_reading(
        raw,
        changed_at=CHANGED,
        reported_at=NOW,
        now=NOW,
        max_age=MAX_AGE,
        plausible=substrate_moisture_range(zero_is_implausible=zero_is_implausible),
    )
    assert reading.valid is valid
    assert (reading.value is None) is not valid


@pytest.mark.parametrize(
    ("unit", "value", "plausible"),
    [
        ("°C", 25.0, True),
        ("°C", 77.0, False),
        ("°C", -20.0, False),
        ("°F", 77.0, True),
        ("°F", 5.0, False),
        (None, 77.0, True),
        (None, 25.0, True),
        (None, 150.0, False),
    ],
)
def test_temperature_range_follows_the_unit(
    unit: str | None, value: float, plausible: bool
) -> None:
    assert temperature_range(unit).contains(value) is plausible


@pytest.mark.parametrize(
    ("band", "value", "plausible"),
    [
        (PORE_EC_RANGE, 2.5, True),
        (PORE_EC_RANGE, 25.0, False),
        (HUMIDITY_RANGE, 65.0, True),
        (HUMIDITY_RANGE, 101.0, False),
        (VPD_RANGE, 1.2, True),
        (VPD_RANGE, 1200.0, False),
    ],
)
def test_quantity_ranges(band: PlausibleRange, value: float, plausible: bool) -> None:
    assert band.contains(value) is plausible


@pytest.mark.parametrize(
    ("unit", "scale"),
    [("µS/cm", 0.001), ("μS/cm", 0.001), ("uS/cm", 0.001), ("mS/cm", 1.0), (None, 1.0)],
)
def test_ec_scale(unit: str | None, scale: float) -> None:
    assert ec_scale(unit) == scale


def test_a_scaled_reading_is_judged_in_the_ranges_unit() -> None:
    """2500 µS/cm is 2.5 mS/cm, not an implausible 2500."""
    reading = validate_reading(
        "2500",
        changed_at=CHANGED,
        reported_at=NOW,
        now=NOW,
        max_age=MAX_AGE,
        plausible=PORE_EC_RANGE,
        scale=ec_scale("µS/cm"),
    )
    assert reading == SensorReading(2.5, None, None)


def _cadence(*minutes: float) -> ReportCadence:
    cadence = ReportCadence()
    for offset in minutes:
        cadence.observe(NOW + timedelta(minutes=offset))
    return cadence


def test_cadence_needs_enough_reports_before_it_is_trusted() -> None:
    assert _cadence(0, 2, 4).expected_interval is None
    assert _cadence(0, 2, 4, 6).expected_interval == timedelta(minutes=2)


def test_cadence_ignores_a_repeated_or_older_report() -> None:
    cadence = _cadence(0, 2, 2, 1, 4, 6)
    assert list(cadence.intervals) == [timedelta(minutes=2)] * 3


def test_cadence_is_a_median() -> None:
    """One long gap does not stretch the window."""
    assert _cadence(0, 2, 4, 6, 66).expected_interval == timedelta(minutes=2)


@pytest.mark.parametrize(
    ("expected", "cap", "window"),
    [
        # Three expected intervals…
        (timedelta(minutes=4), timedelta(minutes=30), timedelta(minutes=12)),
        # …never under the floor…
        (timedelta(seconds=30), timedelta(minutes=30), WINDOW_FLOOR),
        # …never over the cap…
        (timedelta(minutes=20), timedelta(minutes=30), timedelta(minutes=30)),
        # …the cap alone until an interval is learned…
        (None, timedelta(minutes=30), timedelta(minutes=30)),
        # …and no window at all when staleness is off.
        (timedelta(minutes=4), None, None),
    ],
)
def test_validity_window(
    expected: timedelta | None, cap: timedelta | None, window: timedelta | None
) -> None:
    assert validity_window(expected, cap) == window


START = NOW - timedelta(hours=1)
CAP = timedelta(minutes=30)
DELAY = timedelta(minutes=15)


def _read(
    watch: SensorWatch, raw: str, *, reported: datetime, now: datetime
) -> SensorReading:
    return watch.read(
        raw,
        changed_at=reported,
        reported_at=reported,
        now=now,
        stale_cap=CAP,
        plausible=SUBSTRATE_MOISTURE_RANGE,
    )


def test_a_sensor_that_keeps_reporting_the_same_value_is_not_stale() -> None:
    """``last_reported`` advances while ``last_changed`` stays put."""
    watch = SensorWatch(watching_since=START)
    for minute in range(0, 60, 2):
        at = START + timedelta(minutes=minute)
        reading = watch.read(
            "42",
            changed_at=START,
            reported_at=at,
            now=at + timedelta(minutes=1),
            stale_cap=CAP,
            plausible=SUBSTRATE_MOISTURE_RANGE,
        )
        assert reading == SensorReading(42.0, None, None)


def test_a_sensor_that_stops_reporting_goes_stale_after_its_learned_window() -> None:
    """Reporting every 2 minutes, it is stale after 6 — not after the 30 cap."""
    watch = SensorWatch(watching_since=START)
    for minute in (0, 2, 4, 6):
        _read(watch, "42", reported=START + timedelta(minutes=minute), now=START)
    last = START + timedelta(minutes=6)
    assert _read(watch, "42", reported=last, now=last + timedelta(minutes=5)).valid
    stale = _read(watch, "42", reported=last, now=last + timedelta(minutes=7))
    assert stale == SensorReading(None, Invalidity.STALE, last + timedelta(minutes=6))
    assert watch.invalid_since == last + timedelta(minutes=6)


def test_unavailable_reports_do_not_teach_the_cadence() -> None:
    watch = SensorWatch(watching_since=START)
    for minute in range(6):
        _read(watch, "unavailable", reported=START + timedelta(minutes=minute), now=NOW)
    assert watch.cadence.last_reported is None


def test_an_episode_alerts_once_after_the_delay_and_recovers_once() -> None:
    watch = SensorWatch(watching_since=START)
    first_bad = START + timedelta(minutes=1)
    for minute in range(1, 40):
        now = START + timedelta(minutes=minute)
        _read(watch, "150", reported=first_bad, now=now)
        alert = watch.alert(now, DELAY)
        expected = SensorAlert.INVALID if now - first_bad == DELAY else SensorAlert.NONE
        assert alert is expected, minute
    assert watch.cause is Invalidity.IMPLAUSIBLE

    recovered_at = START + timedelta(minutes=40)
    _read(watch, "41", reported=recovered_at, now=recovered_at)
    assert watch.alert(recovered_at, DELAY) is SensorAlert.RECOVERED
    assert watch.alert(recovered_at, DELAY) is SensorAlert.NONE
    assert watch.last_valid_value == 41.0


def test_a_short_episode_raises_nothing() -> None:
    watch = SensorWatch(watching_since=START)
    now = START + timedelta(minutes=1)
    _read(watch, "unavailable", reported=now, now=now)
    assert watch.alert(now + timedelta(minutes=5), DELAY) is SensorAlert.NONE
    _read(watch, "40", reported=now + timedelta(minutes=6), now=now)
    assert watch.alert(now + timedelta(minutes=6), DELAY) is SensorAlert.NONE


def test_an_episode_is_never_older_than_the_watch() -> None:
    """A sensor already down at a restart waits out the delay like any other."""
    watch = SensorWatch(watching_since=START)
    _read(watch, "unavailable", reported=START - timedelta(days=3), now=START)
    assert watch.invalid_since == START
    assert watch.alert(START + timedelta(minutes=14), DELAY) is SensorAlert.NONE


def test_a_missing_entity_is_dated_by_the_watch() -> None:
    watch = SensorWatch(watching_since=START)
    now = START + timedelta(minutes=5)
    reading = watch.read(
        None,
        changed_at=None,
        reported_at=None,
        now=now,
        stale_cap=CAP,
        plausible=SUBSTRATE_MOISTURE_RANGE,
    )
    assert reading.invalidity is Invalidity.UNAVAILABLE
    assert watch.invalid_since == now


def test_a_flapping_sensor_alerts_at_most_once_an_hour() -> None:
    watch = SensorWatch(watching_since=START)
    t = START
    _read(watch, "unavailable", reported=t, now=t)
    assert watch.alert(t + DELAY, DELAY) is SensorAlert.INVALID
    first_alert = t + DELAY
    t = first_alert + timedelta(minutes=1)
    _read(watch, "40", reported=t, now=t)
    assert watch.alert(t, DELAY) is SensorAlert.RECOVERED
    t += timedelta(minutes=1)
    _read(watch, "unavailable", reported=t, now=t)
    assert watch.alert(t + DELAY, DELAY) is SensorAlert.NONE
    assert watch.alert(first_alert + REALERT_AFTER, DELAY) is SensorAlert.INVALID


@pytest.mark.parametrize(
    ("cause", "code"),
    [
        (Invalidity.STALE, "sensor_stale"),
        (Invalidity.IMPLAUSIBLE, "sensor_implausible"),
        (Invalidity.UNAVAILABLE, "sensor_unavailable"),
    ],
)
def test_inhibit_reason(cause: Invalidity, code: str) -> None:
    assert inhibit_code(cause) == code
    assert "sensor.vwc" in inhibit_detail("sensor.vwc", cause)


def test_alert_messages() -> None:
    invalid = invalid_alert_message(
        "sensor.vwc", Invalidity.STALE, growspace_name="Tent", since_local="12:03"
    )
    assert invalid == (
        "The moisture sensor sensor.vwc in Tent has had no usable reading since "
        "12:03: it has stopped reporting. Automatic shots are withheld until it "
        "reports a plausible value again."
    )
    assert recovered_alert_message("sensor.vwc", "Tent", 41.5) == (
        "The moisture sensor sensor.vwc in Tent is reporting again (41.5). "
        "Automatic shots resume."
    )
    assert "again. Automatic" in recovered_alert_message("sensor.vwc", "Tent", None)
