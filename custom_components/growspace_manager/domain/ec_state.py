"""EC State: the one reconciled view of a growspace's electrical conductivity.

ADR-0015. ``ECState`` is the single place EC is *reasoned about* — the input
[[EC Modulation]] and the [[Crop Steering Score]] read instead of reaching into
five scattered fields. It follows the ``StageEnvironmentalTargets`` precedent: a
pure object built per call from injected callables, unit-testable with plain
lambdas, with no coordinator dependency and no polling lifecycle.

The resolver populates the pore-EC modulation-direction recommendation (#463),
the [[Active Feed EC Target]] (``active_feed_ec`` / ``feed_ec_source``, #464), the
runoff measurements (``runoff_ec`` / ``feed_to_runoff_delta``, #465), and the
[[Runoff Reconciliation]] fields (``runoff_percent`` / ``runoff_pct_target`` /
``halt_irrigation``, ADR-0016 #466).

The recommendation is decided from pore-EC-vs-band first; ADR-0016 lets a
*sustained* [[Feed-to-Runoff EC Delta]] above ``max_ec_delta`` escalate a
``HOLD`` to ``FLUSH`` (salts stacking faster than the pen shows). Feed EC itself
is carried for display only and never moves the decision, so feed EC and pore EC
are never conflated (CONTEXT.md "Pore EC Target Band").

The hard runoff safety halt is the separate ``halt_irrigation`` boolean — never
a member of ``ECRecommendation`` — computed unconditionally from
``drain_ec > halt_on_runoff_ec_threshold`` regardless of ``ec_modulation_enabled``,
so a grower opting out of EC Modulation can never mask the safety cut-off
(ADR-0016).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from custom_components.growspace_manager.const import (
    EC_MODULATION_FULL_SCALE_DELTA,
    EC_MODULATION_MAX_FACTOR,
    EC_MODULATION_MIN_FACTOR,
)
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
    # Runoff Reconciliation (ADR-0016, #466). ``runoff_percent`` is the measured
    # drain/feed volume fraction (None without volume sensors); ``runoff_pct_target``
    # is the grower's goal. ``halt_irrigation`` is the hard safety cut-off — its
    # own field, NOT an ``ECRecommendation`` member, computed independently of
    # ``ec_modulation_enabled`` so it can never be masked by the modulation opt-out.
    runoff_percent: float | None = None
    runoff_pct_target: float | None = None
    halt_irrigation: bool = False


def _classify_pore_ec(
    pore_ec: float, band_min: float, band_max: float
) -> ECRecommendation:
    """Map a pore-EC reading against its band to a modulation direction.

    Uses the same strict comparisons as ``ec_modulation_factor_for_reading`` so
    the chosen *direction* and the computed *magnitude* never disagree: above the
    band → ``FLUSH``, below → ``STACK``, exactly at an edge or within → ``HOLD``.
    """
    if pore_ec > band_max:
        return ECRecommendation.FLUSH
    if pore_ec < band_min:
        return ECRecommendation.STACK
    return ECRecommendation.HOLD


def ec_modulation_factor_for_reading(
    measured_ec: float, band_min: float, band_max: float
) -> float:
    """Map a measured pore EC against the band to a bounded shot factor.

    The magnitude half of the [[EC Recommendation]]: above the band → factor
    > 1.0 (flush), below → < 1.0 (stack), within → exactly 1.0. The response is
    proportional to the excursion past the nearest band edge, normalised so an
    excursion of ``EC_MODULATION_FULL_SCALE_DELTA`` saturates at the bound, then
    clamped to ``[EC_MODULATION_MIN_FACTOR, EC_MODULATION_MAX_FACTOR]``.
    """
    if measured_ec > band_max:
        excursion = measured_ec - band_max
        span = EC_MODULATION_MAX_FACTOR - 1.0
        factor = 1.0 + span * (excursion / EC_MODULATION_FULL_SCALE_DELTA)
        return min(EC_MODULATION_MAX_FACTOR, factor)
    if measured_ec < band_min:
        excursion = band_min - measured_ec
        span = 1.0 - EC_MODULATION_MIN_FACTOR
        factor = 1.0 - span * (excursion / EC_MODULATION_FULL_SCALE_DELTA)
        return max(EC_MODULATION_MIN_FACTOR, factor)
    return 1.0


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


def band_for_week(points: list[ECRampPoint], week: int) -> tuple[float, float] | None:
    """Return ``(ec_min, ec_max)`` for ``week`` on a ramp curve, or None.

    The single owner of ramp-curve week resolution, shared by the feed-target seam
    and the ``ECTargetSensor``: an exact week wins; past the last defined week the
    final point holds; before the first week, None.
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
        band = band_for_week(curve.points, week)
        if band is not None:
            return band, "ramp_curve"

    range_ = next((r for r in ec_target_ranges if r.stage == stage), None)
    if range_ is not None:
        return (range_.feed_ec_min, range_.feed_ec_max), "stage_range"

    return None, "none"


