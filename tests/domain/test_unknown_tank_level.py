"""Zero-mock tests for the Unknown Tank Level watch (#790)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.growspace_manager.domain.sensor_validity import (
    Invalidity,
    SensorReading,
)
from custom_components.growspace_manager.domain.unknown_tank_level import (
    REALERT_AFTER,
    TankAlert,
    TankWatch,
    UnknownTankLevel,
    offline_alert_message,
    recovered_alert_message,
    unknown_tank_skip_text,
)

START = datetime(2026, 9, 24, 20, 0, tzinfo=UTC)
GRACE = timedelta(minutes=10)
NAME = "Main Tank"
ENTITY = "sensor.main_tank"


def _valid(level: float) -> SensorReading:
    return SensorReading(level, None, None)


def _invalid(
    since: datetime, cause: Invalidity = Invalidity.UNAVAILABLE
) -> SensorReading:
    return SensorReading(None, cause, since)


def _watch() -> TankWatch:
    return TankWatch(watching_since=START)


def _status(watch: TankWatch, now: datetime):
    return watch.status(NAME, ENTITY, now, GRACE)


# --- the gate's view: status() ------------------------------------------------


def test_a_valid_tank_reports_its_level() -> None:
    watch = _watch()
    watch.observe(_valid(42.0))
    status = _status(watch, START)
    assert status.level == 42.0
    assert status.unknown is None


def test_within_grace_the_last_valid_reading_stands_in() -> None:
    watch = _watch()
    watch.observe(_valid(12.0))
    dropped = START + timedelta(minutes=30)
    watch.observe(_invalid(dropped))

    status = _status(watch, dropped + GRACE - timedelta(seconds=1))

    assert status.level == 12.0
    assert status.unknown is None


def test_past_grace_the_level_is_unknown_with_cause_and_since() -> None:
    watch = _watch()
    watch.observe(_valid(60.0))
    dropped = START + timedelta(minutes=30)
    watch.observe(_invalid(dropped, Invalidity.STALE))

    status = _status(watch, dropped + GRACE)

    assert status.level is None
    assert status.unknown == UnknownTankLevel(NAME, ENTITY, Invalidity.STALE, dropped)


def test_a_tank_never_valid_since_the_start_is_unknown_at_once() -> None:
    watch = _watch()
    watch.observe(_invalid(START - timedelta(hours=3)))

    status = _status(watch, START)

    assert status.level is None
    # The episode is never dated before the watch began.
    assert status.unknown == UnknownTankLevel(
        NAME, ENTITY, Invalidity.UNAVAILABLE, START
    )


def test_an_unobserved_tank_is_unknown() -> None:
    status = _status(_watch(), START)
    assert status.unknown is not None
    assert status.unknown.since == START


def test_recovery_ends_the_episode() -> None:
    watch = _watch()
    watch.observe(_valid(60.0))
    watch.observe(_invalid(START))
    watch.observe(_valid(58.0))

    status = _status(watch, START + timedelta(hours=1))

    assert status.level == 58.0
    assert status.unknown is None


def test_the_episode_keeps_its_start_and_follows_the_latest_cause() -> None:
    watch = _watch()
    watch.observe(_valid(60.0))
    first = START + timedelta(minutes=5)
    watch.observe(_invalid(first, Invalidity.STALE))
    watch.observe(_invalid(first + timedelta(minutes=3), Invalidity.UNAVAILABLE))

    status = _status(watch, first + GRACE)

    assert status.unknown == UnknownTankLevel(
        NAME, ENTITY, Invalidity.UNAVAILABLE, first
    )


# --- the alert's view: alert() -------------------------------------------------


def _alert(watch: TankWatch, now: datetime) -> TankAlert:
    return watch.alert(now, GRACE)


def test_no_alert_within_grace_then_one_alert_when_it_runs_out() -> None:
    watch = _watch()
    watch.observe(_valid(60.0))
    dropped = START + timedelta(minutes=1)
    watch.observe(_invalid(dropped))

    assert _alert(watch, dropped + GRACE - timedelta(seconds=1)) is TankAlert.NONE
    assert _alert(watch, dropped + GRACE) is TankAlert.OFFLINE
    assert _alert(watch, dropped + GRACE * 6) is TankAlert.NONE


def test_after_a_start_the_alert_waits_the_grace_even_without_a_valid_reading() -> None:
    watch = _watch()
    watch.observe(_invalid(START - timedelta(hours=1)))

    assert _alert(watch, START + GRACE - timedelta(seconds=1)) is TankAlert.NONE
    assert _alert(watch, START + GRACE) is TankAlert.OFFLINE


def test_recovery_is_announced_only_for_an_episode_that_alerted() -> None:
    watch = _watch()
    watch.observe(_valid(60.0))
    watch.observe(_invalid(START))
    assert _alert(watch, START + GRACE) is TankAlert.OFFLINE
    watch.observe(_valid(59.0))
    assert _alert(watch, START + GRACE * 2) is TankAlert.RECOVERED
    assert _alert(watch, START + GRACE * 3) is TankAlert.NONE

    quiet = _watch()
    quiet.observe(_valid(60.0))
    quiet.observe(_invalid(START))
    quiet.observe(_valid(60.0))
    assert _alert(quiet, START + GRACE) is TankAlert.NONE


def test_a_flapping_probe_is_paged_at_most_once_an_hour() -> None:
    watch = _watch()
    watch.observe(_valid(60.0))
    watch.observe(_invalid(START))
    first_alert = START + GRACE
    assert _alert(watch, first_alert) is TankAlert.OFFLINE
    watch.observe(_valid(60.0))
    assert _alert(watch, first_alert + timedelta(minutes=1)) is TankAlert.RECOVERED

    second_drop = first_alert + timedelta(minutes=10)
    watch.observe(_invalid(second_drop))
    # Past its own grace, but inside the re-alert wait: held back.
    assert _alert(watch, second_drop + GRACE) is TankAlert.NONE
    # Still unknown once the wait ends: alerts then rather than never.
    assert _alert(watch, first_alert + REALERT_AFTER) is TankAlert.OFFLINE


# --- wording -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cause", "stale_after", "fragment"),
    [
        (Invalidity.UNAVAILABLE, 120, "the sensor is unavailable"),
        (Invalidity.STALE, 120, "no report for over 120 minutes"),
        (Invalidity.IMPLAUSIBLE, 120, "its reading is outside 0–100 %"),
    ],
)
def test_offline_alert_message_names_the_cause(
    cause: Invalidity, stale_after: int, fragment: str
) -> None:
    unknown = UnknownTankLevel(NAME, ENTITY, cause, START)
    message = offline_alert_message(
        unknown,
        growspace_name="Tent",
        since_local="20:00",
        stale_after_minutes=stale_after,
        irrigation_paused=True,
    )
    assert message == (
        f"Main Tank in Tent has had no usable level since 20:00: {fragment}. "
        "Irrigation is paused until it reports again."
    )


def test_offline_alert_message_says_when_irrigation_is_not_paused() -> None:
    unknown = UnknownTankLevel(NAME, ENTITY, Invalidity.UNAVAILABLE, START)
    message = offline_alert_message(
        unknown,
        growspace_name="Tent",
        since_local="20:00",
        stale_after_minutes=120,
        irrigation_paused=False,
    )
    assert message.endswith(
        "Irrigation is not paused, because Pause When Tank Is Low is off."
    )


def test_recovered_alert_message() -> None:
    assert (
        recovered_alert_message("Main Tank", "Tent", 57.4)
        == "Main Tank in Tent is reporting again (57%)."
    )


def test_unknown_tank_skip_text() -> None:
    unknown = UnknownTankLevel(NAME, ENTITY, Invalidity.STALE, START)
    assert (
        unknown_tank_skip_text(unknown) == "tank 'Main Tank' level is unknown (stale)"
    )
