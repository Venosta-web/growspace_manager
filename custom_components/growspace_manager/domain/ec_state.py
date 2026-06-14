"""EC State: the one reconciled view of a growspace's electrical conductivity.

ADR-0015. ``ECState`` is the single place EC is *reasoned about* — the input
[[EC Modulation]] and the [[Crop Steering Score]] read instead of reaching into
five scattered fields. It follows the ``StageEnvironmentalTargets`` precedent: a
pure object built per call from injected callables, unit-testable with plain
lambdas, with no coordinator dependency and no polling lifecycle.

This is the foundational slice (issue #463): the resolver populates pore EC and
the modulation-direction recommendation only. The [[Active Feed EC Target]]
(``active_feed_ec`` / ``feed_ec_source``) and runoff fields (``runoff_ec`` /
``feed_to_runoff_delta``) are part of the accepted ADR-0015 interface and default
to absent here — later slices (#464, #465) populate them without changing this
dataclass's shape. The runoff-percentage and ``halt_irrigation`` fields from
ADR-0016 are added by issue #466.

The recommendation is decided from pore-EC-vs-band **only** — feed and runoff EC
are carried for display and reconciliation but never move the modulation
decision, so feed EC and pore EC are never conflated (CONTEXT.md
"Pore EC Target Band").
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from custom_components.growspace_manager.models import IrrigationStrategy


class ECRecommendation(StrEnum):
    """The single EC *modulation-direction* decision exposed by [[EC State]].

    Modulation-direction only — the runoff safety halt is deliberately a separate
    ``halt_irrigation`` boolean (ADR-0016), never a member here, so a safety
    cut-off and an opt-in advisory adjustment never share a field. Maps 1:1 onto
    the EC Modulation tri-state: ``stack`` ⇔ pore below band (shrink shot, build
    EC), ``hold`` ⇔ within band (factor 1.0), ``flush`` ⇔ pore above band
    (enlarge shot, induce runoff), ``unavailable`` ⇔ no reading / opt-out.
    """

    UNAVAILABLE = "unavailable"
    STACK = "stack"
    HOLD = "hold"
    FLUSH = "flush"


@dataclass(frozen=True, slots=True)
class ECState:
    """A reconciled snapshot of a growspace's EC, derived per call.

    Stores nothing of its own: every field is read from already-persisted config
    or sensor readings. ``recommendation`` is ``UNAVAILABLE`` exactly when EC
    Modulation has no actionable input (opted out, no valid band, or no pore
    reading); ``pore_ec`` is then ``None``.
    """

    pore_ec: float | None
    recommendation: ECRecommendation
    # Accepted ADR-0015 interface fields populated by later slices (#464/#465).
    active_feed_ec: tuple[float, float] | None = None
    feed_ec_source: str = "none"
    runoff_ec: float | None = None
    feed_to_runoff_delta: float | None = None


def _classify_pore_ec(
    pore_ec: float, band_min: float, band_max: float
) -> ECRecommendation:
    """Map a pore-EC reading against its band to a modulation direction.

    Uses the same strict comparisons as ``_ec_modulation_factor_for_reading`` so
    the chosen *direction* and the computed *magnitude* never disagree: above the
    band → ``FLUSH``, below → ``STACK``, exactly at an edge or within → ``HOLD``.
    """
    if pore_ec > band_max:
        return ECRecommendation.FLUSH
    if pore_ec < band_min:
        return ECRecommendation.STACK
    return ECRecommendation.HOLD


class ECStateResolver:
    """Builds an :class:`ECState` snapshot for one growspace.

    ``read_pore_ec`` is injected (in production, the live coordinator's bound
    ``_average_pore_ec``) so the pore-EC averaging semantics keep a single owner
    and the resolver stays pure and lambda-testable.
    """

    def __init__(
        self,
        strategy: IrrigationStrategy,
        read_pore_ec: Callable[[], float | None],
    ) -> None:
        """Initialize with the growspace's strategy and a pore-EC reader."""
        self._strategy = strategy
        self._read_pore_ec = read_pore_ec

    def resolve(self) -> ECState:
        """Resolve the current :class:`ECState`.

        Returns an ``UNAVAILABLE`` state (no pore reading carried) when modulation
        is opted out, the [[Pore EC Target Band]] is absent or inverted, or no
        pore-EC reading is available — each a graceful [[Sensor-Gated Capability]]
        absence, never a raise. Otherwise carries the reading and its direction.
        """
        strategy = self._strategy
        if not strategy.ec_modulation_enabled:
            return ECState(pore_ec=None, recommendation=ECRecommendation.UNAVAILABLE)

        band_min = strategy.pore_ec_target_min
        band_max = strategy.pore_ec_target_max
        if band_min is None or band_max is None or band_min >= band_max:
            return ECState(pore_ec=None, recommendation=ECRecommendation.UNAVAILABLE)

        pore_ec = self._read_pore_ec()
        if pore_ec is None:
            return ECState(pore_ec=None, recommendation=ECRecommendation.UNAVAILABLE)

        return ECState(
            pore_ec=pore_ec,
            recommendation=_classify_pore_ec(pore_ec, band_min, band_max),
        )
