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
