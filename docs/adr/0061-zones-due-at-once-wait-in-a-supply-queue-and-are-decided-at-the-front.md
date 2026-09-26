# Zones Due at Once Wait in a Supply Queue, and Are Decided at the Front

**Status:** Accepted — not yet implemented

ADR-0058 put one [[Irrigation Supply]] on each growspace and opens strictly one [[Irrigation Zone]] on it at a time. ADR-0060 bounded a growspace at 6 zones and warns, at configuration time, when a growspace's own settings cannot fit its pump. Neither says what happens when two zones want water in the same minute (#859).

Today nothing arbitrates. A steering shot, a scheduled shot and a Manual Run all **cancel** whatever irrigation cycle is already running and start their own. Under ADR-0054 an aborted shot costs the daily cap its whole plan, so with several zones this would waste allowance and lose shots whichever zone asked last.

Each growspace gets one **[[Supply Queue]]**, and a zone waits in it with a **[[Supply Claim]]**.

1. **A claim, not a shot.** A Supply Claim says only that a zone is due. It carries no composed shot.
   - A zone holds at most one claim. A zone that comes due again while it is queued adds nothing.
   - When a claim reaches the front of the queue, the zone decides afresh. A steering zone runs its Steering Phase Machine and composes its shot from the current [[Control Measurement]]. The [[Infiltration Gate]] and the [[Pump Cycle Gate]] are checked then, not when the zone first asked.
   - A late shot is therefore never sized from a reading it no longer matches. At the envelope's worst case, a claim behind five others has waited 5 × (118 s + 32 s), about 12.5 minutes.
2. **Order.** Claims are served first in, first out, by the minute the zone became due. Ties go to the grower's zone order, the order of the growspace's zone list.
   - Ties are the ordinary case, not an edge case. At lights-on every steered zone enters P1 on the same tick.
   - A served zone that comes due again joins the back. With one claim per zone, that is round-robin, and no zone can be starved.
3. **Nothing that asks for water preempts a running shot.** A running cycle is stopped only by what already stops the pump: the emergency stop, a latched [[Fault]], a [[Manual Override]] and the watchdog.
   - A [[Manual Run]] goes to the **front** of the queue and waits for the running shot to finish, at most `max_cycle_seconds` plus about 32 s of confirmation. Manual Runs among themselves are first in, first out.
   - A Manual Run is a person's request, not the zone's, so it sits outside the one-claim-per-zone rule. Its confirmed ON moves the zone's cooldown as it does today. The zone's own claim, if next, is then normally withheld by that cooldown.
   - The service returns once the run is queued, as the run already happens in the background.
4. **Drains are not in the queue.** The drain pump is its own output, not the Irrigation Supply, so drains compete for nothing and keep their own schedule.
5. **Waiting counts against the zone.** The steering cooldown still runs from the last **confirmed ON**, and so does the Infiltration Gate's stall backstop and the schedule's `min_interval_minutes`. A shot that waited 8 minutes pushes the zone's next shot 8 minutes later. The interval is about how the substrate responds to water it received, not about the calendar.
6. **No deadline of its own.** A claim is never dropped for being old. The zone's own decision at the front is the deadline, so a phase that matters differently when late does so through the Steering Phase Machine rather than a second table:
   - A P2 claim that reaches the front after `p2_stop` finds P3 and is withheld.
   - A claim that reaches the front after lights-off is refused by the dark check.
   - A P1 claim still inside its window fires, composed for the reading it now sees.

   The wait itself is bounded by round-robin: at most (N − 1) × (longest shot + 32 s), plus any Manual Runs queued ahead.

7. **Recording (ADR-0055).** A [[Delivery Attempt]] still begins when a request reaches the Pump Cycle Gate, which now means when its claim reaches the front. Waiting adds no state and no suppression reason.
   - The attempt gains **`due_at`**, the minute its claim entered the queue. `on_commanded_at − due_at` is the wait.
   - A steering claim the zone withholds at the front makes no attempt, like any withholding tick.
   - While a zone's claim waits, its steering tick reports `suppressed_by = "queued"`. That answers "why isn't zone 3 watering?" without a row.
