"""Whether a control input's reading can be trusted right now (#789).

A reading is usable only while it is **available** (a number), **plausible**
(inside the quantity's physical range) and **fresh** (reported within its
validity window). An invalid reading is ``None`` with the reason and the moment
it stopped being trustworthy — it never becomes 0, which would look like an
empty tank or a bone-dry substrate and drive an actuator.

Freshness reads ``last_reported``, which Home Assistant moves on every report,
including one that repeats the previous value, so a steady sensor that is still
speaking is never stale; only one that has stopped is.

The window is the sensor's [[Observation Validity Window]]: three times the
interval it has been seen to report at, capped by configuration, and the cap
alone until enough reports have been seen to learn an interval. A tank keeps
its own fixed window (ADR-0050).

``SensorWatch`` carries one sensor across ticks: the learned cadence, and the
invalid episode that raises one alert after a delay and one recovery message —
the ``TankWatch`` pattern without a tank's grace, because a control input that
cannot be trusted withholds shots at once.

Pure: the shell hands in the raw state string and its timestamps.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
import math


class Invalidity(StrEnum):
    """Why a reading cannot be trusted."""

    UNAVAILABLE = "unavailable"
    STALE = "stale"
    IMPLAUSIBLE = "implausible"


@dataclass(frozen=True, slots=True)
class PlausibleRange:
    """The physical range of one quantity, inclusive unless ``low_exclusive``."""

    low: float
    high: float
    low_exclusive: bool = False

    def contains(self, value: float) -> bool:
        """Return whether ``value`` is a finite number inside the range."""
        if not math.isfinite(value) or value > self.high:
            return False
        return value > self.low if self.low_exclusive else value >= self.low


TANK_LEVEL_RANGE = PlausibleRange(0.0, 100.0)
SUBSTRATE_MOISTURE_RANGE = PlausibleRange(0.0, 100.0)
# A probe pulled out of the substrate reads 0 in air, which looks bone-dry;
# growers whose probes do that opt into calling 0 implausible.
SUBSTRATE_MOISTURE_RANGE_WITHOUT_ZERO = PlausibleRange(0.0, 100.0, low_exclusive=True)
PORE_EC_RANGE = PlausibleRange(0.0, 20.0)  # mS/cm
HUMIDITY_RANGE = PlausibleRange(0.0, 100.0)
VPD_RANGE = PlausibleRange(0.0, 10.0)  # kPa
CELSIUS_RANGE = PlausibleRange(-10.0, 60.0)
FAHRENHEIT_RANGE = PlausibleRange(14.0, 140.0)
# A temperature without a unit could be either scale; accept both.
UNITLESS_TEMPERATURE_RANGE = PlausibleRange(-10.0, 140.0)

_MICROSIEMENS = frozenset({"µS/cm", "μS/cm", "uS/cm"})


def substrate_moisture_range(*, zero_is_implausible: bool) -> PlausibleRange:
    """Return the substrate moisture range, with or without 0 in it."""
    return (
        SUBSTRATE_MOISTURE_RANGE_WITHOUT_ZERO
        if zero_is_implausible
        else SUBSTRATE_MOISTURE_RANGE
    )


def temperature_range(unit: str | None) -> PlausibleRange:
    """Return the plausible temperature range in the sensor's own unit.

    Values are never converted: a grower on °F sets their targets in °F too.
    """
    if unit == "°C":
        return CELSIUS_RANGE
    if unit == "°F":
        return FAHRENHEIT_RANGE
    return UNITLESS_TEMPERATURE_RANGE


def ec_scale(unit: str | None) -> float:
    """Return the factor that brings an EC reading to mS/cm."""
    return 0.001 if unit in _MICROSIEMENS else 1.0


@dataclass(frozen=True, slots=True)
class SensorReading:
    """A validated reading: a value, or why there is none and since when.

    ``invalid_since`` is None for a valid reading, and for an entity that does
    not exist, whose invalidity has no date of its own.
    """

    value: float | None
    invalidity: Invalidity | None
    invalid_since: datetime | None

    @property
    def valid(self) -> bool:
        """Return whether the reading can be acted on."""
        return self.invalidity is None


def parse_numeric_state(raw: str | None) -> float | None:
    """Parse a state string into a number, or None when it is not one.

    Accepts a trailing ``%`` and a decimal comma, as tank sensors have been seen
    to report. ``nan`` and ``inf`` parse, so the plausibility check can name
    them rather than calling them unavailable.
    """
    if not raw:
        return None
    try:
        return float(raw.replace("%", "").strip().replace(",", "."))
    except ValueError:
        return None


def validate_reading(
    raw: str | None,
    *,
    changed_at: datetime | None,
    reported_at: datetime | None,
    now: datetime,
    max_age: timedelta | None,
    plausible: PlausibleRange,
    scale: float = 1.0,
) -> SensorReading:
    """Validate one raw state against availability, plausibility and age.

    ``raw`` is ``None`` when the entity does not exist. An unavailable or
    implausible reading is invalid from ``changed_at``, when the state took that
    value — undated for an entity that does not exist, which the caller dates;
    a stale one from the moment its window ran out. Implausible outranks stale,
    since it says more about what is wrong. ``max_age=None`` never goes stale,
    for a sensor that reports only when its value changes. ``scale`` brings the
    value to the range's unit before it is judged.
    """
    value = parse_numeric_state(raw)
    if value is None:
        return SensorReading(None, Invalidity.UNAVAILABLE, changed_at)
    value *= scale
    if not plausible.contains(value):
        return SensorReading(None, Invalidity.IMPLAUSIBLE, changed_at)
    if max_age is not None and reported_at is not None and now - reported_at > max_age:
        return SensorReading(None, Invalidity.STALE, reported_at + max_age)
    return SensorReading(value, None, None)


# The Observation Validity Window: this many expected update intervals.
WINDOW_INTERVALS = 3
# Never shorter than this, so a sensor that reports every few seconds is not
# stale after one late report — the control loops tick once a minute anyway.
WINDOW_FLOOR = timedelta(minutes=5)
# How many recent report intervals the cadence remembers, and how many it needs
# before it trusts itself over the cap.
CADENCE_SAMPLES = 8
MIN_CADENCE_SAMPLES = 3


@dataclass(slots=True)
class ReportCadence:
    """The interval one sensor has been seen to report at."""

    last_reported: datetime | None = None
    intervals: deque[timedelta] = field(
        default_factory=lambda: deque(maxlen=CADENCE_SAMPLES)
    )

    def observe(self, reported_at: datetime) -> None:
        """Fold one report time in; a time already seen adds nothing."""
        if self.last_reported is not None and reported_at <= self.last_reported:
            return
        if self.last_reported is not None:
            self.intervals.append(reported_at - self.last_reported)
        self.last_reported = reported_at

    @property
    def expected_interval(self) -> timedelta | None:
        """Return the (upper) median recent interval, or None until enough are seen.

        A median, so one long gap or one burst of reports does not move it.
        """
        if len(self.intervals) < MIN_CADENCE_SAMPLES:
            return None
        ordered = sorted(self.intervals)
        return ordered[len(ordered) // 2]


def validity_window(
    expected_interval: timedelta | None, cap: timedelta | None
) -> timedelta | None:
    """Return the Observation Validity Window, or None when staleness is off."""
    if cap is None:
        return None
    if expected_interval is None:
        return cap
    return min(max(expected_interval * WINDOW_INTERVALS, WINDOW_FLOOR), cap)


# A new episode's alert waits this long after the previous alert, so a sensor
# that drops out every hour does not page every hour (ADR-0050).
REALERT_AFTER = timedelta(minutes=60)
DEFAULT_SENSOR_STALE_AFTER_MINUTES = 30
DEFAULT_SENSOR_ALERT_DELAY_MINUTES = 15


class SensorAlert(StrEnum):
    """What a sensor's alert should say after one watch tick."""

    NONE = "none"
    INVALID = "invalid"
    RECOVERED = "recovered"


