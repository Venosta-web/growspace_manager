# ADR 0047 — A multi-date lifecycle edit reschedules Stage History

**Status:** Accepted (extends [ADR-0013](./0013-lifecycle-dates-are-datetime-through-one-write-seam.md))

## Context

`update_plant` understood exactly two shapes of lifecycle edit. A **Lifecycle
Transition** moves the Plant forward through the stage graph: it closes the open
interval and appends a new one. A **Lifecycle Correction** (`repair_current`)
rewrites the open interval's start, retaining the maximal trustworthy and
graph-compatible earlier prefix and discarding everything after it.

Both shapes require the edit to name **one** stage — explicitly through `stage`,
or implicitly by being the single populated `*_start` field. A payload carrying
two populated dates and no `stage` fits neither, and was refused with
`A lifecycle date edit must identify exactly one current stage`.

The plant overview renders every stage's date input together and, since
[card ADR-0018] and lovelace-growspace-manager-card#894, sends exactly the fields
the grower touched. So the dialog invites precisely the edit the backend refused:
a grower who realises both the veg start and the flower start were wrong had to
fix them one save at a time, and each intermediate save was itself a correction
on the timeline.

Two dates are not a transition and not a single-stage repair. They are closer to
_rebuild the stage history from this set of stage starts_ — and the domain, which
reasons as one open interval plus movement between stages, had no room for two
rewritten boundaries at once.

## Decision

A third operation, **Lifecycle Reschedule** (`PlantLifecycle.reschedule`), owns
edits that move more than one boundary. It is selected structurally: an edit with
no explicit `stage` and **two or more populated `*_start` fields** is a
reschedule; everything else keeps the transition/repair routing unchanged.

1. **Unmentioned intervals are retained, not discarded.** A reschedule starts
   from the Plant's existing trustworthy intervals and changes only what the
   edit names. This is deliberately the opposite of the single-stage repair,
   which discards the ambiguous tail: a repair is told one boundary and cannot
   know whether later intervals still make sense, whereas a reschedule is told
   where each named boundary belongs and the rest is untouched evidence. Only
   the intervals the parser could not trust are dropped, and they are counted
   into the repair event's `discarded_interval_count` as before.

2. **A supplied date retargets a stage's latest interval.** `veg_start` is the
   Compatibility Data projection of the _last_ veg interval, so that is the one
   it moves. After a Reveg, editing `veg_start` corrects the newer veg interval
   and leaves the pre-flower one alone.

3. **A stage the Plant has never been in is inserted where its date places it.**
   Recording a seedling start that was never captured, or entering a flip date
   beside a corrected veg start, is the same gesture as correcting one — the
   dialog offers one input per stage and does not distinguish them.

4. **A coherent set is one that satisfies the existing Stage History rules.**
   Boundaries are re-derived after the moves (each interval ends where the next
   begins, the last stays open), so gaps and overlaps cannot be expressed. What
   remains refusable is: a start later than the correction date; a retained stage
   whose start jumps past its successor's; and an insertion that breaks the
   transition graph. Each is refused **by name** —
   `veg start 2026-08-14 is after flower start 2026-08-12`, not the old
   one-stage wording — and the constructed result is re-validated through the
   same `_validate_intervals` the parser uses, so there is one definition of
   coherent rather than two.

5. **Retained stages are never reordered.** A set that would require it is a
   contradiction, not a re-ordering request. This is what makes the refusal
   messages nameable: the grower is told which two stages disagree, instead of
   being handed a silently re-sorted history.

6. **The Plant ends up in the stage owning the last interval** — the latest
   supplied or retained start. Because retained stages keep their order, a
   reschedule that only corrects existing dates cannot change the Current Stage;
   one that inserts a later stage advances it, which is the point of entering a
   flip date.

7. **One save is one Lifecycle Repair Event.** The draft gains
   `corrected_starts`, every boundary the correction moved in Stage History
   order, and the timeline entry carries one `reasons` line per moved boundary.
   `repair_current` populates it with its single boundary, so the emitted payload
   for a single-stage repair is byte-for-byte what it was.

Refusal happens entirely before the persistence shell is entered, so the existing
atomic guarantee is unchanged: a contradictory set leaves the Plant untouched.

## Consequences

- The card needs no change. It already sends only touched fields, and the
  backend now accepts what the dialog produces.
- Calendar-day reasoning in the domain against full stored Lifecycle Timestamps
  (ADR-0013) is unchanged. The manager stamps the write seam's timestamp only on
  the boundaries the edit named; an untouched interval keeps the precision it was
  stored with, and the derived `end` values chain from the next interval's start.
- A reschedule of untrustworthy history rebuilds it from the supplied starts,
  which makes it a second route out of [[Unknown Stage]] — one that preserves
  more than `repair_current` does, when the grower supplies enough dates.
- `_lifecycle_compatibility_updates` now takes the projected history and the map
  of fields the edit stamped, rather than deriving both from a single target
  stage. The three projections (`_transition_history`, `_correction_history`,
  `_reschedule_history`) stay separate because they preserve stored precision by
  different rules.
- A reschedule that advances the Current Stage does **not** perform the placement
  side effects of a real transition (special growspace moves, harvest metrics) —
  consistent with the editor path's existing corrections, which have never moved
  a Plant between growspaces.

[card ADR-0018]: https://github.com/Venosta-web/lovelace-growspace-manager-card/blob/main/docs/adr/0018-lifecycle-timestamps-datetime-through-one-seam.md
