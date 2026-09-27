# The Card Draws Zones on the Grid and Explains Them in Sentences

**Status:** Accepted — not yet implemented (the card surface for [ADR-0054](./0054-daily-caps-enforce-a-durable-dispensed-volume.md) item 6, [ADR-0055](./0055-delivery-attempts-are-the-durable-record-of-every-pump-request.md), [ADR-0057](./0057-an-irrigation-zone-owns-its-cells-and-every-growspace-starts-with-one.md), [ADR-0059](./0059-a-zone-steers-on-one-elected-probe-and-witnesses-guard-it.md), [ADR-0061](./0061-zones-due-at-once-wait-in-a-supply-queue-and-are-decided-at-the-front.md), [ADR-0062](./0062-a-degraded-zone-holds-or-replays-its-last-clean-day.md) and [ADR-0064](./0064-flow-meters-are-evidence-and-a-flow-rate-is-only-ever-proposed.md) item 13)

The irrigation map's decisions each left the card a question (#864). How does a grower draw an [[Irrigation Zone]] and give it valves and probes? How do today's [[Delivery Attempt]]s read, including the suppressed and the queued ones, and where is "why was I capped?" answered? How do [[Degraded Control]], a substituting witness and a [[Replay Fallback]] look at a glance? And what does a grower with one zone, which is every grower today, see?

It was answered by prototype, not on paper. Three structurally different variants ran inside the real Irrigation dialog on the dev instance, over Demo Tent's real grid and plants, with stub zones, probes, attempts, queue and cap in four scenarios: three zones mid-day, three zones after the cap ran out, one healthy zone, and one zone with `probe_unresponsive`.

- **A, zone switcher.** Zone pills above every tab; each zone's health as a sentence; today's attempts as a table.
- **B, grid is the map.** Zones tinted on the growspace grid, probes as pins on their cells, degraded zones hatched; editing by painting cells on the same grid.
- **C, supply timeline.** One lane per zone across the lit day, every attempt a mark with its queue wait, and a running cap total.

The winner is a hybrid: B's grid for where zones are and for editing them, A's sentences and table for what happened, A's treatment of a single zone, and C's running cap total for the one question it answers best. The prototype is kept, unmerged, on the card's `prototype/864-irrigation-zones` branch.

1. **Zones are drawn on the grid.** A **Zones** tab in the Irrigation dialog shows the growspace grid with each cell tinted by the zone that owns it, and a label per zone carrying its name, its [[Zone Headline]] and its valve count.
   - Probes are pins on their cells: the [[Control Probe]] solid, witnesses dashed, a failing probe red, and a witness standing in for the Control Probe marked as substituting.
   - A zone in Degraded Control is hatched where it stands: red while it holds, amber while it replays. The zone the supply is watering pulses.
   - Tapping a zone opens its panel (item 3). Zones are cells (ADR-0057), so the grid is the one place a grower can see which plants a zone waters. A list of zone names would hide exactly that.
   - The tab exists only with two or more zones.
2. **Zone-owned tabs gain a zone switcher; growspace-owned tabs do not.** With two or more zones, a strip of zone pills scopes Overview, Steering, Schedules, Recipes and Program to one zone, because ADR-0057 moves those settings to the zone. Tanks, Drain EC, Water Analytics and the pump's Configuration stay growspace-wide and get no strip. The split is ADR-0057's ownership table, so the card cannot scope a setting to the wrong owner.
3. **A zone explains itself in sentences.** The zone panel opens with one sentence of what the zone is doing and why, in the words of ADR-0062's alerts:
   - replaying: _"Probe C-1 has not risen after 3 shots since 10:20. Replaying 24 Sep's shots at 80% until it recovers. Check the emitter as well as the probe."_ with the next replay shot;
   - holding: the cause, what still works (Manual Runs), and for a zone set to `hold` the [[Reference Day]] it could replay, with a link to the setting;
   - substituting: the witness, its offset, and that dryback recording and learning are paused;
   - waiting: when its claim was made and which zone is ahead of it (ADR-0061).

   `probe_unresponsive` always names both causes, because the readings cannot tell a probe out of the pot from water not reaching it (ADR-0062 item 8). Below the sentence are the zone's VWC and which probe it came from, its plants and valves, and its [[Calibration Confidence]]. A Disputed zone shows its [[Calibration Proposal]], which opens the Repairs fix rather than applying anything.

4. **Today's attempts are a table.** Each zone panel lists today's Delivery Attempts, newest first: time, what asked (P1 or P2 shot, Manual Run, schedule, replay), planned seconds and litres, delivered litres marked estimated or metered, short or over when metered, and the outcome in words.
   - A claim still waiting is pinned on top as a row with no attempt yet.
   - Merged suppressions show their count and time span (ADR-0055 item 5).
   - A shot that waited shows how long (`due_at`).
   - A replay shot is tagged as one and names the Reference Day shot it replays.
   - Expanding a row shows the lifecycle: due, requested, ON confirmed, OFF read back, planned, charged, estimated, metered.
   - The panel also sums the zone's day as **asked / charged / got**, the three numbers requested-vs-delivered is made of.
