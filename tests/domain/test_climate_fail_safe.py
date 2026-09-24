"""The Climate Fail-Safe and Humidity Interlock rules (#792)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.growspace_manager.domain.climate_fail_safe import (
    ClimateRole,
    EpisodeAlert,
    FailSafeEpisode,
    RoleFailure,
    SafeState,
    fail_safe_due,
    failed_alert_message,
    failed_since,
    interlock_wins,
    recovered_alert_message,
    runtime_exceeded,
    safe_action,
)
from custom_components.growspace_manager.domain.sensor_validity import (
    Invalidity,
    SensorReading,
)

T0 = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
VALID = SensorReading(1.0, None, None)
LOST = SensorReading(None, Invalidity.STALE, T0)


def test_a_controller_fails_only_when_every_input_is_lost() -> None:
    """One reading input keeps it seeing; the last loss dates the failure."""
    lost_at = {"sensor.t": T0, "sensor.h": T0 + timedelta(minutes=3)}
    assert failed_since({"sensor.t": LOST, "sensor.h": VALID}, lost_at) is None
    assert failed_since({"sensor.t": LOST, "sensor.h": LOST}, lost_at) == (
        T0 + timedelta(minutes=3)
    )


def test_a_controller_without_inputs_never_fails() -> None:
    """Nothing to read is nothing to lose."""
    assert failed_since({}, {}) is None


@pytest.mark.parametrize(
    ("since", "elapsed", "due"),
    [
        (None, timedelta(hours=1), False),
        (T0, timedelta(minutes=9, seconds=59), False),
        (T0, timedelta(minutes=10), True),
    ],
)
def test_the_fail_safe_waits_out_its_timeout(
    since: datetime | None, elapsed: timedelta, due: bool
) -> None:
    """A shorter loss holds; the timeout itself is enough."""
    assert fail_safe_due(since, T0 + elapsed, timedelta(minutes=10)) is due


@pytest.mark.parametrize(
    ("mine", "partner", "wins"),
    [
        (T0 + timedelta(minutes=1), T0, True),
        (T0, T0, True),
        (T0, T0 + timedelta(minutes=1), False),
        (T0, None, True),
        (None, T0 + timedelta(minutes=1), True),
    ],
)
def test_the_later_demand_wins_the_interlock(
    mine: datetime | None, partner: datetime | None, wins: bool
) -> None:
    """A partner on without a demand, and a Safe State, never lose."""
    assert interlock_wins(mine, partner) is wins


def test_a_runtime_cap_counts_from_the_start_of_the_run() -> None:
    """A device not seen on has no run to cap."""
    cap = timedelta(minutes=30)
    assert not runtime_exceeded(None, T0, cap)
    assert not runtime_exceeded(T0, T0 + timedelta(minutes=29), cap)
    assert runtime_exceeded(T0, T0 + timedelta(minutes=30), cap)


def _failure(*sensors: str) -> RoleFailure:
    return RoleFailure(sensors, T0)


def test_an_episode_alerts_once_and_recovers_once() -> None:
    """The first failure alerts, a joining role updates, the last one recovers."""
    episode = FailSafeEpisode()
    humidifier = {ClimateRole.HUMIDIFIER: _failure("sensor.vpd")}
    both = {**humidifier, ClimateRole.DEHUMIDIFIER: _failure("sensor.vpd")}

    assert episode.update({}, T0) is EpisodeAlert.NONE
    assert episode.update(humidifier, T0) is EpisodeAlert.FAILED
    assert episode.update(humidifier, T0) is EpisodeAlert.NONE
    assert episode.update(both, T0) is EpisodeAlert.UPDATED
    assert episode.update({}, T0) is EpisodeAlert.RECOVERED
    assert episode.update({}, T0) is EpisodeAlert.NONE


def test_a_flapping_sensor_alerts_at_most_hourly() -> None:
    """A new episode inside the re-alert limit stays quiet, and so ends quietly."""
    episode = FailSafeEpisode()
    failed = {ClimateRole.EXHAUST: _failure("sensor.t")}
    episode.update(failed, T0)
    episode.update({}, T0 + timedelta(minutes=5))

    assert episode.update(failed, T0 + timedelta(minutes=20)) is EpisodeAlert.NONE
    assert episode.update({}, T0 + timedelta(minutes=25)) is EpisodeAlert.NONE
    assert episode.update(failed, T0 + timedelta(minutes=61)) is EpisodeAlert.FAILED


@pytest.mark.parametrize(
    ("role", "state", "text"),
    [
        (ClimateRole.HUMIDIFIER, SafeState.OFF, "the humidifier is switched off"),
        (ClimateRole.DEHUMIDIFIER, SafeState.ON, "the dehumidifier is switched on"),
        (ClimateRole.HUMIDIFIER, SafeState.HOLD, "the humidifier is left as it is"),
        (ClimateRole.EXHAUST, None, "the exhaust runs at 40%"),
    ],
)
def test_each_safe_state_says_what_it_does(
    role: ClimateRole, state: SafeState | None, text: str
) -> None:
    """The alert names what each controller does."""
    assert safe_action(role, state, 40) == text


def test_the_alert_names_the_sensor_and_every_action() -> None:
    """One sensor, two devices: one sentence."""
    failed = {
        ClimateRole.HUMIDIFIER: _failure("sensor.vpd"),
        ClimateRole.DEHUMIDIFIER: _failure("sensor.vpd"),
    }
    actions = {
        ClimateRole.HUMIDIFIER: "the humidifier is switched off",
        ClimateRole.DEHUMIDIFIER: "the dehumidifier is switched off",
    }
    message = failed_alert_message("Tent", failed, actions, since_local="12:00")
    assert message == (
        "Climate control in Tent has had no usable reading from the sensor "
        "sensor.vpd since 12:00, so it has gone to its fail-safe: the "
        "dehumidifier is switched off; the humidifier is switched off. Normal "
        "control resumes when the sensor reports again."
    )


def test_the_alert_names_several_sensors_in_the_plural() -> None:
    """The exhaust fails on all of its sensors at once."""
    failed = {ClimateRole.EXHAUST: _failure("sensor.t", "sensor.h")}
    actions = {ClimateRole.EXHAUST: "the exhaust runs at 50%"}
    message = failed_alert_message("Tent", failed, actions, since_local="12:00")
    assert "the sensors sensor.h, sensor.t since" in message
    assert message.endswith("when the sensors report again.")


def test_the_recovery_says_control_resumed() -> None:
    """The recovery message is short and names the growspace."""
    assert "Tent has usable readings again" in recovered_alert_message("Tent")
