---
status: accepted
---

# Reliability evidence exposes interruptions and observation coverage

Issue #796 asks growers to assess unattended control from durable evidence. During the design interview on 2026-09-30, the user agreed that irrigation operations must remain accountable across crashes: retain intent before actuation, recover interrupted operations explicitly, and expose outcomes that cannot be established. Persisting intent does not prove a physical action occurred. This strengthens the current reliability counters, whose writes coalesce for 60 seconds; the agreed accounting and recovery rules below reuse the existing Delivery Attempt and Safety Ledger models.

The user also agreed that unobserved time, including Home Assistant outages, remains explicitly unknown. Reliability reporting should expose observation coverage over elapsed time separately from armed-and-not-faulted availability during observed time. The current Automation Uptime percentage uses observed minutes as its denominator; presenting it alone can imply continuous reliability when only a fraction of the elapsed time was observed.

The agreed scope is to finish irrigation reliability and truthful reporting, including metered-water totals where delivery evidence exists and active-Grow-Run-at-start attribution. Climate automated runtime needs a separately tracked follow-up that defines controller-owned operation. Existing climate counters remain evidence; extending their runtime semantics is outside this scope.

Pump confirmation and water measurement are independent claims. The existing `completed_verified` export key remains compatible and means a pump cycle ran for its planned duration and read back OFF; documentation and user-facing labels must qualify that meaning. Metered water is reported separately. A blocked hose can satisfy pump confirmation without delivering water, so a verified cycle must never imply verified watering. This preserves ADR-0055's existing distinction.

Periodic counter persistence offers bounded storage and avoids delaying safety actions, but can erase evidence at the moment a crash occurs. Counting offline time as success or failure would invent an observation; excluding it without showing coverage conceals the gap. Those trade-offs motivate the agreed direction. The user confirmed the consolidated design on 2026-09-30. This ADR is accepted; the implementation verification obligations below remain to be fulfilled. The interview produced documentation; no controller changes have been made.

## Historical evidence and measurement precision

Existing totals remain available as legacy evidence, with a dated boundary identifying when the stronger guarantees begin. They cannot be retroactively certified crash-accountable. Observation coverage is reported from that boundary, and finalized Grow Run summaries retain their original meaning rather than being silently reinterpreted.

The agreed target is minute precision for the rolling 24-hour window and hour precision for the rolling 30-day window, with boundary approximation documented. These tighten the monthly window without retaining an unbounded event history; existing UTC calendar-day buckets remain legacy evidence and cannot be reconstructed at finer precision.

The existing accumulated sensor-loss figure is explicitly described as unavailable sensor-minutes. A separate growspace duration counts each observed interval with at least one required control sensor unavailable once, regardless of overlapping outages.

Absent metered evidence is reported as not recorded, never as zero delivered water. Once measurement exists, measured litres are accompanied by measurement coverage. Reading meters is an accepted but unimplemented part of ADR-0064 in the inspected base; implementing that producer remains a separate prerequisite, and runtime estimates never substitute for it.

## Durable accounting and ownership

Counters are projections of durable accounting facts with stable identities, applied exactly once. Delivery Attempts and safety facts are reused as sources; pending accounting normally remains available until the corresponding totals are durably committed, then can be pruned, subject to the explicit bounded-capacity policy below. The retained Safety Ledger ring is not a sufficient lifetime replay source. A missing terminal observation remains unresolved rather than being guessed as a completion. The implementation must commit totals and their deduplication checkpoint atomically. Pending accounting is compacted where doing so preserves its meaning. If its hard limit is still reached, reporting exposes an explicit evidence gap and incomplete totals rather than silently dropping facts or blocking safety actions. Exact guarantees apply only where accounting continuity is established. This deliberately qualifies the normal retain-until-committed rule; the concrete representation and capacity are implementation details to validate against the supported scale envelope.

Failure to persist required delivery intent prevents ON, preserving the current safety boundary. Failure to update reporting instead marks reliability evidence incomplete and raises a diagnostic fault; it does not itself gate irrigation. Neither path may delay emergency OFF. A diagnostic fault here describes reporting integrity and must not silently become a latched controller Fault that changes actuation eligibility.

An operation belongs to the Grow Run active when it was requested, and subsequent outcomes retain that ownership. Requests without an active Run remain Unattributed Activity. Existing finalized summaries retain their recorded meaning. Finalization is refused while the Run has open operations or uncommitted accounting. A recovered operation explicitly closed with an unresolved outcome may be frozen as unknown. Completing a Run remains possible; freezing its reliability summary waits for accounting to settle. Attribution must be retained with the operation so crossing completion or starting another Run cannot transfer ownership.

The export advances to schema version 2, retaining existing counter names and adding explicit measurement status, observation coverage, window precision, and guarantee boundaries. Version 1 exports and existing frozen Run summaries remain readable under their original definitions. The Grow Run reliability definition also needs its own version so a new export schema cannot silently reinterpret an old snapshot.

## Sharing and follow-ups

The user-initiated shareable export contains aggregate counters, measurement status, coverage, precision, and integrity metadata. It omits operator identities and raw operation records; growspace and actuator identifiers are replaced with export-local aliases. Local diagnostics retain original identifiers. No evidence is automatically sent anywhere. Export schema version 2 documents the aliasing so retaining counter names does not imply retaining raw actuator identifiers in open-family suffixes.

| Follow-up                 | Boundary                                                                                                                       |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Climate automated runtime | Separately define controller-owned operation and runtime provenance; preserve current climate evidence without relabelling it. |
| Metered delivery producer | Implement the accepted ADR-0064 metering design separately; until then, measured water is not recorded.                        |

## Implementation verification obligations

- Prove persisted pre-actuation ownership, crash recovery with unknown outcomes, and idempotent application of accounting across repeated crashes and reloads.
- Prove atomic totals/checkpoint persistence and that compaction, overflow, corruption, and unavailable storage never invent complete evidence or delay emergency OFF.
- Distinguish observed runtime from recovery-time bounds or estimates. Unobserved intervals are unknown, not reconstructed from a planned duration.
- Exercise overlapping sensor outages, observation gaps, rolling-window boundaries, historical precision, and legacy guarantee boundaries.
- Exercise request-time Run attribution across completion, absent Runs, pending finalization, unresolved recovered outcomes, and old frozen reliability definitions.
- Document and verify export v2 status semantics and aliases; preserve interpretation of v1 and assert that the shareable document contains no operator identities or raw operation records.

These are obligations for a subsequent implementation, not evidence that the current code satisfies the strengthened design.
