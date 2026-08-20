"""Tests for the Infiltration Monitor seam (domain/infiltration.py).

The monitor is a stateful controller (the ShotComposer / Steering Phase Machine
mould), so these drive it with deterministic ``record``/``reset`` sequences and
plain values — no coordinator, no Home Assistant, no mocks. The sampling rule is
the point of the module: samples come from *distinct sensor updates*, so the
sequences here mimic a probe reporting slower than the minute loop reads it.
"""

from datetime import UTC, datetime, timedelta

from custom_components.growspace_manager.domain.infiltration import (
    InfiltrationMonitor,
    InfiltrationState,
)

_T0 = datetime(2023, 1, 1, 12, 0, tzinfo=UTC)


def _at(minutes: float) -> datetime:
    """Return a sensor update timestamp ``minutes`` after the reference start."""
    return _T0 + timedelta(minutes=minutes)


def test_rising_vwc_across_distinct_updates_is_infiltrating() -> None:
    """VWC climbing between two distinct sensor updates reads INFILTRATING."""
    monitor = InfiltrationMonitor()

    monitor.record(50.0, _at(0))
    monitor.record(54.0, _at(5))

    assert monitor.state is InfiltrationState.INFILTRATING


def test_repeated_reads_of_an_unchanged_sensor_add_no_samples() -> None:
    """A probe that has not updated yet yields UNKNOWN, never a flat slope.

    The minute loop re-reads the same sensor state every tick. Those repeats are
    not measurements, so five of them leave the monitor with one distinct sample
    — "flat because no new data" must not read as SETTLED.
    """
    monitor = InfiltrationMonitor()

    for _ in range(5):
        monitor.record(50.0, _at(0))

    assert monitor.state is InfiltrationState.UNKNOWN


def test_flat_vwc_across_distinct_updates_is_settled() -> None:
    """Distinct updates that barely move read SETTLED: the water has spread."""
    monitor = InfiltrationMonitor()

    monitor.record(54.0, _at(0))
    monitor.record(54.02, _at(5))

    assert monitor.state is InfiltrationState.SETTLED


def test_falling_vwc_is_drying() -> None:
    """VWC dropping past the deadband reads DRYING: the dryback has begun."""
    monitor = InfiltrationMonitor()

    monitor.record(54.0, _at(0))
    monitor.record(52.0, _at(10))

    assert monitor.state is InfiltrationState.DRYING


def test_a_sample_older_than_the_window_does_not_anchor_a_slope() -> None:
    """One fresh reading beside an hour-old one is UNKNOWN, not a flat slope.

    Infiltration spans minutes, so a sample from an hour ago says nothing about
    the current one; averaging across the gap would manufacture a near-zero
    slope and report SETTLED on what is really an absence of data.
    """
    monitor = InfiltrationMonitor()

    monitor.record(50.0, _at(0))
    monitor.record(50.1, _at(60))

    assert monitor.state is InfiltrationState.UNKNOWN


def test_probe_slower_than_the_loop_yields_a_real_slope() -> None:
    """A 5-minute probe read every minute still measures infiltration.

    The failure this guards is the whole reason the monitor exists: a slope
    computed over loop ticks reads exactly `0` between probe updates and would
    report SETTLED mid-infiltration, failing hardest on the slow and averaged
    sensors that need the feature most.
    """
    monitor = InfiltrationMonitor()

    monitor.record(50.0, _at(0))
    for tick in range(1, 5):
        monitor.record(50.0, _at(0))  # same sensor state, re-read each minute
        assert monitor.state is not InfiltrationState.SETTLED, f"tick {tick}"
    monitor.record(54.0, _at(5))

    assert monitor.state is InfiltrationState.INFILTRATING


def test_reset_discards_the_measurement() -> None:
    """After a sensor loss the monitor reports UNKNOWN until it re-measures.

    Readings from either side of a dropout are not a slope — the substrate moved
    while nobody was watching — so ``reset()`` drops the buffer and the first
    reading afterwards is a fresh anchor, not a continuation.
    """
    monitor = InfiltrationMonitor()
    monitor.record(50.0, _at(0))
    monitor.record(54.0, _at(5))

    monitor.reset()
    monitor.record(52.0, _at(10))

    assert monitor.state is InfiltrationState.UNKNOWN
