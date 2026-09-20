"""When a measurement stops being true, and when it only stops being fresh.

Two different things, and the product's whole position on calibration is that
they must not be confused.

**Elapsed time does not revoke a calibration.** A printer measured a year ago
and untouched since still puts ink where it put ink; refusing to print
because a date passed would teach operators that the calibration flow is a
formality to be clicked through. So age produces a **warning** that recommends
a check, and never a refusal.

**A changed dependency does.** The moment the resolution, the printhead, the
declared Printable Area, the density mapping, the calibrated limits, the
compiler, the renderer, the adapter, the fonts, the catalogues, the
calibration sheet or the firmware moves, the numbers on file describe a
printer driven differently from the one about to print. That is a refusal, and
it arrives **naming the field that moved** -- because "recalibrate" without a
reason is indistinguishable from the product having forgotten.

The scope is not in either list. A record of another printer, another stock or
another mounting is not a stale calibration of this print; it is a calibration
of something else, and the answer is that there is none here yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .records import CalibrationDependencies, LocalCalibration

#: There is a current measurement for this printer, and everything it depended
#: on still holds.
CURRENT = "current"
#: There is a measurement, and something it depended on has changed.
STALE = "stale"
#: This printer, stock and mounting has never been measured here.
ABSENT = "absent"

#: After this long, the UI recommends a check. It refuses nothing, and it is
#: a recommendation rather than an expiry: media changes and maintenance are
#: what actually move a printer's registration, and neither follows a
#: calendar. Ninety days is simply often enough that a roll change since the
#: last measurement is likely.
RECHECK_AFTER = timedelta(days=90)

#: The one warning this module raises, spelled as a code so a client can
#: localize it rather than parse prose.
AGE_WARNING = "calibration_older_than_recommended"


@dataclass(frozen=True, slots=True)
class CalibrationStatus:
    """Whether one printer's measurement may authorize a production print.

    `stale_reasons` and `warnings` are deliberately separate lists rather than
    one list of severities: the first blocks and the second does not, and a
    client that had to sort them by severity would eventually sort one wrong.
    """

    state: str
    record: LocalCalibration | None = None
    stale_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    #: How old the record is, where there is one. Reported even when nothing
    #: is wrong, because "measured 4 days ago" is the answer to the question
    #: an operator actually has.
    age_days: int | None = None

    @property
    def is_current(self) -> bool:
        """Whether a production print may proceed on this measurement."""
        return self.state == CURRENT

    @property
    def identity(self) -> str | None:
        """The identity a Render Context carries, or nothing to carry.

        A stale record contributes no identity on purpose. Its numbers are on
        file and its audit value is intact, but a raster must not be cached or
        authorized against a measurement that has stopped describing the
        printer it will come out of.
        """
        if self.record is None or not self.is_current:
            return None
        return self.record.identity

    def as_dict(self) -> dict[str, Any]:
        """Return the status's wire form."""
        return {
            "state": self.state,
            "identity": self.identity,
            "stale_reasons": list(self.stale_reasons),
            "warnings": list(self.warnings),
            "age_days": self.age_days,
            "record": self.record.summary() if self.record else None,
        }


def evaluate(
    record: LocalCalibration | None,
    *,
    required: CalibrationDependencies,
    now: datetime,
) -> CalibrationStatus:
    """Judge one printer's newest measurement against what a print needs now.

    `record` is already scoped: the caller has selected the newest measurement
    of this device, stock and orientation, so an absent one means unmeasured
    rather than superseded.
    """
    if record is None:
        return CalibrationStatus(state=ABSENT)

    age = _age_days(record, now=now)
    warnings = (
        (AGE_WARNING,)
        if age is not None and timedelta(days=age) >= RECHECK_AFTER
        else ()
    )
    reasons = record.dependencies.differences(required)
    if reasons:
        return CalibrationStatus(
            state=STALE,
            record=record,
            stale_reasons=reasons,
            warnings=warnings,
            age_days=age,
        )
    return CalibrationStatus(
        state=CURRENT, record=record, warnings=warnings, age_days=age
    )


def _age_days(record: LocalCalibration, *, now: datetime) -> int | None:
    """How many whole days ago this was measured, or nothing if it cannot say.

    A record whose timestamp this installation cannot parse reports no age
    rather than an invented one. It stays usable: the timestamp is provenance,
    and losing the recommendation to re-check is a smaller harm than refusing
    a measurement that is otherwise intact.
    """
    try:
        recorded = datetime.fromisoformat(record.recorded_at)
    except ValueError:
        return None
    if recorded.tzinfo is None or now.tzinfo is None:
        return None
    return max((now - recorded).days, 0)
