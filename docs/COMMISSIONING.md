# Commissioning irrigation

Work through this guide before you leave irrigation to run unattended. Each
case makes one thing go wrong on purpose and tells you what Growspace Manager
should then do. It also says what to write down. A case passes only when you
have seen that behaviour on your own hardware.

The guide does not certify an installation. It tests the software's side of
the safety model and shows you where that side stops. Some failures can only
be handled in the hardware: Home Assistant being down, a welded relay contact,
a tank running dry halfway through a shot. The
[hardware guide](HARDWARE.md) covers those, and cases 2, 5 and 6 depend on it.

The expected behaviour below is that of `prerelease` at `98157a6`
(`v1.2.4b500`). The safety behaviour ships in **1.2.4**. **1.2.3 and earlier
have none of it**, so this guide does not apply to them. The README's
[Safety and limitations](../README.md#safety-and-limitations) is the short
version of the same model, and
[`services.md`](services.md#irrigation-controller-safety) is the reference.

## Before you start

**Make it safe to get wrong.**

- Point the pump outlet into a bucket or a drain, not at the crop. Every case
  here can end with a pump running when it should not.
- Stay at the equipment for the whole session, and know how you will cut the
  pump's power by hand.
- Fit the hardware fail-safes first: a relay or plug that powers up OFF, an
  on-device maximum ON time, and a float switch in the pump's power. See
  [HARDWARE.md](HARDWARE.md).
- Use a short shot, 30 to 120 seconds. A long one only makes you wait.

**Know where to look.** You will read the same five places in almost every
case:

| Where                                                               | What it tells you                                                                                                                                     |
| :------------------------------------------------------------------ | :---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sensor.<growspace>_irrigation_controller`                          | The state (`ready`, `running`, `inhibited`, `fault`, `emergency_stop`). The `reasons` attribute gives each reason's code, detail and `since` time.    |
| The pump's own entity, and its history                              | What the device reported, and when.                                                                                                                   |
| Notifications                                                       | The growspace's notification target, plus Home Assistant's persistent notifications.                                                                  |
| Settings → Devices & services → Growspace Manager → **Diagnostics** | The safety ledger, the last 500 safety events, with timestamps. It also holds the reliability counters.                                               |
| `growspace_manager.export_reliability_evidence`                     | The [reliability counters](reliability-evidence.md) for one growspace, such as `irrigation.readback.off_unconfirmed` and `runtime.ha_start_inflight`. |

Set a notification target on the growspace before you start. Several cases pass
only if a notification arrives.

**Check the controls.** On the growspace under test:

1. Turn **Automation** on and **Irrigation armed** on. The controller reads
   `ready`, or `inhibited` for a reason you can explain, such as
   `startup_inhibit` in the first five minutes.
2. Start a manual run (`growspace_manager.run_irrigation_cycle`, or the card).
   Press **Emergency stop** while the pump runs. Every output the growspace
   manages switches off, lights and fans included, and the controller reads
   `emergency_stop`. If the stop reports itself incomplete, it names the
   output that did not read safe within about a second. A slow device can
   cause that, so check that output by hand.
3. Call `growspace_manager.reset_safety` as an administrator. It is refused
   while any output reads ON, and accepted once they all read OFF. The
   controller goes back to `ready`.

If any of that is not what you see, stop here and find out why before you go
on.

## What to record

Keep one record per session, with:

- the date, and whether the run was physical or simulated;
- the Home Assistant version;
- the Growspace Manager version and revision (the diagnostics download has
  both);
- every device in the irrigation path: its model, firmware, how it reaches Home
  Assistant, and its power-on setting;
- how the pump, the relay, the float switch and the tank sensor are wired;
- for each case: met, gap or not run, the timestamps the case asks for, and
  anything you did differently from the procedure.

A physical run is worth adding to the [feature matrix](FEATURE_MATRIX.md)
under Observations. [Keeping this file current](FEATURE_MATRIX.md#keeping-this-file-current)
says what an entry needs. Open a pull request, or post the record in
[Discussions](https://github.com/Venosta-web/growspace_manager/discussions)
and someone will add it.

The workspace hub automates all thirteen cases against simulated devices
(`./scripts/commission`, see the
[hub guide](https://github.com/Venosta-web/growspace_manager_workspace/blob/main/docs/COMMISSIONING.md)).
A simulated run proves the software path. It cannot tell you what your relay
does when the power comes back.

## The cases

| #   | Case                                                                     | Needs                                   |
| :-- | :----------------------------------------------------------------------- | :-------------------------------------- |
| 1   | [Sensor disconnect](#1-sensor-disconnect)                                | Crop steering and a moisture sensor     |
| 2   | [Pump stuck ON](#2-pump-stuck-on)                                        | A switch that ignores OFF               |
| 3   | [State mismatch](#3-state-mismatch)                                      | Nothing extra                           |
| 4   | [HA restart mid-irrigation](#4-home-assistant-restart-mid-irrigation)    | Nothing extra                           |
| 5   | [Host power loss](#5-host-power-loss)                                    | Access to the host's and relay's power  |
| 6   | [Empty tank](#6-empty-tank)                                              | A tank level sensor                     |
| 7   | [Invalid VWC](#7-invalid-vwc)                                            | Crop steering and a moisture sensor     |
| 8   | [Stale sensor](#8-stale-sensor)                                          | Crop steering and a moisture sensor     |
| 9   | [Service-call failure](#9-service-call-failure)                          | A pump you can take offline             |
| 10  | [Overlapping requests](#10-overlapping-requests)                         | A schedule, and a drain pump for step 2 |
| 11  | [Manual override](#11-manual-override)                                   | Nothing extra                           |
| 12  | [Configuration change while armed](#12-configuration-change-while-armed) | A second pump or switch to remap to     |
| 13  | [DST and time boundaries](#13-dst-and-time-boundaries)                   | Nothing; this one is reading, not doing |

### 1. Sensor disconnect

The substrate moisture sensor stops reporting while crop steering is deciding
from it.

**Steps**

1. Enable crop steering and wait until the day is in P1 or P2, where shots can
   fire.
2. Unplug the probe, or its gateway, so that its entity reads `unavailable`.
3. Wait 20 minutes. Do not reconnect it before then.
4. Reconnect it.

**Expected**

- From the next steering decision, no automatic shot fires. The controller
  reads `inhibited` with reason `sensor_unavailable`, and the detail names the
  sensor.
- After `sensor_alert_delay_minutes` (15 by default), one notification and one
  persistent notification.
- When the sensor reads again, a second notification says so, the reason
  clears, and steering resumes on its next decision. Clearing the reason fires
  nothing by itself. Missed shots are not made up, and a new shot keeps the
  usual `shot_interval_minutes` from the last one.
- A manual run is not held by the sensor. Timer schedules do not depend on the
  moisture sensor and are not held either.
- A sensor that keeps dropping out is announced at most once an hour.

**Record** the time you unplugged it, the time the reason appeared, the alert
time, and whether any pump command was sent while it was unplugged.

Some probes do not go `unavailable` when unplugged. Their integration keeps
showing the last value. If that happens, you are running case 8 instead: note
it, and keep waiting.

### 2. Pump stuck ON

The pump is told OFF and still reports ON.

Growspace Manager can only read back what the device **reports**. A relay whose
contact has welded shut reports OFF while the pump runs, and no software can
see that. This case therefore tests a device that reports ON after being told
OFF. Only the hardware in [HARDWARE.md](HARDWARE.md) protects you from a
welded contact.

**Steps**

1. Build a switch that ignores OFF. The simplest is a template switch in Home
   Assistant, backed by an `input_boolean`, whose `turn_off` action does
   nothing. Put a lamp or a small load behind it, not the pump.
2. Map it as the growspace's irrigation pump.
3. Start a 30 s manual run and wait for it to end.
4. Try another manual run.
5. Restart Home Assistant.
6. Call `growspace_manager.acknowledge_fault`. Then turn the `input_boolean` off
   by hand and call it again.

**Expected**

- At the end of the run, OFF is sent and the pump is read back after 1 s, then
  every 0.5 s. It still reads ON at 6 s, so the controller reads `fault` with
  reason `fault_off_unconfirmed:<pump>` and `requires_ack: true`.
- A persistent notification appears, and a Repairs issue.
- OFF is sent again at once, and then every minute, until the pump reads OFF.
- The second manual run is refused. So is every scheduled and steering cycle.
- After the restart, the fault is still latched and the OFF re-sends continue.
- `acknowledge_fault` is refused while the pump reads ON, and the refusal
  names it. Only an administrator can call it. Once the pump reads OFF, the
  call is accepted and the controller returns to `ready`. Acknowledging starts
  no cycle.

**Record** the time OFF was sent, the time the fault latched, the notification,
and the controller state after the restart.

### 3. State mismatch

The pump reads ON when no cycle of Growspace Manager's is running.

**Steps**

1. With the controller `ready`, switch the pump on at the device or from its
   own entity, not through Growspace Manager.
2. Try a manual run.
3. Switch the pump off by hand.
4. Set `unexpected_on_policy: enforce_off` (`set_irrigation_settings`) and
   repeat step 1.

**Expected** under the default `alert` policy:

- One notification and one persistent notification. The controller reads
  `inhibited` with reason `override_detected`.
- **The pump is not switched off.** Growspace Manager treats it as a person
  watering by hand.
- The manual run is refused, and so is every automatic cycle, until the pump
  reads OFF. The water is not booked as a Growspace Manager cycle.
- Once it reads OFF, the persistent notification is dismissed and the
  controller returns to `ready`.

**Expected** under `enforce_off`:

- The pump is switched off and read back, and a fault latches with reason
  `fault_unexpected_on:<pump>`. An administrator has to acknowledge it.
- If it will not read OFF, the fault is `fault_off_unconfirmed:<pump>`
  instead, with the minute-by-minute re-sends from case 2.
- With **Automation** off or an emergency stop latched, it only alerts,
  because then Growspace Manager sends no commands at all.

Each detection writes an `unexpected_on` row to the safety ledger, with the
policy and what was done.

**Record** the time the pump went ON, the alert time, the controller reason,
and under `enforce_off` the time the pump read OFF again.

Choose `enforce_off` only if nobody at your site ever runs the pumps by hand.

### 4. Home Assistant restart mid-irrigation

Home Assistant is restarted cleanly while a shot runs.

**Steps**

1. Start a 120 s manual run, or wait for a scheduled one.
2. About 20 s in, restart Home Assistant from Settings.
3. Watch the pump, not only its entity: the entity is gone while Home Assistant
   is down.
4. After the start, watch the controller for five minutes.

**Expected**

- As Home Assistant begins to stop, the running cycle is cancelled, OFF is
  sent, and the pump is read back as in any other cycle. The pump stops within
  a few seconds of the restart. This relies on the pump's own integration still
  taking commands at that point in the shutdown. If the pump cannot be read
  back OFF, `fault_off_unconfirmed` latches and is still latched after the
  start.
- After the start, the controller reads `inhibited` with reason
  `startup_inhibit` for at least `startup_grace_minutes` (5 by default). It
  stays that way until the moisture sensor, if crop steering is on, and every
  tank sensor have reported since the start. The `detail` names what is still
  outstanding.
- No automatic cycle runs inside that window, and a missed one is not
  replayed. A manual run is allowed.
- Crop steering resumes the phase it was in. A restart after P1 completed
  resumes in P2 instead of repeating the morning ramp. The next shot's cooldown
  counts from the last shot the pump confirmed, and the interrupted shot
  counts as one.
- A pump that reads ON at the start is handled as case 3. Under the default
  policy, that leaves it on.
- The reliability counters show `runtime.ha_start`, and an
  `irrigation.aborted.cancel` for the interrupted shot.

**Record** the pump's real ON and OFF times through the restart, the
controller's reasons after the start, and the time of the first automatic shot
afterwards.

The daily cycle and volume counts survive the restart. `cycles_today` and
`volume_dispensed_today` in the diagnostics read the same after the start as
before it, and the interrupted shot is among them: it was charged its whole
planned volume when the pump reported ON
([#787](https://github.com/Venosta-web/growspace_manager/issues/787)).

### 5. Host power loss

The power fails mid-shot, so nothing gets a chance to switch the pump off.

**This case tests your hardware, not Growspace Manager.** While Home Assistant
is not running, nothing in it can stop a pump.

**Steps**

1. Set the relay or plug to the power-on behaviour you will run with.
2. **Host only.** Start a 120 s manual run, then pull the power of the Home
   Assistant host, leaving the relay powered. Watch the pump until something
   stops it. Restore power.
3. **Host and relay.** Start a 120 s run and cut the power to both. Restore
   both.

**Expected**

- In step 2 the pump keeps running until the device's own maximum ON time
  stops it. If it runs until you intervene, the installation has no
  independent bound. Fix that before going on (see
  [HARDWARE.md](HARDWARE.md#an-on-device-maximum-on-time)).
- In step 3 the relay comes back in its power-on state. With power-on OFF, the
  pump stays off.
- At the next start, `runtime.ha_start_inflight` counts a start that found a
  cycle still marked as running. No separate "shot interrupted" alert is sent.
  Then the startup inhibit from case 4 applies.
- A pump that reads ON at the start **while that cycle was still marked as
  running** is Growspace Manager's own. It is switched off and read back,
  whatever `unexpected_on_policy` says, and an `interrupted_cycle` row is
  written to the Safety Ledger. If it will not read OFF,
  `fault_off_unconfirmed` latches and OFF is re-sent every minute. A plug that
  reports late and then restores ON is treated the same way.
  ([#854](https://github.com/Venosta-web/growspace_manager/issues/854))
- A pump that reads ON with no cycle marked as running is handled as case 3:
  under the default `alert` policy it stays on and you get a notification.

**Record** the relay's power-on setting, how long the pump ran in step 2 and
what stopped it, the pump state when power returned, and what Growspace
Manager did at the start.

### 6. Empty tank

The feed tank runs low, and then its sensor stops reporting.

**Steps**

1. Leave `pause_on_low_tank` on (the default).
2. Lower the tank below its `warning_level` (30 % by default). Drain it, or
   lift the level sensor out of the water.
3. Wait for a scheduled cycle, and try a manual run.
4. Refill the tank. Then unplug the tank sensor, or its gateway, and wait 15
   minutes.

**Expected**

- With the tank low, every cycle is skipped, manual runs included, with reason
  `low_tank`. The controller reads `inhibited`, a logbook entry says which tank
  and what level, and a persistent notification appears. The manual run call
  succeeds, but no pump command is sent.
- With the sensor unplugged, its last valid reading is used for
  `tank_unknown_grace_minutes` (10 by default). After that every cycle is
  refused with reason `tank_unknown`, and one **Tank Offline** notification is
  sent. A second message follows when the tank reports again.
- A tank is also unknown when it reads outside 0–100 %, or has not reported for
  its `stale_after_minutes` (120 by default).

**Record** the level at which cycles stopped, the skip reason, the alert times,
and whether the manual run sent any command.

The tank is checked **once, before a cycle starts**. A tank that empties during
a shot does not stop that shot. Protecting the pump from running dry is the
float switch's job (see [HARDWARE.md](HARDWARE.md#a-float-switch-for-dry-run-protection)).
If you fitted one, test it here as well: with the float down, the pump must
not start, whatever Growspace Manager commands.

### 7. Invalid VWC

The moisture sensor reports a value that cannot be true.

**Steps**

1. Enable crop steering, in P1 or P2.
2. Find out what your probe reads in dry air. Hold it out of the substrate for
   a minute.
3. Feed the controller each of `-5`, `150`, `nan` and `0` in turn, for a few
   minutes each. A probe will not produce most of these, so set the moisture
   entity's state from **Developer tools → States**. The next real report
   overwrites it, so keep setting it, or point `soil_moisture_sensor` at a
   template sensor you control for the duration of this case.

**Expected**

- `-5`, `150` and `nan` are implausible. No automatic shot fires, the
  controller reads `inhibited` with reason `sensor_implausible`, and the alert
  from case 1 follows after its delay. An invalid reading is never treated as 0.
- **`0` is valid by default**, because a truly dry pot reads 0, so a shot can
  fire on it. If your probe read 0 in step 2, set
  `moisture_zero_is_implausible: true`. Then `0` behaves like the other three.

**Record** each value, the reason shown, and whether a shot fired.

### 8. Stale sensor

The moisture sensor stops reporting but keeps its last value.

**Steps**

1. Enable crop steering, in P1 or P2.
2. Stop the sensor's reports without making it `unavailable`. For example, take
   the battery out of a sensor whose integration keeps the last state, or stop
   the gateway it reports through.
3. Wait up to 50 minutes.

**Expected**

- The sensor becomes stale after three of the intervals it has been seen
  reporting at. That is never less than 5 minutes, and never more than
  `sensor_stale_after_minutes` (30 by default). A sensor that keeps repeating
  the same value still counts as reporting.
- Once it is stale, no automatic shot fires, and the controller reads
  `inhibited` with reason `sensor_stale`.
- The alert follows `sensor_alert_delay_minutes` (15) after it went stale.

**Record** the sensor's last report time, the time `sensor_stale` appeared, and
the alert time.

### 9. Service-call failure

The pump cannot be commanded.

**Steps**

1. **The pump reads OFF but will not switch on.** Use a switch whose
   `turn_on` raises an error, or that accepts it and never reports ON. The
   template switch from case 2, with a `turn_on` that does nothing, will do.
   Run three manual runs in a row, then a fourth.
2. Acknowledge the fault and put the working pump back. Run one good cycle.
3. **The pump is gone.** Unplug a Zigbee or Wi-Fi plug so its entity reads
   `unavailable`, then start one manual run.

**Expected** for step 1:

- If `turn_on` is refused, or the pump does not report ON within 10 s, OFF is
  sent and read back. The cycle is recorded as **not delivered**: it adds no
  water, does not count towards the daily caps, and does not restart a
  steering cooldown. The ledger gets a `cycle_not_delivered` row.
- The third such cycle in a row on the same pump latches
  `fault_on_command_failed:<pump>` or `fault_on_unconfirmed:<pump>`. The fourth
  run is refused.

**Expected** for step 2: a cycle that confirms ON starts the count again.

**Expected** for step 3: an unavailable pump cannot be read back OFF either, so
the **first** cycle latches `fault_off_unconfirmed:<pump>`, with OFF re-sent
every minute. `acknowledge_fault` is refused until the pump reads OFF again.

The consecutive count is held in memory, so a restart starts it again.

**Record** each run's outcome, the time each fault latched, and its reason.

### 10. Overlapping requests

Two requests want the same pump, or two pumps run at once.

**Steps**

1. **Same pump.** Start a manual run while a scheduled irrigation shot is
   running.
2. **Irrigation and drain.** Schedule a drain event inside a scheduled
   irrigation shot.
3. Watch both pumps' histories, not just the controller.

**Expected** for step 1:

- The newer request wins. The running shot is cancelled, which the reliability
  counters show as `irrigation.aborted.override`, and the manual run starts. A
  scheduled event that fires while an earlier one of the same kind is still
  running replaces it the same way.
- There should be exactly one cycle on the pump, and no ON left behind.

> **Known defect, current `prerelease`.** The new cycle does not wait for the
> cancelled one to finish closing. The cancelled cycle's OFF can therefore
> arrive after the new cycle's ON. The pump then stops early while the new
> cycle still books its full shot. If the OFF of the old cycle lands and the
> ON of the new one follows within its readback window, a
> `fault_off_unconfirmed` can also latch spuriously. Every outcome ends with
> the pump OFF, which is the safe direction. Until it is fixed, do not start a
> manual run over a running shot. Record what you see if you do.

**Expected** for step 2:

- Irrigation and drain are separate pumps with separate cycles. **There is no
  interlock**, and both can run at the same time. If your plumbing cannot take
  that, do not schedule them to overlap.

**Record** the ON and OFF times of every pump, and which request ran.

### 11. Manual override

A person takes the pumps over for a while.

**Steps**

1. Call `growspace_manager.set_override` with `subsystem: irrigation`,
   `duration: "00:10:00"` and a reason.
2. Switch the pump on and off by hand. Try a manual run.
3. Leave the pump ON by hand, and let the override expire.
4. Set another override **while a shot is running**.
5. Set another, restart Home Assistant, and check that it is still there.

**Expected**

- While the override holds, Growspace Manager sends the irrigation and drain
  pumps no command at all: no cycle, no fail-safe, no OFF. The controller
  reads `inhibited` with reason `manual_override`, and the override is listed
  in its `overrides` attribute.
- Switching the pump by hand raises nothing. The manual run is refused.
- The ledger records who set the override and why.
- At expiry, control resumes on the next decision. A pump still ON at that
  moment is an unexpected ON, and case 3 applies.
- An override set during a shot closes that shot first. Its OFF is the last
  command the pump gets.
- The override survives the restart. One that expired while Home Assistant was
  down ends at the next start.
- The emergency stop still reaches every output during an override.

**Record** the override's start and expiry times, every pump command in
between (there should be none), and the ledger entries.

### 12. Configuration change while armed

The pump mapping changes while a shot runs.

**Steps**

1. Start a 120 s manual run on pump A.
2. About 20 s in, change the growspace's irrigation pump to pump B from the
   card, or with `growspace_manager.set_irrigation_settings`.
3. After the shot, run one more cycle.
4. Repeat, but change the pump from the integration's **Configure** dialog
   instead. That dialog reloads the integration.

**Expected** for a change from the card or the service:

- The running shot keeps pump A until its planned end. Then pump A is switched
  off and read back as usual.
- The next cycle uses pump B.
- Within about a minute, Growspace Manager stops watching pump A and starts
  watching pump B. After that, switching pump A on by hand raises nothing.

**Expected** for a change through the Configure dialog:

- The reload cancels the running shot, and pump A is switched off and read
  back.
- The startup inhibit from case 4 then applies.

**Record** pump A's OFF time, the time of the first cycle on pump B, and any
reason the controller showed in between.

No configuration revision number exists yet. The report's proposed safety
model has one, but it has not been built, so write the timeline down yourself.

### 13. DST and time boundaries

**Do not change the clock on a host that runs a crop.** This case is about
knowing what happens, not making it happen.

**What to expect**

- **Shot lengths** are timed on a monotonic clock, so a clock change during a
  shot does not lengthen or shorten it.
- **Timer schedules** fire on local wall-clock time, following Home
  Assistant's own time triggers.
  - On the night the clocks go **forward**, a schedule time inside the skipped
    hour does not run that night. It runs the next day.
  - On the night the clocks go **back**, a schedule time inside the repeated
    hour runs **twice**, an hour apart. The minimum interval between scheduled
    cycles (5 minutes by default) does not stop the second one. The daily caps
    still bound it.
- **Crop-steering phase boundaries** are local-time arithmetic. Nothing
  exercises them across a transition.

**What to do**

Move any schedule time out of the hour your time zone changes in. In most of
Europe and North America that is between 02:00 and 03:00 local time.

**Verified?** No. No test exercises a DST transition or a clock jump, and the
simulated harness reports this case as not exercised.

> **Known defect, current `prerelease`.** For timer schedules, the daily cycle
> and volume counters are **never** reset at midnight. The reset is registered
> during setup and then cancelled immediately when the schedule listeners are
> built. The counters therefore grow from the moment Home Assistant starts.
> With the default caps (24 cycles and 20 L a day), scheduled irrigation stops
> with reason `cycle_limit` or `volume_cap` once the total since the last
> restart reaches them, and stays stopped until the next restart. Crop steering
> is not affected. Until this is fixed, check the controller each morning for
> those two reasons.
