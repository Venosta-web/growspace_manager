"""Metered volume over an actuator-confirmed window (ADR-0064)."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.growspace_manager.domain.metering_window import (
    MeterAbsence,
    MeteringWindow,
    MeterReading,
    integrate_meter,
)

ON = datetime(2026, 9, 28, tzinfo=UTC)


def at(seconds: float) -> datetime:
    return ON + timedelta(seconds=seconds)


def readings(*pairs: tuple[float, float | None]) -> list[MeterReading]:
    return [MeterReading(at(seconds), value) for seconds, value in pairs]


def test_cumulative_sums_late_reports_and_counts_a_reset_from_zero() -> None:
    window = MeteringWindow(ON, at(10), next_on_commanded_at=at(25))

    assert (
        integrate_meter(
            "cumulative_total",
            window,
            readings((-2, 11), (6, 13), (10, 14), (16, 1), (20, 2), (25, 50)),
        )
        == 5
    )


def test_rate_holds_each_reading_to_the_next_and_stops_at_the_tail() -> None:
    window = MeteringWindow(ON, at(5))
    assert integrate_meter(
        "rate", window, readings((-1, 0.1), (5, 0.2), (10, 0.1), (70, 1))
    ) == pytest.approx(7)


@pytest.mark.parametrize(
    ("kind", "off", "reports", "reason"),
    [
        ("cumulative_total", None, [(-1, 1), (11, 2)], MeterAbsence.STALE),
        ("cumulative_total", 10, [(-1, 1), (10, 2), (71, 3)], MeterAbsence.STALE),
        ("cumulative_total", 10, [(11, 2)], MeterAbsence.STALE),
        ("rate", 10, [(-1, 0.1), (71, 0)], MeterAbsence.STALE),
        ("rate", 10, [(1, 0.1)], MeterAbsence.STALE),
        ("rate", 10, [(-1, 0.1), (5, None), (6, 0)], MeterAbsence.UNAVAILABLE),
        (
            "cumulative_total",
            10,
            [(-1, 1), (15, None), (20, 4)],
            MeterAbsence.UNAVAILABLE,
        ),
    ],
)
def test_unusable_readings_have_an_absence_reason(kind, off, reports, reason) -> None:
    assert (
        integrate_meter(
            kind,
            MeteringWindow(ON, None if off is None else at(off)),
            readings(*reports),
        )
        is reason
    )


def test_rate_can_start_at_the_on_readback_and_measure_zero() -> None:
    assert integrate_meter("rate", MeteringWindow(ON, at(10)), readings((0, 0))) == 0


def test_a_cumulative_report_exactly_at_the_end_of_the_tail_counts() -> None:
    assert (
        integrate_meter(
            "cumulative_total", MeteringWindow(ON, at(10)), readings((-1, 1), (70, 2))
        )
        == 1
    )
