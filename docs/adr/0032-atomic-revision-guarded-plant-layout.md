# Commit plant layouts atomically behind a layout revision

Guided Arrange keeps a complete Plant Layout local until Done, so the integration will expose one revision-guarded command rather than replaying the existing move and swap operations. The command accepts a growspace, its expected Layout Revision, and the complete plant-to-cell mapping; under one lock it validates membership, bounds, uniqueness, and revision equality, then persists every position and advances the revision as one unit. Any validation or persistence failure changes nothing, and a stale revision returns a distinct conflict result. This preserves honest Cancel semantics and prevents a delayed arrangement from overwriting layout changes made by another session.

Existing growspaces begin at revision `0`. Every add, remove, move, swap, or transplant advances the affected growspace revision under the plant-manager lock; a transplant advances both source and destination. A successful complete-layout commit emits one [[Plant Layout Changed]] event with the new revision and refreshes the plant projections, rather than emitting a sequence of move/swap events. The view-model contract advertises the revision and atomic-layout capability so older integrations cause the card to withhold Arrange instead of falling back to immediate writes.

Changing grid dimensions also advances the revision. A dimension reduction that would strand a plant is rejected unless the same atomic command supplies a valid complete layout. The manager validates and persists against a staged copy and publishes the new state, revision, projections, and event only after persistence succeeds; otherwise it restores the exact pre-command state before releasing the lock.

The WebSocket command is `growspace_manager/set_plant_layout`. It accepts `growspace_id`, `expected_layout_revision`, and `placements: [{ plant_id, row, col }]` using the existing backend coordinate convention. The mapping must contain exactly one placement for every current plant and no others. Success returns the authoritative `growspace_id`, `layout_revision`, and `placements`; a no-op returns the current revision and mapping without an event or revision increment. Each serialized growspace advertises `layout_revision` and `capabilities.atomic_plant_layout` so the card can capability-gate Arrange.

## Considered Options

- Replaying individual move and swap calls was rejected because partial failure makes the original layout impossible for the card to restore reliably.
- Comparing individual plant timestamps or a client-computed hash was rejected because neither is the authoritative revision of the complete growspace layout.
