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

## IrrigationStrategy

Configuration for VWC-based crop steering. Lives on `Growspace` alongside `EnvironmentConfig`. Key fields: `enabled`, `lights_on_time` (user-configured), `detected_lights_on_time` (auto-tracked — see **Light Cycle Tracking**), `auto_light_tracking`.

## Light Cycle Tracking

An optional sub-feature of Crop Steering. When `IrrigationStrategy.auto_light_tracking = True` and the growspace has at least one entity in `EnvironmentConfig.light_sensors`, the backend listens for the light sensor's off→on transition each day and records the wall-clock time as `IrrigationStrategy.detected_lights_on_time`. The VWC coordinator resolves lights-on time as `detected_lights_on_time ?? lights_on_time` — the user's manual value is never overwritten and acts as the fallback.

**Precondition**: only active when `IrrigationStrategy.enabled = True`.

## Photoperiod Flip

The event when any plant in a growspace transitions from veg to flower stage (i.e. `Plant.flower_start` becomes today). At this moment the daily light hours must drop from `EnvironmentConfig.veg_day_hours` (default 18h) to `EnvironmentConfig.flower_day_hours` (default 12h). The system fires a HA notification via the existing `NotificationManager` and surfaces a persistent **FlowerFlipChip** in the card.

If `auto_light_tracking` is enabled the system will auto-adapt its derived lights-off time from the sensor once the hardware schedule is changed, but the notification and chip still fire to prompt the user to verify their hardware.

## FlowerFlipChip

A pulsing growspace chip (same component as other header chips) that appears on the day `flower_start` is reached for any plant in the growspace. Persists until explicitly dismissed by the user; dismiss state is keyed to `growspaceId + flower_start` so it auto-resets if the transition date is changed. Clicking it opens the Irrigation Dialog on the Steering tab and scrolls `lights_on_time` into focus.

## Simulation Layer

HA `input_number` + `template sensor` entities used as stand-ins for real hardware sensors.

- **Demo simulation** (`growspace_demo.yaml`): dynamic sinusoidal variation for realistic Bayesian logic testing.
- **E2E simulation** (`growspace_e2e.yaml`): fully static pass-through sensors, prefixed `e2e_`, controllable from Playwright via `input_number.set_value` WebSocket calls.
