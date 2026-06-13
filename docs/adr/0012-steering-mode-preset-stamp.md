# Steering Mode is a preset stamp, not a live setting

Selecting a Steering Mode (`vegetative` / `balanced` / `generative`) writes the mode's recommended setpoints into the ordinary editable strategy fields **once**, then stores the mode as the grower's *declared intent*. The crop-steering loop never reads the mode — only the explicit fields. The mode therefore decays into a label the moment it is stamped: the grower may tweak any field afterwards, and the [[Measured Classification]] (derived from the live score) is reported *against* the declared intent as `intent_deviation` ("intended generative, substrate reads vegetative"). The score itself stays an absolute −1…+1 measurement and never bends toward the declared mode.

Re-selecting the already-declared mode re-stamps rather than no-ops — it doubles as "reset to this mode's defaults", deliberately discarding hand tweaks. `declared_steering_mode` is nullable; `None` ("never stamped") is a real third state distinct from an explicit `balanced`, so `intent_deviation` is `null` until the first stamp rather than falsely reading "on target".

## The preset table shape

The surprising part is *what varies by what*:

- **Percent shot sizes, in-cycle dryback, p2-stop offset, and the pore-EC band vary by media × mode.** These are genuinely agronomic: rockwool drybacks smaller and stacks EC higher than coco; generative stacks higher and stops watering earlier than vegetative.
- **Raw seconds defaults vary by mode only — not media.** A shot expressed in pump-seconds is meaningless without a specific pump flow rate and pot size (which is exactly why Volume Mode exists). Media-keying a pump-dependent number would imply a precision it cannot have, so the seconds presets are deliberately crude mode-only cadence fallbacks.
- **`soil` gets gentle, near mode-independent presets.** Professional crop steering (the AROYA methodology) is a coco/rockwool practice on low-buffer media. Soil is buffered; growers do not dryback-steer it the same way, and an aggressive generative dryback on soil is agronomically dubious. Rather than refuse to stamp on soil (a worse UX and an extra failure path), soil's three modes barely differ.
- **`target_vwc_percent` is never stamped.** It describes field capacity for a medium — a substrate/strain saturation property — not a steering direction. Stamping it per-mode would fight the grower's substrate choice.

The stamp writes only the **active** Shot Sizing Mode's representation (seconds *or* percent, never both): the coordinator only reads the active fields, so writing the inactive set would change nothing live while writing values the grower cannot see in their current UI mode.

## Baseline value table (HITL gate)

Adopted as the implementation baseline; individual cells still require maintainer sign-off on the implementation PR.

Volume Mode (percent of substrate volume) + dryback / p2-stop / pore-EC, by media × mode:

| media | mode | P1 % | P1 int | P2 % | P2 int | dryback % | p2_stop min | pore EC min–max |
|---|---|---|---|---|---|---|---|---|
| coco | veg | 2.0 | 5 | 2.0 | 20 | 2.0 | 60 | 2.5–4.0 |
| coco | balanced | 3.0 | 8 | 3.0 | 35 | 3.0 | 120 | 3.0–5.0 |
| coco | generative | 4.0 | 12 | 4.0 | 60 | 5.0 | 210 | 4.0–6.5 |
| rockwool | veg | 2.0 | 5 | 1.5 | 15 | 1.5 | 60 | 3.0–5.0 |
| rockwool | balanced | 3.0 | 8 | 2.5 | 30 | 2.5 | 120 | 4.0–6.0 |
| rockwool | generative | 4.0 | 12 | 4.0 | 55 | 4.0 | 210 | 5.0–8.0 |
| soil | veg | 2.0 | 8 | 2.0 | 30 | 2.0 | 60 | 1.5–3.0 |
| soil | balanced | 2.5 | 10 | 2.5 | 40 | 2.5 | 90 | 2.0–3.5 |
| soil | generative | 3.0 | 12 | 3.0 | 50 | 3.0 | 120 | 2.5–4.0 |

Seconds Mode (mode-only crude defaults):

| mode | P1 sec | P1 int | P2 sec | P2 int |
|---|---|---|---|---|
| veg | 8 | 5 | 6 | 20 |
| balanced | 10 | 8 | 8 | 35 |
| generative | 14 | 12 | 12 | 60 |

## Rejected alternatives

- **A live mode that the coordinator reads each tick.** Would make the mode authoritative and the explicit fields advisory — the inverse of every other strategy field, and it removes the grower's ability to hand-tune. The stamp keeps one source of truth: the explicit fields.
- **A uniform 9×8 table (every field varies by media × mode, including seconds and soil).** Simpler table shape, but it dresses up pump-dependent seconds as media-precise and pretends soil steers like rockwool.
- **Refusing to stamp on soil / requiring a profile first.** Agronomically honest but adds failure paths and blocks the common Seconds-Mode grower from a feature their sensors otherwise support (Sensor-Gated Capability spirit).

## Consequence

Once a grower stamps, the values bake into the stored strategy and survive across restarts; changing the baseline table later does not retroactively re-stamp existing growspaces. The mode is a one-shot expansion, so the table is a migration-free constant — but also means a table correction only reaches a grower who re-stamps.
