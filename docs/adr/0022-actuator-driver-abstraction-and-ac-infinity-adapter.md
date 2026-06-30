# 22. Actuator-driver abstraction and AC Infinity adapter

Date: 2026-06-30

## Status

Accepted

## Context

GSM controls four kinds of actuator — exhaust fan, circulation fan, humidifier,
dehumidifier — and historically modelled each as a single HA `entity_id` string
stored on `EnvironmentConfig` (`exhaust_fan_entities`, `circulation_fan_entities`,
`humidifier_entities`, `dehumidifier_entities`). Three separate dispatch sites each
decided *how* to command a device by sniffing the entity domain inline:

- `exhaust_fan_coordinator._dispatch` — `fan.set_percentage` for `fan.*`,
  `turn_on`/`turn_off` for `switch.*`/`input_boolean.*`.
- `circulation_fan_coordinator` — `fan.set_percentage`.
- `vpd_on_off_controller._control_devices` — `turn_on`/`turn_off` over
  `switch`/`humidifier`/`fan`/`input_boolean`, else `homeassistant.*`.

Users increasingly run AC Infinity controllers via the `ac_infinity` HACS
integration. That integration exposes **no `fan` platform**. Each port is a
*bundle* of entities:

- a mode `select` (Active Mode: `Off`, `On`, `Auto`, `Timer to On`,
  `Timer to Off`, `Cycle`, `Schedule`, `VPD` — hardcoded English option strings),
- a speed `number` (On Speed, integer **0–10**, step 1 — not a 0–100 percentage),
- sensors for status/current power, temperature, humidity, VPD.

To run a port at 60 %, you must set the mode `select` to `On` *and* write `6` to
the speed `number`. To turn it off, set the mode to `Off`. There is no single
`entity_id` whose `STATE_ON`/percentage GSM can read or write, so AC Infinity
devices simply do not work with the domain-sniffing dispatch. We want them to
work **optionally**, without breaking existing plain-`fan`/`switch` setups.

`ac_infinity`'s `iot_class` is **`cloud_polling`** and it does **not** update
local state optimistically after a control write — neither the mode `select` nor
the `current_power` sensor reflects a change until the next cloud poll
(`MIN_TIME_BETWEEN_UPDATES = 5 s` floor, interval user-configurable). The
per-port power sensor (`current_power`, `POWER_FACTOR`, bare int) has no
guaranteed `0` reading when the port is Off — its off value is firmware-dependent.

## Decision

**Introduce an `ActuatorDriver` abstraction** with a uniform interface
(`set_speed(pct)`, `turn_on()`, `turn_off()`, `is_on()`) and one implementation
per actuator kind: a `fan` driver, a `switch`/on-off driver, and an
`ACInfinityDriver`. The exhaust-fan, circulation-fan, and VPD on/off coordinators
resolve a driver per configured actuator and command it through this interface;
the inline domain-sniffing is removed from all three sites. Speed is always
passed to a driver as a 0–100 percentage; each driver maps it to the device's
native surface.

**`ACInfinityDriver` treats one port as a two-entity bundle** — mode `select`
and speed `number` — with these semantics:

- `set_speed(pct)`: `pct <= 0` → mode `select` → `Off`; otherwise mode → `On`
  and number → `clamp(round(pct / 10), 1, 10)`. (Off threshold is `0`, matching
  the `fan` driver — *not* the switch driver's `min_speed` — so an AC Infinity
  exhaust keeps running at low intensity where a switch exhaust would already be
  off.)
- `turn_on()`: mode → `On` and number → a per-device configured **on-speed**
  (default `10`). `turn_off()`: mode → `Off`.
- `is_on()`: read the bound **mode `select`**; on = state not in
  `{Off, unavailable, unknown}`. Chosen over the `current_power` sensor because,
  under cloud polling, both readbacks lag a poll equally so the sensor buys no
  freshness, while the `select` gives a deterministic `Off` where the power
  reading is firmware-dependent. The bundle therefore needs only the `select`
  and `number`; a power sensor is not required.
- On teardown / control-flag-off / growspace deletion: **no action** — the port
  is left in its last commanded state (documented).

**Config model:** keep the existing `*_entities: list[str]` fields untouched and
add parallel `*_ac_infinity_devices` fields holding the three-entity bundle plus
on-speed. The driver resolver yields drivers from both lists. No storage
migration.

**Scope:** ship the backend (driver abstraction + `ACInfinityDriver` + config
fields + serialization + tests) first; the Lovelace card's Config Dialog bundle
editor is a separate follow-up. Until then, bundles are configured via
storage/options.

## Consequences

- All three coordinators route writes through one tested seam; adding a future
  device kind (e.g. another bundled controller) is a new driver, not edits to
  three dispatch methods.
- The 0–100 → 0–10 mapping and `select`+`number` choreography live in exactly
  one place. Hardcoding `"On"`/`"Off"` is safe — `ac_infinity` mode options are
  hardcoded English, not translated.
- Because `ac_infinity` is cloud-polled with no optimistic write-back, `is_on()`
  (from the `select`) **lags** a command by up to one poll interval. The
  VpdOnOffController will therefore re-issue `On`/`Off` until the poll catches up;
  these writes are idempotent and floored by `MIN_TIME_BETWEEN_UPDATES` (5 s) and
  GSM's own min-runtime/off-time gating, so the effect is redundant API calls, not
  incorrect control. (This lag is identical for either readback source, which is
  why it does not favour the power sensor.)
- GSM seizing a port suppresses the controller's own Auto/VPD/Schedule
  automation while GSM drives it — intended, since GSM is the brain — and on
  release the user must restore the native mode themselves.
- Two code paths per actuator role (`*_entities` + `*_ac_infinity_devices`) until
  a future unified binding model is justified; chosen over a migration to keep
  this change non-breaking.
- Reversal is costly: the driver interface and the parallel config fields become
  part of stored config and the coordinators' control flow.
