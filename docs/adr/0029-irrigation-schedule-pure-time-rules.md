# 0029. Irrigation Schedule owns the time-schedule rules

Date: 2026-07-07

## Status

Accepted

## Context

Candidate 2 of the 2026-07-05 architecture review targeted the
"IrrigationCoordinator scheduling brain". By the time it was worked, the big
brains were already behind domain seams: the Steering Phase Machine
(ADR-0023) with the VWC coordinator as its effects shell, and the Pump Cycle
Gate / Shot Composer (ADR-0021) with `_run_pump_cycle` as theirs.

What remained inline was the base time-schedule logic, scattered across four
coordinator methods with the `"HH:MM[:SS]"` parse duplicated three times:
add-item validation, listener registration, dedup, and next-occurrence
projection. The duplication had already produced a live bug: the add path
normalized `"08:00"` to `"08:00:00"` before storing, but the remove path
compared the raw input string — so `remove_irrigation_time` with `"08:00"`
silently removed nothing.

## Decision

`domain/irrigation_schedule.py` (the EC State / Pump Cycle Gate mould: pure,
no `hass`) is the one owner of what a schedule time *is* and how the
schedule lists change:

- `normalize_schedule_time` — strict, for writes; raises `ValueError`.
  Shared by add and remove, so they cannot disagree about time identity.
- `parse_stored_time` — lenient, for reads; `None` on malformed entries.
- `upsert_item` / `remove_items` — pure list operations returning a
  `ScheduleChange` (new list + updated flag / removed count).
- `schedulable_events` — dedup (keyed on the *parsed* time, so a legacy
  `"08:00"` and a normalized `"08:00:00"` cannot register twice) plus the
  valid/malformed split the shell logs.
- `next_occurrence` — soonest future occurrence, rolling past times to
  tomorrow.

The coordinator keeps the effects: `async_track_time_change` registration,
save/reload, task management, logging.

## Consequences

- Removing `"08:00"` now matches the stored `"08:00:00"` (bug fix). An
  invalid time on remove now raises `ValueError` like add, instead of
  silently matching nothing.
- The broad `try/except` swallow in `async_remove_schedule_item` is gone;
  programming errors bubble.
- Schedule semantics are unit-tested with plain values in
  `tests/domain/test_irrigation_schedule.py`; coordinator tests shrink to
  wiring.
- This closes candidate 2 as re-scoped: no further "scheduling brain"
  extraction is pending for the base coordinator — future reviews should
  not re-suggest extracting `_run_pump_cycle` or the listener wiring, which
  are deliberate effect shells (ADR-0021/0023 precedent).
