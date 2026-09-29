# One Supply, One Open Zone, and No Delivery Group

**Status:** Accepted — not yet implemented

ADR-0057 gave an [[Irrigation Zone]] "its valve outputs" and left their number, and whether a pump owns a group of zones, to #552. The research (#545) found three things. The one observed install ran 54 valves as 8 zones, 6–7 valves per zone, all opened together. TrolMaster NFS-2 binds each pump to a group of valves. AROYA forbids two zones open at once, and OpenSprinkler runs one zone at a time within a group unless the grower opts into parallel. The PRD's "Delivery Group" was reaching for the gap between the steered unit and the actuated unit.

At 2–6 zones that gap is closed by the zone itself, and the rest follows from keeping one supply per growspace.

1. **No Delivery Group.** A zone owns **one or more valves that always open together**, and **each valve belongs to exactly one zone**. The 54-valve install is 8 zones of 6–7 valves each. A valve that fed two zones would make them impossible to water separately, so they are one zone. Valves of one zone opened at different times are two cohorts, so they are two zones. Neither case leaves anything for a group to hold.
2. **One [[Irrigation Supply]] per growspace**: a pump, or a master valve on pressurised mains, since both are just an output. A grower with two feeds has two growspaces. That keeps tanks, feed EC and the EC ramp where ADR-0057 put them, and it keeps arbitration, caps and faults single-level. The cost is that one room with two feeds becomes two growspaces that duplicate light and climate config. Pump groups come back only for a real grower who cannot live with that.
3. **One open zone at a time.** Zones on a supply run strictly in turn, with no parallel mode. This is the published reference shape. It keeps a zone's flow rate true, because two open zones would split one pump's output, and it makes a supply meter unambiguous. How zones due at once queue stays the map's arbitration item, and the numbers are #551's.
4. **Meters.** A meter sits on the supply or on a zone. A zone meter measures its zone. A supply meter is attributed to the one [[Delivery Attempt]] whose valves were open during the reading's window. A reading outside any open attempt (a leak, or a person at the pump) is recorded as unattributed and never charged to a zone. Units, cumulative-vs-rate and tolerance belong to the flow-meter item (ADR-0055).
5. **Actuation order.** Each step is confirmed through ADR-0022's driver, with no lead or lag settings:
   1. Every valve of **other** zones must read closed first, or the attempt is refused as `foreign_valve_open`. A valve found open with no attempt of ours is an [[Unexpected On]], like a pump.
   2. This zone's valves open, and each is read back. If one does not read open, the supply is never started: the attempt is `not_delivered`, and the valves already opened are closed and read back.
   3. The supply starts and must confirm ON. Charging starts here (ADR-0054).
   4. The supply stops and is read OFF. Then the valves close, and each is read closed.

   Starting against closed valves would deadhead a pump, and the confirmation waits already space the steps. OpenSprinkler's ±600 s adjustments serve pressure hardware we have no evidence about.

6. **Faults are growspace-wide.** A valve that will not read closed waters its zone on every other zone's run, and with one supply per growspace every output shares that supply. So any latched fault on any output blocks the growspace, which settles what ADR-0057 left open.
7. **The hobby grower.** The implicit zone's valve list is empty by default, which is today's pump-only setup. A single-zone grower whose pump feeds a solenoid may list it in irrigation settings, and it then follows the order above. Valves become mandatory only at two zones or more (ADR-0057). No group appears anywhere, because none exists.

## Considered Options

- **A first-class Delivery Group,** as the smallest jointly actuated or measured set. With valves always opening together and belonging to one zone, it would be a second name for the zone's valve list. The measured boundary it was meant to hold (one meter on a manifold) is handled by attribution in item 4, which holds only because of item 3.
- **Pump groups (several supplies per growspace).** This is the documented general shape, but it pushes tanks, feed, caps, faults and arbitration down a level for a case no grower has asked for.
- **An opt-in parallel mode.** It splits the pump's flow between zones, so each zone's flow rate is wrong, and it makes a supply meter unattributable.
- **Configurable pump lead and lag.** A knob tuned for hardware we cannot observe. Confirmed ordering already prevents deadheading.

## Consequences

- An `IrrigationZone` carries `valves: list[str]`, empty only for a lone implicit zone. The Delivery Attempt records which valves it opened and their readbacks beside the supply's.
- The Unexpected On watch covers valves as well as the supply.
- The arbitration item on #544 can now be framed as one queue per growspace.
