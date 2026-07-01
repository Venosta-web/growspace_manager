# Grow Light Controller: Configurator vs Live-Driven Two-Path Control

The Grow Light Controller drives a growspace's lights from a single schedule (cycle start = `lights_on_time`, derived read-only end = start + veg/flower photoperiod) plus a fixed power, but it does **not** command lights uniformly the way the fan/humidifier controllers do. It has two control paths chosen by device kind:

- **AC Infinity = configurator.** GSM does not tick the device. It writes the device's *onboard* schedule once — Active Mode → `Schedule`, the `schedule_mode_on_time` / `schedule_mode_off_time` `time` entities, the `on_power` number, and the **Sunrise** ramp (`onTimeSwitch` switch + `onTime` duration) — and the AC Infinity controller runs the cycle autonomously. Settings are (re)pushed on config save, integration restart, and photoperiod flip.
- **Plain (`switch.*` / `light.*`) = live-driven.** No onboard schedule exists, so a subsystem coordinator ticks the entity on at the configured power from cycle start and off at the derived end. No sunrise on this path.

## Considered Options

- **Single uniform path (always drive On/Off live, even for AC Infinity).** Rejected: it throws away native sunrise. A smooth hardware ramp only happens in AC Infinity's onboard `Schedule` mode; it cannot be reproduced by toggling the `On`/`Off` Active-Mode select that ADR-0022's `ACInfinityDriver` uses. Sunrise is the headline feature, so the uniform path defeats the purpose.
- **Software-simulated sunrise for plain dimmables.** Deferred: a brightness-ramp loop for `light.*` is possible but out of scope for "simple for now"; sunrise stays AC-Infinity-only.

## Consequences

- This is a deliberate deviation from ADR-0022's "command every actuator uniformly through `ActuatorDriver`." The grow-light AC Infinity interaction (`Schedule` mode + `time` entities + sunrise) is a *different* surface from the `On`/`Off` + intensity bundle that ADR-0022 standardised, and must not be folded into `ActuatorDriver`.
- Because the AC Infinity device runs the cycle itself, GSM must re-push the schedule whenever the derived photoperiod changes (veg→flower flip) — the device has no knowledge of plant stage. A missed re-push leaves a stale (too-long) photoperiod on the hardware.
- **The "re-push on flip" trigger needs a signal source that does not exist yet.** `PhotoperiodFlipChecker` today only calls `async_send_notification`; it fires no event and exposes no hook to subscribe to. Implementation must add the mechanism — either extend `PhotoperiodFlipChecker` (which already iterates growspaces at midnight + on startup) to drive the controller's re-push, or give the Grow Light Controller its own midnight/startup re-derivation. Without this, "push on flip" is unimplementable as stated and the AC Infinity schedule silently goes stale at flip.
