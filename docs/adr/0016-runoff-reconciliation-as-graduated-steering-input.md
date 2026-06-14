# Runoff becomes a graduated steering input through the EC State seam

**Status:** Accepted

**Depends on ADR-0015** ([[EC State]]). This ADR turns runoff from a binary
safety cut-off into a real, graduated steering signal — and it does so *through*
the `ECState` seam, not as a sixth scattered code path.

Today runoff has two behaviors and one corpse:

- `_is_halted_by_runoff_ec` — a hard binary: latest `drain_ec` over
  `halt_on_runoff_ec_threshold` ⇒ suspend all irrigation. All-or-nothing.
- `max_ec_delta` — fires a log-warning/notification on a manual
  `log_drain_reading`, duplicated across two files (ADR-0015 consolidates the
  duplication).
- `target_runoff_percent` — **dead**: stored, settable, shown in the view model,
  read by nothing. The grower's stated runoff goal influences zero decisions.

A professional runoff conversation is graduated, not binary: *within* the EC
band and at target runoff %, hold; runoff EC drifting high, bias toward flush
(bigger shots, more runoff) *before* it hits the panic threshold; the hard halt
is the **top** of that ramp, not a separate world.

## Decision

Make `target_runoff_percent` and `max_ec_delta` **live**, and route the runoff
signal through `ECState`'s [[EC Recommendation]] rather than a parallel branch.

### 1. Compute the runoff observables (new derived values, no new stored fields)

From the latest [[DrainReading]] `ECState` derives two values it already has the
inputs for:

- **[[Runoff Percentage]]** = `drain_volume_ml / feed_volume_ml × 100`, compared
  against `DrainConfig.target_runoff_percent`. `None` when either volume is
  absent — see Sensor-Gated Capability below.
- **[[Feed-to-Runoff EC Delta]]** = `drain_ec − feed_ec` of the latest reading,
  compared against `DrainConfig.max_ec_delta`.

These join the `ECState` dataclass (`runoff_percent: float | None`,
`feed_to_runoff_delta` already present from 0015) — derived, never persisted.

### 2. Runoff biases the recommendation; it does not get its own loop

The graduated response lives **inside** `ECState.recommendation`. The pore-EC
band remains the primary signal (it is the closed loop; ADR-0012 stamps it).
Runoff is a **bias on the same enum**:

- Pore EC within band **but** [[Feed-to-Runoff EC Delta]] above `max_ec_delta`
  (substrate is accumulating salts faster than the pen shows) → recommendation
  escalates `HOLD → FLUSH`.
- Pore EC within band and runoff healthy → `HOLD`.
- The existing binary halt is surfaced as a **separate `halt_irrigation: bool`
  field on `ECState`**, *not* a member of `ECRecommendation`. It is computed
  unconditionally from `drain_ec > halt_on_runoff_ec_threshold`, **independent of
  `ec_modulation_enabled`**. `_is_halted_by_runoff_ec` reads the bool;
  `_compute_ec_modulation` reads the enum. Two criticality levels (a safety
  cut-off vs. an opt-in advisory adjustment) get two fields, so the halt can
  never be masked by a grower opting out of modulation — see the decision note
  below.

EC Modulation continues to read only `ECState.recommendation` (the 0015 seam),
so **no new actuation path is introduced** — `FLUSH`-by-runoff and
`FLUSH`-by-pore-EC produce the same upward shot-size bias through the existing
`_ec_modulation_factor_for_reading` magnitude helper. The recommendation gains
runoff awareness; the actuator stays single.

**Which EC drives the magnitude (implementation decision).** The helper maps an
EC reading's excursion *past the band* to a factor, so a pore reading that is
*within* the band yields exactly 1.0 — meaning a runoff-driven `FLUSH` (pore
within band) would otherwise change the recommendation without enlarging the
shot. The resolution: the magnitude reads **whichever EC is driving the flush**.
A pore-driven flush/stack uses pore EC (byte-identical to today); a runoff-driven
flush uses the **runoff EC**, which sits above the band precisely when salts are
stacking. Both go through the one unchanged helper, so a fired shot stays
explainable from a single factor. A runoff `FLUSH` whose runoff EC happens to be
within the band yields a modest 1.0 — acceptable, since the over-target *delta*
that triggered it does not by itself imply the substrate EC is high.

