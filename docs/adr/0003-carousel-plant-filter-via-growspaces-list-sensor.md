# ADR 0003: Carousel active-growspace filter reads plant counts from `sensor.growspaces_list`

**Status**: Accepted

## Context

The carousel card needs to know which growspaces have `total_plants > 0` so it can skip inactive ones when `filter_empty` is enabled. The card already subscribes to `sensor.growspaces_list` (via `GrowspaceOptionsController`) to populate the editor dropdown; that entity currently exposes only `{id: name}` per growspace.

Three alternatives were considered:

1. **Extend `sensor.growspaces_list`** — add `total_plants` to each entry's attribute value. No new subscription, no new entity; the card reads what it already receives.
2. **WebSocket subscription in the carousel** — subscribe to full growspace data the way the inner manager card does. No backend change, but the carousel becomes significantly heavier and duplicates the manager card's data pipeline.
3. **New `sensor.growspaces_overview` entity** — a dedicated diagnostic sensor with full per-growspace metadata. Clean separation but adds a permanent HA entity whose only consumer is this one card feature.

## Decision

Extend `sensor.growspaces_list` attributes from `{id: name}` to `{id: {name, total_plants}}`. The frontend reads `total_plants` from the attribute it already subscribes to.

## Consequences

- The attribute shape of `sensor.growspaces_list` is now a breaking change surface. Any external automation or template that reads `sensor.growspaces_list.attributes.growspaces` and assumes string values will break. Backwards-compatibility shim: if the card receives a string value for a growspace entry, it treats it as `{name: value, total_plants: 0}`.
- `GrowspaceOptionsController` must be updated to parse both the old and new attribute shape.
- No new WebSocket subscription or HA entity is introduced. The carousel remains a lightweight consumer of existing state.
