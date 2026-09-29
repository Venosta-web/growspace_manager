"""Pure decision for whether a base pump cycle may fire — the Pump Cycle Gate.

This module holds the skip/fire decision for an irrigation or drain pump cycle
(ADR-0021). It is deliberately free of Home Assistant and coordinator
dependencies: the coordinator resolves sensors into ``TankReading``s, the tanks
at an Unknown Tank Level (ADR-0050) and a ``lights_dark`` bool, computes the cycle volume, then asks ``decide_cycle`` for
a :class:`CycleVerdict`. The coordinator owns every resulting effect — the
warning log, the low-tank persistent notification, the logbook entry, the pump
control and the daily counters.

Deliberately distinct from ``halt_irrigation`` (the EC-runoff safety cut on EC
State, ADR-0016) and from the zero-plant steering-phase suspension (ADR-0011):
this is the pre-cycle tank/limit/dark gate on the base pump.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from .unknown_tank_level import UnknownTankLevel, unknown_tank_skip_text

if TYPE_CHECKING:
    from custom_components.growspace_manager.models import IrrigationConfig

EVENT_TYPE_IRRIGATION = "irrigation"
MAX_CYCLE_SECONDS = 3600


def cycle_runtime_limit(config: IrrigationConfig) -> int:
    """Keep even an old or malformed stored limit within the hard safety bound."""
    return max(1, min(config.max_cycle_seconds or 600, MAX_CYCLE_SECONDS))


class SkipReason(Enum):
    """Why a pump cycle was not fired. The shell maps these onto effects."""

    LOW_TANK = "low_tank"
    TANK_UNKNOWN = "tank_unknown"
    CYCLE_LIMIT = "cycle_limit"
    VOLUME_CAP = "volume_cap"
    DARK = "dark"
    FAULT = "fault"
    EMERGENCY_STOP = "emergency_stop"
    STARTUP = "startup_inhibit"


@dataclass(frozen=True, slots=True)
class TankReading:
    """A resolved tank level for one configured irrigation tank."""

    name: str
    level: float
    warning_level: float


@dataclass(frozen=True, slots=True)
class CycleVerdict:
    """The decision a Pump Cycle Gate returns.

    ``message`` is the pre-formatted logbook text; ``low_tank`` carries the
    offending reading for the persistent notification (set only for
    ``LOW_TANK``), ``unknown_tank`` the tank whose level is unknown (set only
    for ``TANK_UNKNOWN``). A ``fire=True`` verdict carries ``reason=None``.
    """

    fire: bool
    reason: SkipReason | None = None
    message: str = ""
    low_tank: TankReading | None = None
    unknown_tank: UnknownTankLevel | None = None


def cycle_volume_liters(config: IrrigationConfig, duration: float) -> float:
    """Return the estimated water volume for a cycle in litres.

    Returns 0.0 when the flow rate is not configured, which disables the
    volume-cap check for that cycle.
    """
    flow_rate = config.pump_flow_rate_ml_per_sec
    if not flow_rate:
        return 0.0
    return duration * flow_rate / 1000.0


def first_low_tank(tank_readings: list[TankReading]) -> TankReading | None:
    """Return the first tank reading below its warning level, else None."""
    for reading in tank_readings:
        if reading.level < reading.warning_level:
            return reading
    return None


def safety_cap_blocks(
    config: IrrigationConfig,
    cycles_today: int,
    volume_today: float,
    cycle_volume_l: float,
) -> SkipReason | None:
    """Return the cap/limit reason that blocks an irrigation cycle, else None.

    Covers the daily cycle limit and the daily volume cap. Exported on its own
    because the Adaptive Shot Control loop probes it alone to set its ``capped``
    diagnostic; ``decide_cycle`` calls it internally so the thresholds live in
    one place.
    """
    if (
        config.max_cycles_per_day is not None
        and cycles_today >= config.max_cycles_per_day
    ):
        return SkipReason.CYCLE_LIMIT

    if (
        cycle_volume_l > 0
        and config.daily_volume_cap_liters is not None
        and volume_today + cycle_volume_l > config.daily_volume_cap_liters
    ):
        return SkipReason.VOLUME_CAP

    return None


def decide_cycle(
    *,
    event_type: str,
    is_manual: bool,
    config: IrrigationConfig,
    tank_readings: list[TankReading],
    lights_dark: bool,
    cycles_today: int,
    volume_today: float,
    cycle_volume_l: float,
    fault: bool = False,
    emergency_stop: bool = False,
    startup_inhibit: str | None = None,
    unknown_tanks: Sequence[UnknownTankLevel] = (),
) -> CycleVerdict:
    """Decide whether a pump cycle may fire, in precedence order.

    ``startup_inhibit`` is the Startup Inhibit's detail while it holds; it
    blocks every automatic cycle, irrigation and drain alike, and never a
    manual one. Low tank, then an Unknown Tank Level, apply to all cycles,
    manual included (when ``pause_on_low_tank``);
    the cycle limit, volume cap and dark-period checks apply to irrigation
    cycles only, and a manual run bypasses the dark check.
    """
    prefix = event_type.capitalize()

    if emergency_stop:
        return CycleVerdict(
            False,
            SkipReason.EMERGENCY_STOP,
            f"{prefix} skipped — emergency stop latched",
        )
    if fault:
        return CycleVerdict(
            False, SkipReason.FAULT, f"{prefix} skipped — hardware fault latched"
        )
    if startup_inhibit is not None and not is_manual:
        return CycleVerdict(
            False, SkipReason.STARTUP, f"{prefix} skipped — {startup_inhibit}"
        )

    if config.pause_on_low_tank:
        low = first_low_tank(tank_readings)
        if low is not None:
            reason_text = (
                f"tank '{low.name}' is low "
                f"({low.level:.1f}% < {low.warning_level:.1f}%)"
            )
            return CycleVerdict(
                fire=False,
                reason=SkipReason.LOW_TANK,
                message=f"{prefix} skipped — {reason_text}",
                low_tank=low,
            )
        if unknown_tanks:
            unknown = unknown_tanks[0]
            return CycleVerdict(
                fire=False,
                reason=SkipReason.TANK_UNKNOWN,
                message=f"{prefix} skipped — {unknown_tank_skip_text(unknown)}",
                unknown_tank=unknown,
            )

    if event_type != EVENT_TYPE_IRRIGATION:
        return CycleVerdict(fire=True)

    cap_reason = safety_cap_blocks(config, cycles_today, volume_today, cycle_volume_l)
    if cap_reason is SkipReason.CYCLE_LIMIT:
        reason_text = (
            f"Daily cycle limit reached ({cycles_today}/{config.max_cycles_per_day})"
        )
        return CycleVerdict(
            fire=False,
            reason=cap_reason,
            message=f"{prefix} skipped — {reason_text}",
        )
    if cap_reason is SkipReason.VOLUME_CAP:
        reason_text = (
            f"Daily volume cap would be exceeded "
            f"({volume_today:.3f}L + {cycle_volume_l:.3f}L "
            f"> {config.daily_volume_cap_liters}L cap)"
        )
        return CycleVerdict(
            fire=False,
            reason=cap_reason,
            message=f"{prefix} skipped — {reason_text}",
        )

    if not is_manual and config.skip_during_dark and lights_dark:
        return CycleVerdict(
            fire=False,
            reason=SkipReason.DARK,
            message=f"{prefix} skipped — lights are currently off (dark period)",
        )

    return CycleVerdict(fire=True)