# Sustained-delta window (ADR-0016): "sustained" means agreement across the tail
# of the persisted DrainConfig.readings — up to the last 3 readings, requiring at
# least 2, all exceeding max_ec_delta. Reads existing rolling-window state; adds
# no new storage and never touches the recorder-free SubstrateTracker (ADR-0010).
_SUSTAINED_WINDOW = 3
_SUSTAINED_MIN = 2


@dataclass(frozen=True, slots=True)
class RunoffInputs:
    """Everything the resolver needs about runoff, read once per resolve.

    ``readings`` is the growspace's ``DrainConfig.readings`` (the resolver takes
    its own tail for the sustained-delta check); ``max_ec_delta`` and
    ``target_runoff_percent`` are the grower's drain-monitoring targets;
    ``halt_threshold`` is ``IrrigationConfig.halt_on_runoff_ec_threshold`` (``None``
    when the safety halt is disabled). An empty/None instance means "no runoff
    data" — every derived field degrades to its absent value.
    """

    readings: list[DrainReading]
    max_ec_delta: float
    target_runoff_percent: float | None = None
    halt_threshold: float | None = None


def runoff_halt(runoff: RunoffInputs) -> bool:
    """Return True when the hard runoff-EC safety halt is active.

    The single owner of the halt decision (ADR-0016): the latest drain EC exceeds
    ``halt_threshold``. Deliberately **independent of EC Modulation** — it never
    consults ``ec_modulation_enabled`` — so a grower opting out of modulation can
    never mask the safety cut-off. ``resolve()`` sets ``ECState.halt_irrigation``
    from this, and the irrigation hot path calls it directly, so both agree
    without either rebuilding the other's state.
    """
    if runoff.halt_threshold is None or not runoff.readings:
        return False
    return runoff.readings[-1].drain_ec > runoff.halt_threshold


def _runoff_percent(reading: DrainReading | None) -> float | None:
    """Return ``drain_volume_ml / feed_volume_ml × 100`` for a reading, or None.

    ``None`` when there is no reading or either volume is absent/non-positive — a
    lower [[Sensor-Gated Capability]] tier (EC-only growers get delta
    reconciliation and the halt, but not [[Runoff Percentage]]).
    """
    if reading is None or reading.drain_volume_ml is None or not reading.feed_volume_ml:
        return None
    return reading.drain_volume_ml / reading.feed_volume_ml * 100.0


# Crop Steering Score runoff buckets (ADR-0016 §3, ratified). Keyed off the
# grower's max_ec_delta (Δmax); symmetric ±0.3, mirroring the EC-trend budget so
# the runoff fill and a pore-EC trend occupy the same shared axis.
_RUNOFF_SCORE_STRONG = 0.3
_RUNOFF_SCORE_MODERATE = 0.2


