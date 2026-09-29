# Hardware

Growspace Manager runs inside Home Assistant. **While Home Assistant is down,
it cannot switch anything off.** A crash, a power cut or a hung host leaves
every output in whatever state it was in. That includes a pump in the middle of
a shot. This page covers the protection that has to live in the hardware, and
lists which devices have actually been tested.

Two more limits come from the same place:

- **Readback reads what the device reports, not whether water flows.** A relay
  whose contact has welded shut reports OFF while the pump runs. Growspace
  Manager then has nothing to see.
- **The tank is checked before a shot, not during it.** A tank that runs dry
  halfway through a shot does not stop that shot.

Fit the protections below before you run the
[commissioning guide](COMMISSIONING.md), which checks several of them.

## Hardware fail-safes

### Normally-closed valves

Where water is held back by a valve rather than by a pump that is off, use a
**normally-closed** solenoid valve: one that closes when its power is cut. A
power failure, a relay that loses its supply and a cut wire then all end with
the valve shut.

Growspace Manager drives `switch` entities. It does not drive Home Assistant
`valve` entities, so a valve is driven through the relay that powers it.

### Relays and plugs that power up OFF

Most smart plugs and relays can be told what to do when their power comes back.
Many ship set to restore their last state, so a plug that was ON when the power
failed comes back ON. Nothing is there to switch it off until Home Assistant has
started, and under the default `unexpected_on_policy: alert` Growspace Manager
leaves a pump it finds running on
([commissioning case 5](COMMISSIONING.md#5-host-power-loss)).

Set every pump, valve and heater output to **power on OFF**. The setting's
name differs by ecosystem:

| Firmware or integration | Setting                                                                              |
| :---------------------- | :----------------------------------------------------------------------------------- |
| ESPHome                 | `restore_mode: ALWAYS_OFF` on the switch ([example below](#esphome-example))         |
| Tasmota                 | `PowerOnState 0`                                                                     |
| Shelly                  | The output's power-on default, set to Off                                            |
| Zigbee2MQTT             | `power_on_behavior: off`, where the device exposes it                                |
| ZHA                     | The device's start-up behaviour (`start_up_on_off`) configuration entity, set to Off |
| Matter                  | The power-on behaviour on start-up (`StartUpOnOff`) configuration entity, set to Off |

Menus change between firmware versions, so treat the table as a pointer. Then
prove the setting works: with the output ON, cut its power, restore it, and
check that it comes back OFF. That is step 3 of commissioning case 5.

### An on-device maximum ON time

An ON time limit that runs **on the device** stops the pump even when Home
Assistant never sends OFF. It is the only protection here that covers a host
that hangs or loses power while the relay stays powered.

| Firmware | How                                                                                                                       |
| :------- | :------------------------------------------------------------------------------------------------------------------------ |
| ESPHome  | A script restarted by every ON and stopped by every OFF (`max_on_guard` in the [example below](#esphome-example))         |
| Tasmota  | `PulseTime`. Values from 112 are seconds plus 100, so `PulseTime 760` switches the output off 660 s after it switched on. |
| Shelly   | The output's auto-off timer                                                                                               |

Set the limit **longer than any shot you will run**, so it never fires in
normal operation, and shorter than the time it takes to flood the room.
Growspace Manager cuts every cycle at `max_cycle_seconds`: 600 s by default,
and never more than 3600 s. A limit of `max_cycle_seconds` plus a minute is a
reasonable start.

A device limit that fires during a shot is not noticed by Growspace Manager.
It still counts the shot as delivered in full. That is one more reason to keep
the limit above your longest shot.

### A float switch for dry-run protection

A pump that runs dry can overheat and fail. A float switch in the tank that
cuts the pump's power when the level falls below the intake protects it, even
mid-shot and even with Home Assistant down.

- **Wire it to fail safe.** Use a float that is closed while there is water
  above it, so that a cut wire or an unplugged float reads the same as an empty
  tank.
- **Put it where the pump cannot get round it.** Either in series with the
  pump's supply, rated for the pump's current or switching a contactor, or as
  an input to the relay's own controller (as in the example below).
- **The same applies to a leak sensor.** One on the floor that cuts the pump's
  power directly stops a burst line from emptying the tank into the room.

How Growspace Manager sees it depends on where the float sits:

- **In the relay's controller**, as in the example: the relay refuses ON while
  the float is down, so the pump never reports ON. Growspace Manager records
  the cycle as not delivered, and the third in a row latches
  `fault_on_unconfirmed`
  ([case 9](COMMISSIONING.md#9-service-call-failure)).
- **In series with the pump's power**: the relay still reports ON, so
  Growspace Manager books the shot although no water moved. Use a tank level
  sensor as well, so its `low_tank` gate stops the cycles
  ([case 6](COMMISSIONING.md#6-empty-tank)).

## ESPHome example

One ESP32 drives the pump relay and reads the float switch. Home Assistant sees
a single switch, **Pump**, and a binary sensor for the float. On its own,
whatever Home Assistant is doing, the device:

- boots with the relay OFF, after a reboot, a crash or a power cut;
- switches the relay OFF after `max_on`, however it was switched on;
- switches the relay OFF, and refuses ON, while the float reads no water;
- reboots after 15 minutes without a Home Assistant connection, which also
  leaves the relay OFF.

The relay itself is `internal`, so Home Assistant can only reach it through the
template switch that checks the float. The template switch reports the relay's
real state. A refused ON therefore never reads ON, and Growspace Manager's
readback sees it.

**Status: compiled, not yet run on hardware.** On 2026-09-25 this exact file
compiled with ESPHome 2026.9.0 (ESP-IDF 5.5.5) for the `esp32dev` board. It
has not been flashed to a device. Bench-test it before you connect a pump:

1. Power-cycle the board with the relay ON. It must come back OFF.
2. Set `max_on` to `30s`, switch the relay on, and time it. Put it back
   afterwards.
3. Hold the float down, as an empty tank would leave it. The relay must
   switch off, and switching it on must do nothing.
4. Pull the float's wire out of its terminal. The result must be the same as
   step 3.

Replace the `!secret` values with your own, and pick pins that suit your board.

```yaml
# Growspace Manager: fail-safe pump relay for ESPHome.
# Compiled with ESPHome 2026.9.0 for an ESP32 (esp32dev board).
#
# Home Assistant sees one switch, "Pump". Map that to the growspace's
# irrigation (or drain) pump. The relay itself is internal, so nothing can
# switch it on without going through the float check below.
#
# What this device does on its own, whatever Home Assistant is doing:
#   - boots with the relay OFF, after a reboot, a crash or a power cut;
#   - switches the relay OFF after max_on, however it was switched on;
#   - switches the relay OFF, and refuses ON, while the float reads no water.

substitutions:
  name: pump-relay
  friendly_name: Pump relay
  # Avoid the ESP32 strapping pins (0, 2, 5, 12, 15): they can glitch at boot.
  relay_pin: GPIO26
  float_pin: GPIO27
  # Longer than your longest shot, and shorter than the time it takes to do
  # damage. Growspace Manager cuts a cycle at max_cycle_seconds (600 s by
  # default), so 11 minutes leaves room for its own OFF to arrive first.
  max_on: 11min

esphome:
  name: ${name}
  friendly_name: ${friendly_name}

esp32:
  board: esp32dev

logger:

api:
  encryption:
    key: !secret api_encryption_key
  # With no Home Assistant connected for this long the device reboots, and
  # the relay comes back OFF. 15 min is ESPHome's default; it is spelled out
  # here so nobody sets it to 0s without knowing what it did.
  reboot_timeout: 15min

ota:
  - platform: esphome
    password: !secret ota_password

wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password

binary_sensor:
  # Wire the float so that it CLOSES to GND while there is water above it.
  # A cut wire or an unplugged float then reads "no water", which is the
  # safe direction.
  - platform: gpio
    id: tank_water
    name: Tank water above float
    pin:
      number: ${float_pin}
      mode:
        input: true
        pullup: true
      inverted: true
    filters:
      # Ignore ripples on the surface.
      - delayed_on_off: 2s
    on_release:
      - logger.log:
          level: WARN
          format: "Float reads no water: pump relay OFF"
      - switch.turn_off: relay

switch:
  # The physical relay. Internal: Home Assistant cannot drive it directly.
  - platform: gpio
    id: relay
    pin: ${relay_pin}
    internal: true
    # Power-on state OFF, never restored from flash.
    restore_mode: ALWAYS_OFF
    on_turn_on:
      - script.execute: max_on_guard
      - lambda: id(pump).publish_state(true);
    on_turn_off:
      - script.stop: max_on_guard
      - lambda: id(pump).publish_state(false);

  # The switch Home Assistant sees. It reports the relay's real state, so a
  # refused ON never reads ON and Growspace Manager's readback catches it.
  - platform: template
    id: pump
    name: Pump
    icon: mdi:water-pump
    restore_mode: ALWAYS_OFF
    optimistic: false
    turn_on_action:
      - if:
          condition:
            binary_sensor.is_on: tank_water
          then:
            - switch.turn_on: relay
          else:
            - logger.log:
                level: WARN
                format: "Pump ON refused: float reads no water"
    turn_off_action:
      - switch.turn_off: relay

script:
  # The on-device max-on interval. Restarted by every ON, stopped by every OFF.
  - id: max_on_guard
    mode: restart
    then:
      - delay: ${max_on}
      - logger.log:
          level: WARN
          format: "Pump relay reached max_on: switching OFF"
      - switch.turn_off: relay
```

## What Growspace Manager needs from a device

- **Pumps** are `switch` entities that report the device's real state. Avoid
  optimistic or `assumed_state` switches, such as a template switch with no
  state of its own, or an RF plug with no feedback. Those report whatever
  they were last told, so every readback passes and a failure is never
  detected.
- **Substrate moisture** is a numeric sensor in % (0–100). **Pore EC** is in
  mS/cm or µS/cm; µS/cm is converted.
- **Tank level** is a numeric sensor in % (0–100). A sensor that only reports
  when its value changes needs `stale_after_minutes: 0`, or it will be
  declared unknown after two hours without a change.
- **Climate devices** (humidifier, dehumidifier, fans) are `switch`, `fan`,
  `humidifier` or `number` entities, or AC Infinity controller ports.
- **Label printers** are Niimbot printers through Home Assistant's `niimbot`
  integration.

## Supported and tested devices

Each row says who tested the device, when, and what was checked. The status is
one of:

| Status          | Meaning                                                                                                                                          |
| :-------------- | :----------------------------------------------------------------------------------------------------------------------------------------------- |
| Author-verified | The maintainer ran it on this physical device, and a dated record says what was checked.                                                         |
| User-reported   | A user reported it working on their hardware, and the row links the report. Not reproduced by the maintainer.                                    |
| Untested        | Nobody has recorded a run on physical hardware. It is expected to work because it presents standard entities. Automated tests do not count here. |

| Category         | Device                                                                           | Status          | Who         | When       | What was verified                                                                                                                                                                                                           |
| :--------------- | :------------------------------------------------------------------------------- | :-------------- | :---------- | :--------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Label printer    | Niimbot B1 (firmware 5.22, hardware 5.1), 50×30 mm labels, `niimbot` integration | Author-verified | Venosta-web | 2026-09-22 | 15 prints at three densities: edge ticks, text at 2.2 mm and 1.6 mm, QR codes at three payload sizes, a breeder logo, and a batch printed from the card. [Record](evidence/labels/niimbot-b1.50x30.v1/2026-09-22/run.json). |
| Label printer    | Other Niimbot models and label sizes                                             | Untested        | —           | —          | Automated tests only.                                                                                                                                                                                                       |
| Pump relay       | The [ESPHome example](#esphome-example) above                                    | Untested        | —           | 2026-09-25 | Compiled with ESPHome 2026.9.0 for `esp32dev`. Not flashed.                                                                                                                                                                 |
| Pump relay, plug | Any `switch` entity (Zigbee, Matter, Wi-Fi, ESPHome, Tasmota, Shelly)            | Untested        | —           | —          | No irrigation run on physical hardware has been recorded. The one commissioning run used simulated switches ([feature matrix](FEATURE_MATRIX.md#2026-09-24--irrigation-commissioning-simulated)).                           |
| Fans, lights     | AC Infinity controllers, through the `ac_infinity` integration                   | Untested        | —           | —          | Automated tests, and a simulated AC Infinity integration on the maintainer's development instance.                                                                                                                          |
| Climate          | Humidifiers, dehumidifiers and fans on switches, plugs or `fan` entities         | Untested        | —           | —          | Automated tests only.                                                                                                                                                                                                       |
| Sensor           | Substrate moisture (VWC) and pore EC probes                                      | Untested        | —           | —          | Automated tests, and simulated sensors on the development instance.                                                                                                                                                         |
| Sensor           | Tank level sensors                                                               | Untested        | —           | —          | Automated tests, and simulated sensors on the development instance.                                                                                                                                                         |
| Sensor           | Temperature, humidity and illuminance sensors                                    | Untested        | —           | —          | Automated tests, and simulated sensors on the development instance.                                                                                                                                                         |

No user reports have been recorded yet.

### Adding a device

If a device works for you, or does not, say so in
[Discussions](https://github.com/Venosta-web/growspace_manager/discussions) or
open a pull request against this table. Include:

- the device's model and firmware, and the Home Assistant integration it
  uses;
- your Home Assistant and Growspace Manager versions;
- the date;
- what you checked. For an irrigation output, that is the
  [commissioning cases](COMMISSIONING.md) you ran and what each one showed,
  plus the device's power-on setting.

"It turns on and off" is worth a row. Say that is all it was.