5. **The cap is one bar, and "why?" is a running total.** The cap tile reads as ADR-0054 fixed it, "Toward daily cap 30.5 / 48 L · 23 / 40 cycles", with "Liters today" beside it as [[Aggregate Water Use]].
   - With two or more zones the bar is split by zone colour, so who spent the cap is visible without asking.
   - Its **Why?** opens the day's charged litres as a running total against the cap, marking the minute it ran out, with each zone's share and shot count. It says that the cap counts what was charged: the plan at confirm-ON, raised to a meter's reading, and an aborted shot's whole plan. When a Disputed flow rate inflated the charges, it says that too and offers the proposal.
   - A day-long lane per zone was rejected as the main surface (see below). The running total keeps the one thing that lane did best.
6. **A zone label shows only the zone's own state.** The **[[Zone Headline]]** is the one state a zone's label shows, by precedence: holding or replaying, then substituting, then watering, then waiting for the supply, then steering.
   - Growspace-wide holds are shown once, on the cap bar and the safety chip: the cap, a [[Fault]], the emergency stop, an operator hold. They are never repeated on every zone.
   - In the prototype, stamping the cap on every label hid that one zone was also replaying on a failed probe, which is still true when the cap resets at midnight.
7. **At a glance: the safety chip, plus one line when a zone needs attention.** The header gains no zone summary while all zones are healthy.
   - When any zone holds, replays or substitutes, one compact chip beside the safety chip names the worst zone and its headline, with a count of any others ("Bench C: replaying 24 Sep +1"), and opens the Zones tab.
   - One dot per zone and a supply summary were both rejected: they add a permanent chip that says nothing on a healthy day.
8. **Zones are edited where they stand.** **Edit zones** turns the same grid into an editor:
   - pick a zone and drag across cells to give them to it; add a zone;
   - place a probe by choosing a sensor and then a cell, and tap a probe to make it the Control Probe;
   - toggle valves in the zone panel, where a valve another zone owns is shown as taken and named ("opens Bench B") (ADR-0058);
   - name the zone and choose `hold` or `replay` for when its probe fails.

   Saving is one write under the layout's revision guard (ADR-0032). A save made after someone else changed the layout is refused as a whole and says so, and nothing is merged. The card pre-checks what the backend will refuse, so the grower learns before saving: a zone without a valve once there are two, a zone with no cells, and `envelope_exceeded`. The backend stays the authority.

9. **One zone sees nothing new, bar three things.** A single-zone growspace shows no zone word, no strip, no Zones tab and no tint (ADR-0057 item 5). What it can meet:
   - **`probe_unresponsive`,** as a reason on the existing safety chip and as the same sentence at the top of Overview, naming both causes and, when the zone holds, the day it could replay;
   - **the cap tile's new wording** (ADR-0054 item 6);
   - **today's attempts table,** under Water Analytics, since requested-vs-delivered is not a zone question.

   The door into zones is one line in Configuration, beside the pump: **"Water part of this tent separately…"**. It opens the editor with the implicit zone revealed as "Zone 1".

10. **Calibration surfaces** (ADR-0064 item 13) split by owner. Each zone's stage and evidence count, and its proposal, sit in its panel (item 3). The [[Tank–Pump Disagreement]] and each meter's [[Unattributed Flow]] are growspace-wide and sit in Water Analytics beside "Liters today". Of these, only the zone stage and the proposal were prototyped.

## Considered Options

- **A's zone strip as the main zone surface.** It scopes tabs well, and item 2 keeps it for that. It cannot show which plants a zone waters. A pill has room for one state, so a zone both waiting and substituting read only as waiting.
- **C's supply timeline as the main surface.** It is the only view that shows the shared supply taking turns, and the running cap total survives in item 5. On a 12-hour axis a 45-second shot is a hairline, it takes a zoom control to read, and it hands a single-zone grower a new screen, which breaks item 9.
- **A permanent zone chip in the header** (a dot per zone, or the supply's state). It is noise on a healthy day, and the safety chip already carries everything growspace-wide.
- **Editing zones in a form or table.** A form keeps cells and valves apart from the grid they describe. Row-only assignment (C's table) is quick for benches but cannot express a zone that is not whole rows. Both remain possible behind the grid; neither replaces it.

## Consequences

- **The card needs a read of Delivery Attempts, and none exists.** ADR-0055 stores every attempt per growspace for 7 days, and nothing hands them to the card. The backend gains a read-only WebSocket command for one growspace's attempts on one local day. It carries, per row, what ADR-0055 item 6 records, plus `due_at`, the merged count and span, and for a replay the Reference Day shot. It lands before the card, with its contract fixture. The table needs no zones, so this can ship ahead of 1.4.0.
- **The `zones` array (ADR-0057) carries what the headline and sentences need.** Per zone:
  - state;
  - the Degraded Control cause and since when;
  - the Replay Fallback's Reference Day and next shot;
  - the substituting witness, its offset and since when;
  - a waiting claim's `due_at`;
  - Calibration Confidence and its evidence count;
  - cells, valves, and probes with role, cell and health.

  The card derives the Zone Headline from these and stores nothing of its own.

- **A zone's reason must name its zone.** With two or more zones, a hold on the controller's reasons has to say which zone it is, or the header line in item 7 cannot be built.
- **`probe_unresponsive` joins the card's known safety reasons**, with its text, before 1.4.0. Without it a single-zone grower meets the one new hold of ADR-0059 as "unrecognised reason".
- The recipe edit dialog's zone list and the per-zone "recipe updated" state (ADR-0065) are also card surface. They belong to the recipe library's edit flow, were not prototyped here, and go to the ticket that implements ADR-0065.
- The card work follows the backend in the contract order: backend implementation, contract fixture, card.
