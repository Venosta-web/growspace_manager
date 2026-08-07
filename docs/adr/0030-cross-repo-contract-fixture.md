# ADR 0030 — Cross-repo contract fixture + GSM-first landing order

**Status:** Accepted (consumer side: lovelace card ADR 0029)

## Context

The dominant bug class of the last month (~10 incidents) was cross-repo payload
drift: a field added or changed on one side of the GSM ↔ card boundary silently
dropped at some hop — missing from a service schema (`lst_offset`), not persisted
(`control_humidifier`), absent from the WS view model (drying fields), or emptied
fields omitted from the save payload (the env-clear regression, card #439).
Nothing automated checks that what `presentation/` + `websocket/` emit matches
what the card's `api-schema.ts` parses; every drop was found by a human noticing
a value vanish.

Alternatives considered: a shared schema source of truth (JSON Schema / TypeSpec
generating both sides) — structurally correct but a multi-week two-repo migration
for a solo project; or relying on e2e round-trips — slow, main-gated, and blind to
fields the specs don't touch.

A second, related gap: cross-repo features landed in whatever order PRs got
merged, with "the card must stay safe against the released GSM" enforced only by
the maintainer's memory (the #522/#439 episode).

## Decision

1. **GSM owns a golden contract fixture.** A snapshot test serializes one
   **maximally populated** growspace — every optional sub-config set (AC Infinity
   bundles, grow light, exhaust, drain, notifications, tank, vision…) — to
   `tests/fixtures/contract/growspace_payload.json`. Any payload-shape change
   fails the test until the fixture is deliberately regenerated. Maximal
   population is the load-bearing property: every past drop-bug involved an
   *optional* field, so a sparse fixture would catch nothing.
2. **Card CI strict-parses the fixture** (unknown and missing keys both fail),
   fetched from **two refs**: GSM `prerelease` (leading edge) and the latest GSM
   release (what users actually run). See card ADR 0029.
3. **GSM-first landing order.** For any cross-repo feature, the GSM side merges
   to `prerelease` and ships in a GSM release **before** the card PR merges to
   `dev`. Sole exception: a card PR may land first if it is backward-safe against
   the released GSM — and the release-fixture parse passing *is* that proof,
   replacing the judgment call.

## Consequences

- Adding a payload field now requires touching the fixture — one deliberate extra
  step that converts "silently dropped" into "CI told me which side is behind."
- The fixture must be kept maximal as new sub-configs appear; a field added to the
  model but not to the fixture builder is invisible to the contract. The
  `gsm-field-roundtrip` checklist carries this as a station.
- Card PRs that move with an unreleased GSM change will fail the release-fixture
  check until GSM ships — that is the intended signal to hold the card merge, not
  a flake to bypass.
- The env-draft-seeder bug class (fields dropped on dialog reopen) is *not*
  covered here — a parse test cannot see dialog lifecycle. That net is the
  config-dialog round-trip e2e spec (card ADR 0025 amendment).
