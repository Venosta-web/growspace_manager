# ADR 0031 — The Infiltration Gate suppresses steering shots while VWC is still climbing

**Status:** Accepted (rider on [ADR-0023](./0023-steering-phase-machine-owns-the-tick-decision.md); relates to [ADR-0014](./0014-adaptive-shot-interval-and-tunable-feedback.md) and [ADR-0010](./0010-substrate-tracker-persists-events-not-recorder.md))

## Context

The crop-steering minute loop decides whether to fire a shot from the **instantaneous** VWC reading. After a shot, delivered water keeps redistributing through the substrate for minutes — fast in rockwool, slow in coco and large pots — and the probe reports a value still climbing toward its settled peak. Both phase rules read that unsettled value:

| Phase | Fires when | Failure |
|---|---|---|
| P1 ramp-up (`steering_phase.py:294`) | `vwc < target_vwc_percent` + cooldown | Sitting at 52% while genuinely heading to 58%, target 55% → another P1 shot fires → lands at 63% |
| P2 maintenance (`:311`) | `vwc < trigger` + cooldown | Infiltration slower than `p2_shot_interval_minutes` → a second shot stacks on the first |

P1 is the worse case: ramp-up is **open-loop**, stepping VWC upward while blind to where the previous step actually landed. The consequences are overshot target VWC, inconsistent [[Dryback]] behaviour, and wasted water.

Three properties of the existing code shape the solution.

**The sampling pipeline is blind to sensor freshness.** `_get_sensor_value` (`irrigation_coordinator.py:288`) returns `float(state.state)` and discards `state.last_updated`; `_feed_substrate_reading` stamps readings with the *loop's* `now()`. The loop ticks every 60s, so a probe reporting every 5 minutes yields five identical reads. Any slope computed over loop ticks reads exactly `0` → "settled" → the gate opens mid-infiltration, failing hardest on the slow/averaged sensors most likely to lag infiltration in the first place.

**`SubstrateTracker._peak_settling` looks like the answer and is not.** It is literally "VWC is still rising since the last shot", but it clears only when VWC drops more than `SUBSTRATE_NOISE_FLOOR_PCT` (0.5pp) *below* the pending peak (`substrate_tracker.py:194`). On a plateau it stays `True` indefinitely, collapsing `infiltrating` and `settled` into one blocking state — and a gate built on it would withhold irrigation until dryback had visibly begun, which is precisely what P1 exists to avoid. It is also read by *both* dryback windows (`:186`, `:205`), so retuning its clearing rule would silently change measured Overnight and In-Cycle Dryback values.

**[[Adaptive Shot Control]] already corrects overshoot, but after the fact and on a bad signal.** ADR-0014's factors shrink the next shot and lengthen the next cooldown in response to a measured overshoot ratio. That measurement comes from `_composer.observe(moisture_before, moisture_after, ...)`, where `moisture_after` is read after `wait_seconds = min(duration_sec, 15)` (ADR-0008) — at most **15 seconds** after the pump stops, mid-infiltration by construction. The measured ΔVWC is therefore systematically smaller than the true one, so the controller reads *undershoot* where the substrate overshot, and per ADR-0014 relaxes both factors toward 1.0 (bigger shots, shorter cooldowns). Adaptive Shot Control is currently biased toward *more* water. Correcting after the fact on a premature reading cannot substitute for not creating the error.

## Decision

Introduce the **[[Infiltration Gate]]**: a new pure-ish stateful module `domain/infiltration.py` whose state threads into the [[Steering Phase Machine]] as a plain value and is consumed in `_evaluate_shot` beside the existing cooldown check.

```
InfiltrationState = INFILTRATING | SETTLED | DRYING | UNKNOWN

InfiltrationMonitor
    .record(vwc: float, sensor_last_updated: datetime) -> None
    .state -> InfiltrationState
    .reset() -> None
```

1. **Sample on distinct sensor updates, never on loop ticks.** The monitor appends to a small in-memory ring only when `state.last_updated` actually advances, and computes slope in percentage points per minute across those distinct samples. "Flat because settled" and "flat because no new data has arrived" become different answers — the latter is `UNKNOWN`, never `SETTLED`.

2. **A sibling of `_peak_settling`, not a repurpose.** The tracker's flag keeps its current meaning and its current role in dryback bounding. The monitor is a separate stateful controller in the [[ShotComposer]] / [[Steering Phase Machine]] mould — plain values in, no `hass`, no coordinator, owns its own `reset()` rule — so `tests/domain/test_infiltration.py` is zero-mock like its siblings.