### 3. Runoff feeds the Crop Steering Score

`calculate_crop_steering_score` ignores runoff entirely today. Runoff joins the
score on a **shared EC axis**, not as a fourth independent component — because the
pore-[[EC Trend]] and a sustained [[Feed-to-Runoff EC Delta]] are *correlated EC
signals* (both report salts moving). Summing both at full ±0.3 would make the
EC-ish contribution ±0.6 — larger than dryback's ±0.4 — inverting the intended
primacy of dryback. So the EC axis holds **one** value, capped ±0.3:

- When a pore-EC Trend is measured (`rising` → +0.3, `falling` → −0.3), it sets
  the axis. The pore band is the closed loop (ADR-0012 stamps it), so a measured
  in-substrate Trend is authoritative.
- Only when the Trend is `None` (no pore-EC sensors) or `stable` does the runoff
  delta fill the axis. Runoff's job is to **extend** the EC signal to growers
  without pore-EC sensors, never to override or stack on a measured Trend. When
  both agree, pore already maxes the axis, so the result is identical; the rule
  only bites on disagreement, where the continuous in-substrate sensor wins.

The fill is `None`-safe: absent drain data contributes exactly 0.0, so the score
is unchanged for growers without a runoff pen.

**The ratified bucket (HITL gate, now closed).** "Sustained" reuses §2's notion —
unanimous agreement across the tail (last 2–3 entries) of the already-persisted
`DrainConfig.readings`, scored on the *weakest* agreeing reading (no new state, no
[[SubstrateTracker]] involvement; ADR-0010 keeps it recorder-free). Symmetric,
keyed off the grower's `max_ec_delta` (Δmax):

| weakest reading in tail | nudge |
|---|---|
| ≥ 2·Δmax | +0.3 |
| ≥ Δmax | +0.2 |
| straddles / within ±Δmax | 0.0 |
| ≤ −Δmax | −0.2 |
| ≤ −2·Δmax | −0.3 |

The +0.2 tier fires at exactly the `max_ec_delta` point §2's flush-bias engages,
so actuator and readout agree. [[Runoff Percentage]] does **not** feed the score
in v1 — it is a noisier, volume-sensor-gated, volume (not EC) signal; it stays in
the `ECState` payload for display and may later join the shot-frequency axis. As
in ADR-0012's baseline table, individual cells still take maintainer sign-off on
the implementation PR.

### The interface delta on ECState

```python
@dataclass(slots=True)
class ECState:                       # extended from 0015
    ...
    runoff_percent: float | None     # drain_vol / feed_vol × 100, or None
    runoff_pct_target: float | None  # DrainConfig.target_runoff_percent
    recommendation: ECRecommendation # now also: FLUSH-by-runoff (NOT halt)
    halt_irrigation: bool            # drain_ec > halt threshold; ec-mod-independent
```

`ECRecommendation` stays the four modulation-direction values from 0015
(`stack`/`hold`/`flush`/`unavailable`) — **no `HALT` member**. The hard halt is
the separate `halt_irrigation` bool. The score's runoff fill is a pure
`runoff_score_component(readings, max_ec_delta) -> float` (the bucket table
above, `None`-safe); `calculate_crop_steering_score` composes it onto the shared
EC axis (pore Trend wins; the fill applies only when Trend is `None`/`stable`),
so the score logic stays a pure function and no method is added to `ECState`.

### Why the halt is a separate field, not an enum member

Folding `HALT` into `ECRecommendation` was the original sketch and is rejected.
ADR-0015 specifies that when `ec_modulation_enabled` is False the recommendation
is `UNAVAILABLE` (factor 1.0) — the enum is the *modulation* machine, gated by the
modulation opt-in. A grower with a runoff-EC sensor and a halt threshold set but
who has **not** opted into EC Modulation would then have their *safety halt
computed inside a machine that is switched off*. A safety cut-off must not depend
on an unrelated advisory opt-in. `halt_irrigation` is therefore its own boolean,
evaluated unconditionally from `drain_ec > halt_on_runoff_ec_threshold`. This is
what makes the ADR's own claim — "the safety floor never depends on the richest
sensor tier" — actually hold; the enum-member design quietly violated it by tying
the floor to the modulation opt-in.

