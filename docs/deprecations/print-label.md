# Deprecation: the `growspace_manager.print_label` service

`growspace_manager.print_label` — the **Classic** label request, including its
`preview: true` form — is deprecated as of **1.2.3** and will be removed in
**2.0.0**.

Nothing changes yet. Through every 1.x release the service keeps working and
keeps printing the same label, byte for byte: since 1.2.3 it is answered by a
Compatibility Adapter that resolves the request once and renders it through
the same renderer Label Templates use. Home Assistant logs one warning per run
the first time the service is called, naming this page.

## Timeline

| Release                                 | What happens                                                                                                                                                                            |
| :-------------------------------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **1.2.3**                               | Deprecation announced. The Compatibility Adapter ships enabled in a stable release for the first time.                                                                                  |
| next stable after 1.2.3                 | The adapter's second stable release. After it, the duplicate fixed-coordinate paint code behind the adapter may be retired. That is internal: the service and its output do not change. |
| at least one further stable 1.x release | The last release that carries the service, still deprecated.                                                                                                                            |
| **2.0.0**                               | The service is removed.                                                                                                                                                                 |

2.0.0 removes it **only if** every caller below has a supported replacement
and no critical or high-severity migration defect is open. If that is not true
when 2.0.0 is cut, the removal moves, and this page and the changelog will
name the new version before it does. The removal will never land in a release
this page has not named.

## What to change

### Growspace Manager card

Card releases up to and including **v1.3.x** print by calling this service. On
a 2.0.0 backend their print buttons will fail.

Newer card releases (in prerelease as `v1.4.0-next.*`) print through Label
Templates instead, and need an integration that has them. The order that is
safe at every step is: integration to a 1.x release of 1.2.3 or later, then
the card, then — only once the card is upgraded — the integration to 2.0.0.
An older card keeps printing on every 1.x release.

### Dashboards

A dashboard button whose action calls `growspace_manager.print_label` has the
same deadline as an automation (see below). Printing from the card's own print
dialog is the supported path and needs no change on your side.

### Automations, scripts and service calls

**There is no replacement service yet.** Label Template printing is currently
reachable only over the WebSocket API described below, which a Home Assistant
automation or script cannot call.

A template-based print service is a precondition for removal, not an
afterthought: until it ships, 2.0.0 cannot remove `print_label`. When it does,
this section will show the before and after. Until then keep calling
`print_label` — it is supported for the whole of 1.x.

### Custom frontends and WebSocket clients

Print through a Label Template with a preview-then-print handshake. Both steps
name a template as `{"kind": ..., "id": ..., "revision": ...}`, a printer as
`device_id`, and optionally a printer profile, locale and density.

- **A strain label** — `growspace_manager/preview_label_record` with `strain`
  (and `phenotype`) returns an `approval_id` and the rendered raster; send both
  back to `growspace_manager/print_label_record` as `approval_id` and
  `expected_raster_identity`.
- **A plant label**, or several — `growspace_manager/preflight_label_batch`
  with `plant_ids` (a one-element list for a single plant), then
  `growspace_manager/print_label_batch` with the returned `preflight_id`.

## Fields that do not carry over

The Label Template routes accept no per-call overrides. Breeder, lineage and
breeder logo come from the strain library, so record them there instead of
passing `breeder`, `lineage` or `breeder_logo`. `base_url` has no equivalent.
If you depend on one of these, say so on the issue tracker before 2.0.0: an
advertised path without a replacement is exactly what holds the removal back.