3. **Both phases are gated.** The gate is a *floor* under whatever interval the grower configured: a no-op when `p1/p2_shot_interval_minutes` already exceeds infiltration time, biting only on the misconfiguration that produces the bug.

4. **Fail open.** `UNKNOWN` never blocks. Because `_evaluate_shot` checks the configured cooldown *first* and returns early, the gate is **strictly additive** — it can only ever delay a shot that fires today, never permit one today's code blocks. On a dead or missing signal the behaviour is exactly today's.

5. **A stall backstop derived from the grower's own setting.** The gate may hold a shot for at most `3 ×` the active phase's `shot_interval_minutes`; past that it fires anyway and logs once. No new configuration field, self-scaling per growspace and per phase. The log line ("fired despite infiltration") is itself the diagnostic for a leaking valve or a drifting probe.

6. **A suppressed shot is explainable.** `SteeringTickVerdict` gains a `suppressed_by` reason — which also retrofits the currently-silent `cooldown` / `no_pump` / `zero_volume` blocks — surfaced in `shot_composition_payload()` for the card and written to the logbook **edge-triggered** (once when suppression begins, once when it releases), following the `_sensor_warning_logged` latch precedent rather than firing every minute.

Retiming `observe()`'s `moisture_after` to the monitor's `SETTLED` signal is **deliberately out of scope**, filed as a follow-up with its own amendment to ADR-0008 and ADR-0014: it changes measured feedback behaviour for every existing grower and has no fail-open guarantee to hide behind. With the gate in place the mistraining is second-order — stacking is already prevented.

## Consequences

- **Shots are composed against settled readings.** The VWC feeding the P1 target check and the P2 trigger check has finished responding to the previous shot, so the phase rules mean what they say.
- **There is no regression path.** The additive-to-cooldown property is a hard guarantee, not a hope: a bug in the monitor degrades to today's behaviour rather than to a stopped pump.
- **Freshness-aware sampling arrives as a reusable seam.** The monitor is the first component in the integration to read `last_updated`. Other consumers of `_get_sensor_value` remain freshness-blind; this ADR does not change them.
- **The slope deadband is the one genuinely open number.** It cannot be derived from `SUBSTRATE_NOISE_FLOOR_PCT`, which is a magnitude rather than a rate. It ships as a constant in `const.py` alongside the other substrate tuning values, to be validated against real coco and rockwool traces.
- **`projected_shot_window` can be annotated but not predicted.** Release time depends on the substrate, so the projection keeps its cooldown-derived bounds; the payload carries the suppression flag so the card can label the window as held rather than showing a countdown that will not fire.
- **Honest scope:** this prevents the *creation* of the overshoot. The premature `observe()` reading that leaves Adaptive Shot Control biased toward more water is recorded here and fixed separately.

## Why Not

- **Reuse `SubstrateTracker._peak_settling`** — zero new state, but it cannot express `SETTLED` (it clears only on a 0.5pp drop, so a plateau blocks forever, killing P1 ramp-up), and retuning it would change measured dryback values across two features.
- **Slope over loop ticks** — simplest, and broken for every probe reporting slower than once a minute: it reads flat and opens the gate at exactly the moment the feature exists to hold it.
- **`async_track_state_change_event` on the moisture sensor** — the most faithful sampling and no dedupe logic, but it adds a listener plus an unload path and makes a purely time-driven coordinator event-driven, for a signal the minute loop already samples often enough.
- **Fail closed** — matches the grain of `volume_mode_active` and `any_light_sensor_on`, which both fail toward not-actuating. Rejected because here not-actuating is the harmful direction: it would invert the failure mode from "slight overshoot" to "drought", and a restart or sensor dropout would suspend irrigation entirely. The tracker already made the same call for this signal, assuming a persisted pending peak is settled (`substrate_tracker.py:80-82`).
- **An absolute maximum-suppression constant** — predictable, but wrong at both ends of the media/pot-size range, and it is exactly the "additional configurable timeout" the trend-based approach was chosen to avoid.
- **No override at all, surface a repair issue instead** — keeps the gate's guarantee absolute and never masks a hardware fault, but an away-from-home grower loses a day of irrigation to a stuck sensor.
- **Name it "VWC Trend Gate"** — collides with [[EC Trend]], which already binds `rising`/`stable`/`falling` to a *daily* baseline-vs-latest comparison; VWC's daily direction is [[Dryback]], a different concept at a ~500× different timescale. "Settling" was likewise unavailable — ADR-0008 owns "Sensor Settling Delay".
- **Put it in the [[Pump Cycle Gate]]** — that gate is deliberately walled off from steering concerns (tank/limit/dark on the base pump); folding a steering-timing rule into it would break a boundary ADR-0021 states explicitly.
