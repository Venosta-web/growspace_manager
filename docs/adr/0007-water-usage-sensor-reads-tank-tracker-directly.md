# ADR 0007 — WaterUsageSensor Reads TankWaterTracker Directly in Tank-Derived Mode

**Status:** Accepted

## Context

`WaterUsageSensor` reports cumulative water consumption for a growspace. It has always read from `WaterUsageData` (stored on the growspace model), which is updated by explicit watering events via `watering_service`.

When Tank-Derived Water Mode is active — a growspace has at least one tank with `volume_liters` configured and no `irrigation_flow_sensors` or `drain_volume_sensors` — no explicit watering events fire. Water consumption is inferred from tank level changes by `TankWaterTracker`, which accumulates events in `TankWaterHistory`. This meant `WaterUsageSensor` reported zero indefinitely in tank-derived mode.

Two approaches were considered for bridging the gap:

**Option A — Write-through:** When `TankWaterTracker` detects a consumption event, write the inferred liters into `WaterUsageData` (incrementing `total_liters` and appending to `daily_readings`).

**Option B — Read-through:** `WaterUsageSensor` detects tank-derived mode at read time and pulls directly from the qualifying `TankWaterTracker` instances instead of `WaterUsageData`.

## Decision

**Option B — read-through.** `WaterUsageSensor` checks the tank-derived condition on each read. When active, it sums consumption events across all qualifying trackers since `growspace.water_usage.cycle_start_date`. `WaterUsageData` is not written to in tank-derived mode.

## Consequences

- `TankWaterHistory` is the single owner of tank-derived consumption data. No duplication.
- If a grower adds flow sensors later (leaving tank-derived mode), `WaterUsageSensor` switches back to `WaterUsageData` automatically. The tank history is not cleared and remains available to `TankDerivedWaterSensor` and WebSocket analytics.
- `reset_water_tracking` works identically in both modes: it advances `cycle_start_date`, which acts as the filter anchor for the tank-derived sum. `TankWaterHistory` is never cleared on reset.
- `WaterUsageSensor` becomes mode-aware: it contains a branch on the tank-derived condition. This is the trade-off accepted over write-through's cleaner sensor logic.

## Why Not Write-Through

Write-through would pollute `WaterUsageData` with inferred measurements mixed alongside flow-sensor measurements, with no flag to distinguish them. If the grower later adds flow sensors, the historical entries in `daily_readings` would be a mix of sources. Resetting `WaterUsageData` on mode switch would lose data. Keeping `TankWaterHistory` as the authoritative source avoids all of this.
