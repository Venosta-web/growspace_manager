# EC State is one domain module that reconciles feed, pore, and runoff EC

**Status:** Accepted

The integration today carries **five disconnected EC representations** and only
one closes a loop. Per-stage **feed** EC ranges (`ECTargetRange`) and weekly
**feed** EC ramp curves (`ECRampCurve`) are CRUD-and-display only — nothing in
steering reads them. The **pore-EC** band drives the one closed loop (EC
Modulation scales P2 shots). **Runoff/drain** EC drives only a binary halt
(`_is_halted_by_runoff_ec`). The **runoff target** (`target_runoff_percent`) is
dead weight — stored, settable, shown in the view model, read by nothing; its
sibling `max_ec_delta` only fires a log-warning on a manual `log_drain_reading`,
and *that* logic is duplicated verbatim across `managers/growspace.py` and
`services/growspace_facade.py`.

For a professional grower the feed chart, the substrate pen, and the runoff pen
are **one conversation** ("I'm feeding 2.8, the substrate reads 5.5, the runoff
comes back at 6.2 — am I stacking or do I flush?"). The code has no place where
that conversation happens. This ADR creates one.

## Decision

Introduce a single typed domain module, `domain/ec_state.py`, following the
[[StageEnvironmentalTargets]] precedent: a pure class constructed from injected
callables and config, unit-testable with plain lambdas, behind a small
interface. It becomes the **one place EC is reasoned about**. It owns three jobs:

1. **Resolve the [[Active Feed EC Target]]** for a growspace from the ramp curve
   / per-stage range, given the plant's stage and week.
2. **Read the measured worlds** — pore EC (reusing the exact `_average_pore_ec`
   semantics) and runoff EC (the latest [[DrainReading]]).
3. **Reconcile** them into one typed [[EC State]] result carrying a single
   [[EC Recommendation]] enum.

EC Modulation and the [[Crop Steering Score]] read `ECState`; they stop reaching
into five scattered fields. This is the **seam**.

### The interface

```python
class ECRecommendation(StrEnum):
    UNAVAILABLE = "unavailable"  # no pore-EC measurement at all
    STACK       = "stack"        # pore EC below band → reduce flush, build EC
    HOLD        = "hold"         # pore EC within band → neutral
    FLUSH       = "flush"        # pore EC above band → induce runoff, dilute

@dataclass(slots=True)
class ECState:
    active_feed_ec: tuple[float, float] | None  # resolved (min, max), or None
    feed_ec_source: str        # "ramp_curve" | "stage_range" | "none"
    pore_ec: float | None      # averaged pore-EC reading, or None
    runoff_ec: float | None    # latest DrainReading.drain_ec, or None
    feed_to_runoff_delta: float | None  # runoff_ec − feed_ec of latest reading
    recommendation: ECRecommendation

class ECStateResolver:  # builds an ECState snapshot per call
    def __init__(
        self,
        strategy: IrrigationStrategy,            # band + modulation flag
        feed_targets: FeedTargetSource,          # ramp curves + stage ranges
        read_pore_ec: Callable[[], float | None],
        latest_drain_reading: Callable[[], DrainReading | None],
        stage: str | None,
        week: int,
    ) -> None: ...
    def resolve(self) -> ECState: ...
```

`read_pore_ec` is injected as the bound `_average_pore_ec` of the live
`VWCIrrigationCoordinator`, so the **averaging semantics are not re-implemented**
— they have one owner. `latest_drain_reading` returns `growspace.drain_config.
readings[-1]` or `None`. `feed_targets` is a tiny adapter over `NutrientManager.
ec_ramp_curves` and `IrrigationConfig.ec_target_ranges`.

### Invariants

- **Feed EC and pore EC are never conflated.** This is the load-bearing
  invariant from CONTEXT.md's [[Pore EC Target Band]]: pore EC legitimately runs
  *above* feed EC when stacking. `ECState` keeps `active_feed_ec` and `pore_ec`
  in separate fields and the recommendation is computed **only** from
  `pore_ec` vs. the [[Pore EC Target Band]] — never from feed EC. Feed target and
  runoff are carried for *display and for ADR-0016's reconciliation*, never to
  override the pore-band decision in v1.
- **The recommendation maps 1:1 onto today's EC Modulation tri-state.** `STACK`
  ⇔ pore EC below band (factor < 1.0), `HOLD` ⇔ within band (factor 1.0),
  `FLUSH` ⇔ above band (factor > 1.0), `UNAVAILABLE` ⇔ no reading / opt-out
  (factor exactly 1.0, available False). The numeric factor still comes from the
  existing `_ec_modulation_factor_for_reading` pure helper — `ECState` chooses
  the *direction*, the helper computes the *magnitude*.
- **Feed-target stage resolves to the furthest-along stage present.** A growspace
  has **no single canonical stage** — `view_model_builder.py` tracks per-stage
  weeks (`veg_week`, `flower_week`, …) independently from each stage's max-days.
  So feed-target resolution must *pick* a stage, and the rule is deliberately the
  **most advanced stage with live plants** (flower over veg over seedling). It
  never under-feeds the most EC-demanding cohort; the cost is over-stating EC for
  younger plants in a mixed tent, accepted because the target is advisory
  (reconciliation display + a bounded score nudge, not actuation). `week` is then
  `days_to_week(max_days_in_that_stage)`, reusing the view model's existing
  per-stage day counts — no new week concept is invented. (Rejected: *dominant
  stage by plant count* — simpler-sounding but can feed flower plants a veg-week
  EC when seedlings outnumber them, the more dangerous error.)

### Unavailable / error modes ([[Sensor-Gated Capability]])

Each field degrades independently to `None`; nothing raises:

- No ramp curve and no matching stage range → `active_feed_ec = None`,
  `feed_ec_source = "none"`. A grower who never configured feed targets loses
  nothing.
- No pore-EC sensors / all dropped out → `pore_ec = None` →
  `recommendation = UNAVAILABLE` → modulation factor 1.0. **Exactly today's
  behavior.**
- No drain readings → `runoff_ec = None`, `feed_to_runoff_delta = None`. v1's
  recommendation does not consult runoff, so this changes nothing.

### What lives behind the seam vs. what callers keep

| Behind `ECState`                                     | Callers keep                          |
|------------------------------------------------------|---------------------------------------|
| Feed-target resolution (ramp curve → week → range)   | Firing the pump / safety caps         |
| Pore-vs-band direction → `ECRecommendation`          | The `_ec_modulation_factor_for_reading` magnitude helper |
| Latest-runoff lookup + feed→runoff delta             | `ShotComposition` diagnostics assembly |
| The duplicated drain-reading append + `max_ec_delta` warning | Notification delivery (manager-owned)         |

`_compute_ec_modulation` shrinks to: build `ECState`, branch on
`recommendation`, return `(factor, available)`. It no longer knows the band
lives on five fields.

### Consolidating the duplicate drain logic

The byte-identical append-and-warn block in `managers/growspace.py` (~631–665)
and `services/growspace_facade.py` (~483–503) is **shotgun-surgery bait**: any
change to the EC-delta rule must be made twice and the two copies already
diverge in how they notify (event bus vs. notification manager). The append +
rolling-window + `feed_to_runoff_delta` computation moves behind the seam as a
single `record_drain_reading` helper; the two call sites keep only their own
notification transport. This is part of the deletion test below.

## Deletion test

Delete `domain/ec_state.py`. What breaks, and is the breakage proportionate?

- `_compute_ec_modulation` loses its direction source and must re-grow the
  band-resolution + pore-read inline (it had exactly this before — proportionate
  regression, the module genuinely subsumed it).
- The crop-steering score loses any EC-target awareness it gained (in 0016).
- The two drain call sites must re-duplicate the append/window/warning.

Nothing *outside* EC reasoning breaks — feed-target CRUD, the display sensor,
and the view-model payload still function because the module **reads** those
representations, it does not own their storage. That is the right depth: the
module is the one place EC is *interpreted*, not the one place it is *stored*.

## Rejected alternatives

- **Bolt the feed target onto EC Modulation directly** (read the ramp curve
  inside `_compute_ec_modulation` and clamp the band to it). Rejected: it
  **conflates feed and pore EC** — the exact thing CONTEXT.md forbids — and
  buries feed-target resolution inside a P2-shot method where the crop-steering
  score can't reach it. The five representations would become four, still not a
  single reasoning point.
- **A new coordinator (`ECCoordinator`) that polls and publishes EC state.**
  Rejected: EC has no independent update cadence — it is derived on demand from
  sensors the VWC loop already reads each minute. A coordinator adds a lifecycle,
  a second God-object risk, and a polling interval the integration must not make
  user-configurable, for state that is a pure function of inputs. The
  `StageEnvironmentalTargets` precedent (a pure per-call object, not a
  coordinator) is the established shape for exactly this.
- **Fold EC reasoning into the existing `SubstrateTracker`.** Rejected:
  the tracker is deliberately *measurement history* (ADR-0010, recorder-free,
  chart-only) — it must never become a place that reads config targets or emits
  actuation recommendations. Feed targets and recommendations are config/decision
  concerns, not measured events.

## Migration / back-compat

`ECState` adds **no new model fields** and changes **no stored shape**. It reads
`IrrigationStrategy` (band + `ec_modulation_enabled`), `IrrigationConfig.
ec_target_ranges`, `NutrientManager.ec_ramp_curves`, and `DrainConfig.readings`
— all already persisted. Existing stored configs deserialize unchanged. A
growspace with only a pore-EC sensor gets **byte-identical modulation behavior**:
`active_feed_ec` and `runoff_ec` resolve to `None` and the recommendation is
driven purely by pore-vs-band, as today.

## Tension flagged

ADR-0012 ([[Steering Mode]] preset stamp) stamps the [[Pore EC Target Band]] but
**not** any feed-EC target — feed EC is hand-mixed and the stamp deliberately
never touches it. `ECState` honors this: it *resolves* a feed target from the
grower's separately-configured ramp curve/range but never *writes* one and never
lets the feed target move the band. No contradiction, but the boundary is worth
recording: the stamp owns the band, the grower owns the feed curve, and
`ECState` only reads both.
