# Growspace reliability evidence

Growspace Manager keeps a durable count of how it has operated each growspace:
irrigation requests and outcomes, pump command and readback failures,
control-sensor dropouts, controller inhibits, faults and emergency stops, and
restarts. Nothing is sent anywhere. The grower can read the counts in three
places:

- **Export.** Call `growspace_manager.export_reliability_evidence` with
  `growspace_id` and `return_response: true`. The service returns the document
  below to the client that called it, and to nobody else.
- **Diagnostics.** The config entry diagnostics include one such document per
  growspace, under `reliability`.
- **Sensor.** Each growspace has a diagnostic-category **Reliability** sensor.
  Its state is the lifetime count of `irrigation.completed_verified`. Its
  attributes are the key counters listed under
  [The diagnostic sensor](#the-diagnostic-sensor).

## The document

```json
{
  "schema_version": 1,
  "unreadable": false,
  "growspace_id": "tent",
  "as_of": "2026-09-24T12:00:00+00:00",
  "days_since_last_fault": 2,
  "lifetime": {
    "irrigation.requested": 412,
    "runtime.automation_uptime_percent": 99.1
  },
  "last_24h": {
    "irrigation.requested": 6,
    "runtime.automation_uptime_percent": 100.0
  },
  "last_30d": {
    "irrigation.requested": 180,
    "runtime.automation_uptime_percent": 98.7
  }
}
```

- `as_of` is in UTC.
- `days_since_last_fault` is `null` until the first fault is latched.
- The three counter maps use the same keys. A key that is absent means zero.
- `runtime.automation_uptime_percent` is derived when the document is built,
  and is `null` for a window with no observed minute.

## Counters

Each counter is incremented in exactly one place.

| Key                                     | Counts                                                                                                                                                                                                            |
| :-------------------------------------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `irrigation.requested`                  | Every pump cycle that reached the controller, whether or not it fired.                                                                                                                                            |
| `irrigation.skipped.<reason>`           | A cycle refused before the pump was commanded. See [Skip reasons](#skip-reasons).                                                                                                                                 |
| `irrigation.fired`                      | The pump read back ON.                                                                                                                                                                                            |
| `irrigation.completed_verified`         | The pump ran for its planned duration and then read back OFF.                                                                                                                                                     |
| `irrigation.completed_unverified`       | The pump ran for its planned duration but did not read back OFF.                                                                                                                                                  |
| `irrigation.aborted.<cause>`            | An admitted cycle that did not run to its end: `cancel`, `e_stop`, `override` (automation turned off, irrigation disarmed, a Manual Override of irrigation, or a manual run replacing it), `error` or `watchdog`. |
| `irrigation.command_failure.on`         | `turn_on` raised.                                                                                                                                                                                                 |
| `irrigation.command_failure.off`        | `turn_off` raised or timed out during a stop attempt: a cycle closing, or the watchdog. The re-sends each minute after an OFF-unconfirmed fault are not counted.                                                  |
| `irrigation.readback.on_unconfirmed`    | The pump did not read ON after `turn_on`.                                                                                                                                                                         |
| `irrigation.readback.off_unconfirmed`   | A pump that would not read OFF latched a fault. A watchdog and the cycle it cancelled can both find the same pump still ON, and that counts once.                                                                 |
| `irrigation.readback.unexpected_on`     | A configured pump read ON with no cycle of Growspace Manager's in flight, at a start or while running, and no Manual Override of irrigation set (#793).                                                           |
| `sensors.control_unavailable_minutes`   | Each sampled minute in which a control sensor was missing, `unknown`, `unavailable` or not a number.                                                                                                              |
| `sensors.stale_events`                  | A control sensor becoming stale.                                                                                                                                                                                  |
| `sensors.implausible_readings`          | A control sensor reading becoming implausible.                                                                                                                                                                    |
| `controller.inhibit.<reason>`           | The irrigation controller entering `inhibited`, by reason code.                                                                                                                                                   |
| `controller.fault_latched`              | A fault latched that was not already latched.                                                                                                                                                                     |
| `controller.fault_acknowledged`         | An administrator acknowledged a fault.                                                                                                                                                                            |
| `controller.emergency_stop`             | An emergency stop latched that was not already latched.                                                                                                                                                           |
| `runtime.ha_start`                      | One Home Assistant start. A config entry reload does not count.                                                                                                                                                   |
| `runtime.ha_start_inflight`             | A start that found a pump's in-flight marker, meaning the previous process stopped while that pump was running a cycle.                                                                                           |
| `runtime.automated_seconds.<entity_id>` | Seconds an actuator ran in a cycle that was not manual.                                                                                                                                                           |
| `runtime.estimated_water_l`             | The Pump-Cycle Water Estimate of each irrigation cycle, the same figure water usage books. It is an estimate from the configured flow rate, not metered water.                                                    |
| `runtime.observed_minutes`              | Minutes sampled while the integration was running.                                                                                                                                                                |
| `runtime.automation_eligible_minutes`   | Sampled minutes in which automatic irrigation was armed and no fault was latched. `runtime.automation_uptime_percent` is this as a percentage of `runtime.observed_minutes`.                                      |
| `climate.command_failure.<role>`        | A humidifier, dehumidifier, exhaust or circulation command that raised or did not answer within 10 s.                                                                                                             |
| `climate.fail_safe.<role>`              | A humidifier, dehumidifier or exhaust controller entering its safe state after losing every control sensor for the fail-safe timeout.                                                                             |
| `climate.interlock`                     | The humidifier or dehumidifier switched off because the other's later demand took over.                                                                                                                           |
| `climate.max_runtime_stop`              | A humidifier or dehumidifier switched off at its maximum continuous runtime.                                                                                                                                      |

### Skip reasons

A cycle held by an operator control is skipped before the gate is asked:

- `automation_off`
- `irrigation_disarmed`
- `emergency_stop`

A cycle held because a person has the pumps is skipped the same way (#793), manual
runs included:

- `manual_override`
- `override_detected`

A cycle the Pump Cycle Gate refuses is skipped with the gate's reason:

- `low_tank`
- `tank_unknown`
- `cycle_limit`
- `volume_cap`
- `dark`
- `fault`
- `emergency_stop`
- `startup_inhibit`

### Control sensors

The control sensors are:

- the substrate moisture sensor, while crop steering drives the pump;
- each configured irrigation tank.

They are sampled once a minute. Validity follows `domain/sensor_validity.py`,
the rules the Unknown Tank Level uses:

- **Implausible:** outside 0–100 %, or not finite.
- **Stale, for a tank:** no report for longer than the tank's own
  `stale_after_minutes`. When that is `0`, the tank is never stale.
- **Stale, for moisture:** never. No staleness window is configured for the
  moisture sensor, so it is counted only as unavailable or implausible.

## The diagnostic sensor

The sensor's attributes are:

- the lifetime count of each key counter, with the dots replaced by underscores:
  - `irrigation_requested`
  - `irrigation_fired`
  - `irrigation_completed_verified`
  - `irrigation_completed_unverified`
  - `controller_fault_latched`
  - `controller_emergency_stop`
  - `runtime_ha_start`
  - `runtime_ha_start_inflight`
- `days_since_last_fault`;
- `automation_uptime_percent_30d`.

The Recorder does not store any of these attributes. The uptime changes every
minute, and the full history is in the export. The state is recorded.

## Storage and durability

- **Where.** The counts live in `.storage/growspace_manager.reliability_<entry_id>`.
- **Lifetime.** The lifetime map survives restarts.
- **Windows.** The 24-hour map keeps minute buckets and the 30-day map keeps UTC
  calendar-day buckets. At a boundary, the first has minute resolution and the
  second day resolution.
- **Pruning.** Old buckets are pruned whenever that growspace is written to.
  Storage is therefore bounded by 1,441 minute buckets and 31 day buckets per
  growspace, plus the lifetime map.
- **Open families.** `irrigation.skipped.*`, `controller.inhibit.*` and
  `runtime.automated_seconds.*` each keep at most 16 distinct keys. Any further
  key is folded into `<family>.other`.
- **Removed growspaces.** A growspace's counts are dropped at the next start
  after the growspace is removed.
- **When counts are written.** Recording never waits on the disk, so a pump
  fail-safe or an emergency stop is never delayed by a counter. A count updates
  memory at once. Writes are coalesced and reach the disk within 60 seconds, and
  Home Assistant flushes any pending write when it stops. A crash can therefore
  lose up to a minute of counts.
- **In-flight marker.** The in-flight marker is written and cleared without
  that delay. The restart it exists to detect is the one that would lose a
  delayed write. A marker left behind by a cycle that did close would make the
  next start switch off a pump a person had turned on.
- **A marker found at a start** is counted once, and kept until its pump reads
  OFF. A pump that reads ON at that start, or later, is switched off as the
  cycle's own ([#854](https://github.com/Venosta-web/growspace_manager/issues/854)).
- **Unreadable file.** If the stored file cannot be decoded, the error is logged
  once. From then on:
  - `unreadable` is `true` in the document;
  - the sensor is unavailable;
  - nothing is counted;
  - the file is left untouched for inspection.

## Not counted yet

| What                                                                                  | Why                                                                                                                                                                                                                   |
| :------------------------------------------------------------------------------------ | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Verified water                                                                        | Needs metered per-cycle delivery (#546, #549). `runtime.estimated_water_l` is an estimate and is never labelled verified.                                                                                             |
| Whether a Grow Run was active at a start, and reliability as a Grow Run Activity Fact | Needs the Grow Run model (#669).                                                                                                                                                                                      |
| Climate automated runtime, inhibits and faults                                        | Climate controllers count failed commands, safe states, interlocks and runtime stops (#792), but have no fault latch or readback. Without command provenance, automated runtime cannot be told from manual operation. |
