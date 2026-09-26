# A Manual Run Is a Pump Cycle; Hand Watering Is a Report

**Status:** Accepted — not yet implemented

"Manual delivery" named two unrelated things (#550). `run_irrigation_cycle` runs the pump because a person asked: it passes the [[Pump Cycle Gate]] and counts toward the daily limits. `water_plant` and `water_growspace` actuate nothing at all. They record litres a person says they gave: they set `last_watered`, write a `manual` entry into `WaterUsageData`, deduct nutrient inventory and emit a watering event. That second path looked like an ungated hole, but it has nothing to gate.

They stay two concepts, and neither is called "manual delivery":

1. **[[Manual Run]]** is Growspace Manager running the pump on a person's request.
   - It passes every gate except the dark check and the [[Startup Inhibit]].
   - It is a [[Delivery Attempt]] with a `manual` trigger (ADR-0055) and charges [[Dispensed Volume]] (ADR-0054).
   - **It never trains [[Adaptive Shot Control]].** The composer measures whether _its own_ sizing overshot, and a Manual Run's size was chosen by a person. A grower who only runs by hand keeps the factors at 1.0, the documented neutral, rather than being trained on volumes the composer never chose. There is no opt-in. This reverses the standing wart in the ADR-0014 amendment.
   - A Manual Run still abandons any observation pending when it starts.
2. **[[Hand Watering]]** is a person's report of water they gave themselves.
   - It is **never gated and never actuates an output**, and any future "water now" control has to be a Manual Run.
   - It never charges Dispensed Volume or a cycle, and it is not a Delivery Attempt.
   - Each report gains a stable `watering_id`, for ADR-0038's idempotent projection, and the reporting HA `user_id`. It keeps its current storage: the plants, the `manual` source in `WaterUsageData`, and the watering event.
3. **When it happened.** An optional `watered_at` may put a Hand Watering up to **7 days** in the past, matching Delivery Attempt retention, but never in the future. The entry is dated to that local day in the water figures. Anything older is Grow Run backdating (ADR-0036). A Hand Watering reported _now_ abandons any pending observation; a late one describes the past and does not.
4. **Attribution is by plant.** `water_growspace` already splits its amount across the growspace's plants. Once zones exist (#548), a "watered the tent" report reaches each zone in proportion to its plants, with no zone rule of its own.
5. **The monitored tank.** An optional `from_monitored_tank` flag, defaulting to off, marks water drawn from a tank that [[Tank-Derived Water Mode]] already measures. In that mode such an entry is recorded but left out of [[Aggregate Water Use]]. This narrows ADR-0017's accepted double-count to the grower who does not say where the water came from; the separate-container case keeps ADR-0017's behaviour.

## Considered Options

- **Converge on one concept** by routing Hand Watering through the gate or the pump through the watering service. Gating a report refuses a fact about the past, and recording a pump run as a report loses the actuation evidence ADR-0055 exists for.
- **Keep training on Manual Runs** (the ADR-0014 status quo). It trains on volumes the composer did not choose.
- **Exclude them by default with an opt-in.** It adds a knob whose effect nobody can reason about.
- **Let Hand Watering consume the cap.** Dropped in ADR-0054: a jug moves no pump water, and the cap limits the controller.

## Consequences

- The Manual Run exclusion lands in `observe()`, which on `prerelease` still runs from the 15 s settling report after every irrigation cycle: #534's Settled Observation was decided in docs but not built (#855).
- The `water_plant` and `water_growspace` schemas gain `watered_at` and `from_monitored_tank`. The card and the contract fixture follow, backend first.
