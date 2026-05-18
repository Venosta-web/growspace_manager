# ADR 0002 — Service calls for drying data entry, not HA helper entities

**Status:** Accepted

## Context

The Drying & Curing Tracking spec described "input_number" entities for entering daily weight and moisture readings. In Home Assistant, `input_number` is a helper entity whose state is set by the user directly. The alternative is a service call (an action the user invokes with parameters).

## Decision

Use service calls (`log_drying_weight`, `log_moisture_reading`) for all drying data entry.

## Rationale

Every other data-entry pattern in this integration uses service calls: `log_drain_reading`, `water_plant`, `apply_ipm`, `capture_snapshot`. Using HA helper entities would require the integration to watch state-change events on external helpers, making the data flow indirect and harder to test. It would also break the architectural constraint that all mutable integration data flows through the coordinator via service calls.

Service calls are directly testable, appear in the integration's `services.yaml`, and map cleanly to the Lovelace card's form-submission pattern.

## Consequences

- Users cannot enter weight/moisture readings via the HA UI without a Lovelace card or automation.
- The integration's service API surface grows by two service calls.
- Existing `@handle_service_errors` and `service_registration.py` patterns apply without modification.
