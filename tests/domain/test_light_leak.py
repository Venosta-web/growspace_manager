"""Tests for the Light Leak Guard's pure decisions (#794)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest

from custom_components.growspace_manager.domain.light_leak import (
    EpisodeTransition,
    LeakCause,
    LightLeakEpisode,
    in_watched_dark_period,
    leak_causes,
)


@dataclass
class _Plant:
    flower_start: str | None


def _watched(
    now: datetime,
    plants: list[_Plant],
    *,
    lights_on_time: str = "06:00:00",
    all_stages: bool = False,
) -> bool:
    return in_watched_dark_period(
        now,
        plants,
        lights_on_time=lights_on_time,
        veg_hours=18,
        flower_hours=12,
        all_stages=all_stages,
    )


# ---------------------------------------------------------------------------
# The watched dark period, across the photoperiod flip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("now", "flower_start", "expected"),
    [
        # Flip day: the six hours the 12h day gives up are dark already.
        (datetime(2026, 7, 3, 20, 0), "2026-07-03", True),
        (datetime(2026, 7, 3, 18, 0), "2026-07-03T00:00:00+00:00", True),
        (datetime(2026, 7, 3, 17, 59), "2026-07-03", False),
        # The night before the flip is still a veg night, and veg is not watched.
        (datetime(2026, 7, 2, 20, 0), "2026-07-03", False),
        (datetime(2026, 7, 3, 2, 0), "2026-07-04", False),
        # Well into flower: watched in the dark, never in the light.
        (datetime(2026, 7, 20, 3, 0), "2026-07-03", True),
        (datetime(2026, 7, 20, 12, 0), "2026-07-03", False),
        # An unusable flower_start counts as not flowering.
        (datetime(2026, 7, 20, 3, 0), "not-a-date", False),
        (datetime(2026, 7, 20, 3, 0), None, False),
    ],
)
def test_dark_period_follows_the_flip(
    now: datetime, flower_start: str | None, expected: bool
) -> None:
    """The guard's dark period is the controller's, flip day included."""
    assert _watched(now, [_Plant(flower_start)]) is expected


def test_one_flowering_plant_is_enough() -> None:
    """A mixed growspace is flowering once any plant has flipped."""
    plants = [_Plant(None), _Plant("2026-07-01")]
    assert _watched(datetime(2026, 7, 3, 20, 0), plants) is True


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 7, 3, 20, 0), False),  # inside the 18h veg day
        (datetime(2026, 7, 3, 2, 0), True),  # veg night
    ],
)
def test_all_stages_watches_the_veg_night(now: datetime, expected: bool) -> None:
    """``all_stages`` watches a veg growspace against its veg photoperiod."""
    assert _watched(now, [], all_stages=True) is expected


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 7, 20, 7, 59), False),
        (datetime(2026, 7, 20, 8, 0), True),
        (datetime(2026, 7, 20, 19, 59), True),
        (datetime(2026, 7, 20, 20, 0), False),
    ],
)
def test_dark_period_wraps_midnight(now: datetime, expected: bool) -> None:
    """A lights-on in the evening puts the dark period across the day."""
    plants = [_Plant("2026-07-01")]
    assert _watched(now, plants, lights_on_time="20:00") is expected


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("managed_light_on", "illuminance", "expected"),
    [
        (False, None, set()),
        (False, 0.0, set()),
        (False, 1.0, set()),  # at the threshold is not above it
        (False, 1.5, {LeakCause.ILLUMINANCE}),
        (True, None, {LeakCause.MANAGED_LIGHT_ON}),
        (True, 40.0, {LeakCause.MANAGED_LIGHT_ON, LeakCause.ILLUMINANCE}),
    ],
)
def test_leak_causes(
    managed_light_on: bool, illuminance: float | None, expected: set[LeakCause]
) -> None:
    """Each reading contributes its own cause; an unreadable sensor none."""
    causes = leak_causes(
        managed_light_on=managed_light_on,
        illuminance=illuminance,
        threshold_lux=1.0,
    )
    assert causes == frozenset(expected)


# ---------------------------------------------------------------------------
# Episodes
# ---------------------------------------------------------------------------

_T0 = datetime(2026, 7, 3, 20, 0)
_DEBOUNCE = timedelta(minutes=2)


def _run(episode: LightLeakEpisode, readings: list[bool]) -> list[EpisodeTransition]:
    """Observe one reading a minute from _T0."""
    return [
        episode.observe(_T0 + timedelta(minutes=i), leaking, _DEBOUNCE)
        for i, leaking in enumerate(readings)
    ]


def test_episode_confirms_once_after_the_debounce() -> None:
    """Evidence alerts once it has held for the debounce, then stays quiet."""
    transitions = _run(LightLeakEpisode(), [True, True, True, True, True])
    assert transitions == [
        EpisodeTransition.NONE,
        EpisodeTransition.NONE,
        EpisodeTransition.CONFIRMED,
        EpisodeTransition.NONE,
        EpisodeTransition.NONE,
    ]


def test_evidence_shorter_than_the_debounce_never_alerts() -> None:
    """A brief flash — a door opened and closed — is not an episode."""
    transitions = _run(LightLeakEpisode(), [True, True, False, True, True, False])
    assert EpisodeTransition.CONFIRMED not in transitions
    assert EpisodeTransition.CLEARED not in transitions


def test_confirmed_episode_clears_and_the_next_one_alerts_again() -> None:
    """Clearing ends the episode; a fresh run of evidence is a new one."""
    transitions = _run(LightLeakEpisode(), [True, True, True, False, True, True, True])
    assert transitions == [
        EpisodeTransition.NONE,
        EpisodeTransition.NONE,
        EpisodeTransition.CONFIRMED,
        EpisodeTransition.CLEARED,
        EpisodeTransition.NONE,
        EpisodeTransition.NONE,
        EpisodeTransition.CONFIRMED,
    ]


def test_zero_debounce_confirms_on_first_sight() -> None:
    """A debounce of zero alerts on the first reading."""
    episode = LightLeakEpisode()
    assert episode.observe(_T0, True, timedelta(0)) is EpisodeTransition.CONFIRMED


def test_duration_measures_the_current_run() -> None:
    """Duration runs from the first reading of evidence, and is zero without."""
    episode = LightLeakEpisode()
    assert episode.duration(_T0) == timedelta(0)
    _run(episode, [True, True, True, True])
    assert episode.duration(_T0 + timedelta(minutes=3)) == timedelta(minutes=3)
