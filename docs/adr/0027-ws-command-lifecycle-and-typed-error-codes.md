# 27. WS Command Lifecycle and typed error-code completion

Date: 2026-07-06

## Status

Accepted

## Context

The WebSocket package was already half-deep: registration is table-driven
(each module exposes a `COMMANDS` tuple consumed by one loop), every handler
is wrapped by `handle_ws_errors`, and coordinator resolution is one call
(`GrowspaceCoordinator.get_for_service_call`). What remained shallow:

- Every one of the 66 handlers carried the `(hass, connection, msg)` plumbing
  and its own `connection.send_result(msg["id"], payload)` — so every handler
  test needed a mock connection and asserted on `send_result` calls. The
  connection mechanics were part of every handler's interface without ever
  varying.
- ADR-0005's typed error-code contract was implemented on the card
  (`errors.ts` types `coordinator_not_ready` / `entity_not_found` /
  `validation_failed` / `internal_error` / `rate_limited` and coerces unknown
  codes to `internal_error`) but only half on the backend: it sent
  `unknown_error` instead of `internal_error`, never sent `entity_not_found`
  or `coordinator_not_ready`, and grew five ad-hoc codes (`invalid_args`,
  `not_loaded`, `ai_error`, `seedfinder_unavailable`, `fetch_failed`) —
  mostly inline `connection.send_error` calls bypassing the decorator — which
  the card silently flattens to `internal_error`. Not-found and retry-later
  UX distinctions died on the wire.

## Decision

1. **Payload-returning handlers.** A WS handler is
   `(hass, coordinator, msg) → payload | None`. The registration wrapper in
   `websocket/_common.py` owns the whole lifecycle: resolve coordinator →
   execute → `send_result` → error map. Handlers never see the connection
   (verified: no handler uses it beyond send_result/send_error today). The
   handler's return value is the test surface.
2. **Declarative command table.** `COMMANDS` entries become `WSCommand`
   records: `(type, handler, schema, resolve="targeted"|"any", sync=False)`.
   `targeted` resolves via `get_for_service_call(hass, msg)`; `any` via
   `get_any(hass)` (global commands: strain library, genetics, nutrients,
   lineage). Sync reads keep a `@callback` wrapper path.
3. **Backend adopts ADR-0005's error vocabulary** (the card moves zero lines):
   `unknown_error` → `internal_error`; new typed exceptions produce the
   missing codes — `EntityNotFoundError` → `entity_not_found`,
   `CoordinatorNotReadyError` → `coordinator_not_ready`, `RateLimitedError` →
   `rate_limited`. The ad-hoc codes are retired: inline `send_error` calls
   become raises mapped by the shared table.
4. **Typed exceptions subclass the existing hierarchy**
   (`EntityNotFoundError(ServiceValidationError)` etc. in `exceptions.py`),
   so the service-call path keeps today's behaviour unchanged — only the WS
   error map distinguishes the subclasses.

## Consequences

- Handler tests assert on returned payloads / raised exceptions; no mock
  connections. The lifecycle wrapper is tested once.
- Adding a WS command = one handler function + one `WSCommand` row; the
  lifecycle, error semantics, and resolution mode are inherited, not
  re-implemented.
- The card's not-found / retry-later narrowing becomes reachable; nothing on
  the wire changes shape except error `code` strings, which the card already
  types or coerces.
- The `test_core_init` hardcoded command count (67) is unaffected — no
  commands are added or removed.
