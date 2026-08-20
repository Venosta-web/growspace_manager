# ADR 0004 — Separate `detected_lights_on_time` from user-configured `lights_on_time`

**Status:** Accepted

## Context

The Light Cycle Tracking feature auto-detects when grow lights turn on each day (off→on transition on `EnvironmentConfig.light_sensors`) and uses that time to anchor crop-steering phase windows.

Two approaches were considered for storing the detected value:

**Option A — overwrite `lights_on_time` in place:** The tracker writes the detected time directly into `IrrigationStrategy.lights_on_time` and persists it. The VWC coordinator reads it as normal.

**Option B — store separately as `detected_lights_on_time`:** The tracker writes to a new nullable field. The VWC coordinator resolves lights-on time as `detected_lights_on_time ?? lights_on_time`.

## Decision

Option B — `detected_lights_on_time: str | None` is a separate field on `IrrigationStrategy`.

## Rationale

Option A is destructive. A sensor glitch (e.g. a brief state flap at 03:47) permanently overwrites the user's configured schedule with a bogus time. The user's manual value is then gone from storage and the fallback is lost.

Option B preserves the user's configured value as an always-available fallback. It also makes the auto/manual distinction explicit and inspectable: the card can show "auto: 06:12" alongside the user's "manual: 06:00" without ambiguity.

## Consequences

- `IrrigationStrategy` gains one nullable field (`detected_lights_on_time`).
- VWC coordinator reads `detected_lights_on_time or lights_on_time` rather than `lights_on_time` directly.
- The Steering tab shows `detectedLightsOnTime` as a read-only badge next to the `lightsOnTime` input when auto-tracking is on.
- No migration needed for existing data — the field defaults to `None`.
