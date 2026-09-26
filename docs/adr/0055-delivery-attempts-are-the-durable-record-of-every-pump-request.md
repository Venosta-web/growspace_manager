# Delivery Attempts Are the Durable Record of Every Pump Request

**Status:** Accepted — partly implemented. #787 records every irrigation attempt from confirm-ON, when it is charged, to its close as `completed` or `aborted`, and derives Dispensed Volume from them in the per-growspace store of item 5, retention, row limit and fail-closed read included. Suppressed attempts, the write before the ON command, drain attempts, the trigger evidence beyond its kind, `not_delivered` windows, metered evidence and the restart handling of item 9 are not yet.

Nothing recorded one pump request from start to end (#549). [[Reliability Evidence]] counts requested, fired and completed cycles but keeps no individual cycle. The [[Safety Ledger]] keeps events, but only transitions, faults and not-delivered cycles, in one 500-row ring shared by every growspace. The [[In-flight Marker]] notes only that a pump is running. So "what happened to the 14:30 shot", and "why was I capped", had no answer, and a restart could not tell our own interrupted shot from a person at the pump.

Every request that reaches the [[Pump Cycle Gate]] now becomes one **[[Delivery Attempt]]**, and those attempts are the source of [[Dispensed Volume]].

1. **Scope.** Scheduled, steering, manual and drain requests all get an attempt, including the ones the gate or an operator hold refuses: a suppressed request is half the requested-vs-delivered story. A steering tick that withholds a shot never asks, so it makes no attempt; recording those would mean one row a minute.
2. **Lifecycle.** An attempt moves **Requested → Actuated → Closed**. It is actuated when the pump confirms ON. It closes with an outcome of `suppressed` (with the reason), `not_delivered` (an [[Unconfirmed Pump Cycle]]), `completed`, `aborted` (with the cause) or `interrupted`, and a separate flag for whether OFF was read back. Its delivered-volume evidence is `estimated` (measured ON time × flow rate) or `metered`, and only a metered attempt can be **short** or **over**. "Verified" is not a state, because `completed_verified` in Reliability Evidence already means OFF was read back, and those documented counter keys stay as they are.
3. **Actuator confirmation** is what already ships, unchanged: the event-driven ON wait (10 s), the [[Pump Readback]] of OFF (1 s to 6 s), and their fault latches, all through ADR-0022's driver. The attempt records the four moments (ON commanded, ON read, OFF commanded, OFF read). It adds no gate and changes no timing, so actuator confirmation is a complete answer for the majority who will never fit a flow meter.
4. **When it is written to disk.** The attempt is written through **before the ON command**, once the gate has passed. It is written through again **at confirm-ON**, which charges it against Dispensed Volume (ADR-0054). Its close, and every suppressed attempt, go through a batched save like Reliability Evidence. The first write exists so that a crash between command and confirmation still leaves an open attempt behind. A lost close costs nothing: the next start finds the attempt open and closes it as `interrupted`.
5. **Storage and retention.** Each growspace gets its own store, `growspace_manager.deliveries_<entry>_<growspace>`, so a write rewrites one growspace's week and not everyone's.
   - Raw attempts are kept for **7 days**.
   - Consecutive suppressions with the same reason are **merged into one row**, with a count and first/last times.
   - A hard limit of 2,000 rows evicts the oldest rows _not dated today_. Today's charged rows are never evicted, because the cap is derived from them.
   - An unreadable store **holds that growspace's cycles**, reported the way `fault_record_unreadable` is.
   - Anything older than 7 days survives as the daily water sums, the Reliability Evidence counts, and whatever Grow Runs later project.
6. **What an attempt records.**
   - **Identity:** a stable `attempt_id`, `growspace_id` and `output`. A zone identity is added by #548.
   - **Trigger and its evidence:** for `schedule`, the slot; for `steering`, the phase, the triggering VWC reading, base seconds and the VWC and EC factors; for `manual`, the HA `user_id`; for `drain`, the slot.
   - **Plan:** planned seconds, and the flow rate that turned them into planned litres, snapshotted so a later config edit cannot rewrite history.
   - **Timestamps:** `requested_at`, `on_commanded_at`, `on_confirmed_at`, `off_commanded_at` and `off_confirmed_at`.
   - **Outcome:** the state, the suppression reason or abort cause, and whether OFF was read back.
   - **Volumes:** `charged_l`, `estimated_l`, the evidence kind, and for `not_delivered` the window in which water may have moved.
   - **Deliberately left out:** sensor series, config snapshots beyond that flow rate, notification text, user names, and the OFF-retry chatter (the Safety Ledger's). The stable id is what makes a future Grow Run projection idempotent (ADR-0038).
7. **An Unconfirmed Pump Cycle** charges nothing. Its attempt records the window from the ON command to OFF read back, at most about 16 s, for anyone reconciling a tank drop. Two of them at most can precede the fault that the third latches, which is well inside what a runaway backstop is for.
8. **Metered evidence.**
   - **What it adds:** `metered_l`, together with what produced it: the meter entity, `cumulative_total` or `rate`, and the configured unit. Research found no unit or accumulation convention across controllers (#545).
   - **Short and over** are judged against `estimated_l`, never the plan, because an aborted shot is not short. The tolerance belongs to the map's flow-meter configuration item, and so does whether `metered_l` replaces the runtime estimate in [[Aggregate Water Use]].
   - **Effect on the cap:** a meter can only **raise** the charge, to `max(charged_l, metered_l)`, and like ADR-0054's tank disagreement it is evidence and never a gate.
9. **Restart.** An attempt still open at start is closed as `interrupted` and keeps its confirm-ON charge.
   - **Its pump reads ON:** the pump is **ours, not a person's**. It is switched off and read back, with the existing fault on failure, whatever `unexpected_on_policy` says.
   - **Its pump reads OFF:** the attempt closes with an end time bounded by the last evidence.
   - **A pump reading ON with no open attempt** is an [[Unexpected On]], exactly as before.
   - Nothing is replayed. The In-flight Marker keeps its counter; the question it could not answer, whose run this is, now belongs to the attempt.

## Considered Options

- **Put attempts in the Safety Ledger.** It already writes through and fails closed, but its 500 rows are shared by every growspace, so shot rows would push faults and acknowledgements out.
- **Put attempts in `IrrigationSafetyStore` under a key of their own.** That store is fail-closed and written through already, but it is one JSON file, and every shot would rewrite every growspace's week.
- **Use Home Assistant's Recorder.** It purges, commits in batches, and cannot hold cycles when unreadable, so it cannot be the cap's source.
- **Keep ADR-0054's `{date, cycles, liters}` record beside the attempts.** Two stores written at the same moment about the same shot would eventually disagree, and the one that enforces would be the one nobody can audit.
- **Record steering withholds.** One row a minute, about decisions not to ask.

## Consequences

- ADR-0054's storage (item 4) is replaced; its rule stands. Dispensed Volume is today's charges summed over the growspace's attempts.
- A crash mid-shot under the default `alert` policy no longer leaves our own pump running as a person's: it is switched off at start. Until this lands, that is present-day behaviour, because `_in_flight` lives only in memory (#854).
- `irrigation_flow_sensors` stays what it is, a field whose only effect is to switch Tank-Derived Water Mode off (#853). What the metered stage is configured by is the map's flow-meter item.
