# Environment action metadata presents canonical patch fields

**Status:** Accepted

`configure_environment` remains the Home Assistant seam for public Environment Patch writes, but its curated `services.yaml` metadata presents only canonical field names. Runtime compatibility aliases remain accepted by `CONFIGURE_ENVIRONMENT_SCHEMA` and are tested separately; exposing both spellings would make the preferred interface ambiguous. A structural contract test keeps metadata field coverage, requiredness, and absence of top-level defaults aligned with the runtime schema and Environment Field Ownership, while descriptions and selectors remain curated because they carry user-facing judgment that cannot be generated from Voluptuous.

The Lovelace-card counterpart is ADR-0047. The two artifacts remain separately released: this decision adds no generated cross-repo artifact and does not change Home Assistant action names or payload semantics.

The Home Assistant options flow remains an adapter to the same `Environment Patch` domain module and keeps its current UX. Consolidating its duplicated commit helpers is a later slice: it must route both options-flow handlers through one adapter without moving validation or mutation policy back out of the domain seam.

## Considered Options

- Generate all metadata from Voluptuous. Rejected because useful selectors and descriptions contain information the validator does not own.
- Expose canonical and legacy aliases together. Rejected because compatibility acceptance is not the preferred public interface.
- Rely on hassfest alone. Rejected because hassfest validates metadata shape, not parity with the registered action schema or patch semantics.
