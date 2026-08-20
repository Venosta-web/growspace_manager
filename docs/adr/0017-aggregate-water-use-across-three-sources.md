# ADR 0017 — Aggregate Water Use Across Manual, Tank-Derived, and Pump-Cycle Sources

**Status:** Accepted (supersedes part of [ADR-0007](./0007-water-usage-sensor-reads-tank-tracker-directly.md))

## Context

A growspace can receive water three ways, each tracked differently:

| Pathway | How volume is known | Where stored | Persisted |
|---|---|---|---|
| **Manual / explicit watering** (`watering_service.async_water_plant`) | caller passes liters | `WaterUsageData.total_liters` + `daily_readings` | yes |
| **Tank-derived inference** (`TankWaterTracker`) | Δ tank-level % × `volume_liters` | `TankWaterHistory` events | yes |
| **Pump-cycle irrigation** (time-based + VWC/crop-steering) | pump runtime × `pump_flow_rate_ml_per_sec` | `_volume_dispensed_today` (in-memory, daily-cap only) | **no — resets on restart** |

Two consumers needed a single "water use" number but each was wrong:

- The **briefing KPI** (`briefing_scheduler._collect_kpis`) read `getattr(water_usage, "total_water_l", 0.0)` — a field that does not exist (`WaterUsageData` has `total_liters`). The KPI returned `0.0` unconditionally for every grower.
- The **`WaterUsageSensor`** correctly branched manual vs tank-derived (per ADR-0007) but knew nothing about pump-cycle volume, so a pure crop-steering grower with a pump and no tank also saw zero.

There is no documented "flow-based water use." No code converts an `irrigation_flow_sensor` reading into liters; the flow-sensor config is only a *gate* that disables Tank-Derived Water Mode.

## Decision

Define one canonical per-growspace figure, computed by a **single shared helper** that every consumer (`WaterUsageSensor`, briefing KPI, AI context, Tank-Derived Water Chip payload) calls:

```
water(growspace) = manual + (tank_derived  if tank-mode
                             else pump_estimate)
```

1. **Precedence between measurement sources.** Tank-derived and pump-cycle describe the *same physical water* whenever a pump draws from a monitored tank (tank mode gates on the absence of flow/drain *sensors*, but pump volume comes from a config flow-rate, not a sensor — so both can fire). They are therefore mutually exclusive: **tank-derived wins when the growspace is in Tank-Derived Water Mode; pump-estimate is the fallback otherwise.** Never summed.

2. **Manual is always added on top** of the chosen measurement source — including in tank mode. This catches the grower who hand-waters from a *separate* source (watering can) that the tank never sees.

3. **Pump-cycle volume is persisted write-through into `WaterUsageData`**, exactly like manual watering: a fired pump cycle bumps `total_liters` and appends to `daily_readings`. Each daily reading carries a **`source` tag** (`"manual"` | `"pump_estimate"`). The write is **gated on the growspace not being in Tank-Derived Water Mode**, so tank-measured water is never also written as a pump estimate.

4. **Window.** The KPI and the AI summary line report **today** (calendar day, local midnight) — the only window all three sources answer cleanly and the one a daily briefing needs. The shared helper exposes both *today* and *since cycle start*, so `WaterUsageSensor.native_value` keeps its since-`cycle_start_date` semantics ([[Water Usage Cycle]]) while the KPI/chip/AI use today.

## Consequences

- One definition of "water use" across sensor, chip, KPI, and AI. Fixing the KPI's phantom field and unifying the rule happen in one motion.
- **Pump-cycle volume now survives restart**, because it lands in the persisted `WaterUsageData` rather than the in-memory cap counter.
- The `source` tag answers ADR-0007's objection to write-through (mixed measurements "with no flag to distinguish them"). Tank-derived stays read-through per 0007; only pump-cycle is written through, and only outside tank mode.
- **Accepted trade-off:** in Tank-Derived Water Mode the figure is now tank-derived **+ manual**. If a grower hand-waters *from the monitored tank*, that water is counted twice (once as the tank-level drop, once as the manual event). This deliberately reverses ADR-0007's tank-derived-alone rule, chosen because the separate-source watering case is judged more important to capture than the in-tank hand-water case is to avoid.

## Why Not

- **Plain sum of all three** — double-counts a pump drawing from a monitored tank.
- **Strict precedence (one source wins, manual not added)** — undercounts hand-watering that runs alongside automation.
- **Leave pump volume ephemeral / read-time only** — a restart silently zeroes a grower's day, reproducing the bug being fixed. Recomputing liters retroactively is impossible: no persisted per-shot volume log exists.
- **A new dedicated pump-volume store** (parallel to `TankWaterHistory`) — duplicates the rolling-window + serialization cost when `WaterUsageData.daily_readings` already does the job once a `source` tag is added.