def runoff_score_component(readings: list[DrainReading], max_ec_delta: float) -> float:
    """Bucket a sustained [[Feed-to-Runoff EC Delta]] into a steering-score nudge.

    Fills the [[Crop Steering Score]]'s shared EC axis only when no pore-EC trend
    is measured (the caller enforces that). "Sustained" reuses the same
    unanimous-tail notion as the flush bias: the last 2–3 readings must all agree,
    and the nudge is bucketed on the **weakest** agreeing reading (the min delta
    when stacking, the max when diluting). Symmetric off ``max_ec_delta`` (Δmax):
    ≥2·Δmax → +0.3, ≥Δmax → +0.2, ≤−Δmax → −0.2, ≤−2·Δmax → −0.3.

    Returns 0.0 on a straddling/within-band tail, too few readings, or a
    non-positive ``max_ec_delta`` — so a grower without drain data scores
    unchanged.
    """
    tail = readings[-_SUSTAINED_WINDOW:]
    if len(tail) < _SUSTAINED_MIN or max_ec_delta <= 0:
        return 0.0
    deltas = [r.drain_ec - r.feed_ec for r in tail]
    weakest_stack = min(deltas)  # smallest positive when all stacking
    weakest_dilute = max(deltas)  # largest (closest to 0) when all diluting
    if weakest_stack >= 2 * max_ec_delta:
        return _RUNOFF_SCORE_STRONG
    if weakest_stack >= max_ec_delta:
        return _RUNOFF_SCORE_MODERATE
    if weakest_dilute <= -2 * max_ec_delta:
        return -_RUNOFF_SCORE_STRONG
    if weakest_dilute <= -max_ec_delta:
        return -_RUNOFF_SCORE_MODERATE
    return 0.0


def _is_sustained_high_delta(readings: list[DrainReading], max_ec_delta: float) -> bool:
    """Return True when the recent drain readings *sustain* an over-target delta.

    Looks at the last ``_SUSTAINED_WINDOW`` readings, requires at least
    ``_SUSTAINED_MIN`` of them, and only reports True when **every** reading in
    that tail has a [[Feed-to-Runoff EC Delta]] above ``max_ec_delta``. A single
    mis-measured catch therefore cannot trigger a flush bias.
    """
    tail = readings[-_SUSTAINED_WINDOW:]
    if len(tail) < _SUSTAINED_MIN:
        return False
    return all(r.drain_ec - r.feed_ec > max_ec_delta for r in tail)


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
        read_runoff: Callable[[], RunoffInputs] | None = None,
    ) -> None:
        """Initialize with the strategy and injected EC readers."""
        self._strategy = strategy
        self._read_pore_ec = read_pore_ec
        self._read_feed_target = read_feed_target or (lambda: (None, "none"))
        self._read_runoff = read_runoff or (
            lambda: RunoffInputs(readings=[], max_ec_delta=0.0)
        )

    def resolve(self) -> ECState:
        """Resolve the current :class:`ECState`.

        The feed target, runoff measurements, and the safety halt are resolved
        independently of modulation state — they are carried even when the
        recommendation is ``UNAVAILABLE`` (opt out / no band / no reading), since
        none of them gate on the pore band. A sustained over-target runoff delta
        then escalates a ``HOLD`` recommendation to ``FLUSH`` (ADR-0016).
        """
        active_feed_ec, feed_ec_source = self._read_feed_target()
        runoff = self._read_runoff()
        latest = runoff.readings[-1] if runoff.readings else None

        runoff_ec = latest.drain_ec if latest is not None else None
        feed_to_runoff_delta = (
            latest.drain_ec - latest.feed_ec if latest is not None else None
        )
        runoff_percent = _runoff_percent(latest)
        halt_irrigation = runoff_halt(runoff)

        recommendation, pore_ec = self._resolve_modulation()
        recommendation = self._apply_runoff_bias(recommendation, runoff)

        return ECState(
            pore_ec=pore_ec,
            recommendation=recommendation,
            active_feed_ec=active_feed_ec,
            feed_ec_source=feed_ec_source,
            runoff_ec=runoff_ec,
            feed_to_runoff_delta=feed_to_runoff_delta,
            runoff_percent=runoff_percent,
            runoff_pct_target=runoff.target_runoff_percent,
            halt_irrigation=halt_irrigation,
        )

    @staticmethod
    def _apply_runoff_bias(
        recommendation: ECRecommendation, runoff: RunoffInputs
    ) -> ECRecommendation:
        """Escalate ``HOLD → FLUSH`` on a sustained over-target runoff delta.

        Only a ``HOLD`` (pore within band) is escalated: ``STACK`` is the grower
        deliberately building EC, an existing ``FLUSH`` already induces runoff,
        and ``UNAVAILABLE`` has no pore reading to reconcile against. The runoff
        signal speaks *through* the one EC recommendation — it never adds a second
        actuator (CONTEXT.md "Shot Size Composition").
        """
        if recommendation is not ECRecommendation.HOLD:
            return recommendation
        if _is_sustained_high_delta(runoff.readings, runoff.max_ec_delta):
            return ECRecommendation.FLUSH
        return recommendation

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
