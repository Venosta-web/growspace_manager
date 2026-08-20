# ADR 0005 — `get_data` Decomposition and Component–Card Contract Hardening

**Status:** Accepted

## Context

The `get_data` WebSocket command returns a flat dict of 70+ fields assembled from three sources: explicit keys, a `**biological_metrics` spread, and a `_get_environment_attributes()` update. The frontend `GrowspaceAdapter` reads all fields directly from the flat shape. As the integration grew to 35+ commands and 40+ services, the implicit contract accumulated: no build-time validation, scattered field transformations, opaque error codes, and a 30-second stale-data window after mutations.

Issue #382 defined five hardening initiatives. This ADR records the key design decisions made during planning.

## Decisions

### 1. `get_data` decomposition is a breaking change

The `get_data` response shape is replaced in a single coordinated deploy across both repos. No parallel `get_data_v2` command. The frontend adapter and Zod schemas are updated at the same time as the backend payload.

**Why:** A parallel command would require both shapes to be maintained indefinitely and would leave the old flat adapter in place, defeating the purpose of decomposing. Since both repos are deployed together, a clean break is feasible.

### 2. Six sub-objects, not five

The PRD proposed `identity`, `grid`, `environment`, `irrigation`, `metrics`. We use **six**: `identity`, `grid`, `environment`, `sensors`, `irrigation`, `metrics`.

`sensor_types`, `sensor_coordinates`, and `sensor_groups` are extracted into a dedicated `sensors` sub-object rather than included in `environment`. These are lookup maps consumed exclusively by the 3D scene renderer — they are not environment state.

`energy_tracking` belongs in `metrics` (whole-growspace power usage, not watering lifecycle data) rather than `irrigation`.

### 3. Typed error codes stay inside HA's wire format

`connection.send_error()` already produces `{ success: false, error: { code, message } }`. The typed `ErrorCode` enum (`coordinator_not_ready`, `entity_not_found`, `validation_failed`, `internal_error`) is a TypeScript type-layer artifact only. The Python side standardises the string values passed to `send_error()`; `base-api.ts` narrows the thrown error by code. No `{ ok: bool }` wrapper is added to the result body.

**Why:** Wrapping errors as `success: true` with `{ ok: false }` in the body would be non-standard, break HA's own error-handling conventions, and require every API client to add an `ok` check on top of the existing try/catch.

### 4. Six focused sub-adapters, no wrapping `mapResponseToFrontend()`

The `GrowspaceAdapter` is split into six sub-adapters (one per sub-object). There is no single `mapResponseToFrontend()` entry point — that would just be a pass-through adding indirection. For the outbound direction, `mapPayloadToBackend()` is only written after auditing all 11 remaining API clients; if only one method in one file does manual camelCase→snake_case translation, the abstraction is not warranted.

### 5. Snapshot tests cover query commands only

Of the ~35 WebSocket commands, only query commands (~15–18) get snapshot tests. Mutation commands get cache-invalidation tests instead — their responses are empty or trivial and snapshotting them adds no contract value. Fixture files live in the backend repo and are copied into the frontend CI pipeline.

### 6. Cache invalidation via backend decorator, not frontend `SyncService` wiring

The 30-second TTL cache in `view_model_builder.py` is explicitly invalidated on mutation via a decorator or post-mutation hook on the backend. `SyncService.refreshGrowspaceData()` is not wired into the API clients. The existing HA entity-state push already triggers `updateHass` → refresh on the frontend; explicit post-mutation refresh is only added to `base-api.ts` if the entity-push latency proves to be a real problem.

**Why:** Injecting `SyncService` into all API clients creates a dependency inversion and requires changes to all 12 clients. The backend-side cache bust + entity push is sufficient and requires no frontend architecture changes.
