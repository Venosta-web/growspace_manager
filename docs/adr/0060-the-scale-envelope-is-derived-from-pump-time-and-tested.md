# The Scale Envelope Is Derived From Pump Time, and Tested

**Status:** Accepted — not yet implemented

The PRD asserted 128 zones, 8 probes per zone and 32 active delivery groups as acceptance criteria, which charting ruled out as certifying a fiction (#544). "2–6 zones" survived only as inference: the research (#545) found **no source that states a zone count**, only hardware ceilings from 4 (Autogrow) to hundreds, and a floor of "one zone per cultivar". A stated envelope is a product promise, so #551 asked for numbers that a test backs.

The **[[Scale Envelope]]** is one set of numbers, with no profiles:

|                                          | Limit  | Where it comes from                                                                                                                                                                                 |
| ---------------------------------------- | ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [[Irrigation Zone]]s per growspace       | **6**  | Pump time (below), ADR-0055's store, and the top of the 2–6 inference                                                                                                                               |
| Probes per zone, each substrate quantity | **4**  | Three sources converge on about 3 per cohort (AROYA, Athena, peer-reviewed container work), plus the [[Control Probe]]. METER says scheduling needs _fewer_, so a fifth buys evidence, not control. |
| Valves per zone                          | **8**  | The only observed install ran 6–7 per zone (ADR-0058)                                                                                                                                               |
| Irrigated growspaces per instance        | **10** | A hobby grower's handful of tents, with a margin                                                                                                                                                    |
| Simultaneous deliveries per instance     | **10** | One per [[Irrigation Supply]] (ADR-0058), so bounded by growspaces                                                                                                                                  |

1. **Why 6.** The shared pump is the binding constraint, because zones on a supply run strictly in turn (ADR-0058). ADR-0058's confirmed ordering costs at most about **32 s** per shot: valve open ≤10 s, supply ON ≤10 s, OFF readback ≤6 s, valves-closed readback ≤6 s. With steering's default 15-minute interval, N zones fit only while N × (shot + 32 s) ≤ 900 s. Six zones fit shots up to **118 s**; ten fit only 58 s. ADR-0055's 2,000-row store per growspace also holds 6 zones × 40 shots/day × 7 days = 1,680 rows. The number is therefore **derived, not observed**, and this record is the inference chain the map requires anyone citing 2–6 to name.
2. **Past the envelope, by whether the thing is new.**
   - **Refused:** zones, probes and valves are new configuration with no existing users. A 7th zone, a 5th probe of a quantity or a 9th valve is refused with a typed `envelope_exceeded` (ADR-0027) naming the limit. Untested means unsupported.
   - **Warned:** irrigated growspaces already exist in the wild, so an instance past 10 gets a Home Assistant **Repairs** issue saying it is outside the tested envelope, and nothing stops.
3. **Settings that cannot fit.** A growspace inside the envelope can still be configured beyond its own pump. The trigger is its zone count × (longest configured shot + 32 s) exceeding its shortest configured interval. That raises a **Repairs warning at configuration time, never a refusal**, naming the zones and the shortfall. What happens at runtime when shots cannot all be served is the map's arbitration item.
4. **The load test.** A CI pytest suite, `tests/envelope/`, simulates the full envelope: 10 growspaces × 6 zones × 4 moisture and 4 pore-EC probes, with a fake clock and stub drivers that confirm every command, over 7 simulated days of minute ticks at 40 shots per zone per day. It asserts:
   - **Event-loop cost:** p99 of one instance-wide minute tick ≤ **100 ms** on the CI runner. Home Assistant's loop is shared, and this is the cost that grows with zones × probes.
   - **Storage:** each growspace's Delivery Attempt store stays ≤ **2,000 rows**, and never evicts a charged row dated today. Each write to disk stays ≤ **150 KB**.
   - **Pump time:** a unit test asserts 6 × (118 s + 32 s) ≤ 900 s on the constants themselves, so moving a limit or a confirmation timeout breaks it.
   - **Entities:** the entities created per zone are snapshotted, so growth is a visible diff.

   Real disk and device latency are not measured. They are hardware evidence ([[Reliability Evidence]]), not a CI property.

5. **Moving a limit.** The limits are named constants, and raising one means raising the load test with it in the same change.

## Considered Options

- **The PRD's 128 / 8 / 32.** Certifies a topology nobody has, and no test could honestly back it.
- **Per-profile envelopes** (hobby, pro, facility). Profiles are the facility machinery this map ruled out. The only real variable is shot length, and item 1's arithmetic already expresses it.
- **Refuse everything past the envelope, growspaces included.** It would break installs that already run more than ten growspaces, for a limit about irrigation.
- **Warn on everything, refuse nothing.** An envelope nobody is stopped at is a suggestion, and for zones and probes there is no existing user a refusal could hurt.
- **Entity count or tick budget as the binding reason.** A growspace carries about 21–36 entities on the dev instance, and a zone adds a handful. At single digits neither binds before pump time does.

## Consequences

- The zone, probe and valve write paths gain the `envelope_exceeded` refusal, and setup gains the two Repairs issues.
- `tests/envelope/` is the first load test in the repository, and it runs in CI.
- The arbitration item on #544 inherits a concrete bound: at most 6 zones per queue, and a known shortfall warning when a growspace's own settings do not fit.
