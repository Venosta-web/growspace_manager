# Deprecation: the `growspace_manager.print_label` service

`growspace_manager.print_label` — the **Classic** label request, including its
`preview: true` form — is deprecated as of **1.2.3** and will be removed in
**2.0.0**.

Through every 1.x release the service keeps working and keeps printing the same
label, byte for byte, through the Compatibility Adapter. New automations,
scripts, and dashboard buttons should call
`growspace_manager.print_label_template`, which prints saved records through a
published Label Template and the same production-safety decision as the
Growspace Manager card.

## Timeline

| Release                                 | What happens                                                                                                                                       |
| :-------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------- |
| **1.2.3**                               | Deprecation announced. The Compatibility Adapter isolates every Classic request, still painted by the Classic fixed-coordinate design.             |
| a later 1.x release                     | The adapter paints Classic labels through the same compiler Label Templates use, reproducing today's output.                                       |
| the two stable releases that follow     | That adapter ships enabled twice. Only then may the fixed-coordinate paint code be retired — internally: the service and its output do not change. |
| at least one further stable 1.x release | The last release that carries the service, still deprecated.                                                                                       |
| **2.0.0**                               | The service is removed.                                                                                                                            |

2.0.0 removes it **only if** every caller below has a supported replacement
and no critical or high-severity migration defect is open. If that is not true
when 2.0.0 is cut, the removal moves, and this page and the changelog will name
the new version before it does. The removal will never land in a release this
page has not named.

## What to change

### Growspace Manager card

Card releases up to and including **v1.3.x** print by calling the Classic
service. On a 2.0.0 backend their print buttons will fail.

Newer card releases (in prerelease as `v1.4.0-next.*`) print through Label
Templates instead, and need an integration that has them. The order that is
safe at every step is: integration to a 1.x release of 1.2.3 or later, then the
card, then — only once the card is upgraded — the integration to 2.0.0. An
older card keeps printing on every 1.x release.

### Automations, scripts and service calls

The replacement service accepts either:

- `strain` with an optional saved `phenotype`; or
- `plant_ids`, containing one or more live plant IDs in print order.

Choose the layout with either an explicit `template` reference or a
`label_size_id`, which uses that size's effective default. `device_id` is
required; `profile_id`, `density`, and `locale` are optional.

There is no preview or approval round trip. The service makes production
prints only: the template must be published, its Capability Profile must be
product verified, and the selected printer's calibration must be current. A
hard refusal prints nothing and, when a response is requested, returns
`outcome: refused` with the exact `blocked_by` reasons and a recovery action.
Calls made by automations and scripts without a Home Assistant user are allowed
through this production-only path; they gain no template-management,
calibration, evidence-label, or test-print authority.

#### Automation: plant label

Before:

```yaml
actions:
  - action: growspace_manager.print_label
    data:
      plant_id: 01JEXAMPLEPLANT
      device_id: printer-device-id
```

After, using the Label Size's effective default:

```yaml
actions:
  - action: growspace_manager.print_label_template
    data:
      label_size_id: growspace.stock.50x30.v1
      plant_ids:
        - 01JEXAMPLEPLANT
      device_id: printer-device-id
    response_variable: label_print
```

Use the same call for several plants by adding IDs to `plant_ids`. Every plant
is captured and preflighted before the first label prints.

#### Script: strain label with a named template

Before:

```yaml
sequence:
  - action: growspace_manager.print_label
    data:
      strain: Blue Dream
      phenotype: "#1"
      device_id: printer-device-id
```

After:

```yaml
sequence:
  - action: growspace_manager.print_label_template
    data:
      template:
        kind: named
        id: 01JEXAMPLETEMPLATE
      strain: Blue Dream
      phenotype: "#1"
      device_id: printer-device-id
      density: normal
    response_variable: label_print
```

Omit `response_variable` when the script does not need the structured result.
The physical print and its safety checks are unchanged.

### Dashboards

Printing from the card's own print dialog is already on the supported Label
Template path and needs no change. Migrate a dashboard button that calls the
Classic service as follows.

Before:

```yaml
type: button
name: Print plant label
tap_action:
  action: perform-action
  perform_action: growspace_manager.print_label
  data:
    plant_id: 01JEXAMPLEPLANT
    device_id: printer-device-id
```

After:

```yaml
type: button
name: Print plant label
tap_action:
  action: perform-action
  perform_action: growspace_manager.print_label_template
  data:
    label_size_id: growspace.stock.50x30.v1
    plant_ids:
      - 01JEXAMPLEPLANT
    device_id: printer-device-id
```

Dashboard actions do not consume service responses. A refused call still
prints nothing; use an automation or script with `response_variable` when the
dashboard must surface the exact blocker.

### Custom frontends and WebSocket clients

Interactive clients keep the preview-then-print handshake. Both steps name a
template as `{"kind": ..., "id": ..., "revision": ...}`, a printer as
`device_id`, and optionally a printer profile, locale and density.

- **A strain label** — `growspace_manager/preview_label_record` with `strain`
  (and `phenotype`) returns an `approval_id` and the rendered raster; send both
  back to `growspace_manager/print_label_record` as `approval_id` and
  `expected_raster_identity`.
- **A plant label**, or several — `growspace_manager/preflight_label_batch`
  with `plant_ids` (a one-element list for a single plant), then
  `growspace_manager/print_label_batch` with the returned `preflight_id`.

## Fields that do not carry over

- `preview: true` is **dropped**. The supported preview is the interactive
  Label Template flow in the card or the WebSocket preview API; there is no
  service preview mode.
- `base_url` has no replacement. Canonical backend-owned QR routes are used.
- `breeder`, `lineage`, `breeder_logo`, `fields`, `qr_target`, and all other
  per-call content overrides are not accepted. Save record content in the
  strain library and encode visibility and layout in the Label Template.
