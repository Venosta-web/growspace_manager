# Adaptive shot interval and user-tunable VWC feedback

The VWC crop-steering loop already adapts shot **size**: `_shot_scale_factor`
compares the actual VWC rise from the last settled shot against the target rise
and shrinks the next shot (clamped `[0.5, 1.0]`) on overshoot, recovering toward
nominal on undershoot. This decision adds a symmetric adaptation of shot
**interval** and makes the whole feedback controller user-tunable, behind a
single master toggle.

## Interval adapts via a cooldown factor, not a new trigger

P2 maintenance shots already self-space: they fire when VWC drops below
`target − maintenance_dryback` (or `soil_trigger_percent`), so the *actual* P2
spacing already tracks how fast the substrate dries. `p1/p2_shot_interval_minutes`
is only a **minimum-cooldown floor**. Adaptive interval therefore does **not**
introduce a new trigger or replace the dryback mechanism — it scales that
cooldown floor with a new `_interval_scale_factor` (sibling to
`_shot_scale_factor`), clamped `[1.0, interval_ceiling]`. The factor only ever
**lengthens** the floor or returns it to nominal; it never shortens below the
configured interval. Like the size factor it is session-only and resets to 1.0
at lights-on and across the P1→P2 transition.

Rejected: (a) adapting the dryback **setpoint** instead, making interval purely
emergent — this conflates the steering target (a grower-owned lever) with a
control-loop correction; (b) driving interval from an independent dryback-**rate**
signal — more "correct" in isolation but a second estimator to tune and explain,
for a marginal gain over reusing the overshoot ratio already computed for size.

## Overshoot lengthens the interval (accepted double-correction)

On overshoot the controller both shrinks the shot (size factor down) **and**
lengthens the interval (interval factor up); on undershoot both recover toward
nominal. The two corrections push the same direction — less water delivered per
unit time — which is a deliberate double-correction. It is defensible because
shot size and shot spacing are physically distinct levers (volume per shot vs.
dryback depth between shots), and the shared `aggressiveness`/`recovery` gains
plus the clamps bound any compounding. The alternative — interval reacting to a
different signal than size — was rejected for the reason above.

## One master toggle, shared tunables, default on

Five fields are added to `IrrigationStrategy`: `dynamic_shot_enabled` (master
switch over both size and interval adaptation), and shared tunables
`dynamic_aggressiveness`, `dynamic_recovery`, `dynamic_shot_size_floor`, and
`dynamic_interval_ceiling`. Size and interval share one aggressiveness/recovery
pair so the loop has one consistent "feel"; only the bounds differ (size floor
below 1.0, interval ceiling above 1.0).

`dynamic_shot_enabled` defaults **True**. The size feedback shipped always-on
and undocumented, so defaulting off would silently disable it for existing
growspaces on upgrade; defaulting on preserves that behavior, and the genuinely
new capability is the *ability to turn it off*. The cost is that interval
adaptation also switches on for existing growspaces — a real behavior change,
mitigated by a modest default `dynamic_interval_ceiling` and the fact that a
well-tuned space rarely overshoots, so the factor sits near 1.0 in practice.

## Amendment (2026-08-08) — the feedback update runs on a settled reading, or not at all (#534)

Everything above assumed `observe()` receives the VWC the shot actually
achieved. It did not. `moisture_after` was read after ADR-0008's
`min(duration, 15s)` wait — mid-[[Infiltration]] by construction — so `d_actual`
was systematically **smaller** than the true rise. The controller therefore read
*undershoot* where the substrate overshot, and the rules above then recovered
the size factor toward 1.0 (bigger shots) and relaxed the interval factor toward
1.0 (shorter cooldowns). The feedback loop written to correct overshoot was
biased toward **more water**, compounding the error it exists to remove.
ADR-0031's [[Infiltration Gate]] stops the overshoot being *created*; this
amendment fixes the measurement that mistrains the correction.

### The measurement waits for a signal, not a timer

`observe()` fires when the [[Settled Observation]] resolves: the
`InfiltrationMonitor` reports at least two distinct sensor updates stamped after
the cycle's `end_dt`, with a slope that is no longer positive. The monitor
returns the reading itself rather than a boolean, so `moisture_after` is
provably one of the samples the readiness rule was evaluated over — there is no
second sensor read anywhere in the path to drift from it.

Three sub-decisions, each with a rejected alternative:

- **`drying` satisfies the wait, not only `settled`.** Falling VWC is
  unambiguous evidence infiltration finished. Requiring flatness would strand
  growspaces with a brisk [[Dryback]] — the *well-tuned* case — whose slope can
  cross from rising to falling without a tick inside the deadband, starving
  feedback on exactly the spaces that are working. The cost is a reading below
  the true peak, bounded by one to two sample intervals of dryback: ~0.1–0.5pp
  against shot deltas of 2–5pp. Tracking the post-cycle peak instead was
  rejected as a worse trade — a max over samples is more exposed to a single
  spiky reading, converting a small systematic bias into an occasional large one
  in the shot-shrinking direction.
