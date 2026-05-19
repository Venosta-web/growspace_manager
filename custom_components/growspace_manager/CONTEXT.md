# Growspace Manager — Domain Glossary

## Growspace

A physical grow area (tent, room, shelf). Has a name, dimensions, a plant grid (`rows × plants_per_row`), and an `EnvironmentConfig` that links sensor entity IDs to it.

## GrowspaceType

An enum (`flower`, `veg`, `mother`, `dry`, `cure`, `clone`) that describes the dominant lifecycle phase happening in a growspace.

**GrowspaceType is derived, not configured.** For regular growspaces it is computed from the most advanced `PlantStage` found across all plants in that growspace, following the priority ladder:

```
cure > dry > late_flower > mid_flower > early_flower > mother > veg > seedling == clone
```

Exception: the canonical special growspaces (`mother`, `veg`, `clone`, `dry`, `cure`) are created with an explicit type via the internal `upsert_growspace` manager method and exist before any plants are added.

## PlantStage

The lifecycle phase of an individual plant (`seedling`, `clone`, `veg`, `flower`, `dry`, `cure`, `mother`). Determined by which start-date fields are set on the plant record (e.g. `flower_start` being set moves the plant into flower stage).

## Dominant Stage

The single `PlantStage` that wins when a growspace contains plants at multiple stages. Computed by `determine_coordinator_stage()` using the priority ladder above. Maps to the growspace's effective `GrowspaceType`.

## EnvironmentConfig

The set of HA sensor entity IDs linked to a growspace. Covers: temperature, humidity, VPD, CO₂, substrate temperature, soil moisture, feed EC, substrate EC, runoff EC, pH, drain volume, irrigation flow, power, energy, irrigation tanks, lights, fans, humidifier, dehumidifier. All sensor types can be linked to any growspace regardless of its `GrowspaceType`.

## Simulation Layer

HA `input_number` + `template sensor` entities used as stand-ins for real hardware sensors.

- **Demo simulation** (`growspace_demo.yaml`): dynamic sinusoidal variation for realistic Bayesian logic testing.
- **E2E simulation** (`growspace_e2e.yaml`): fully static pass-through sensors, prefixed `e2e_`, controllable from Playwright via `input_number.set_value` WebSocket calls.
