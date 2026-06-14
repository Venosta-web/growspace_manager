# Lifecycle dates are datetime, written through one seam

A [[Lifecycle Timestamp]] (`seedling_start … cure_start` on `Plant`) is a timezone-aware **ISO 8601 datetime string** — date *and* time — at every layer: config-flow create, stage transitions, cloning, WebSocket update, and storage. Date-only (`YYYY-MM-DD`) is no longer a representation the system *produces*.

The decision the system makes about that representation lives in exactly one place: `to_lifecycle_timestamp(supplied)` in `domain/date_logic.py`. Given a supplied value (str / `date` / `datetime`) it preserves the moment; given `None` it defaults to `dt_util.now()`. It always returns an ISO datetime **string**. Every write site calls it instead of formatting inline.

## Why

The representation decision was duplicated across ~9 sites in two repos, each choosing independently — and they disagreed. The card rendered a `datetime-local` picker, validated that a time was present, then **truncated the time away** in `formatDateForBackend` before sending. The backend stored date-only from `DateSelector` create and `.date().isoformat()` transitions, but full datetime from the `mother_start` auto-set and from the WebSocket update path (`parse_date_field` → `setattr`). The result was a plant whose `*_start` fields mixed date-only and datetime depending on which code path last touched them, and a false "Set both date and time for lifecycle dates before saving" toast when the edit dialog re-validated untouched date-only fields against a stricter contract than create/transitions produced.

The `transition_date: date | None` parameter type made truncation structural, not incidental — the `date` type cannot carry a time, so every signature using it discarded one. Widening these to `DateInput` (str / `date` / `datetime`) and routing through the seam is what makes "datetime throughout" expressible.

## Decisions

- **Write seam.** All lifecycle-date writes go through `to_lifecycle_timestamp()`. Deleting it would re-scatter the `.date().isoformat()` choice across create / transition / clone / facade / WebSocket sites — which is exactly the bug surface it replaces.
- **Create flow captures time.** The config-flow `DateSelector()` for `veg_start` / `flower_start` becomes `DateTimeSelector()`, so datetime is captured at the first entry point rather than promoted later.
- **Model fields stay `str | None`.** The seam returns an ISO string and the update path stores the string (not a `datetime` object), closing the prior type-truth gap where fields annotated `str` held a `datetime` after an update. Storage stays JSON-clean.
- **No migration for existing data.** `parse_date_field` already promotes a legacy date-only value to midnight-local on read, and every consumer (day counts, calendar, sensors) reads through it. Old plants keep their date-only `*_start` string until next edited; new writes are full datetime. This is graceful read-time promotion — no migration pass, no downtime.

## Consequences

- `WeightEntry` / `MoistureEntry` `date` fields (drying observations) are deliberately **out of scope** — they remain date-only.
- A plant's stored `*_start` values may be mixed-representation during the transition period (old date-only, new datetime). This is intentional and safe because reads normalise; assertions in tests must not assume a uniform format for pre-existing fixtures.
- Paired with the card-side seam (`lovelace-growspace-manager-card` ADR-0018), which stops truncating and removes the now-impossible "set both date and time" validation.