- **Requiring post-`end_dt` samples is the whole safety property.** A bare
  `state is SETTLED` check is not merely weaker, it fails *silently toward the
  original bug*: right after a shot, a 5-minute probe's sample ring still holds
  only pre-shot flat readings, reporting `settled` before the cycle has appeared
  in the data at all. The monitor's window cutoff runs only inside `record()`,
  so a dead probe likewise leaves a stale ring reporting `settled` forever.
- **The wait is bounded by ADR-0031's backstop expression**
  (`INFILTRATION_BACKSTOP_INTERVALS × interval_minutes × effective_factor`),
  anchored on `end_dt` and computed from the snapshot rather than live state —
  a pending observation must not read the interval factor it is about to
  change. Reusing the backstop rather than minting a timeout constant keeps one
  coherent story: the point where the gate stops believing the infiltration
  signal is the point where the observation stops waiting for it, and it
  self-scales per growspace and per phase with no new configuration field. A
  fixed constant was rejected on the grounds ADR-0031 already gave for absolute
  suppression limits — it is wrong at both ends of the media and pot-size range.

### An observation is abandoned, never approximated

Three paths abandon: the bound expires; a fast-following cycle starts
(`_last_cycle_timestamp` advances past the snapshot's `end_dt`, i.e. confirmed
switch-on, manual runs included); or a sensor dropout outlasts the bound. In
every case `observe()` simply does not run, leaving both factors untouched.

Note the bound (`3 × interval`) deliberately exceeds the cooldown
(`1 × interval`), so a shot firing mid-observation is normal operation. That
makes abandonment load-bearing rather than an edge case: without it, a second
shot's water would be attributed to the first shot's delta, and the controller
would read a large *overshoot* on a fiction — replacing today's systematic
under-read with an occasional wild over-read. Shortening the bound to dodge this
was rejected: it would time out on precisely the slow-substrate growspaces the
feature exists to serve.

The **sensor-dropout case needs no branch at all**, which is the design's best
property. The loop already calls `InfiltrationMonitor.reset()` on an unavailable
sensor; since readiness requires two samples stamped after `end_dt`, a cleared
ring cannot satisfy it until fresh post-cycle samples arrive. A brief dropout
that recovers still yields a valid observation; one that does not falls out the
bound. No pre-dropout sample can reach the slope.

"Fail open" is deliberately **not** the phrase for this. For the Infiltration
Gate it means let the shot through; here the harmful action is running the
feedback update on a bad reading, so the safe direction is to do nothing. Same
words, inverted mechanics.

### The observation lives in the minute loop, not a task

The pending observation is a frozen snapshot retained on
`VWCIrrigationCoordinator` (beside `_infiltration`, `_machine` and `_composer`,
all per-growspace controller state) and evaluated by `_update_loop` immediately
after the monitor is fed. A second background task polling the monitor was
rejected for one decisive reason: it would re-read the sensor itself, measuring
on a different read from the one the readiness rule was evaluated over — a value
the monitor never saw, on a slow probe usually from a moment it never sampled.
Loop evaluation also removes the poll-cadence question (the loop's 60s tick is
already the monitor's feed cadence), the second task set and unload path, and
any window between the fast-follow check and the `observe()` call.

A consequence to leave standing rather than fix: while steering is disabled or
the loop early-returns, a pending observation is never evaluated and simply
lingers until the next cycle replaces it. It can never be observed — readiness
and the fast-follow check both gate on it — so adding a timer to reap it would
be machinery for no behaviour.

### Consequences for existing growspaces

- **No migration and no grace period.** The factors are session-only, live
  nowhere in `storage_manager.py`, and reset to 1.0 at midnight and on P1→P2.
  There is no persisted state to migrate; the retuning self-applies within one
  light cycle.
- **`observe()` no longer runs once per cycle.** A slow probe, a fast shot
  cadence or a flaky sensor now yields few observations or none, leaving the
  factors near nominal for much of the day. Adaptation becomes *less active but
  directionally correct*, where it was fully active and biased toward more
  water. This is the trade, not a free win.
- **The Infiltration Gate now does double duty.** By enforcing spacing it is
  also what keeps observations viable; a growspace that shots faster than its
  substrate settles has no valid overshoot measurement to be had, and saying so
  is more honest than synthesising one from two shots.
- **Manual runs still train the controller**, as they always have, though the
  composer did not choose their volume — while simultaneously invalidating any
  observation they land inside. That asymmetry is a known wart, left standing so
  this change moves exactly one variable; excluding them is a separate
  behaviour change with its own blast radius (a grower who mostly hand-waters
  would go from trained to never-trained) and deserves its own argument.
- **CONTEXT.md's [[Adaptive Shot Control]] entry becomes true.** It already
  claimed the coordinator "triggers `observe()` after each settled cycle" — a
  description of the intent, never of the code. The gap is now closed rather
  than reworded.
