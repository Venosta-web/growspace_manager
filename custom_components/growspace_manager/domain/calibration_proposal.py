"""The Calibration Proposal: a corrected flow rate, offered and never applied.

A corrected ``pump_flow_rate_ml_per_sec`` changes how long every volume-sized
shot runs and what the daily cap charges, so it is only ever **proposed**, as a
fixable Repairs issue the grower applies (ADR-0064 item 7).

This module builds the proposal from its first source, the tank. A raised
[[Tank–Pump Disagreement]] says the tank drop and the pump figure have parted
company for days; the ratio of the two on the disagreeing days is what the
configured rate is off by, if the flow rate is the cause. The tank cannot say
which zone its water went to, and a zone with a meter has better evidence, so a
tank-sourced proposal exists only for a growspace with **one zone and no meter
on it**. The meter-sourced proposal will reuse the same shape.

A ratio close to a common unit mix-up is not a flow rate the grower got wrong:
it is a unit declared wrong somewhere, and proposing it would rescale every
shot by that factor. The **unit guard** withholds Apply for it, and the issue
names the entity whose unit to check instead.

Everything here is arithmetic over the disagreement's judged days. It reads no
sensor and touches no ``hass``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import statistics

from .tank_pump_disagreement import DayComparison, DayVerdict, TankPumpDisagreement


@dataclass(frozen=True, slots=True)
class UnitMixUp:
    """A factor that a wrong declared unit produces, and the units that make it."""

    factor: float
    units: str


#: The ratios a unit mix-up produces rather than a wrong flow rate.
UNIT_MIX_UPS: tuple[UnitMixUp, ...] = (
    UnitMixUp(3.785, "gallons and litres"),
    UnitMixUp(0.264, "gallons and litres"),
    UnitMixUp(1000.0, "litres and cubic metres or millilitres"),
    UnitMixUp(0.001, "litres and cubic metres or millilitres"),
)
#: How close to a mix-up factor, as a share of it, a ratio has to be.
UNIT_GUARD_TOLERANCE = 0.05


def unit_mix_up(ratio: float) -> UnitMixUp | None:
    """Return the unit mix-up ``ratio`` is within 5% of, if any."""
    return next(
        (
            mix_up
            for mix_up in UNIT_MIX_UPS
            if abs(ratio - mix_up.factor) <= UNIT_GUARD_TOLERANCE * mix_up.factor
        ),
        None,
    )


def tank_ratios(days: Iterable[DayComparison]) -> list[float]:
    """Return tank drop ÷ pump figure for each disagreeing day.

    A day where either side is zero says the pump is not drawing from this tank,
    or the tank is not moving; neither is a flow rate off by some factor, so it
    is not evidence.
    """
    return [
        day.tank_l / day.pump_l
        for day in days
        if day.verdict is DayVerdict.DISAGREES and day.tank_l > 0 and day.pump_l > 0
    ]


def tank_evidence_applies(*, zones: int, zone_metered: bool) -> bool:
    """Whether the tank may speak for the zone: one zone, and no meter on it."""
    return zones == 1 and not zone_metered


@dataclass(frozen=True, slots=True)
class CalibrationProposal:
    """A corrected flow rate for one zone, and the evidence behind it.

    ``entities`` are the sensors the evidence was read from, which the unit
    guard names when the ratio looks like a mix-up rather than a wrong rate.
    """

    configured_ml_per_sec: float
    median_ratio: float
    evidence_count: int
    entities: tuple[str, ...]

    @property
    def proposed_ml_per_sec(self) -> float:
        """The configured rate corrected by the median ratio."""
        return round(self.configured_ml_per_sec * self.median_ratio, 2)

    @property
    def mix_up(self) -> UnitMixUp | None:
        """The unit mix-up the ratio looks like, which withholds Apply."""
        return unit_mix_up(self.median_ratio)

    @property
    def applicable(self) -> bool:
        """Whether the grower may apply it, rather than check a unit."""
        return self.mix_up is None


def tank_sourced_proposal(
    disagreement: TankPumpDisagreement,
    *,
    configured_ml_per_sec: float,
    zones: int,
    zone_metered: bool,
) -> CalibrationProposal | None:
    """Propose a corrected rate from a raised Tank–Pump Disagreement, if one fits.

    It proposes the configured rate × the median, over the disagreeing days,
    of the tank drop ÷ the pump figure. There is nothing to propose while the
    disagreement is not raised, when the tank cannot be attributed to the zone,
    when no rate is configured to correct, or when no disagreeing day has
    water on both sides.
    """
    if (
        disagreement.raised_on is None
        or not tank_evidence_applies(zones=zones, zone_metered=zone_metered)
        or configured_ml_per_sec <= 0
    ):
        return None
    ratios = tank_ratios(disagreement.days)
    if not ratios:
        return None
    proposal = CalibrationProposal(
        configured_ml_per_sec=configured_ml_per_sec,
        median_ratio=statistics.median(ratios),
        evidence_count=len(ratios),
        entities=disagreement.tanks,
    )
    return proposal if proposal.proposed_ml_per_sec > 0 else None
