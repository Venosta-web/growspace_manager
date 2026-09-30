# A Degraded Zone Holds, or Replays Its Last Clean Day If Asked

**Status:** Accepted — implemented

ADR-0059 defined [[Degraded Control]]: a zone with no trustworthy [[Control Measurement]] and no Witness Probe able to substitute. Its VWC-triggered shots, Adaptive Shot Control and substrate event recording stop. It is reported through ADR-0051's pipeline, withheld at once and alerted after `sensor_alert_delay_minutes`. What the zone does instead was left to the map's fallback item (#860), and until then the answer was hold.

A hold is safe against the failure ADR-0051 was written for, a dead probe that keeps asking for water. It is not safe against the opposite one. In coco or rockwool a probe that fails at 09:00 leaves the zone without water for the rest of the lit period, which can dry plants past recovery before anyone reads the alert.

Two facts shape the answer.

- **Steering is demand-driven, so a recipe says nothing about a day's water.** P1 fires at its interval until the target VWC is reached. P2 fires only when VWC falls below the dryback trigger, and its interval is a cooldown, not a rate. Firing P2 every interval would overwater badly, and without a probe nothing tells P1 when to stop.
- **The zone's recent demand is already recorded.** Delivery Attempts (ADR-0055) keep every confirmed steering shot for 7 days, with its time, its planned seconds and its zone.

1. **Hold, then replay, and only if asked.** Degraded Control still withholds at once, as under ADR-0051. A zone whose `degraded_fallback` is `replay` starts a **[[Replay Fallback]]** when the alert fires, `sensor_alert_delay_minutes` after the zone degraded. The grace is the alert delay itself, so a short dropout never waters blind, and the fallback starts at the moment the grower is told.
   - `degraded_fallback` is a per-zone setting, `hold` or `replay`, and defaults to `hold`. Every earlier case of actuating from missing data has been opt-in: auto-advance, `moisture_zero_is_implausible`, and ADR-0045's rule that the program holds when it has no unambiguous instruction.
   - The Degraded Control alert on a `hold` zone names the day it could replay and the setting that turns replay on. That alert arrives exactly when a grower needs to hear it.
   - **A single-probe zone gets the same answer.** With no witness, every probe failure is Degraded Control (ADR-0059), so these zones will meet the fallback most often. How many probes a zone has does not change whether actuating without data is acceptable, and a Repairs suggestion on a healthy zone would be nagging about a setup that works.
2. **A [[Reference Day]]** is the most recent past local day on which all of the following held:
   - steering was enabled on the zone;
   - its own Control Probe gave a valid measurement across the whole lit window, with no Degraded Control, no substitution, and no unwatched stretch (a restart, for example) longer than `sensor_alert_delay_minutes`;
   - at least one steering shot was confirmed;
   - no shot of the day was a replay.

   A day qualifies when its lit window closes, and is recorded on the zone's `SubstrateHistory` as `reference_days`, beside ADR-0049's `last_confirmed_shot_at`. It is written through the same debounced save and keeps the last 7 days. The replay uses the most recent listed day **whose day length matches today's**, since the switch from 18 h to 12 h changes demand entirely and a veg day must never be replayed in flower. Its shots are the zone's Delivery Attempts from that day with `trigger=steering`. ADR-0058's one-open-zone rule makes each one's zone unambiguous.

3. **What a replay fires.** Each Reference Day shot keeps its offset from lights-on and is mapped onto today's lights-on.
   - **Smaller, not fewer:** each shot runs at a fixed **80%** of its recorded `planned_s`, capped at `max_cycle_seconds`. Keeping the times keeps the zone's rhythm. Indoor demand barely changes from one day to the next, and 80% guards against it having fallen since. A replay is conservative once the plants have grown, which is the safer direction. There is no setting for the percentage, because nobody would tune it.
   - **No correction** for live plant count or flow rate. The recorded seconds are what the zone's own plumbing delivered.
   - **Nothing is caught up.** Only shots whose offset is still ahead of the fallback's start are replayed, so shots missed during the grace are lost, as ADR-0049 refuses to replay a withheld shot. A probe that fails before lights-on costs the zone nothing.
4. **Bounds.** A replay shot is a [[Supply Claim]] in the [[Supply Queue]], decided afresh at the front (ADR-0061), and passes every gate a steering shot passes:
   - **Pump Cycle Gate:** the daily caps, the tanks, faults, overrides, the [[Startup Inhibit]], and the dark gate when `skip_during_dark` is on.
   - **Cooldown:** held until the shorter of the P1 and P2 intervals has passed since the last confirmed ON, so a Manual Run just before it still counts.
   - **Never in P3.** A replay shot fires only between lights-on + P0 and `p2_stop`, whether or not the dark gate is on. A Reference Day has no shots outside that window, and the rule is stated anyway.
   - **Zero live plants** leaves the zone idle, as it does steering.
   - **The Infiltration Gate is skipped,** because it needs a measurement.
5. **Recording.** A replay shot is a Delivery Attempt with a new trigger, **`fallback`**, and charges [[Dispensed Volume]] like any other cycle.
   - It never trains [[Adaptive Shot Control]] and never counts toward `probe_unresponsive`, which counts steering shots only.
   - It writes no substrate event. The gap stays a gap, as ADR-0059 requires.
   - A day containing one is never a Reference Day, so a replay can never become the basis of the next one.
6. **Reporting.** While replaying, the zone reports **`fallback`** instead of `inhibited`, keeping its Degraded Control cause (`sensor_stale`, `sensor_implausible`, `sensor_unavailable` or `probe_unresponsive`) and the Reference Day's date.
   - **Start:** the ADR-0051 alert itself says a replay is running, for example "Zone 2: probe stale since 09:00 — replaying 24 Sep's shots at 80% until it recovers."
   - **End:** the Reference Day ages out after at most about six days, with the Delivery Attempts that hold its shots. The zone then holds, and gets one more push saying so. Otherwise the fallback ends with ADR-0051's recovery message.
   - **No daily reminder.**
7. **Resuming.** Steering resumes on the first trustworthy Control Measurement, with no Startup Inhibit.
   - A witness that becomes able to substitute (ADR-0059) takes priority over the replay at once, because it steers on a measurement.
   - Replay shots move `last_confirmed_shot_at`, so the cooldown and the Infiltration Gate's stall backstop carry across the handover, and the Steering Phase Machine decides P1 or P2 from the reading it now sees.
   - A probe that flaps passes the grace again on each new episode, so it cannot switch a zone rapidly between replay and steering.
8. **Unresponsive probes get the same replay.** Three flat steering shots mean either that the probe is out of the pot or that the water is not reaching the pot. The readings cannot tell these apart. If the probe is out, a replay saves the plant where a hold lets it dry. If the emitter is out, a replay puts water on the floor, bounded by the daily cap and visible, where a hold changes nothing for the plant. The alert for `probe_unresponsive` names both causes, so the grower checks the emitter as well as the probe.
9. **Seam.** Choosing the Reference Day and laying out today's replay are pure functions beside `domain/control_measurement.py`: the zone's `reference_days`, the Reference Day's attempts, today's phase boundaries and the fallback's start in, the planned replay shots out. The Steering Phase Machine keeps the steering decision and the [[Irrigation Controller]] the effects.

## Considered Options

- **Keep holding.** Safe against a probe that asks for water, and a slow drought against one that stops. The grower can do a Manual Run, but only once they see the alert.
- **Fall back at once.** Waters blind on every short Zigbee dropout, the case ADR-0051's alert delay exists to keep quiet.
- **A fallback built from the recipe's P1 and P2 intervals.** P2's interval is a cooldown, not a rate, and P1 has no end without a probe.
- **A fallback schedule the grower writes for each zone.** One more setting to fill in and keep current as the plants grow. A forgotten schedule from veg is worse than a hold.
- **Replay at full size, or as fewer shots with the same total.** Full size assumes demand has not fallen. Fewer, larger shots change the rhythm the zone was steering to and channel more in coco.
- **Correct the replay for plant count.** Delivery Attempts do not record the live count behind a shot, and a zone that lost plants mid-run is rare enough for 80% to cover.
- **Replay by default, or by default for coco and rockwool.** Actuating from missing data would then happen without anyone choosing it, and #863 would have a silent behaviour change to explain to every existing user.
- **Default single-probe zones to `replay`, or file a Repairs suggestion for them.** The probe count is not what makes blind watering acceptable, and the `hold` alert already carries the suggestion at the right moment.
- **Hold on `probe_unresponsive`.** Right when the emitter is out, and a drought when the probe is, which is the failure the unresponsive check was added to catch.
- **Resume behind a Startup Inhibit.** The cooldown and the Infiltration Gate already carry across the handover, and the grace on re-entry already stops a flapping probe.
- **Catch up the shots missed during the grace.** Replays what was withheld, which ADR-0049 refuses.

## Consequences

- Nothing changes for a zone left on `hold`, which is every zone after upgrade, except that its Degraded Control alert names the day it could replay. What #863 tells existing users is only that the setting exists.
- `SubstrateHistory` gains `reference_days`. The Delivery Attempt trigger gains `fallback`. The zone's reported state gains `fallback`, with its cause and Reference Day.
- A zone set to `replay` with no Reference Day holds, and its alert says there is nothing to replay. That is a new zone, one whose day length just changed, or one degraded for more than about six days.
- #864 (the card, [ADR-0066](0066-zones-are-a-scope-over-the-irrigation-dialog-and-a-zones-day-is-a-timeline.md)) can show a zone as replaying, which day it replays, and its replay shots, from the state and the attempts. It needs no further backend state.
