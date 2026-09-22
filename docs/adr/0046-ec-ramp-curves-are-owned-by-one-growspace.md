# EC ramp curves are owned by one growspace

**Status:** Accepted

Decided in
[workspace#108](https://github.com/Venosta-web/growspace_manager_workspace/issues/108),
which found that no `ECRampCurve` had ever driven the [[Active Feed EC Target]].

Two defects sat on top of each other. The live one was a call-path misalignment:
`services/ec_ramp.py` called `ConfigFacade.save_ec_ramp_curve` by keyword with
`name, stage, points, curve_id`; the facade's signature had no `stage` at all,
began with `growspace_id`, and ended in `**kwargs`, so `stage` was swallowed and
dropped while `growspace_id` arrived `None` and took a legacy branch that picked
an arbitrary growspace; the facade then called the manager **positionally**
against a differing signature. Every curve was stored with a growspace id as its
`name`, the grower's typed name as its `stage`, and the grower's chosen stage
gone. Because feed-EC resolution matches `curve.stage` against a canonical stage,
it could never match, and feed EC silently fell through to `ECTargetRange` in
every install. The tests missed all of it by replacing the facade method with an
`AsyncMock`.

Underneath was the design question ADR-0045 had already flagged: a curve had no
growspace binding at all. `resolve_active_feed_ec` took the first curve whose
stage matched, in dictionary insertion order, so with two flower curves
configured, which one drove a growspace was an accident.

## Decision

**A curve is owned by exactly one growspace, and a growspace has at most one
curve per stage.** `ECRampCurve` stores `growspace_id`; `active_curve_for` in
`domain/ec_state.py` is the single owner of curve selection and is a lookup on
`(growspace_id, stage)`, not a choice; `async_save_ec_ramp_curve` refuses a
second curve for a `(growspace_id, stage)` the growspace already covers rather
than storing a pair whose precedence would be an accident.

The facade signature names every parameter the manager names, requires them all,
carries no `**kwargs`, and calls the manager by keyword. A caller that passes a
name the facade does not have now raises `TypeError` at the call rather than
silently dropping the grower's data. That property, not the specific argument
list, is what this ADR is protecting.

### Ownership rather than ADR-0045's by-reference binding

ADR-0045 bound an [[Irrigation Program]] to a growspace by an explicit
`irrigation_program_id` on the growspace, keeping programs a portable global
library, and it cited `ECRampCurve` as the implicit-binding footgun not to
repeat. The binding _is_ explicit here; what differs is which object holds it.

An Irrigation Program covers a whole run — `(stage, week)` slots across every
live stage — so one id on the growspace is a complete binding that stays correct
as the run advances. An `ECRampCurve` covers **one stage**. A single
`ec_ramp_curve_id` on the growspace would therefore go stale the moment the
growspace transitions from veg to flower: the bound veg curve stops applying, and
feed EC silently falls back to `ECTargetRange` — reproducing the exact failure
shape this ADR exists to remove, and requiring a grower gesture at precisely the
moment the grower is thinking about something else. Ownership makes the
transition free: the growspace's own flower curve applies because the growspace
already owns it.

The cost is that a grower running three tents on the same ramp keeps three
copies. That is real but recoverable — a copy-to-growspace gesture can be added
later without changing the storage shape — whereas a binding that silently
detaches on a stage change is not recoverable by the grower, because nothing
tells them it happened.

Ownership also makes the whole system agree by construction. `ECTargetRange`,
the fallback the curve outranks, already lives on the growspace's
`IrrigationConfig`. A global curve and a per-growspace fallback in one resolution
rule is what let the ambiguity exist.

## Unmigrated curves are surfaced, never rewritten

The facade was the only writer, so **a stored curve with an empty `growspace_id`
is unmigrated** — exact, with no heuristic and no false positives. Such a curve
matches no growspace in `active_curve_for` and stays inert, which is not a
regression: its garbage `stage` already matched nothing.

`ec_ramp_migration.py` raises a create-or-clear repair issue per unmigrated
curve, following `exhaust_migration.py` (ADR-0019). It does not repair the data.
Two of the three fields could be un-shuffled — `growspace_id` from the corrupt
`name`, `name` from the corrupt `stage` — but the grower's stage was never
written to storage and cannot be reconstructed, and a curve with no stage drives
nothing. Repairing the recoverable fields would produce a curve that looks
correct in the list and still silently does nothing, which is the failure mode
this ADR is removing. One re-save from the EC Ramp tab restores all three fields
at once, and the repair clears itself when it does. The ramp points, the only
data the grower cannot retype from memory, were never corrupted.

## Consequences

- `growspace_manager.save_ec_ramp_curve` requires `growspace_id`. This is a
  breaking service-contract change: the card must ship the matching payload in
  the same release, and a hand-written automation calling the service fails
  loudly with a validation error rather than storing a curve that does nothing.
- `ConfigFacade.remove_ec_ramp_curve` drops the `growspace_id` parameter it
  accepted and ignored; a curve id already identifies exactly one curve.
- The `ECTargetSensor` and the feed-target seam resolve through the same
  `active_curve_for`, so the sensor cannot display one growspace's curve while
  the feed target resolves another's.
