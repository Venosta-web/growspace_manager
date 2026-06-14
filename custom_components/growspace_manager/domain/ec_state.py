"""EC State: the one reconciled view of a growspace's electrical conductivity.

ADR-0015. ``ECState`` is the single place EC is *reasoned about* — the input
[[EC Modulation]] and the [[Crop Steering Score]] read instead of reaching into
five scattered fields. It follows the ``StageEnvironmentalTargets`` precedent: a
pure object built per call from injected callables, unit-testable with plain
lambdas, with no coordinator dependency and no polling lifecycle.

The resolver populates the pore-EC modulation-direction recommendation (#463)
and the [[Active Feed EC Target]] (``active_feed_ec`` / ``feed_ec_source``, #464).
The runoff fields (``runoff_ec`` / ``feed_to_runoff_delta``) are part of the
accepted ADR-0015 interface and default to absent here — issue #465 populates
them without changing this dataclass's shape. The runoff-percentage and
``halt_irrigation`` fields from ADR-0016 are added by issue #466.

The recommendation is decided from pore-EC-vs-band **only** — feed and runoff EC
are carried for display and reconciliation but never move the modulation
decision, so feed EC and pore EC are never conflated (CONTEXT.md
"Pore EC Target Band").
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from custom_components.growspace_manager.models import DrainReading, IrrigationStrategy
from custom_components.growspace_manager.utils import (
    calculate_plant_stage,
    days_to_week,
)
from homeassistant.util import dt as dt_util

from .stage_calculator import calculate_days_in_stage

if TYPE_CHECKING:
    from custom_components.growspace_manager.models import (
        DrainConfig,
        ECRampCurve,
        ECRampPoint,
        ECTargetRange,
        Plant,
    )

# Stages whose plants sit on the irrigation line and are therefore fed. ``dry``
# and ``cure`` are excluded — those plants are no longer irrigated, so they never
# drive the feed target (CONTEXT.md "Active Feed EC Target"). Ordered by
# progression so the **furthest-along** live stage wins when stages are mixed.
_LIVE_STAGE_ORDER: dict[str, int] = {
    "seedling": 10,
    "clone": 20,
    "mother": 30,
    "veg": 40,
    "flower": 50,
}


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
    # Active Feed EC Target (#464): the resolved feed-EC min/max and where it
    # came from ("ramp_curve" / "stage_range" / "none"). Feed EC is carried for
    # display/reconciliation only — it never moves the modulation recommendation.
    active_feed_ec: tuple[float, float] | None = None
    feed_ec_source: str = "none"
    # Runoff measurements from the latest drain reading (#465): the drained EC
    # and the feed→runoff EC delta (drain_ec − feed_ec). Both None when there are
    # no readings. Carried for display/reconciliation; ADR-0016 makes them steer.
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


def resolve_feed_stage_week(plants: list[Plant]) -> tuple[str | None, int]:
    """Return ``(stage, week)`` for the furthest-along **live** stage.

    A growspace has no single canonical stage, so feed-target resolution picks
    the most advanced stage with live (irrigated) plants — never under-feeding
    the most EC-demanding cohort (CONTEXT.md "Active Feed EC Target"). ``week`` is
    ``days_to_week`` of the max days any plant has spent in that stage, reusing
    the view model's per-stage day-count convention. Returns ``(None, 0)`` when
    no live plants are present (empty, or all in dry/cure).
    """
    best_order = -1
    best_stage: str | None = None
    for plant in plants:
        stage = calculate_plant_stage(plant)
        order = _LIVE_STAGE_ORDER.get(stage)
        if order is not None and order > best_order:
            best_order = order
            best_stage = stage

    if best_stage is None:
        return None, 0

    max_days = max(
        (calculate_days_in_stage(plant, best_stage) for plant in plants),
        default=0,
    )
    return best_stage, days_to_week(max_days)


def _band_for_week(points: list[ECRampPoint], week: int) -> tuple[float, float] | None:
    """Return ``(ec_min, ec_max)`` for ``week`` on a ramp curve, or None.

    Matches the existing ``ECTargetSensor`` resolution: an exact week wins; past
    the last defined week the final point holds; before the first week, None.
    """
    for point in points:
        if point.week == week:
            return (point.ec_min, point.ec_max)
    last = points[-1]
    if week >= last.week:
        return (last.ec_min, last.ec_max)
    return None


def resolve_active_feed_ec(
    stage: str | None,
    week: int,
    ec_ramp_curves: dict[str, ECRampCurve],
    ec_target_ranges: list[ECTargetRange],
) -> tuple[tuple[float, float] | None, str]:
    """Resolve the [[Active Feed EC Target]] as ``(band, source)``.

    The weekly ``ECRampCurve`` for the stage wins; failing that, the per-stage
    ``ECTargetRange`` (which has no week dimension). ``(None, "none")`` when the
    stage is unknown or neither is configured — a graceful Sensor-Gated absence.
    """
    if stage is None:
        return None, "none"

    curve = next((c for c in ec_ramp_curves.values() if c.stage == stage), None)
    if curve is not None and curve.points:
        band = _band_for_week(curve.points, week)
        if band is not None:
            return band, "ramp_curve"

    range_ = next((r for r in ec_target_ranges if r.stage == stage), None)
    if range_ is not None:
        return (range_.feed_ec_min, range_.feed_ec_max), "stage_range"

    return None, "none"


# ── Drain reading recording ──────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class DrainRecord:
    """Outcome of recording one drain reading behind the seam.

    ``alert`` is the threshold decision (monitoring enabled AND the
    [[Feed-to-Runoff EC Delta]] exceeds ``max_ec_delta``); callers act on it via
    their own notification transport. ``ec_delta`` is exposed so the caller's
    alert message and event payload need not recompute it.
    """

    reading: DrainReading
    ec_delta: float
    alert: bool


def record_drain_reading(
    drain_config: DrainConfig,
    feed_ec: float,
    drain_ec: float,
    drain_volume_ml: float | None = None,
    feed_volume_ml: float | None = None,
) -> DrainRecord:
    """Append a drain reading, enforce the rolling window, and decide the alert.

    The one owner of drain-reading bookkeeping (ADR-0015): the build + append +
    rolling-window trim + [[Feed-to-Runoff EC Delta]] + threshold decision that
    used to be duplicated byte-for-byte across ``GrowspaceManager`` and the
    service facade. Each caller keeps only its own save and notification
    transport (event bus vs. notification manager).
    """
    reading = DrainReading(
        timestamp=dt_util.now().isoformat(),
        feed_ec=feed_ec,
        drain_ec=drain_ec,
        drain_volume_ml=drain_volume_ml,
        feed_volume_ml=feed_volume_ml,
    )
    drain_config.readings.append(reading)
    if len(drain_config.readings) > drain_config.max_readings:
        drain_config.readings = drain_config.readings[-drain_config.max_readings :]

    ec_delta = drain_ec - feed_ec
    alert = drain_config.enabled and ec_delta > drain_config.max_ec_delta
    return DrainRecord(reading=reading, ec_delta=ec_delta, alert=alert)


class ECStateResolver:
    """Builds an :class:`ECState` snapshot for one growspace.

    Dependencies are injected as callables so the resolver stays pure and
    lambda-testable. ``read_pore_ec`` is the live coordinator's bound
    ``_average_pore_ec`` (the averaging semantics keep a single owner);
    ``read_feed_target`` returns the resolved [[Active Feed EC Target]] and its
    source. ``read_feed_target`` defaults to "no feed target", so a caller that
    only needs the modulation recommendation (e.g. the P2-shot hot path) can omit
    it and pay nothing for feed resolution.
    """

    def __init__(
        self,
        strategy: IrrigationStrategy,
        read_pore_ec: Callable[[], float | None],
        read_feed_target: Callable[[], tuple[tuple[float, float] | None, str]]
        | None = None,
        read_drain: Callable[[], DrainReading | None] | None = None,
    ) -> None:
        """Initialize with the strategy and injected EC readers."""
        self._strategy = strategy
        self._read_pore_ec = read_pore_ec
        self._read_feed_target = read_feed_target or (lambda: (None, "none"))
        self._read_drain = read_drain or (lambda: None)

    def resolve(self) -> ECState:
        """Resolve the current :class:`ECState`.

        The feed target and runoff measurements are resolved independently of
        modulation state — they are carried for display even when the
        recommendation is ``UNAVAILABLE`` (opt out / no band / no reading), since
        neither gates on the pore band.
        """
        active_feed_ec, feed_ec_source = self._read_feed_target()
        runoff_ec, feed_to_runoff_delta = self._resolve_runoff()
        recommendation, pore_ec = self._resolve_modulation()
        return ECState(
            pore_ec=pore_ec,
            recommendation=recommendation,
            active_feed_ec=active_feed_ec,
            feed_ec_source=feed_ec_source,
            runoff_ec=runoff_ec,
            feed_to_runoff_delta=feed_to_runoff_delta,
        )

    def _resolve_runoff(self) -> tuple[float | None, float | None]:
        """Return ``(runoff_ec, feed_to_runoff_delta)`` from the latest reading.

        Both ``None`` when no drain reading exists — a graceful
        [[Sensor-Gated Capability]] absence for growspaces without a runoff pen.
        """
        reading = self._read_drain()
        if reading is None:
            return None, None
        return reading.drain_ec, reading.drain_ec - reading.feed_ec

    def _resolve_modulation(self) -> tuple[ECRecommendation, float | None]:
        """Resolve the modulation direction and the pore reading behind it.

        Returns ``(UNAVAILABLE, None)`` when modulation is opted out, the
        [[Pore EC Target Band]] is absent or inverted, or no pore-EC reading is
        available — each a graceful [[Sensor-Gated Capability]] absence, never a
        raise.
        """
        strategy = self._strategy
        if not strategy.ec_modulation_enabled:
            return ECRecommendation.UNAVAILABLE, None

        band_min = strategy.pore_ec_target_min
        band_max = strategy.pore_ec_target_max
        if band_min is None or band_max is None or band_min >= band_max:
            return ECRecommendation.UNAVAILABLE, None

        pore_ec = self._read_pore_ec()
        if pore_ec is None:
            return ECRecommendation.UNAVAILABLE, None

        return _classify_pore_ec(pore_ec, band_min, band_max), pore_ec
