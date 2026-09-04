# 46. Irrigation Change — one write seam for irrigation configuration

Date: 2026-09-03

## Status

Accepted

## Context

Writing a growspace's irrigation settings used to mean knowing which writer you
were standing in. The settings action, the strategy action and the options flow
each did their own field mapping, their own normalization, their own
`setattr`-in-place, and their own save/refresh; ADR-0012's Steering Mode stamp
did the same again through a separate `StrategyStamp` shell. The interface of
"change irrigation" therefore included the writer's private conventions, and
its bug class was structural rather than incidental:

- **Validation ran on the payload, not on the result.** Volume Mode's
  prerequisites and the Pore EC Target Band's ordering are properties of the
  *post-change* state, so a sparse edit could remove a prerequisite the change
  itself never mentioned.
- **A write was not atomic.** Fields were assigned onto the live models one at
  a time, so a persistence failure left the growspace running a half-applied
  change no rollback undid.
- **The stamp narrated before it happened.** `StrategyStamp` fired the
  Steering Mode logbook entry before `async_commit`, so a failed save left a
  logbook line asserting a mode the growspace was not steering.

Issue #710 replaced the three patch writers with one `Irrigation Change` seam.
This ADR records the seam's completed shape, once clearing and the Steering
Mode stamp joined it (#711).

## Decision

**One function — `async_apply_irrigation_change` — performs every irrigation
configuration write.** It owns canonical field ownership, normalization,
post-change validation, the atomic swap of both models, persistence ordering,
rollback and the immutable `IrrigationChangeResult`. Transports translate their
input and present failures; they hold no write rules.

### Three operations, one tail

Operations differ only in how the candidate state is *resolved*:

| operation | resolves to |
|---|---|
| **patch** (`settings`, `strategy`, `options`, `steering_phase`) | the sparse fields the grower edited, normalized from the transport's compatibility spellings |
| **clear** | a default `IrrigationConfig`, with the strategy disabled |
| **Steering Mode stamp** | the preset the server's table gives for (named mode × stored media type × active Shot Sizing Mode), plus the mode recorded as declared intent |

Everything after resolution is identical and lives once: validate the complete
candidate → swap both models → invalidate → commit → *then* narrate → refresh.
A commit failure restores the prior models and returns, so a refused write
leaves neither changed state nor a logbook entry claiming it happened. Ordering
the logbook after the commit is the point of moving the stamp here.

### Clear resets the whole config

A clear names no setpoint — sending one is refused, because a caller spelling
out values has confused a reset with a patch. It restores the entire
`IrrigationConfig`, schedules and per-stage EC target ranges included: times
pointed at a pump that is no longer configured are not a setting worth keeping.
It disables the strategy rather than resetting it, so the grower's tuning
survives being switched off, with one exception — `shot_sizing_mode` returns to
Seconds, because Volume Mode is defined by a pump flow rate and a substrate
profile, and the clear has just taken the flow rate away. Every other operation
is refused for leaving a growspace in Volume Mode with no way to size a shot;
a clear must not create that state by the back door.

### A Steering Mode is named, never spelled out

The stamp accepts one field, `steering_mode`. The media column and the
representation come from the growspace's own stored state, not the payload, so
no transport can stamp a mode against a medium the growspace is not in or write
the sizing representation the coordinator is not reading. Preset values
themselves are unwritable through this operation; a grower who wants a
different number edits the ordinary strategy field afterwards, exactly as
ADR-0012 intends. The stamp always writes — re-selecting the declared mode is
"reset to this mode's defaults" — while the result reports only the fields that
actually differ.

### Retained public adapters

No public command name or payload changed. `set_irrigation_settings`,
`set_irrigation_strategy`, `set_steering_phase`, `apply_steering_mode` and the
irrigation options flow all remain, now as thin adapters. Clearing gained the
one new adapter, `clear_irrigation` — the irrigation counterpart of
`remove_environment`, which by contrast is documented as deliberately bypassing
its own patch seam. This one does not.

### What stays outside

The seam writes irrigation **configuration**. It is not a general irrigation
API, and these deliberately keep their own owners:

- schedule collections (`add`/`remove_irrigation_time`, `add`/`remove_drain_time`)
- per-stage EC target ranges (`set_ec_target_range`)
- Drain Monitoring configuration and drain readings
- runtime cycles (`run_irrigation_cycle`) and the steering tick
- water tracking and irrigation analytics

Each is a collection or a runtime action rather than a sparse edit to the two
configuration models, and folding them in would buy a shared name for
operations that share no rule. `IrrigationConfig` still *holds* the schedule
and EC-range collections, which is why a clear resets them and why no patch
operation may write them.

The [[Irrigation Recipe]] and [[Irrigation Program]] stamps (ADR-0045) remain
on `StrategyStamp`. They resolve a mapping from stored recipes rather than from
a server-owned table, and moving them is a change to recipe semantics, not to
this seam; until then they keep the pre-#711 effect ordering.

## Consequences

- Adding an irrigation configuration field means adding it to the model and to
  one ownership set; every transport gets it, and no transport changes.
- A field absent from both ownership sets is now refused by name rather than
  silently dropped — which is the intended behaviour, and does mean a payload
  that used to be quietly ignored is now an error the caller sees.
- A Steering Mode stamp is atomic and validated like any other change: it
  cannot produce an invalid Pore EC band or survive a failed save.
- `clear_irrigation` is new public surface. Nothing calls it from the card yet;
  it exists so the reset gesture has one honest implementation rather than
  being open-coded the first time a caller needs it.
- Two stamp seams coexist until recipes move. That is a known, bounded
  duplication, recorded here so the next reader does not have to rediscover
  which one is canonical: this one is.
