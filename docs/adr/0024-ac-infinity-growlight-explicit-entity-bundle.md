# AC Infinity Grow Light: Explicit Entity Bundle Matching the Actuator Convention

The AC Infinity grow-light configurator (ADR-0023) needs to write ~6 entities on one port: the `active_mode` select (→ "Schedule"), `schedule_mode_on_time`, `schedule_mode_off_time`, the `on_power` number, and the sunrise switch + duration number. These are stored as an **explicit entity bundle** — each entity ID captured verbatim in config — matching the convention the fan/humidifier AC Infinity work established (`AC_INFINITY_DEVICE_SCHEMA`: `mode_entity` + `speed_entity` + `on_speed`, PRs #502–509 / `configure_environment`). The growlight bundle is that same shape widened to the extra schedule/sunrise entities.

## Considered Options

- **One picker + device-registry resolution** (keyed on `ac_infinity`'s `translation_key`/`unique_id` suffixes). Rejected: it would couple GSM to `ac_infinity`'s internal entity keys, and — decisively — it contradicts the just-established convention. The merged fan/humidifier config surface deliberately stores explicit entity IDs and takes *no* dependency on the upstream integration's internals; a resolution-based grow-light path would be the odd one out and reintroduce exactly the coupling the convention avoids. Ergonomics (fewer pickers) does not justify diverging from the settled pattern for a single actuator role.

## Consequences

- The user picks each AC Infinity entity explicitly (~6 pickers per grow light) — more setup friction than a single device picker, accepted for convention-consistency and zero upstream coupling.
- No dependency on `ac_infinity`'s internal entity keys: an upstream rename breaks nothing in GSM (the user's stored entity IDs are HA-registry-stable, and renames surface as normal missing-entity errors).
- This is **not** the first AC Infinity config surface — `configure_environment` + `AC_INFINITY_DEVICE_SCHEMA` + the card payload (the `feat-ac-infinity-configure-env` line of work) established that for the fan/humidifier roles first. The grow-light bundle extends that surface rather than founding it, and should reuse the same schema/validation/preservation plumbing (note the "configure_environment is a full replace" behavior — the growlight bundle must be preserved on unrelated env edits like every other field).

## Amendment (2026-07-07)

The ergonomics half of this decision was revisited: the card now offers a **device-picker
pre-fill** (card repo ADR-0028) on all AC Infinity editors — the user picks the `ac_infinity`
port device and the card resolves the member entities via `translation_key` at edit time,
pre-filling (and on re-pick, overwriting) the existing entity pickers. This is UI sugar only:
the **stored config remains the explicit entity bundle decided here**, no backend or runtime
resolution was introduced, and an upstream key rename degrades the pre-fill back to the manual
flow without breaking anything stored. The rejection above stands for storage and backend; it
no longer implies the *pickers themselves* must be filled by hand.
