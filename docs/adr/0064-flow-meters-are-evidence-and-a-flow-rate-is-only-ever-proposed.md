# Flow Meters Are Evidence, and a Flow Rate Is Only Ever Proposed

**Status:** Accepted — not yet implemented

Earlier decisions already fixed how a flow meter's reading is used. They did not say how a grower configures a meter, or how its readings become trust in a zone's numbers (#861).

- **Per attempt (ADR-0055).** A [[Delivery Attempt]] carries `metered_l`, the meter entity, `cumulative_total` or `rate`, and the unit. Short and over are judged against `estimated_l`. A meter can only raise the cap charge, and it is never a gate.
- **Placement (ADR-0058).** A meter sits on the [[Irrigation Supply]] or on an [[Irrigation Zone]]. A supply meter is attributed to the one open attempt. Readings outside any attempt are unattributed.
- **Disagreement (ADR-0054, item 5).** A material disagreement between the tank drop and the pump volume is a calibration signal and is never enforced. Its threshold, wording and placement were left open.
- **Research (#545).** There is no unit or accumulation convention. OpenSprinkler totalises per run, Galcon reports m³/h and TrolMaster reports both. Two of five controllers have no flow input at all, and Athena's methodology never mentions a meter.
- **The field that exists (#853).** `irrigation_flow_sensors` is a flat growspace-level `list[str]` that no code reads. It used to switch [[Tank-Derived Water Mode]] off, and since #853 it does nothing at all (ADR-0017, amended).

Most growers will never fit a meter. So actuator confirmation stays the complete baseline, and every decision below has to leave a meter-less growspace exactly as honest as it is today.

1. **Configuration: `flow_meters` replaces `irrigation_flow_sensors`.**
   - Each entry is `{entity_id, placement}`, and `placement` is `supply` or a zone id.
   - The old field is **retired on load and never promoted**. Nothing ever checked that its entries were meters, and one could be a gal/min rate that would triple every cap charge. Any entries it held are logged once, and the implementing PR's `CHANGELOG.md` line says they must be added again as flow meters. This finishes #853 by deleting the field instead of reinterpreting it.
   - **Kind and unit come from Home Assistant's own metadata, with no override.**
     - `device_class` `water` or `volume` with `state_class` `total` or `total_increasing` is **cumulative**. `volume_flow_rate` is **rate**.
     - The unit is the entity's `unit_of_measurement`, converted by HA's volume and volume-flow-rate converters.
     - An entity that cannot be classified is refused when it is configured, with a message naming the fix: a `template` or `utility_meter` sensor, or `customize`.
     - Raw pulse counters and K-factors are out of scope. Turning pulses into litres is the job of ESPHome's `pulse_meter` and similar integrations.
2. **Cardinality: at most one meter per placement.**
   - A growspace has at most one supply meter and at most one meter per zone, and the two may coexist. The ADR-0060 envelope needs no new limit, because this caps meters at 1 + 6.
   - When both see an attempt, the **zone meter** gives it its `metered_l`, because it sits nearer the emitters.
   - The supply meter's reading is recorded on the same attempt as `supply_metered_l`. A gap between the two points at the plumbing between them. It is shown, never alerted on, like [[Unattributed Flow]] (item 10).
3. **The [[Metering Window]], and how litres are computed.**
   - **Window.** It runs from supply ON confirmed to OFF read back, plus a tail of up to **60 s**. The tail catches line drain-down and meters that report late, such as OpenSprinkler's end-of-run total. The next attempt's ON command cuts it short.
   - **Cumulative.** Sum the deltas between consecutive readings, starting from the last reading before the window. A decrease is a reset, with HA's `total_increasing` semantics: the new value counts from zero.
   - **Rate.** Integrate each reading as held until the next one, in litres per second after conversion.
   - **No usable reading.** If any of the following holds, `metered_l` is **absent, never guessed**:
     - a cumulative meter has no reading stamped after OFF was read back within the tail;
     - a rate meter has no update inside the window;
     - `unavailable` or `unknown` appears anywhere in the window.

     The attempt then records `meter_stale` or `meter_unavailable` and stays `estimated`. A silent meter raises no alert of its own; its zone drifts back to Unverified (item 6).

4. **Short and over.**
   - The tolerance is fixed at **±15%** of `estimated_l`, with an absolute floor of **0.1 L** so tiny shots and line-fill transients are never flagged. It is not configurable and not learned.
   - 15% sits just above the 10% emitter-variation threshold in #545, and just above the ±10% of a cheap hall-effect meter.
   - Short and over answer only whether an attempt departed from its own estimate. A learned tolerance would absorb a wrong configured flow rate until the evidence vanished. A **systematic** departure is a calibration question, and item 6 answers it.
5. **The cap.** A meter raises the charge to `max(charged_l, metered_l)` in every confidence stage, with no bound, exactly as ADR-0055 says.
   - Gating the raise on Verified would make it pointless: Verified means the meter agrees with the estimate, so the raise only matters when they disagree.
   - A bound such as 2 × `charged_l` would blunt a mis-declared unit, but it would also blunt the protection against a flow rate set too low, which is what the raise exists for.
   - A mis-scaled meter makes its zone Disputed within a handful of shots, and the unit guard in item 7 names it. The cap is a runaway backstop that errs toward having counted water (ADR-0054).
6. **[[Calibration Confidence]]: per zone, derived, meter-only.** It says how far a zone's estimated volumes can be believed. It belongs to the zone because the flow rate does (ADR-0057). A supply meter can still judge each zone, because only one is ever open (ADR-0058).
   - **Evidence** is the ratio `metered_l / estimated_l` over the zone's **last 10 metered attempts** that meet all of these:
     - they are in the 7-day store;
     - they were `completed` or `aborted`;
     - they are above the 0.1 L floor;
     - they came after the last reset.
   - **Verified:** at least 5 such attempts, with a median ratio within ±15%.
   - **Disputed:** at least 5, with the median outside ±15%. This opens a meter-sourced [[Calibration Proposal]].
   - **Unverified:** anything else. This is the actuator-confirmed baseline, and every zone without a meter stays here.
   - The median means one bad reading cannot flip the stage.
   - **Nothing is stored.** The stage is computed from the Delivery Attempt store, so it decays when metered evidence stops arriving and the attempts age out.
   - A **reset** happens when the zone's flow rate, valves or meter changes. Only attempts after it count.
   - **The tank never moves a zone's stage.** It can attribute to a zone only when there is one zone, and it also counts leaks, draws and evaporation. Its evidence goes into item 9 instead.
7. **A Calibration Proposal is never applied automatically.** A corrected `pump_flow_rate_ml_per_sec` changes how many seconds every volume-sized shot runs and what the cap charges at confirm-ON, so changing it is the grower's decision.
   - **Form.** It is one fixable Repairs issue per zone. It shows the configured rate, the proposed rate, the evidence count and the median ratio. **Apply** writes the rate through [[Irrigation Change]] (ADR-0046), which resets the zone's confidence (item 6) and closes the issue. This is a fix, not an announcement, so ADR-0063's rule against announcement-only Repairs holds.
   - **Meter-sourced.** It opens when the zone is Disputed, and proposes the configured rate × the median ratio.
   - **Tank-sourced.** It opens only when the growspace has **one zone and that zone has no meter**. It then opens when a [[Tank–Pump Disagreement]] is raised, and proposes the configured rate × the median, over the disagreeing days, of the tank drop ÷ the pump figure. Its text names a leak and a draw from the tank as the other explanations, and the grower's confirmation is the check against mistaking a leak for a slow pump. With two or more zones the tank cannot be attributed, and a zone with a meter outranks it, so in both cases it proposes nothing. Most growers have a tank and no meter, so this is the only calibration evidence most of them will ever get.
   - **Ignore** is honoured until the zone leaves Disputed, or the disagreement clears. The issue is then deleted, so Home Assistant forgets the dismissal, and it is filed afresh on re-entry.
   - **Unit guard.** A median ratio within 5% of a common unit mix-up offers **no Apply**. The mix-ups are 3.785 and 0.264 (gallons and litres) and 1000 and 0.001 (litres against m³ or mL). The issue says instead that the meter's declared unit looks wrong, and names the entity. That turns item 5's risk into the right fix, not a wrong rate.
8. **[[Aggregate Water Use]] gains a fourth source, `metered`.**
   - **Per attempt**, `metered_l` replaces `estimated_l` whenever it is present, in any stage. The meter is the direct instrument, and a Disputed stage usually indicts the configured rate, not the meter. It is written through to `WaterUsageData` with `source: "metered"`, wherever the pump estimate is written today, and in a fully metered growspace also in tank mode. An attempt with no reading is still written as `pump_estimate`.
   - **Precedence** is **fully metered > tank > pump estimate**. A growspace is **fully metered** when it has a supply meter or a meter on every zone. It then takes its measurement source from its attempts, metered where it can be and estimated where it cannot, even when a tank qualifies.
   - Tank-Derived Water Mode stays active for the tank's own sensor, its chart and item 9. This is a precedence rule within ADR-0017, not the gate #853 removed, and it is decided by configuration, as tank mode is.
   - A tank reads a coarse level after the fact and counts leaks and draws, while a meter at the supply or zone measures the water on its way to the plants. Aggregate Water Use answers what the plants got.
   - **Switching** into or out of fully metered works like the #853 amendment's one-time switch. Today's figure settles at midnight, and the cycle's at the next `reset_water_tracking`.
9. **The Tank–Pump Disagreement** is the signal that ADR-0054's item 5 asked for.
   - **Per local day.** It is evaluated after midnight for the day just ended.
   - **The comparison.** On one side is the tank drop, summed over the qualifying tanks, minus any [[Hand Watering]] marked `from_monitored_tank`. On the other is the pump figure: today's attempts summed, metered where they can be and estimated where they cannot (item 8).
   - **Threshold.** A day **disagrees** when the gap is more than **25%** of the larger figure **and** more than **1 L**. The signal is **raised after 2 consecutive disagreeing days** and clears after 2 agreeing ones. The threshold is looser than the attempt tolerance, and persistence is required, because tank level resolution is the weakest input here.
   - **Days skipped.** A day counts neither way when it has no actuated attempt, or when a tank reading was unknown for any part of it (ADR-0050).
   - **Wording**, for example: _"The tank dropped 12.4 L yesterday; the pump delivered 8.1 L (35% less). A flow rate set too low, a leak, or water drawn from the tank can cause this."_
   - **Where it appears.** It is in a `calibration` block of the growspace view model, and there is a logbook line when it is raised and when it clears. It is a Repairs issue only when it is a tank-sourced Calibration Proposal (item 7). It gets no new entity: one can follow when a grower asks to automate on it.
10. **[[Unattributed Flow]].** A supply or zone meter may read flow outside every Metering Window of its own. That can be a leak, a siphon, mains pressure behind a master valve, or a person at the pump. Supply ON with no attempt is already caught as an [[Unexpected On]], and what remains has no known cause or destination.
    - It is recorded as a daily per-meter `unattributed_l` in the growspace's delivery store, for 7 days like the attempts.
    - It is never in [[Dispensed Volume]] or Aggregate Water Use.
    - It is shown in the same `calibration` block, and never alerted on or gated.
11. **Drain volume is out of scope.** `drain_volume_sensors` is just as unread, and it stays as it is. Runoff volume answers a steering question, runoff percentage for [[Runoff Reconciliation]], not an accounting one. A drain's Delivery Attempt measures the drain pump, not the runoff.
12. **Release.** `placement: <zone id>` needs ADR-0057's zones, and ADR-0063 keeps 1.4.0 as the zone release alone. Everything that reads a meter therefore ships **after 1.4.0, as its own minor release**. Replacing `irrigation_flow_sensors` with `flow_meters` is an additive minor store-version step within the v2 store.
    - The Tank–Pump Disagreement and the tank-sourced proposal need no meter and no zone, only Delivery Attempts with measured ON time. They are not held back for the metering release.
    - They also do not widen ADR-0063's scope for 1.3.0.
13. **Surfaces.** The growspace view model gains a `calibration` block with:
    - each zone's stage and evidence count;
    - the Tank–Pump Disagreement's state and its last days;
    - each meter's Unattributed Flow.

    #864 decides how the card shows them ([ADR-0066](0066-the-card-draws-zones-on-the-grid-and-explains-them-in-sentences.md)). Where there is a fix to apply, the Calibration Proposal is the fix.

## Considered Options

- **Reinterpret `irrigation_flow_sensors` as a list of supply meters.** Every stored entry would start raising cap charges. None of them was ever checked, and nothing records what their units are.
- **A grower-declared unit and kind, with an override.** Home Assistant already declares both, and a second declaration can disagree with the first. A badly declared entity is fixed where every other consumer of it would also benefit.
- **Several meters per zone, or one meter per growspace.** Several needs a reduction rule nobody has asked for. One loses the zone meter's precision on a multi-zone supply.
- **A learned or configured short/over tolerance.** A learned one absorbs the very bias it should expose. A configured one is a knob that growers would loosen until the warnings stopped.
- **Confidence per supply or per attempt only.** The flow rate belongs to the zone, so a supply-level stage hides which zone is wrong, and per-attempt evidence already exists without a rollup.
- **Let the tank move zone confidence.** It cannot attribute to a zone once there are two, and it counts water that never went through the pump.
- **Apply a corrected flow rate automatically.** It changes how much water every later shot delivers without anyone choosing that, and a meter declared in the wrong unit would rescale a zone's watering by a factor of four.
- **Bound the meter's cap raise, or raise only once Verified.** Both disable the protection against a flow rate set too low, which is what the raise is for.
- **Keep the tank ahead of the meter in Aggregate Water Use.** A coarse level read after the fact, counting leaks and draws, would outrank the instrument that measures the delivery itself.
- **Decide metered coverage per day.** The figure would change source from day to day, depending on whether a meter happened to report.
- **Alert on Unattributed Flow, or count it as water use.** Its cause and destination are unknown, so an alert would be a guess and so would the figure.
- **Ship metering in 1.4.0, or supply meters in 1.3.0.** The first breaks ADR-0063's rule that zones ship alone. The second defines placement before zones exist and then has to redefine it.

## Consequences

- `EnvironmentConfig.irrigation_flow_sensors` is removed. `flow_meters` appears, and the store takes a minor-version step. The card's sensor picker for the old field goes with it (#864).
- The Delivery Attempt gains `supply_metered_l` and the absence reasons `meter_stale` and `meter_unavailable`, beside ADR-0055's metered fields.
- `WaterUsageData.daily_readings` gains the `metered` source tag. ADR-0017's rule becomes `manual + (metered if fully metered, else tank-derived if tank mode, else pump estimate)`.
- A meter-less growspace changes only by gaining the Tank–Pump Disagreement and, with one zone, a tank-sourced proposal it can ignore. Every zone without a meter reports Unverified, which is what it has always been.
- The delivery store gains a daily Unattributed Flow record per meter.
- Confidence, the disagreement and the unit guard are pure functions over attempts, tank readings and configuration, in `domain/`. They read no sensors and touch no `hass`.
