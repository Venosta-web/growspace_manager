# ADR 0001 — DryingData as a separate dataclass, not an extension of HarvestMetrics

**Status:** Accepted

## Context

Drying & Curing Tracking requires storing a time-series of weight readings and moisture readings on a Plant during the `dry` stage. The existing `HarvestMetrics` dataclass already lives on `Plant` and holds `wet_weight` and `dry_weight`.

Two options were considered:
1. Add `weight_log` and `moisture_log` directly to `HarvestMetrics`.
2. Create a new `DryingData` dataclass on `Plant`.

## Decision

Create a new `DryingData` dataclass on `Plant`.

## Rationale

`HarvestMetrics` holds final-outcome snapshots recorded at harvest (wet weight, dry weight, THC %). Adding in-progress time-series observations to the same class conflates two distinct concerns: "what was the harvest outcome" vs "what is happening during drying." A future reader would find it surprising that a class named `HarvestMetrics` contains a rolling daily log.

`DryingData` mirrors the existing pattern: `harvest_metrics: HarvestMetrics` on `Plant`. It defaults to empty lists and a `None` visual tag, making the entire feature opt-in with zero breakage for existing data.

## Consequences

- Existing `HarvestMetrics` remains clean as a final-outcomes model.
- New `Plant` storage format gains a `drying_data` key; a `__pre_deserialize__` migration default handles existing records.
- Any future drying-related fields (e.g. humidity log, temperature log) have a natural home in `DryingData`.