8. **Holds.** The queue releases its head whenever the supply is free. It never holds claims back for a reason of its own.
   - Under an operator hold, a Manual Override, an [[Unexpected On]] or a latched Fault, each claim reaches the gate and is suppressed with the hold's reason, exactly as every request is today. ADR-0055 merges the consecutive rows.
   - Once the hold clears, zones claim again by their own decisions.
9. **Restart.** The queue lives in memory only. A restart drops it and nothing is replayed (ADR-0049). A claim that never reached the gate has no attempt to close.
10. **The shared cap is not divided.** The daily caps stay per growspace (ADR-0057). A zone that uses up the allowance before others have had a turn is accepted as the safe direction. Each attempt it suppresses names the cap, and today's attempts already show which zones used it.
11. **When the zones cannot all be served on time**, every zone is still served, only less often: its effective interval stretches to the queue's cycle. Nothing is skipped for being late. ADR-0060's configuration-time Repairs warning is the only alert. The wait is visible on every attempt through `due_at`, and how the card shows it belongs to #864.
12. **Seam.** The queue is a pure `domain/supply_queue.py` in the Steering Phase Machine's mould: plain values in, the next claim out, and zero-mock tests. The growspace's [[Irrigation Controller]] is its effects shell. It replaces today's cancel-the-running-task code in the schedule handler, the steering shot and the Manual Run.

## Considered Options

- **Queue composed shots.** A shot sized when its zone became due fires up to 12.5 minutes later against a reading it no longer matches. A queue of shots can also hold several per zone.
- **Order by VWC deficit (most behind first).** It compares figures across probes and substrates on different baselines, which ADR-0059 refused to do for probes within one zone.
- **Order by steering phase (P1 before P2).** A long P1 ramp on one zone can starve every P2 zone behind it.
- **A fixed zone priority.** The same starvation, chosen by the grower rather than by the phase.
- **Let a Manual Run preempt the running shot.** The aborted shot costs the cap its whole plan (ADR-0054) and the zone loses it, to save a person the rest of one shot: about two and a half minutes for the longest shot the envelope fits, and never more than `max_cycle_seconds` (600 s by default).
- **Count the cooldown from the due time.** A late shot could then be followed early, against a substrate still taking up the water it just received.
- **A deadline per phase** (for example, a P2 claim older than 10 minutes is skipped). It is a second rule about phase timing beside the Steering Phase Machine's, and the two could disagree.
- **A `queued` Delivery Attempt state, opened when the claim is queued.** It costs a row and a write per wait, and a claim the zone withholds at the front would leave behind exactly the steering-withhold row ADR-0055 rejected.
- **Hold claims in the queue while the supply is held.** When the hold clears, every zone would fire back to back on claims from before it, and the queue would need its own view of every hold the gate already knows.
- **A durable queue.** It replays requests after a restart, which ADR-0049 refuses for steering shots.
- **Per-zone shares of the daily cap, or a reserve for zones not yet served.** Budgeting is not a runaway backstop (ADR-0057). A reserve refuses water that a zone needs now for a zone that might need it later.
- **A runtime Repairs issue when a zone's observed wait exceeds its interval.** Every overrun that settings cause is already caught at configuration time. The rest would mostly fire on days someone ran several Manual Runs.

## Consequences

- **A single-zone growspace changes behaviour too.** A scheduled shot or Manual Run arriving during a running shot now waits for it instead of cancelling it. How existing users are told belongs to #863.
- The Delivery Attempt gains `due_at`. The Steering Tick Verdict's `suppressed_by` gains `queued`, for a tick that would fire while its zone's claim is already waiting. It remains a diagnostic that nothing branches on.
- `tests/envelope/` (ADR-0060) drives the queue with the full 6 zones, so its tick budget and pump-time arithmetic include arbitration.
- #864 (the card) can show a zone as queued and a delivered shot's wait. It needs no new backend state beyond `due_at` and the steering diagnostic.
