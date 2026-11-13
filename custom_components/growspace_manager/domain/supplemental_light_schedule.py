"""Resolve supplemental windows on the same local clock as the main lights."""

from dataclasses import dataclass

from ..models.supplemental_light import (
    LightAnchor,
    LightWindowEndpoint,
    SupplementalLightWindow,
)

DAY_MINUTES = 24 * 60


@dataclass(frozen=True, slots=True, order=True)
class LightPeriod:
    """Half-open interval in minutes from the start of the main cycle."""

    start: int
    end: int

    def resolve(self, main_start: int) -> dict[str, str]:
        """Display the endpoints as local HH:MM clock times."""

        def clock_time(offset: int) -> str:
            hour, minute = divmod((main_start + offset) % DAY_MINUTES, 60)
            return f"{hour:02d}:{minute:02d}"

        return {"start": clock_time(self.start), "end": clock_time(self.end)}


def resolve_windows(
    windows: list[SupplementalLightWindow], duration: int
) -> tuple[list[LightPeriod], list[str]]:
    """Return the union of valid windows and explain each skipped window."""

    def offset(endpoint: LightWindowEndpoint) -> int:
        anchor = duration if endpoint.anchor == LightAnchor.OFF else 0
        return anchor + endpoint.offset_minutes

    valid: list[LightPeriod] = []
    reasons: list[str] = []
    for index, window in enumerate(windows, start=1):
        start, end = offset(window.start), offset(window.end)
        if start >= end:
            reasons.append(f"Window {index} must end after it starts.")
        elif start < 0 or end > duration:
            reasons.append(f"Window {index} is outside the planned main-light cycle.")
        else:
            valid.append(LightPeriod(start, end))

    periods: list[LightPeriod] = []
    for period in sorted(valid):
        if periods and period.start <= periods[-1].end:
            previous = periods.pop()
            period = LightPeriod(previous.start, max(previous.end, period.end))
        periods.append(period)
    return periods, reasons


def current_or_next_period(
    periods: list[LightPeriod], elapsed: int
) -> tuple[LightPeriod | None, bool]:
    """Find the active period or next start, wrapping to tomorrow when needed."""
    for period in periods:
        if elapsed < period.end:
            return period, elapsed >= period.start
    return (periods[0] if periods else None), False
