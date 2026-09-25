# Feature matrix

This file records how each feature of Growspace Manager has been checked, and
what has not been checked. A feature listed here can still have bugs. The
matrix shows what the evidence covers.

Last reviewed **2026-09-25** against `prerelease` at `adfb338`
(`v1.2.4b499`). The latest stable release is **1.2.3**.

## Evidence levels

| Level          | Meaning                                                                                                                                                                 |
| :------------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Implemented    | The code exists, and no test named here exercises it.                                                                                                                   |
| Automated test | The test suite exercises it. That suite runs against a real Home Assistant core, with simulated entities, on every pull request. It proves the logic, not the hardware. |
| Simulated live | It ran on a live Home Assistant instance with simulated devices (the workspace hub's `ha-dev`), and a dated record exists.                                              |
| Physical       | It ran on real hardware, and a dated record names the device.                                                                                                           |
| Not built      | It is tracked, but not implemented.                                                                                                                                     |

A row shows the strongest level that covers the feature as it is now.

- A live record counts only if the software it ran contains the feature. When
  the feature changed after the run, the row says so.
- Each live level links to its entry under [Observations](#observations). That
  entry gives the date, the versions, and whether the run was simulated or
  physical.

## Irrigation and climate safety

All of this arrived after 1.2.3. **1.2.3 and earlier have none of it.** The
"Since" column gives the first beta that contained each item. The README's
[Safety and limitations](../README.md#safety-and-limitations) describes the
behaviour itself.

| Feature                                                                                        | Since     | Evidence                                                                                                           | Tests                                                                                                 |
| :--------------------------------------------------------------------------------------------- | :-------- | :----------------------------------------------------------------------------------------------------------------- | :---------------------------------------------------------------------------------------------------- |
| Irrigation Controller state, structured reasons, persistent fault latch (#783)                 | 1.2.4b467 | Simulated live ([2026-09-24](#2026-09-24--irrigation-commissioning-simulated)), readback changed since by #785     | `tests/domain/test_irrigation_safety.py`, `tests/services/test_irrigation_safety_store.py`            |
| Pump readback after every command, fault on mismatch (#785)                                    | 1.2.4b476 | Automated test                                                                                                     | `tests/services/test_irrigation_unconfirmed_pump.py`, `tests/services/test_irrigation_coordinator.py` |
| Cycle runtime ceiling, watchdog, default daily caps (#788)                                     | 1.2.4b473 | Automated test                                                                                                     | `tests/domain/test_pump_cycle.py`, `tests/core/test_irrigation_cap_migration.py`                      |
| Automation switch, irrigation arm, emergency stop (#791)                                       | 1.2.4b474 | Automated test                                                                                                     | `tests/services/test_safety_controls.py`, `tests/components/test_safety_button.py`                    |
| Crop steering restores its day after a restart; startup inhibit (#786)                         | 1.2.4b472 | Automated test                                                                                                     | `tests/core/test_steering_restart.py`                                                                 |
| Pump found ON at a start: alerted and held, switched off only under `enforce_off` (#784, #793) | 1.2.4b494 | Automated test; simulated live **gap** before #793 ([2026-09-24](#2026-09-24--irrigation-commissioning-simulated)) | `tests/services/test_manual_override.py` (`test_a_pump_on_at_startup_is_an_unexpected_on`)            |
| Moisture sensor freshness and plausibility gate (#789)                                         | 1.2.4b483 | Automated test                                                                                                     | `tests/domain/test_sensor_validity.py`, `tests/integration/test_control_sensor_validity.py`           |
| Unreadable tank fails closed, Tank Offline alert (#790)                                        | 1.2.4b478 | Automated test                                                                                                     | `tests/domain/test_unknown_tank_level.py`                                                             |
| Low-tank pause                                                                                 | ≤ 1.2.3   | Simulated live ([2026-09-24](#2026-09-24--irrigation-commissioning-simulated), focused run)                        | `tests/domain/test_pump_cycle.py`                                                                     |
| Climate fail-safe on sensor loss, humidity interlock, runtime cap (#792)                       | 1.2.4b485 | Automated test                                                                                                     | `tests/domain/test_climate_fail_safe.py`, `tests/integration/test_climate_fail_safe.py`               |
| Manual override and unexpected-ON detection (#793)                                             | 1.2.4b494 | Automated test                                                                                                     | `tests/domain/test_manual_override.py`, `tests/services/test_manual_override.py`                      |
| Light-leak detection during the dark period (#794)                                             | 1.2.4b470 | Automated test                                                                                                     | `tests/domain/test_light_leak.py`, `tests/integration/test_light_leak_guard.py`                       |
| Subsystem diagnostics (#795)                                                                   | 1.2.4b477 | Automated test                                                                                                     | `tests/components/test_diagnostics.py`                                                                |
| Durable reliability evidence (#796)                                                            | 1.2.4b480 | Automated test                                                                                                     | `tests/services/test_reliability_evidence.py`                                                         |
| Daily safety counters survive a restart (#787)                                                 | —         | Not built                                                                                                          | —                                                                                                     |
| DST and clock-jump behaviour of schedules                                                      | —         | Not verified: no dedicated test, and no commissioning case                                                         | —                                                                                                     |

## Cultivation features

Everything in this section was in 1.2.3.

| Feature                                                             | Evidence                                                                  | Tests                                                                                                                                                              |
| :------------------------------------------------------------------ | :------------------------------------------------------------------------ | :----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Plant tracking and lifecycle stages                                 | Automated test                                                            | `tests/domain/test_plant_lifecycle.py`, `tests/logic/test_plant_lifecycle_manager.py`, `tests/managers/test_plant_lifecycle_atomic.py`                             |
| Grid layouts                                                        | Automated test                                                            | `tests/domain/test_grid_builder.py`                                                                                                                                |
| Crop steering: phases, shot composition                             | Automated test                                                            | `tests/domain/test_steering_phase.py`, `tests/logic/test_crop_steering.py`                                                                                         |
| Irrigation Recipes and Irrigation Programs                          | Automated test                                                            | `tests/domain/test_irrigation_recipe.py`, `tests/domain/test_irrigation_program.py`, `tests/services/test_irrigation_programs.py`                                  |
| VPD climate control: dehumidifier, humidifier, exhaust, circulation | Automated test                                                            | `tests/integration/test_dehumidifier_coordinator.py`, `tests/integration/test_exhaust_fan_coordinator.py`, `tests/integration/test_circulation_fan_coordinator.py` |
| Grow light control                                                  | Automated test                                                            | `tests/integration/test_grow_light_coordinator.py`, `tests/integration/test_grow_light_ac_infinity.py`                                                             |
| Tank monitoring                                                     | Automated test                                                            | `tests/services/test_tank_monitor.py`                                                                                                                              |
| Bayesian stress and mold-risk analytics                             | Automated test                                                            | `tests/logic/test_bayesian_evaluator.py`                                                                                                                           |
| Strain library, genetics and seed inventory                         | Automated test                                                            | `tests/integration/test_strain_library_services.py`, `tests/test_seed_inventory_sensor.py`                                                                         |
| Drying and curing                                                   | Automated test                                                            | `tests/domain/test_drying_calculator.py`, `tests/sensors/test_drying_sensors.py`                                                                                   |
| Label Templates and Niimbot printing, B1 with 50×30 labels          | Physical ([2026-09-22](#2026-09-22--label-printing-physical))             | `tests/labels/`                                                                                                                                                    |
| Label printing on other Niimbot models and sizes                    | Automated test only; no physical record                                   | `tests/labels/`                                                                                                                                                    |
| Growspace Vision checkups, evidence store, capture continuity       | Simulated live ([2026-09-04](#2026-09-04--growspace-vision-v1-simulated)) | `tests/test_vision_client.py`, `tests/domain/test_visual_comparison.py`, `tests/domain/test_capture_continuity.py`                                                 |
| AI Grow Master, briefings and the Assist intent                     | Automated test                                                            | `tests/integration/test_ai_assistant.py`, `tests/integration/test_intent.py`                                                                                       |

The README screenshots and the live demo come from the same `ha-dev`
instance, driven by simulated sensors. They show the interface. They are not
verification records.

## Observations

Newest first. Records that live in the
[workspace hub](https://github.com/Venosta-web/growspace_manager_workspace) are
linked there.

### 2026-09-24 — Irrigation commissioning, simulated

- **Environment:** simulated. The run used the hub's `ha-dev` instance and its
  simulated pumps, tank and VWC sensors.
- **Home Assistant:** 2026.8.2.
- **Growspace Manager:** manifest 1.2.3, at `prerelease` revision `3235ca5a`.
  - Already included: #783, #786, #788, #791 and #794.
  - Came later: #785, #789, #790, #792 and #793.
- **Harness:** hub `scripts/commission` at hub revision `4967f41`.
- **Record:**
  [`docs/acceptance/irrigation-safety-simulated.md`](https://github.com/Venosta-web/growspace_manager_workspace/blob/main/docs/acceptance/irrigation-safety-simulated.md)
  in the hub.

| Case                      | Outcome                                                                                             | Since this run                                                                                       |
| :------------------------ | :-------------------------------------------------------------------------------------------------- | :--------------------------------------------------------------------------------------------------- |
| Pump stuck ON             | Met                                                                                                 | Readback reworked by #785. Not re-run.                                                               |
| Service-call failure      | Met                                                                                                 | Readback reworked by #785. Not re-run.                                                               |
| Empty tank                | Met in a focused run at 18:22Z. Not exercised in the full run, because a cycle was already running. | Not re-run.                                                                                          |
| Unexpected ON             | Gap                                                                                                 | #793 added detection. Not re-run.                                                                    |
| HA restart mid-shot       | Gap                                                                                                 | The pump is now detected at the start, but under the default policy it is still left ON. Not re-run. |
| Power loss mid-shot       | Gap                                                                                                 | As for the restart case. Not re-run.                                                                 |
| Invalid VWC               | Gap                                                                                                 | #789 added the plausibility gate. Not re-run.                                                        |
| Overlapping requests      | Gap                                                                                                 | Both pumps were observed ON together. Not re-run.                                                    |
| Config change while armed | Gap                                                                                                 | The pump remap was accepted while the old pump still read ON. Not re-run.                            |
| Sensor disconnect         | Not exercised                                                                                       | The fixture was not mounted.                                                                         |
| Stale sensor              | Not exercised                                                                                       | The fixture was not mounted.                                                                         |
| Manual override           | Not exercised                                                                                       | `set_override` did not exist yet. It arrived with #793.                                              |
| DST / clock               | Not exercised                                                                                       | The backend frozen-time test does not exist.                                                         |

### 2026-09-22 — Label printing, physical

- **Environment:** physical.
- **Printer:** Niimbot B1, firmware 5.22, hardware 5.1, with 50×30 mm labels.
- **Software:** profile `growspace.profile.niimbot-b1.50x30.v1`, label contract
  1.0 generation 3.
  - The run does not record the integration revision.
  - The profile was promoted on this evidence in `61bc3d9`, which shipped in
    1.2.3.
- **Checked:** 15 prints, five copies at each of three densities.
  - Edge ticks, text legibility at 2.2 mm and 1.6 mm, QR scanning at three
    payload sizes, a breeder logo, and a batch printed from the card.
  - Tick counts were identical on all fifteen prints.
- **Record:**
  [`docs/evidence/labels/niimbot-b1.50x30.v1/2026-09-22/run.json`](evidence/labels/niimbot-b1.50x30.v1/2026-09-22/run.json),
  with a photograph of the strip beside it.

### 2026-09-04 — Growspace Vision V1, simulated

- **Environment:** simulated. The camera frames were generated. The Vision App
  ran natively on an x86-64 host.
- **Growspace Vision App:** image `1.0.0` (amd64), model DINOv2 INT8 1.0.0,
  schema 1.
- **Home Assistant and Growspace Manager:** versions not recorded.
- **Result:** the path passed from camera pixels, through the App, the
  integration and the evidence store, to the card. Rejected frames raised
  capture-continuity alerts. Captures and alerts survived a Home Assistant
  restart.
- **Record:**
  [`docs/acceptance/vision-v1-simulated.md`](https://github.com/Venosta-web/growspace_manager_workspace/blob/main/docs/acceptance/vision-v1-simulated.md)
  in the hub.

## Not verified

- **Irrigation on physical hardware.** No physical commissioning run has been
  recorded. The commissioning guide is
  [#799](https://github.com/Venosta-web/growspace_manager/issues/799).
- **Climate actuators on physical hardware.** No record exists.
- **The irrigation safety work from #785 onward on a live instance.** No
  simulated run has been made since it landed.
- **Physical cameras and ARM hosts** for Growspace Vision. Neither image
  quality nor latency and memory have been measured.
- **Metered water.** Every volume is an estimate from the configured flow rate.

## Keeping this file current

After each commissioning run, whether the hub's `./scripts/commission` or a
physical run of the same cases, add an entry under
[Observations](#observations). The entry gives:

- the date;
- simulated or physical;
- the Home Assistant version;
- the integration version and revision;
- the outcome of each case;
- for a physical run, also the device models, their firmware, and the relay's
  power-restore setting.

Then raise every row that the run covers. Change a row's level only on a record
whose revision contains the behaviour the row describes. When a pull request
changes that behaviour, note the change in the row.
