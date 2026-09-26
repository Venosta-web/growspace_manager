# An Irrigation Zone Owns Its Cells, and Every Growspace Starts With One

**Status:** Accepted — not yet implemented

Irrigation was one loop per growspace. The pump, schedule, flow rate, steering strategy, phase, substrate history and the single `soil_moisture_sensor` all sat on the growspace (#548). Growers who run several cultivars on one pump need several independently steered cohorts. The research (#545) found that the reference hardware is one shared pump opening N solenoid valves one at a time, and that a zone is not a valve: the one observed install ran 54 valves as 8 zones. Subareas were built in the meantime, but they are climate-sensor groupings with no plants and no actuation, so they are not this.

An **[[Irrigation Zone]]** is one steered cohort within a growspace: the plants watered together and controlled as one loop.

1. **Physically.** The pump stays with the growspace as the shared supply; whether a pump owns a group of zones is #552's question. A zone owns the valve outputs that open to water it, and how many is also #552's. The implicit zone has no valve, because the pump waters it directly, which is today. With two or more zones, **every zone must own a valve**, or running the pump for one zone would water a valve-less zone too.
2. **Membership is by cell.** A zone owns a set of grid `(row, col)` cells, and a plant belongs to the zone that owns its cell. Drippers sit at positions, not on plants, so a plant moved to another cell is watered by that cell's valve whatever the model says. The zone's live plant count, which shot sizing multiplies by, follows automatically.
   - Every cell belongs to exactly one zone.
   - Resizing the grid gives new cells to the zone that owns the adjacent row or column.
   - Zone edits sit under the layout's revision guard (ADR-0032).
3. **Storage and identity.** Zones are stored as `Growspace.irrigation_zones: list[IrrigationZone]`, the Subarea pattern, and a zone never outlives or leaves its growspace. Ids are unique within the growspace: short random ids for new zones, and the fixed id `default` for the implicit zone. That fixed id is what makes the migration idempotent and lets **today's per-growspace irrigation entities keep their unique_ids** as that zone's entities.
4. **What the zone owns:**
   - its cells, plants and live count, and its valve outputs;
   - its substrate probes (moisture, pore EC, bulk EC and substrate temperature), the container #547 combines;
   - the flow rate through its emitters, because one pump delivers a different rate into a different emitter count;
   - `irrigation_times`, `irrigation_duration`, `soil_trigger_percent` and `min_interval_minutes`;
   - all of `IrrigationStrategy` except the light fields;
   - `active_steering_phase` / `phase_changed_at`, and its own `SubstrateHistory`.

   **What the growspace keeps:**
   - the pump and the drain pump; the drain schedule, `DrainConfig`, and the runoff-EC and drain-volume sensors;
   - the tanks, feed-EC sensors, `ec_target_ranges` and the EC ramp (ADR-0046), because feed comes from the shared tank;
   - `lights_on_time`, light tracking and day hours, so the steering _day_ stays one per growspace because the lights are;
   - `max_cycle_seconds`, the grace and stale windows, `unexpected_on_policy`, `skip_during_dark`, `pause_on_low_tank` and `log_to_logbook`;
   - `water_usage`.

5. **The implicit zone.** It stays invisible while it is the only zone: a single-zone growspace shows no zone concept anywhere, and it cannot be deleted. Adding a second zone reveals it as a nameable zone ("Zone 1") the user can give cells away from. Removing zones down to one hands every cell back to the last one and hides zones again.
6. **Migration** happens at load and only one way. `Growspace.from_dict` moves the zone-owned fields into a `default` zone the first time it sees the old shape, following the existing legacy-key precedent, and deletes the growspace-level copies so each fact has one source. It is idempotent. A downgrade finds no schedule or strategy and stops automatic irrigation, which fails toward no water, never runaway water. That is the price of refusing a dual-write that would keep two sources forever, and the release notes say so.
7. **Legacy calls.**
   - **Writes and actions** that are zone-scoped (`run_irrigation_cycle`, strategy, settings, schedule times, recipe, program, steering mode) gain an optional `zone_id`. With one zone, `growspace_id` alone resolves to it, so every existing automation keeps working. With two or more and no `zone_id`, the call is refused with a typed `zone_required` (ADR-0027); guessing would water the wrong plants.
   - **Reads** keep their legacy top-level fields, mirroring the `default` zone that today's entities belong to, and add a `zones` array.
   - **Hand Watering** and every growspace-owned setting keep their signatures.
8. **Runtime state.**
   - **Per zone:** the Steering Phase Machine, ShotComposer, SubstrateTracker, the Infiltration monitor and Settled Observation, and the schedule's due-time tracking. Each Delivery Attempt names its zone (ADR-0055).
   - **Per growspace:** the Irrigation Controller's state, Safety Ledger, automation and arm switches, emergency stop, Manual Override of `irrigation`, Reliability Evidence, Dispensed Volume and the **daily caps** (ADR-0054). The cap is the runaway backstop on the shared pump, and one zone using up the allowance stopping every zone is the safe direction.
   - **Out of scope:** how zones due at once share the pump belongs to the map's arbitration item.
9. **Faults and the Startup Inhibit.** Any latched fault on any output of a growspace **blocks the whole pump**. A valve that will not read closed waters its zone every time the pump runs for another one, so per-output fault scoping is only honest for independent pumps (#552). The Startup Inhibit (ADR-0049) keeps its growspace-wide grace time and tank readiness, but clears **per zone** once that zone's probes have reported, so one dead probe holds only its own zone and #547's degraded-control rules take it from there.

## Considered Options

- **Membership by plant id.** Moving a plant would keep its zone while a different valve waters it.
- **A zone is a valve.** Contradicted by the only observed install (#545), and it would force #552's answer.
- **Zones as a sibling store or config-entry scope.** It adds lifecycle and orphan handling for something that cannot exist without its growspace.
- **Reuse Subareas.** That would put air sensors and watering on one concept, which is the ambiguity this split removes.
- **Keep growspace-level copies for rollback.** Two sources of truth on every write, with no end date.
- **Per-zone caps.** Budgeting, not a runaway backstop; it belongs with arbitration.
- **Assume a zone's first reference in a legacy multi-zone call.** It silently waters the wrong plants.

## Consequences

- Zones beyond `default` get entities with new unique_ids scoped by zone. The card learns zones on its irrigation surfaces only, and its contract fixture follows the backend.
- `environment_config.soil_moisture_sensor` and the substrate probe lists leave `EnvironmentConfig`; anything else reading them (environment reporting, the EC trend) reads the zone.
- #551 (the scale envelope) and #552 (zone, delivery group and valve cardinality) are unblocked.
