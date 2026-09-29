# Zones Are a Scope Over the Irrigation Dialog, and a Zone's Day Is a Timeline

**Status:** Accepted — not yet implemented (the card surface for [ADR-0054](./0054-daily-caps-enforce-a-durable-dispensed-volume.md) item 6, [ADR-0055](./0055-delivery-attempts-are-the-durable-record-of-every-pump-request.md), [ADR-0057](./0057-an-irrigation-zone-owns-its-cells-and-every-growspace-starts-with-one.md), [ADR-0059](./0059-a-zone-steers-on-one-elected-probe-and-witnesses-guard-it.md), [ADR-0061](./0061-zones-due-at-once-wait-in-a-supply-queue-and-are-decided-at-the-front.md), [ADR-0062](./0062-a-degraded-zone-holds-or-replays-its-last-clean-day.md), [ADR-0064](./0064-flow-meters-are-evidence-and-a-flow-rate-is-only-ever-proposed.md) item 13 and [ADR-0065](./0065-a-zone-keeps-the-recipe-revision-it-was-stamped-with.md)). The Delivery Attempt read its Consequences call for is `growspace_manager/get_delivery_attempts` (#888).

The irrigation map's decisions each left the card a question (#864). How does a grower draw an [[Irrigation Zone]] and give it valves and probes? How do today's [[Delivery Attempt]]s read, including the suppressed and the queued ones, and where is "why was I capped?" answered? How do [[Degraded Control]], a substituting witness and a [[Replay Fallback]] look at a glance? And what does a grower with one zone, which is every grower today, see?

It was answered by prototype, not on paper. Three whole-concept variants ran inside the real card, with synthetic zones, probes, attempts, queue and cap:

- **A, zone scope.** A scope control over the existing irrigation dialog, and a Zones editor that paints grid cells.
- **B, zone board.** A separate Zones rail group with one expandable table, and a deliveries ledger on Overview for everyone.
- **C, map and day timeline.** Zones tinted on the main plant grid, a swimlane timeline of the day, and a spatial editor with placeable probes.

The winner is **A's scope, Zones editor and single-zone answer, carrying C's timeline** in place of a deliveries list. It is variant D on the card's `prototype/zones-864` branch, the primary source. A second, independent prototype of the same question (`prototype/864-irrigation-zones`) reached two findings that this record keeps: the [[Zone Headline]] in item 6, and the missing Delivery Attempt read in the Consequences.

1. **Zones are a scope over the dialog, not a new place.** With two or more zones, the irrigation dialog's content header carries a scope control, **Whole tent · Zone 1 · Zone 2 …**, where the growspace pill was.
   - Each zone has its colour dot and, when something needs attention, a glyph: ▲ for a warning or fault, ● for watering or queued.
   - The existing tabs stay. Overview reads the chosen scope.
   - Zones appear only on irrigation surfaces (ADR-0057). The main card's plant grid gets no zone tint and no zone tags.
2. **Whole tent** (Overview) shows the shared supply and every zone together:
   - one banner per troubled zone (item 5);
   - a **Pump** card: which zone is open, the next [[Supply Claim]] with its due time, and the [[Dispensed Volume]] meter, "Toward daily cap X / Y L · n / m cycles" (ADR-0054 item 6), stacked by zone colour;
   - a **Zones** list: phase, VWC, litres today and status per zone, each row opening that zone's scope;
   - a **timeline** of the lit day (item 3).
3. **A day is a swimlane timeline.** One lane per zone, plus a **cap lane** showing the cumulative charge against a dashed cap line, with a "cap reached HH:MM" marker. Each Delivery Attempt is a mark:
   - bar height is the litres charged;
   - a hollow dashed bar is queued, a white outline running, a red outline aborted, and × not sent (suppressed);
   - a striped bar is a replay shot, and "M" a [[Manual Run]];
   - a dashed underline is the wait from `due_at` to the gate (ADR-0061);
   - a lane is hatched while its zone holds and tinted while it replays;
   - P3 is shaded, and a line marks now.

   Clicking a mark shows that attempt: its volume, metered or estimated, and what was charged; its wait; its planned seconds at the zone's flow rate; and the zone's [[Calibration Confidence]]. With nothing selected, the line under the timeline reads "Cap so far: Zone 1 x L · Zone 2 y L · …". **That line answers "why was I capped?"**: the cap lane shows when it ran out, and the line shows who spent it.

4. **A zone's scope** shows:
   - its banner;
   - a status card: phase, VWC and which probe it came from, target, Calibration Confidence, and its recipe with ADR-0065's "Recipe updated to rev N" and its hand-tuned drift;
   - **its own lane**, with a cap lane showing the whole tent's charge and this zone's share in its colour;
   - its shot list underneath.
5. **Degraded and substituted zones read as one sentence.** A banner says what the zone is doing, backed by the ▲ in the scope control and the hatched or tinted band on its lane.
   - Holding: _"No trustworthy probe since 09:10. Holding…"_, and for a zone set to `hold`, a link to turn on replay that names the [[Reference Day]] it would repeat at 80%.
   - Replaying: _"Replaying 25 Sep's shots at 80% — 2 left before P2 stop."_
   - Substituting: _"Steering on witness TEROS B… learning paused."_

   `probe_unresponsive` names both causes, the probe and the emitter, because the readings cannot tell them apart (ADR-0062 item 8).

6. **A zone shows only its own state.** Its **[[Zone Headline]]**, which picks its glyph, its status and its banner, follows one precedence: holding or replaying, then substituting, then watering, then queued, then steering.
   - Holds that stop the whole growspace — the cap, a [[Fault]], the emergency stop, an operator hold — are shown once, on the cap lane, the Pump card and the safety chip, and never stamped on every zone.
   - A prototype that stamped the cap on every zone hid the one that was also replaying on a failed probe, which is still true when the cap resets at midnight. A zone both queued and substituting read only as queued.
7. **Zones are edited under Equipment › Zones** (its badge is the zone count).
   - Pick a zone colour, then click or drag across grid cells to assign them. Plant names show in the cells, and probes show as ◉ control and ○ witness.
   - Beside the grid, one card per zone carries its name, its valves, its [[Control Probe]] and its witnesses. A zone with no valve shows **needs a valve** (ADR-0057, ADR-0058).
   - "＋ Add zone" is refused past 6 with `envelope_exceeded` (ADR-0060).
   - Saving goes through the layout revision guard. A conflict shows `layout_revision_conflict` with a Reload, and nothing is merged (ADR-0032).
8. **A single-zone grower sees nothing new.** No scope control, no Zones rail item, no timeline, no tint (ADR-0057 item 5).
   - The one door into zones is a **"Split into zones"** row on Configuration.
   - `probe_unresponsive` is the one new thing they can meet: an Overview banner, _"Probe not responding. VWC stayed flat through 3 shots. Holding — check the probe is in the pot and the emitter is dripping,"_ which names the day it could replay.
   - The cap tile's wording changes for everyone, as ADR-0054 item 6 already decided.

## Considered Options

- **B's board**, a separate Zones rail group with one expandable table. It duplicates the tabs rather than scoping them, so a zone's settings would live in two places.
- **A deliveries ledger for everyone,** on Overview or under Water Analytics. Requested-vs-delivered is not only a zone question, but a table of every shot is the one new screen a single-zone grower would meet every day. The timeline gives the same answer where zones exist.
- **Zones tinted on the plant grid,** on the main card or in a Zones tab of the dialog. A zone is its cells (ADR-0057), and a tinted grid shows which plants a zone waters. On the main card it puts zones on a surface ADR-0057 keeps them off. In the dialog it is a second map beside the scope, which already carries each zone's status. The grid stays the editor (item 7), where cells are the point.
- **A permanent zone chip in the card header** (a dot per zone, the supply's state, or the worst zone). The safety chip already carries everything growspace-wide, and the scope's glyphs carry the rest once the dialog is open.
- **A dropdown per cell, and a spatial editor with draggable probe tokens.** A matrix of dropdowns hides the grid it describes. Draggable tokens add a second editing gesture the paint-and-card editor does not need.

## Consequences

- **The card needs a read of Delivery Attempts, and none exists.** ADR-0055 stores every attempt per growspace for 7 days, and nothing hands them to the card. The backend gains a read-only WebSocket command for one growspace's attempts on one local day. It carries, per row, what ADR-0055 item 6 records, plus `due_at`, the merged count and span, and for a replay the Reference Day shot it repeats. It lands before the card, with its contract fixture.
- **The `zones` array (ADR-0057) carries what the scope, the banners and the headline read.** Per zone:
  - state;
  - the Degraded Control cause and since when;
  - the Replay Fallback's Reference Day and the replay shots left;
  - the substituting witness, its offset and since when;
  - a queued claim's `due_at`;
  - Calibration Confidence and its evidence count;
  - the Applied Recipe's revision state (ADR-0065);
  - cells, valves, and probes with role, cell and health.

  The card derives the Zone Headline from these and stores nothing of its own.

- **The supply's state is read too:** which zone is open and the queue's claims in order (ADR-0061), for the Pump card.
- **`probe_unresponsive` joins the card's known safety reasons**, with its text, before 1.4.0. It is the one hold a single-zone grower can newly meet, and without it the safety chip calls it an unrecognised reason. With two or more zones, a zone's hold on the controller's reasons names its zone.
- **Not decided here:**
  - the recipe edit dialog's list of zones on an older revision (ADR-0065 item 4) belongs to the recipe library's edit flow;
  - the [[Tank–Pump Disagreement]] and [[Unattributed Flow]] are growspace-wide and were not prototyped. They go to the card ticket for the metering release.
- The card work follows the backend in the contract order: backend implementation, contract fixture, card. The prototypes' code is not a starting point for it.
