# A Zone Keeps the Recipe Revision It Was Stamped With

**Status:** Accepted — not yet implemented (amends [ADR-0045](./0045-irrigation-recipes-are-substrate-relative-and-hold-by-default.md); builds on [ADR-0057](./0057-an-irrigation-zone-owns-its-cells-and-every-growspace-starts-with-one.md) and [ADR-0063](./0063-zones-ship-alone-and-an-older-build-refuses-the-store.md))

Under ADR-0057 each [[Irrigation Zone]] owns its steering strategy, including its recipe and program. Several zones, in one growspace or several, can now run the same [[Irrigation Recipe]]. The PRD behind this map pictured a Draft → Reviewed → Approved → Scheduled → Active → Retired pipeline for recipes, which was ruled out because Home Assistant has no per-user identity to hang authority on. #862 asked whether any recipe versioning is warranted at 2–6 zones.

The question assumed that editing a shared recipe silently changes the zones running it. It does not. A [[Recipe Stamp]] is by value (ADR-0045): the zone holds the numbers, and the coordinator never reads the recipe. The edit does three other things, all visible on `prerelease` today.

- **It reads as a hand tweak.** `recipe_has_drifted` re-resolves the recipe as it is _now_ against the zone's fields. After an edit, every zone that ran it reports `applied_recipe_drifted: true` although nobody touched it. Nothing can tell "the grower tweaked this zone" from "the recipe moved after it was stamped".
- **It stalls auto-advance under a false message.** The current week stays `up_to_date`, because `applied_recipe_id` still matches. When the next week calls for a different recipe, [[Program Progression]] holds with `drifted` and notifies that "auto-advance never overwrites a hand tweak". No hand tweak happened.
- **It never reaches the zones already on it.** When the next slot names the same recipe, as flower weeks 3–5 commonly do, progression reads `up_to_date` for good. The corrected values reach a zone only if the grower re-applies them by hand, once per zone.

The first two are wrong answers the product acts on. The third exists because several zones can now share one recipe. A revision library would solve all three, but it is much larger than the problem, so this decision takes the smallest form that does.

1. **A recipe carries a [[Recipe Revision]].** `revision: int` starts at 1. An edit that changes a stored value raises it by one; a rename does not. Earlier revisions are not kept in the library.
2. **A stamp keeps an [[Applied Recipe]] on the zone.** A Recipe Stamp records `applied_recipe: {id, revision, values}` on the zone, replacing `applied_recipe_id`, beside the existing `recipe_applied_at`. `values` is the recipe's own stored half as it was at that revision (percents, not the seconds they resolved to), limited to the fields a zone stamp writes (decision 5).
3. **Drift and an update are two facts, never one.**
   - **Drifted** means the zone's live fields differ from what its Applied Recipe's `values` resolve to against the zone's live plumbing and plant count. ADR-0045's rule survives: in Seconds [[Shot Sizing Mode]], gaining or losing a plant reads as drift, because the configured seconds no longer deliver the recipe's per-pot dose.
   - **[[Recipe Updated]]** means `recipe.revision > applied_recipe.revision`.
   - Both can be true at once, and the payload reports them separately. This replaces ADR-0045's "no drift hash is stored". A hash was rejected because it goes stale against a recipe held by reference. A copy of what was stamped cannot go stale, because it records what happened rather than deriving from what the recipe says now.
   - A deleted recipe's zones keep reporting drift from their copy, where today they report `null`.
4. **An edit offers to reach the zones on an older revision.** After an edit that raises the revision, the card lists every zone, across every growspace since the library is global, whose Applied Recipe names this recipe at an older revision, each with its drift state.
   - Untweaked zones are preselected, and tweaked zones are not, since re-applying discards the tweak.
   - The zones that auto-advance will re-stamp anyway (decision 6) are named as such.
   - Each selected zone is an ordinary Recipe Stamp through [[Irrigation Change]] (ADR-0046). There is no batch service; the card calls `apply_irrigation_recipe` once per zone.
   - A zone left out shows "recipe updated to revision N" until it is re-applied.
   - Nothing is re-stamped by the edit itself.
