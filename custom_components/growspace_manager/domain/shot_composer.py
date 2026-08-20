"""ShotComposer: the one place steering shot size is composed.

Owns the [[Shot Size Composition]] (``effective = base × VWC factor × EC
factor``, then safety caps) and the [[Adaptive Shot Control]] feedback factors.

Unlike [[EC State]] — a pure-per-call resolver — this is a *stateful* controller
in the ``SubstrateTracker`` mould: the size/interval factors persist across
ticks and reset on phase events, so they are retained here rather than
recomputed. The module owns the ``reset()`` *rule* (both factors → 1.0); the
[[VWCIrrigationCoordinator]]'s phase machine owns *when* to call it (lights-on,
P1→P2).

The EC modulation factor and the safety-cap check are **injected callables** so
the [[EC State]] seam and the downstream ``_run_pump_cycle`` cap enforcement stay
exactly where they are — the composer never reaches into the coordinator or HA.
This keeps the feedback math and the composition unit-testable with plain values
(see ``tests/domain/test_shot_composer.py``). Tuning fields and ADR-0014
behaviour are unchanged from the prior in-coordinator implementation; the move is
purely structural (locality + test surface).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging

from custom_components.growspace_manager.models import IrrigationStrategy

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ShotComposition:
    """Fully-explained composition of the most recent fired steering shot.

    Surfaced in diagnostics/payload so any shot is explainable end to end:
    ``effective = base × vwc_factor × ec_factor``, then safety caps clamp the
    delivered duration (``capped`` is True when a cap actually reduced it).
    ``ec_modulation_available`` distinguishes "modulation off / no pore-EC
    sensor / no reading → factor 1.0" from "within band → factor 1.0".
    """

    phase: str
    base_seconds: int
    vwc_factor: float
    ec_factor: float
    ec_modulation_available: bool
    composed_seconds: int
    effective_seconds: int
    capped: bool
    timestamp: str


@dataclass(frozen=True, slots=True)
class FeedbackTuning:
    """The [[Adaptive Shot Control]] tuning the feedback update needs.

    A small value object extracted from ``IrrigationStrategy`` so ``observe()``
    stays free of the model and trivially constructable in tests.
    """

    enabled: bool
    target_vwc_percent: float
    aggressiveness: float
    recovery: float
    size_floor: float
    interval_ceiling: float

    @classmethod
    def from_strategy(cls, strategy: IrrigationStrategy) -> FeedbackTuning:
        """Build the tuning from a growspace's irrigation strategy."""
        return cls(
            enabled=strategy.dynamic_shot_enabled,
            target_vwc_percent=strategy.target_vwc_percent,
            aggressiveness=strategy.dynamic_aggressiveness,
            recovery=strategy.dynamic_recovery,
            size_floor=strategy.dynamic_shot_size_floor,
            interval_ceiling=strategy.dynamic_interval_ceiling,
        )


class ShotComposer:
    """Stateful owner of the Shot Size Composition and Adaptive Shot Control.

    Holds the VWC size factor and the interval factor across ticks. ``observe``
    runs the feedback update after a settled cycle; ``reset`` returns both
    factors to nominal; ``compose`` produces the finished ``ShotComposition``.
    The factors are plain attributes so tests can seed a mid-grow state, mirroring
    the deterministic-sequence testing of ``SubstrateTracker``.
    """

    def __init__(self) -> None:
        """Start at nominal: both factors 1.0, no shot composed yet."""
        self.size_factor: float = 1.0
        # Interval-domain sibling of the size factor (ADR-0014): scales the
        # minimum-cooldown floor. Clamped [1.0, interval_ceiling] — only ever
        # lengthens spacing or recovers to nominal, never shortens.
        self.interval_factor: float = 1.0
        # Last fired shot's full composition, exposed for diagnostics. None until
        # a shot has been composed this session.
        self.last_composition: ShotComposition | None = None

    def reset(self) -> None:
        """Return both feedback factors to nominal (1.0)."""
        self.size_factor = 1.0
        self.interval_factor = 1.0

    def observe(
        self,
        moisture_before: float | None,
        moisture_after: float | None,
        tuning: FeedbackTuning,
    ) -> None:
        """Adjust the feedback factors from a shot's effect on soil moisture.

        Drives both the size factor (shot volume/duration) and the interval
        factor (minimum-cooldown spacing) from the same overshoot ratio: on
        overshoot the shot shrinks and the interval lengthens; on undershoot both
        recover toward nominal (1.0). Inert when Adaptive Shot Control is disabled
        or either reading is missing (ADR-0014).
        """
        if not tuning.enabled:
            return
        if moisture_before is None or moisture_after is None:
            return

        d_target = tuning.target_vwc_percent - moisture_before
        d_actual = moisture_after - moisture_before

        # Guard against division by very small numbers or non-positive actual delta
        if d_target <= 0.5 or d_actual <= 0:
            return

        ratio = d_actual / d_target
        if ratio > 1.0:
            # Overshot target: shrink the shot and lengthen the interval.
            error = ratio - 1.0
            self.size_factor = max(
                tuning.size_floor,
                min(1.0, self.size_factor - tuning.aggressiveness * error),
            )
            self.interval_factor = min(
                tuning.interval_ceiling,
                max(1.0, self.interval_factor + tuning.aggressiveness * error),
            )
            direction = "overshot VWC target"
        else:
            # Undershot or met target: recover both factors toward nominal.
            error = 1.0 - ratio
            self.size_factor = max(
                tuning.size_floor,
                min(1.0, self.size_factor + tuning.recovery * error),
            )
            self.interval_factor = min(
                tuning.interval_ceiling,
                max(1.0, self.interval_factor - tuning.recovery * error),
            )
            direction = "dynamic shot VWC feedback"

        _LOGGER.debug(
            "%s. Expected delta: %.2f%%, actual: %.2f%%. "
            "Size factor: %.2f, interval factor: %.2f",
            direction,
            d_target,
            d_actual,
            self.size_factor,
            self.interval_factor,
        )

    def compose(
        self,
        phase: str,
        base_seconds: int,
        get_ec_factor: Callable[[], tuple[float, bool]],
        check_cap: Callable[[int], bool],
        timestamp: str,
    ) -> ShotComposition:
        """Compose ``base × VWC factor × EC factor`` into a ``ShotComposition``.

        EC modulation applies to P2 maintenance shots only; P1 ramp-up keeps a
        neutral EC factor of 1.0 and never calls ``get_ec_factor``. ``check_cap``
        reports whether the downstream safety caps would block the composed
        duration — actual enforcement still happens in ``_run_pump_cycle`` — so a
        capped shot records ``effective_seconds = 0``. The result is stored as
        ``last_composition`` and returned.
        """
        if phase == "P2":
            ec_factor, ec_available = get_ec_factor()
        else:
            ec_factor, ec_available = 1.0, False

        composed_factor = self.size_factor * ec_factor
        composed_seconds = max(1, int(round(base_seconds * composed_factor)))
        capped = check_cap(composed_seconds)

        composition = ShotComposition(
            phase=phase,
            base_seconds=base_seconds,
            vwc_factor=round(self.size_factor, 3),
            ec_factor=round(ec_factor, 3),
            ec_modulation_available=ec_available,
            composed_seconds=composed_seconds,
            effective_seconds=0 if capped else composed_seconds,
            capped=capped,
            timestamp=timestamp,
        )
        self.last_composition = composition
        return composition