@dataclass(slots=True)
class SensorWatch:
    """One sensor's cadence and invalid episode.

    ``invalid_since`` is set while the sensor is invalid, and never earlier than
    ``watching_since``, so a sensor that was already down at a restart waits out
    the alert delay like any other; ``alerted`` is set once the episode alerted.
    """

    watching_since: datetime
    cadence: ReportCadence = field(default_factory=ReportCadence)
    invalid_since: datetime | None = None
    cause: Invalidity | None = None
    last_valid_value: float | None = None
    alerted: bool = False
    last_alert_at: datetime | None = None

    def read(
        self,
        raw: str | None,
        *,
        changed_at: datetime | None,
        reported_at: datetime | None,
        now: datetime,
        stale_cap: timedelta | None,
        plausible: PlausibleRange,
        scale: float = 1.0,
    ) -> SensorReading:
        """Validate one state against the learned window, and fold it in.

        Only numeric reports teach the cadence, so a sensor flapping to
        ``unavailable`` does not look like one that reports often.
        """
        if reported_at is not None and parse_numeric_state(raw) is not None:
            self.cadence.observe(reported_at)
        reading = validate_reading(
            raw,
            changed_at=changed_at,
            reported_at=reported_at,
            now=now,
            max_age=validity_window(self.cadence.expected_interval, stale_cap),
            plausible=plausible,
            scale=scale,
        )
        self.observe(reading, now)
        return reading

    def observe(self, reading: SensorReading, now: datetime) -> None:
        """Fold one validated reading into the episode."""
        if reading.invalidity is None:
            self.last_valid_value = reading.value
            self.invalid_since = None
            self.cause = None
            return
        self.cause = reading.invalidity
        if self.invalid_since is None:
            since = reading.invalid_since or now
            self.invalid_since = max(since, self.watching_since)

    def alert(self, now: datetime, delay: timedelta) -> SensorAlert:
        """Advance the episode and return what, if anything, to announce."""
        if self.invalid_since is None:
            if self.alerted:
                self.alerted = False
                return SensorAlert.RECOVERED
            return SensorAlert.NONE
        if self.alerted or now - self.invalid_since < delay:
            return SensorAlert.NONE
        if self.last_alert_at is not None and now - self.last_alert_at < REALERT_AFTER:
            return SensorAlert.NONE
        self.alerted = True
        self.last_alert_at = now
        return SensorAlert.INVALID


