# A Setup Preset Stamps Offered Modules, Never Targets

**Status:** Accepted

GSM#798 made the config flow create the first Growspace and store the Setup Preset the grower picked, but only as a label. Nothing read it, the card could not see it, and no service could change it. card#973 needs it to decide which steps its setup checklist offers: a drying room has no lights to map, and a soil tent has no irrigation pump to wire. It also requires that a preset stamps "feature visibility and which subsystems are offered, never cultivation targets", applied once and freely editable afterwards.

## Decision

1. **A preset stamps a [[Setup Module]] set, with [[Steering Mode]] semantics (ADR-0012).** `domain/setup_preset.py` holds one table from preset to the growspace type it creates and the modules it offers. Choosing a preset writes the full module map once and stores the preset as a label. From then on the modules are ordinary flags, edited one at a time through `update_growspace`'s `setup_modules`, and nothing reads the preset to decide behaviour. Re-choosing the declared preset re-stamps and discards hand edits, as re-selecting a Steering Mode does.
2. **The table offers modules; it does not rank them.** Lights and air are core and climate, irrigation and substrate are optional, in every room. card#973 fixes those roles, and "optional modules never block Dashboard ready" only holds if no preset can promote one. A preset decides only whether each module is offered.
3. **The type is stamped only at creation.** The config flow and `add_growspace` set `growspace_type` from the preset. A later stamp through `update_growspace` changes the modules alone. Retyping a live flower tent as a drying room is a change to how its plants are staged, not a visibility choice, and a checklist control must not be able to make it by accident.
4. **No target is written.** A stamp touches `setup_preset` and `setup_modules` and nothing else. Every preset is covered by a test that compares the whole serialized Growspace before and after the stamp.
5. **Unstamped stays unstamped, except for the canonical Growspaces.** `setup_modules` is `None` until the first stamp, and the card then offers everything. The canonical `mother`, `clone`, `dry` and `cure` Growspaces predate presets and are never created through one, but their room is not in doubt. The `get_data` identity block therefore reports the modules their room implies, and a module edit on one starts from that set rather than from "everything offered". The inference is a read, not a write: it never marks the Growspace as stamped.

## Consequences

- The wire gains `identity.setup_preset` (a string or `null`) and `identity.setup_modules` (a map of the five modules to booleans, or `null`). The card declares `setup_preset` as a string, not an enum, so adding a preset here cannot fail its `get_data` parse (card ADR-0031).
- As with ADR-0012, changing the table later does not re-stamp existing Growspaces. A correction reaches only a grower who re-chooses the preset.
- `update_growspace` refuses an undeclared preset or module at the schema. Every refusal is a `vol.Invalid` before any state is touched.
