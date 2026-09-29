# A Zone Steers on One Elected Probe, and Witnesses Guard It

**Status:** Accepted — not yet implemented

ADR-0051 made a single moisture probe trustworthy. Each reading is valid, unavailable, implausible or stale; the stale window is learned from the probe's own cadence; an invalid reading withholds shots at once and alerts later. It said nothing about several probes, because there was only ever `soil_moisture_sensor`. ADR-0057 now gives each [[Irrigation Zone]] a list of substrate probes, and #547 asked what single figure steering acts on and when the controller admits it does not know.

The research (#545) found a real disagreement rather than a practice to copy. Grodan averages in hardware. Athena elects a representative plant of average moisture. UF/IFAS elects the driest position. AROYA says nothing. METER, who make the sensors, add that every spot has its own baseline, so readings are compared over time at the same spot, not against each other.

1. **One elected [[Control Probe]].** The grower marks one probe per zone, at a plant of average moisture, as the steering figure. Every other moisture probe is a **Witness Probe**: health evidence, display, and a possible substitute, **never averaged in**.
   - **Why not a mean or median:** steering targets and dryback are absolute VWC points on one baseline. Two healthy probes can sit 6 points apart, so their mean describes no real pot, and it steps whenever a probe drops in or out. That phantom step can fire a shot or corrupt a dryback.
   - **Why not the driest:** electing the driest (UF/IFAS) serves one probe governing several valves, which ADR-0058 ruled out. It waters every pot until the driest reaches target, and one failing low probe decides for everyone.
2. **The [[Control Measurement]]** is ADR-0051's validated reading plus provenance: the value in % VWC (never converted), `observed_at` from `last_reported`, the cause and `invalid_since` when invalid, the validity window used, and the probe that produced it (entity, role and position label, and `substitute_for` when a witness stands in). Without one the zone is in [[Degraded Control]]; it is never 0.
3. **The probe container.** Its interface is a list of probes, each with `entity_id`, `role` (`control` or `witness`) and a position label: an optional grid cell `(row, col)` and an optional name. Exactly one probe is `control` whenever there is at least one. ADR-0057 made the container the zone, and migration turns `soil_moisture_sensor` into the `default` zone's Control Probe. Pore EC, bulk EC and substrate temperature probes join the same list with their quantity, and pore EC keeps ADR-0051's average of the valid probes, because EC only modulates.
4. **Unresponsive.** Besides ADR-0051's three causes, which judge a reading, a probe is **unresponsive** after **three consecutive confirmed steering shots** with no rise above the infiltration deadband. It recovers on one confirmed shot that does rise.
   - **What counts:** only steering shots, which fire because the substrate is below its trigger. Manual Runs and shots near saturation do not count, since a flat reading there is honest.
   - **What never counts:** disagreement between probes in absolute value, because different baselines are normal.

   This catches a probe pulled out of the substrate that keeps reporting a steady value. That failure passes every existing check, and `moisture_zero_is_implausible` catches it only by opt-in.

5. **Substitution.** When the Control Probe is invalid or unresponsive, a healthy witness with a **learned offset** stands in: the median of control minus witness over the last 24 h in which both were valid. A witness without that history cannot substitute. The measurement says `substitute_for`, and a notice says "steering on witness X". While substituting, Adaptive Shot Control and dryback recording pause. An approximated baseline is good enough to keep watering, but not to learn from or to report as a dryback. Substitution ends the moment the Control Probe is healthy again.
6. **[[Degraded Control]]** is a zone with no trustworthy Control Measurement.
   - **What stops:** VWC-triggered shots, `observe()` and substrate event recording. The gap is recorded as a gap, never interpolated.
   - **What continues:** Manual Runs and every gate.
   - **How it is reported:** as the zone's inhibit, with ADR-0051's cause codes plus `probe_unresponsive`, through ADR-0051's pipeline: withheld at once, alerted after `sensor_alert_delay_minutes`, and a recovery message.
   - **Out of scope:** what replaces the withheld shots, a hold or a conservative recipe, is the map's fallback item. Until it lands, the answer is hold.
7. **Witnesses and the lone probe.**
   - **A failing witness** holds nothing and pages no one. It shows as unhealthy on the card and in diagnostics, and it cannot substitute.
   - **Losing the last healthy witness** while the Control Probe is fine gets one low-tier notice, because the zone has lost its safety net.
   - **A single-probe zone** behaves exactly as under ADR-0051, plus the unresponsive check. With no witness nothing can substitute, so automatic exclusion is impossible by construction: a failure is always Degraded Control, never a silent switch.
8. **Home.** A new pure module, `domain/control_measurement.py`, takes a zone's probes and their readings and returns a Control Measurement or a degraded reason, with no `hass`, following the Pump Cycle Gate and Steering Phase Machine precedent. `sensor_validity.py` stays the per-reading validator. `SubstrateTracker` stays a chart recorder that automation never queries.

## Considered Options

- **Mean or median of valid probes** (Grodan). No single baseline; it steps whenever a probe's validity changes.
- **A trimmed or position-weighted mean.** The same baseline problem, with more knobs.
- **Driest position** (UF/IFAS). Built for one probe covering several valves. It waters everything to the driest pot's target and hands a failing low probe the whole zone.
- **Witnesses as evidence only, and degrade at once** (ADR-0051 unchanged). A three-probe grower would be exactly as fragile as a one-probe grower.
- **Substitute without offset correction.** It steps by the baseline difference at the moment of failover, which is the phantom step item 1 exists to avoid.
- **Exclude on absolute peer disagreement.** Different baselines are normal (METER), so this would exclude healthy probes.

## Consequences

- The steering loop, the Infiltration monitor, Settled Observation and dryback all read the Control Measurement instead of `soil_moisture_sensor`.
- Solo-probe growers gain one new hold, `probe_unresponsive`, which can withhold shots that fire today.
- The map's fallback item can now be phrased: what a zone in Degraded Control does instead of holding.