def inhibit_code(cause: Invalidity) -> str:
    """Return the controller's inhibit reason code for an invalid control input."""
    return f"sensor_{cause.value}"


_CAUSE_TEXT = {
    Invalidity.UNAVAILABLE: "it is unavailable",
    Invalidity.STALE: "it has stopped reporting",
    Invalidity.IMPLAUSIBLE: "its reading is outside the plausible range",
}


def inhibit_detail(entity_id: str, cause: Invalidity) -> str:
    """Return the inhibit's human context."""
    return f"control sensor {entity_id} cannot be trusted: {_CAUSE_TEXT[cause]}"


def invalid_alert_message(
    entity_id: str, cause: Invalidity, *, growspace_name: str, since_local: str
) -> str:
    """Return the text of an invalid control sensor's alert."""
    return (
        f"The moisture sensor {entity_id} in {growspace_name} has had no usable "
        f"reading since {since_local}: {_CAUSE_TEXT[cause]}. Automatic shots are "
        "withheld until it reports a plausible value again."
    )


def recovered_alert_message(
    entity_id: str, growspace_name: str, value: float | None
) -> str:
    """Return the text announcing that an alerted sensor reads again."""
    reading = f" ({value:g})" if value is not None else ""
    return (
        f"The moisture sensor {entity_id} in {growspace_name} is reporting "
        f"again{reading}. Automatic shots resume."
    )