5. **A zone stamp writes only what the zone owns.** Under ADR-0057 the growspace keeps the lights, the drain, the daily caps and the dark gate, and a stamp into one zone must never change them for the zone beside it.
   - From a crop-steering recipe, `lights_on_time` and `auto_light_tracking` move into [[Recipe Provenance]].
   - From a schedule recipe, `drain_times`, `drain_duration`, `daily_volume_cap_liters`, `max_cycles_per_day` and `skip_during_dark` become descriptive in the same way. A zone stamp writes only `irrigation_times` and `irrigation_duration`.
   - These fields are never written by a stamp and never compared for drift. A mismatch with the target growspace warns and the apply proceeds, the pattern ADR-0045 set for media.
   - This holds with one zone too. An action whose reach depended on the zone count would be exactly the surprise ADR-0057 avoids by keeping the implicit zone invisible.
6. **Auto-advance follows a new revision of the slot's recipe.** `up_to_date` now requires the slot's recipe id **and** its current revision to match the zone's Applied Recipe.
   - With `program_auto_advance` on, a new revision of an untweaked zone's current recipe is `due` and is re-stamped on the next refresh, with a logbook entry naming the revision. Programs hold recipes by reference, and auto-advance is consent to that plan. ADR-0045 already accepted that "a fixed shot size propagates to every program using it".
   - With auto-advance off it is `available`, saying the recipe was updated to revision N.
   - The `drifted` [[Program Hold]] now fires only for a real hand tweak.
   - Programs keep referencing a recipe by id, never a revision.
7. **Grow Runs record the Applied Recipe once they record configuration.** No stamp reaches a [[Grow Run]] today. This is a requirement on ADR-0037's configuration timeline, not built here: when that timeline exists, each Recipe Stamp is a run event carrying the zone, the recipe's id and name, the revision, the copied `values` and the trigger (explicit or program). A recipe edit is a library event and never a run event. A run sees it only when a stamp lands in one of its zones.
8. **Migration backfills at revision 1.** In ADR-0063's version 2 migration, behind its [[Pre-Migration Copy]], every stored recipe gets `revision: 1`, and every zone with an `applied_recipe_id` gets an Applied Recipe copying that recipe's current values at revision 1. A zone whose recipe was edited after its stamp then reads as drifted, which is what it reads today. A stamp whose recipe has already been deleted gets no copy and keeps today's `null`.

## Considered Options

- **Keep today's behaviour and word the edit confirmation better.** Leaves the product telling the grower something false and then acting on it.
- **Fix drift attribution only, with re-applying left to the grower.** Leaves the zones already on the recipe unreachable except one by one, which is the problem shared zones created.
- **Copy-on-apply without a revision counter.** An update becomes a value comparison. The card, the logbook and a Grow Run then have no short name for which version a zone runs.
- **Immutable revisions with zones pinned to one.** A library of every revision, and programs that could pin one. It brings back the pipeline machinery the map ruled out, and none of the three problems needs old revisions kept anywhere but on the zones that ran them.
- **An edit log only.** Records that a recipe changed, and fixes none of the three.
- **Re-stamp every untweaked zone on edit.** The silent change to running zones that #862 feared.
- **Leave new revisions to the grower even under auto-advance.** An edited recipe would reach the zone entering week 4 but not the one already in week 3, the inconsistency this decision exists to remove.
- **Write the lights and the growspace's schedule fields from a zone stamp,** with a warning when sibling zones differ. One zone's recipe would then lower every zone's daily cap.
- **Write them only while the growspace has one zone.** Gives one action two reaches.
- **A separate growspace-level recipe kind** for the drain, caps and dark gate. A new object nobody has asked for.
- **Revision numbers only in Grow Runs.** Once the library moves on, the run cannot say what revision 2 contained — the "later edits erase the explanation" failure ADR-0037 rejected.
- **Leave pre-existing stamps without a copy.** Adds an unknown drift state that auto-advance would need a rule for, and is no more accurate than the backfill.

## Consequences

- ADR-0045 is amended: its "no drift hash is stored" becomes the Applied Recipe copy, drift is judged against that copy, and a recipe's light fields are provenance.
- The recipe's wire shape gains `revision`. The zone's gains `applied_recipe {id, revision, values}` and `recipe_updated` beside `applied_recipe_drifted`. Per ADR-0045 and ADR-0030 the golden fixture carries both populated and non-null.
- `edit_recipe` can no longer reach the light fields, which move into provenance, so they are fixed at capture.
- A single-zone grower who sets drains or caps through a schedule recipe loses that in 1.4.0. The implementing PR adds its line under `### Changed` in `CHANGELOG.md` (ADR-0063), and `docs/upgrading/zones.md` names it.
- The edit dialog's zone list and the per-zone "recipe updated" state belong to the card surface (#864).
- The store grows by one Applied Recipe of about 20 values per zone: at most 60 across ADR-0060's envelope.
