# ADR 0006 — Circulation Fan: VPD Mode Temperature Safety Override

**Status:** Accepted

## Context

The CirculationFanController supports three regulation modes (humidity, temperature, VPD). VPD is the preferred mode for experienced growers because it encodes both temperature and humidity in a single target. However, VPD control can drive fan speed in ways that worsen a temperature emergency — e.g. VPD logic may call for low fan speed while the tent is overheating.

## Decision

When regulation mode is `vpd`, two critical temperature thresholds (`critical_temp_low`, `critical_temp_high`) act as a safety override. If either is breached:
- High-temp breach → fans forced to `max_speed` regardless of VPD reading
- Low-temp breach → fans forced to `min_speed` regardless of VPD reading

The override deactivates only when temperature returns within bounds plus `critical_temp_hysteresis` (to prevent rapid toggling). While active, the override replaces VPD output entirely — the Dynamic Wind Layer still applies on top.

This override exists **only** in VPD mode. In humidity or temperature mode, the grower has already chosen a mode where temperature is either the controlled variable or not the concern.

## Alternatives Considered

**Priority stack across all modes**: all modes run simultaneously and the highest demanded speed wins. Rejected: in VPD mode the desired speed can be *low*, so a max-wins rule would not protect against a low-temp emergency correctly.

**Separate emergency mode**: add a fourth regulation mode "temperature safety" the grower switches to manually. Rejected: safety must be automatic; relying on grower intervention defeats the purpose.

## Consequences

- Two extra config fields (`critical_temp_low`, `critical_temp_high`) are only meaningful when `regulation_mode == vpd`. The UI should conditionally show them.
- The temperature sensor (`temperature_sensors[0]`) is the data source for the override check — the same sensor already used in `temperature` regulation mode.
