# ADR 0008 — Sensor Settling Delay runs as a snapshotted background task, not an inline wait

**Status:** Accepted

## Context

Irrigation logbook entries report a "before -> after" moisture comparison (e.g. `Moisture: 46.2% -> 46.2%`). The "after" reading was being captured the instant the cycle's `asyncio.sleep(duration)` completed — before the pump even switched off — so the sensor had no time to reflect the water that was just delivered. The comparison routinely showed no change, making the report misleading.

The fix is the **Sensor Settling Delay**: wait `min(measured_cycle_duration, 15s)` after the cycle ends before reading the "after" value and firing the completion report.

Two structural questions had genuine alternatives:

1. **Where does the wait live relative to "cycle is done"?**
   - *Inline*: extend the `finally` block — sleep, then read sensor, then report, then release `_running_tasks`/`_active_events`. Simple, but ties up to 15 extra seconds of "this event type is busy", blocking a fast-following scheduled or manual cycle even though the pump is already off and hardware is ready.
   - *Background task*: release `_running_tasks`/`_active_events` and turn the pump off immediately as today; spawn a separate task that sleeps, reads the sensor, and reports.

2. **What does the background task read — live coordinator state, or a snapshot?**
   - *Live*: re-read `self._volume_dispensed_today`, `self._cycles_today`, etc. when the task wakes up. Simpler, but if a new cycle starts during the 15s window, the report would describe the *old* cycle using the *new* cycle's counters.
   - *Snapshot*: capture every value the report needs (`start_dt`, `end_dt`, `duration_sec`, `moisture_before`, `volume_dispensed_today`, `cycles_today`, `event_type`) into local variables before spawning the task. The task's only "live" read is the post-wait moisture sensor value — the one thing that *must* be read late.

## Decision

Run the Sensor Settling Delay as a **background task spawned after the pump is off and the running-task slots are released**, operating entirely on a **snapshot of pre-wait state**, with the post-wait moisture read as the sole live value. The task is tracked and cancelled on integration unload, mirroring the existing `_running_tasks`/`_active_events` cleanup discipline.

## Rationale

Decoupling "cycle is operationally complete" from "we're still composing its report" matches the existing principle that reporting/cosmetic concerns shouldn't gate hardware readiness — the pump must be free to run again the moment it's safe, regardless of how long sensor settling takes. Snapshotting is the only way to guarantee the eventual logbook entry actually describes the cycle it claims to, rather than whichever cycle happens to be running 15 seconds later.

## Consequences

- A `GrowspaceEvent` for a cycle can land in the timeline up to 15s after the cycle's pump switched off — slightly out of step with a fast-following cycle's "started" event, but internally consistent and accurate.
- The background task must handle `CancelledError` cleanly (no firing events on a torn-down coordinator) and be registered for cleanup via the integration's unload path.
- This delay/snapshot machinery is shared infrastructure: drain cycles don't yet report moisture, but when they do, they reuse the same settling wait rather than inventing a parallel mechanism.

## Amendment (2026-08-08) — the feedback measurement leaves this wait (#534)

The 15s delay was written to serve **the logbook line**, and it still does: this
decision — the background task, the snapshot contract, the `min(duration, 15s)`
bound, the cancellation discipline — is unchanged for that consumer.

What it silently acquired later was a second consumer. `VWCIrrigationCoordinator`
overrides `_async_report_cycle_completion`, and after `super()` returns it
re-reads the moisture sensor and feeds `_composer.observe()` — so [[Adaptive Shot
Control]]'s feedback measurement inherited a timer chosen for a display string.
Fifteen seconds is mid-[[Infiltration]] by construction, so the measured ΔVWC is
systematically small and the controller reads undershoot where the substrate
overshot (ADR-0031 Context; ADR-0014 amendment for the correction).

**The two consumers are split.** The [[Settled Observation]] moves out of this
task entirely and waits on the [[Infiltration]] signal instead of a timer. The
alternative — retiming *this* wait so both consumers share one settled reading —
was rejected: it would push logbook entries minutes behind the cycle they
describe, rewriting this ADR's "up to 15s out of step" consequence into "up to
several minutes," and it would put a reading corrupted by a fast-following cycle
in front of a grower as fact. The logbook line is early but harmless; the
feedback reading is load-bearing control input. Only the load-bearing one moves.

Consequences for this decision specifically:

- **The snapshot contract now has a second, longer-lived beneficiary.** The
  values this task snapshots are the same values the Settled Observation needs
  (`end_dt`, `moisture_before`), and for the same reason: a report must describe
  the cycle it claims to. The Settled Observation carries its own frozen
  snapshot for the same guarantee over a window measured in minutes rather than
  seconds — where a second cycle landing inside the window is normal operation,
  not an edge case.
- **The two after-readings may disagree.** The logbook can say
  `Moisture: 46.2% -> 46.4%` for a cycle the controller measured as landing at
  48.1%. Both are honest reports of different moments. Surfacing the settled
  delta alongside the 15s one is a real gap, deliberately left to its own issue
  (it is card-visible surface area under ADR-0030's contract fixture).
- **This task no longer waits on behalf of anything but the report**, so its
  bound stays 15s and is not a candidate for retuning when infiltration
  behaviour is discussed.
