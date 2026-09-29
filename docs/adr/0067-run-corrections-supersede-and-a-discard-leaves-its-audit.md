# Run Corrections Supersede, and a Discard Leaves Its Audit

**Status:** Accepted (builds on [ADR-0033](./0033-finalized-grow-runs-survive-source-deletion.md) and [ADR-0034](./0034-grow-runs-own-durable-historical-summaries.md); #917)

The Grow Run MVP (#797) pulled two commands forward from #674 so that a finalized mistake is never permanent: [[Run Reopening]] and [[Activity-free Discard]]. The glossary already fixed their outline — reopening is an administrator's audited return to Completed with a reason, and only an Active Run with nothing attributed may be discarded — but not three things this decision settles.

1. **A reopened Run's snapshot is superseded, never edited or dropped.** Reopening moves the Run Finalization Snapshot into `superseded_snapshots` on the Run, whole, with the Run Revision its finalization produced and the one the reopening produced. The next finalization freezes a new snapshot beside it. An export or an audit can therefore always say what a comparison read before the correction, and the Run Audit Entry at `superseded_revision` says who reopened it and why. Clearing the snapshot and refreezing would have been simpler, but the frozen values would then be silently different after a round trip — exactly the silent mutation ADR-0033 rules out.

2. **Discarding is a Growspace controller's command, not an administrator's.** Run Lifecycle Authorization reserved reopen, void, correction and purge for administrators because each one rewrites or removes history. A discard can only remove a Run that holds no history: the domain refuses one with a movement fact (projected, or still in the Plant outbox naming it), a Participant who joined after or left from the opening set, or a harvest outcome (recorded, or a live Plant naming it as Harvest Source Run), and says which in the refusal's `reasons`. What remains is the undo of a start, and whoever may start a Run may take the start back. The reason is optional for the same reason; reopening keeps it required.

3. **A discarded Run leaves the ledger, but not without trace.** Its Sequence Number stays spent (`next_sequence` does not move back), and the ledger keeps a `discarded` record — Run ID, Sequence Number, start, and the Run's audit ending in the discard. `list_grow_runs` and `get_grow_run` no longer name it, the lifecycle event reports its status as `discarded`, and the logbook line carries the reason. The Unattributed Activity Ledger takes back what the start took: the `covered_since` the start ended, kept on the Run as `prior_coverage`, and a backdated start's claimed days. The days the Run was Active are **not** filled in. Nothing observed them for the Unattributed Activity Ledger, and ADR-0036 keeps what it did not see as `not_observed` rather than inferring it; a Run started before this change, with no `prior_coverage`, resumes coverage from the discard.

## Considered options

- **Discard as a Voided Run.** Rejected: Voided is a retained, visible state excluded from comparison, meant for a Run that did happen and is invalid. An empty Run never happened, and keeping it visible would clutter the Run list with starts nobody meant.
- **Synthesizing Daily Summaries for the discarded Run's days.** No movement fact means the population did not change, so the Plants standing each day are knowable. Rejected anyway: a Daily Summary also asserts that Home Assistant observed the Growspace that day, which is what the `not_observed` gap reason — and every later metric's coverage — depends on.

## Consequences

- The card's contract grows `reasons` on every Run refusal (empty unless there are several causes), `reason` on every Run Audit Entry and `superseded_snapshots` on `get_grow_run`; all three are declared optional in the card so it accepts either backend.
- Void, Purge Run History, Run Boundary Correction and Harvest Attribution Correction remain in #674.