## Sensor-Gated Capability tiers

Runoff reconciliation degrades cleanly along [[Sensor-Gated Capability]]:

| Grower has…                              | They get…                                                |
|------------------------------------------|----------------------------------------------------------|
| Pore-EC only                             | Exactly ADR-0015 behavior; runoff inert                  |
| Drain **EC** readings, no volumes        | [[Feed-to-Runoff EC Delta]] reconciliation + the `halt_irrigation` safety cut-off. **No** [[Runoff Percentage]] |
| Drain EC **and** volume sensors          | Full reconciliation incl. [[Runoff Percentage]] vs. target |

The hard halt works with **no volumes at all** (it reads `drain_ec` only), so the
safety floor never depends on the richest sensor tier.

## What lives behind the seam

The runoff math (percentage, delta, the bias→recommendation mapping, the score
component) all lives in `domain/ec_state.py` + `crop_steering.py`, both pure and
lambda-testable. The pump loop, the notification transports, and `DrainConfig`
storage are untouched. `_is_halted_by_runoff_ec` collapses from a predicate that
re-reads config into a one-line check of `ECState.halt_irrigation`.

## Deletion test

Delete the runoff-bias logic (the 0016 additions on top of 0015): the
recommendation falls back to pore-only `STACK/HOLD/FLUSH/UNAVAILABLE`,
`_is_halted_by_runoff_ec` reverts to its standalone threshold check, and the
score drops its runoff component. ADR-0015's `ECState` still stands and still
reconciles feed vs. pore. The two ADRs are layered, not entangled: 0016 is a
*bias and a score component*, removable without touching 0015's interface beyond
three additive fields.

## Rejected alternatives

- **A separate `RunoffController` parallel to EC Modulation.** Rejected: it
  recreates the disconnection this whole effort removes — two actuators both
  scaling P2 shots, fighting or compounding with no single explainable factor.
  CONTEXT.md's [[Shot Size Composition]] is explicit that a fired shot must be
  explainable from independent, named factors; a second EC actuator breaks that
  contract. Runoff must speak *through* the one EC recommendation.
- **Make runoff % a hard gate (suspend when off-target) like the EC halt.**
  Rejected: runoff percentage is noisy (channeling, uneven emitters, a single
  mis-measured catch) and a low-confidence signal compared to the EC pen.
  Gating irrigation on it would strand plants on a bad reading. It earns a
  *score nudge and a flush bias*, not a cut-off; only runoff **EC** (the
  higher-confidence, safety-relevant signal) keeps the hard `halt_irrigation` cut-off.
- **Resurrect `target_runoff_percent` as a closed actuation loop (drive shot
  size to hit a runoff %).** Rejected for v1: there is no dosing hardware and
  runoff % responds to shot size with long, media-dependent lag; a naive
  proportional loop would oscillate. It becomes an *observability + bias* signal
  now; a true runoff-% setpoint loop is explicitly deferred.

## Migration / back-compat

No new **stored** fields — `runoff_percent`, `runoff_pct_target`, the
`halt_irrigation` flag, and the score bias are all derived per-call from
already-persisted `DrainReading` / `DrainConfig` data (the sustained delta from
the `DrainConfig.readings` tail). Nothing new is serialized. Existing configs
deserialize unchanged; a growspace with no drain readings sees zero behavioral
change. `target_runoff_percent` and `max_ec_delta` keep their current defaults
(20.0 / 0.7) and existing stored values; they simply stop being dead.

## Tension flagged

The runoff score component is the first time the [[Crop Steering Score]] reads a
*config target* (`target_runoff_percent`, `max_ec_delta`) rather than a pure
measurement. The score stays an absolute −1…+1 *measurement* (ADR-0012's
invariant), but "how far runoff EC sits past the grower's max-delta target" is a
measurement-relative-to-a-setting — the same shape as [[Intent Deviation]].
Recorded here so a future reader does not mistake it for the score bending toward
a declared intent: it does not; it reads a physical salt-accumulation signal that
happens to be *thresholded* by a grower-set tolerance.
