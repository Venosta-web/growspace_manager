# ADR 0043 — Vision Checkups migrate through versioned capture contracts

**Status:** Accepted

Decided on 2026-08-31 in
[workspace#73](https://github.com/Venosta-web/growspace_manager_workspace/issues/73),
after the Vision HTTP boundary, scene-comparison policy, Evidence Fusion, evidence
store and Vision Explainer were fixed by workspace issues #67, #66, #69, #70 and
#71.

Local vision changes the unit of truth. The cloud-era pipeline produced one
growspace-level `VisionCheckupResult` across every camera, with an LLM-authored
`severity` and `issues_detected`. Growspace Vision analyzes exactly one image per
request, and Home Assistant's Visual Comparison Result, Evidence Fusion Outcome,
provenance and failures all belong to one capture. A multi-camera checkup therefore
cannot honestly have one aggregate visual or fusion verdict.

The public V1 result is a versioned **Vision Checkup** envelope identified by a
UUIDv7 `checkup_id`. It owns the growspace, trigger source, light window, start and
completion times, and operational status (`completed`, `partial` or `failed`). Its
`captures` are **Vision Capture Results**, one per camera. Every capture carries its
identity and time, image availability, analysis state, quality result, visual
comparison, normalized environmental evidence, Evidence Fusion Outcome, a
measurement-only trend, model and scoring provenance, and an optional Vision
Explainer Report. It never carries an embedding vector, raw sensor readings,
baseline internals, `severity` or `issues_detected`.

There is no cross-camera fusion state. A checkup is `completed` when no capture
failed, `partial` when at least one capture failed and at least one reached another
terminal outcome, and `failed` when every capture failed. Quality rejection is a
recorded non-failure outcome rather than an exception that erases the attempt. A
known-unavailable Vision service fails a manual request before capture and scheduled work skips without
writing repetitive failed-history rows; a failure after image persistence leaves a
tracked failed capture.

## Durable identity

ADR 0041's evidence schema gains a `vision_checkup` table before the repository is
implemented, and every `vision_capture` references its `checkup_id`. Reconstructing a
multi-camera domain event from close timestamps was rejected: simultaneous scheduled
checks, retries and slow cameras make timestamp coincidence non-identity. The table
also gives the service response, history pagination and the existing growspace-level
sensor one durable source.

`limit` and `total` count checkups, not captures. The V1 history projection merges
new envelopes and frozen legacy rows by timestamp, newest first; `capture_total` is a
separate count where it helps the UI. A capture's trend contains at most seven earlier
scored comparisons for the same camera, Grow Run, model version, scoring-policy
version and Framing Epoch. It resets at any provenance boundary and contains only
timestamp, Anomaly Score, visual verdict and fusion state. Legacy rows, narratives
and embeddings never enter it.

## Wire shapes

The new WebSocket commands are
`growspace_manager/get_vision_status` and
`growspace_manager/get_vision_history_v2`. History items form a discriminated union:

```text
VisionCheckup {
  result_schema: "evidence_v1"
  checkup_id, growspace_id, trigger_source, light_window
  started_at, completed_at, status
  captures: VisionCaptureResult[]
}

LegacyVisionCheckupResult {
  result_schema: "legacy_cloud_v1"
  timestamp, check_type, snapshot_paths
  analysis, issues_detected, severity, recommendations
}
```

`VisionCaptureResult` is a presentation projection, not a dump of the evidence
database:

```text
VisionCaptureResult {
  capture_id, camera_id, captured_at, analysis_state
  image: { available, media_content_id? }
  quality: { accepted, reasons, metrics? }
  provenance: {
    vision_schema_version?, service_version?, model_id?, model_version?,
    scoring_policy_version?
  }
  visual: {
    outcome, baseline_state?, samples_collected?, samples_required?,
    raw_distance?, anomaly_score?, verdict?, comparison_confidence?,
    unavailable_reasons
  }
  environment: { verdict, evaluated_at?, stress_reasons, mold_reasons }
  fusion: { state?, confidence?, coverage?, unavailable_reasons }
  trend: { evaluated_at, anomaly_score, verdict, fusion_state? }[]
  report?: { observation, environmental_risk, hypothesis, recommendations }
}
```

Image storage paths never cross the wire. The contract carries a Home Assistant
`media_content_id`, which the card resolves through the authenticated media API. A
pruned image remains a valid history item with `available: false`.

The existing `trigger_vision_checkup` service remains the one public action. During
the compatibility window its response keeps the legacy keys the released card
requires and adds the canonical V1 envelope. For a V1 run the compatibility values
are deliberately non-assertive: `issues_detected: []`, `severity: "none"`, produced
snapshot paths, and the optional explainer prose and recommendations when available.
They are never stored and no new consumer reads them. Removal requires a separate
decision after a minimum card version can be enforced.

## Legacy history

The existing `Growspace.vision_checkup_history` remains frozen exactly as ADR 0041
decided. It is not migrated, amended, used by comparison, used by fusion or fed into a
trend. `severity` and `issues_detected` survive only inside
`LegacyVisionCheckupResult`, where the card presents them as attributed historical
cloud output under a visible **Legacy cloud analysis** label.

The new card presents one chronological Vision History. It maps each V1 capture to
its image and evidence while preserving legacy items as a marked tail. It derives
visual tone from the fusion contract: neutral for `no_detected_change`, informational
for visual-only anomaly, the existing environmental tone for environmental or
concurrent states, and warning for `critical_scene_issue`. There is no replacement
severity field.

## Availability and configuration

Local vision is required for every new checkup after cutover. An absent, stopped,
unreachable or incompatible service never silently falls back to the cloud-only
pipeline. The cloud Vision Explainer is optional after local evidence exists; with no
AI task configured, the visual comparison, environmental evidence and fusion outcome
remain a complete result.

Runtime status is a tagged projection:

```text
VisionStatus {
  availability: "ready" | "unavailable" | "incompatible"
  reason?: "not_installed" | "not_running" | "not_configured" |
           "unreachable" | "schema_mismatch" | "model_unavailable"
  connection_source: "supervisor" | "manual"
  service_version?, vision_schema_version?
  model?: { id, version, dimension }
}
```

The integration probes `/info` and `/models` during setup or reload, periodically in
its coordinator, and immediately before a manual checkup when the cached state is
stale. `get_vision_status` only reads that cache. The card displays the state and
model read-only, keeps camera and schedule editing available while disconnected, and
disables only **Run now** unless availability is `ready`.

Connection settings are integration-wide config-entry options, never repeated on a
growspace or exposed with their bearer token to the card. `connection_mode` is
`automatic` or `manual`: automatic pulls Supervisor discovery through `AddonManager`;
manual exclusively uses the configured endpoint and token. Switching to automatic
clears manual credentials, so there is no silent fallback to an unintended service.

Per-growspace `VisionCheckupConfig` retains only `enabled` and the early, mid and late
schedule. Its old `history_limit` remains accepted for legacy deserialization but is
absent from the V1 public config; evidence retention and history page size are
different concerns. The inert global `ai_settings.vision_checkup_enabled` is removed.
`ai_settings.vision_explainer_sees_image` controls only the optional observation
pass. Baseline size, scoring cuts, freshness, persistence and frame-quality policy are
versioned constants rather than user-editable thresholds.

The existing growspace Vision Checkup sensor keeps its entity identity but no longer
pretends several cameras have one severity. Its state becomes the latest checkup's
operational outcome (`completed`, `partial`, `failed` or `unavailable`) and its
attributes expose per-camera fusion summaries. Automations that need a particular
camera consume those explicit summaries.

## Zero-gap rollout and ordered file plan

The migration uses three release phases. The first lands the additive backend
contract without changing the live cloud-era producer. The second releases a card
that understands both contracts. Only the third cuts production over to local vision
and freezes legacy history. This preserves backend-first contract development without
creating a release window in which newly produced results disappear from the
installed card.

### Phase 1 — additive backend foundation

1. **HTTP boundary:** add
   `custom_components/growspace_manager/vision_models.py` and `vision_client.py`.
   Parse the normative Growspace Vision V1 fixtures strictly, negotiate `/info`, load
   `/models`, send one image per `/analyze`, and map typed transport, protocol,
   quality-rejection and service errors. Cover them in
   `tests/test_vision_client.py` and `tests/test_vision_models.py`.
2. **Durable evidence:** amend
   `custom_components/growspace_manager/models/vision_evidence.py` and
   `custom_components/growspace_manager/data_access/vision_evidence_schema.py` with
   the Vision Checkup record and capture foreign key, then implement
   `custom_components/growspace_manager/data_access/vision_evidence_store.py`. Add repository, migration, grouping,
   retention and failure-order tests beside `tests/test_vision_evidence_schema.py`.
3. **Pure decisions:** complete
   `custom_components/growspace_manager/domain/evidence_fusion.py` and add a pure
   `custom_components/growspace_manager/domain/vision_comparison.py`. Extend
   `custom_components/growspace_manager/notifications/evaluation_snapshot.py` with
   evaluation time and observation sufficiency, retain both active and inactive
   snapshots in `notification_manager.py`, and normalize them in a new
   `domain/environmental_evidence.py` so `within_evaluated_range` can be proved. Add
   `tests/domain/test_evidence_fusion.py`, `test_vision_comparison.py` and
   `test_environmental_evidence.py` for every ADR 0040 truth-table cell, freshness
   boundary, persistence rule, provenance reset and seven-entry trend boundary.
4. **Connection lifecycle:** centralize the unstable Home Assistant `AddonManager`
   import and cached status in
   `custom_components/growspace_manager/vision_connection.py`; add connection options
   and translations through `custom_components/growspace_manager/const.py`,
   `config_flow.py`, `config_handlers/ai_config_handler.py`, `strings.json` and
   `translations/en.json`. Construct and close the client/store/status collaborators
   in `coordinator_builder.py`, `coordinator.py` and `__init__.py`. Add
   `tests/test_vision_connection.py` and config-flow coverage for HAOS pull discovery,
   manual precedence, credential clearing, cache refresh and every status reason.
5. **Additive projection:** add one serializer shared by
   `custom_components/growspace_manager/presentation/vision.py` and consume it from
   `custom_components/growspace_manager/websocket/vision.py`,
   `custom_components/growspace_manager/services/vision_checkup.py` and
   `custom_components/growspace_manager/sensor/vision.py`; register
   `get_vision_status` and `get_vision_history_v2` while leaving the old producer and
   old history command intact. Cover the projection in
   `tests/presentation/test_vision.py`, `tests/core/test_websocket_snapshots.py`,
   `tests/services/test_vision_checkup.py` and `tests/test_vision_sensor.py`. This also
   fixes the current trigger-response drift in which the card requires
   `snapshot_paths` but the service omits it.
6. **Executable contract:** add backend-generated
   `tests/fixtures/contract/vision_status_response.json`,
   `vision_history_response.json` and `trigger_vision_checkup_response.json`, plus a
   `tests/contract/test_vision_contract.py` generator test. Fixtures cover ready and
   unavailable status, V1 completed/partial/rejected/failed captures, mixed legacy
   history, pruned images and both trigger response branches.

Phase 1 passes the Vision contract fixtures, targeted store/fusion/client tests and
the full backend gate. It is additive: the released card continues to parse every
old response and the live producer still writes its legacy list.

### Phase 2 — dual-contract card

7. **Schemas and state:** replace the cloud-only shape in
   `src/slices/camera/schema.ts` with the discriminated V1/legacy union and status
   schemas. Update `src/slices/camera/index.ts` so `visionHistory$` holds checkup
   envelopes, or remove the atom if the dialog remains its only real consumer. Remove
   the unused duplicate Vision result interface in `src/lib/types/dialog.ts`. Extend
   `src/slices/camera/camera.slice.test.ts`.
8. **Contract CI:** extend `.github/workflows/contract-fixture.yml` and
   `tests/contract/contract-fixture.test.ts` to fetch and validate all four backend
   fixtures from the current `prerelease` branch and latest published backend release.
   Against the release ref, the card's V1 fields and commands remain optional and it
   falls back to the legacy command; against `prerelease`, every emitted key is
   declared. This is the executable proof that the card phase is backward-safe.
9. **Configuration and gating:** carry status through the config-dialog shell and
   extend `src/features/config/viewmodels/vision-tab.viewmodel.ts` and
   `src/features/config/components/config-vision-tab.ts` with the read-only connection
   banner and model version. Remove the inert global switch from
   `src/dialogs/gm-settings-panel.ts`; add the explainer-image setting instead. Update
   `src/slices/growspace/schema.ts`, `src/adapters/growspace-adapter.ts`,
   `src/dialogs/config-dialog-sm.ts`,
   `src/features/config/environment-persistence.ts` and
   `src/dialogs/config-dialog.ts` only for the remaining per-growspace schedule fields.
10. **History UI:** replace severity-only projection in
    `src/features/camera/viewmodels/snapshots-dialog.viewmodel.ts` and
    `src/dialogs/snapshots-dialog.ts` with capture evidence, fusion, confidence, coverage,
    trend, provenance, image-unavailable handling and the explicit legacy branch.
    Resolve `media_content_id` through Home Assistant rather than constructing a
    `/local/` path. Cover multi-camera, partial, rejected, failed, disconnected,
    incompatible, legacy and mixed-history cases in the colocated view-model and
    component tests, then extend `tests/e2e/specs/vision-camera-profile.spec.ts`.

Phase 2 passes the release-ref backward-safety fixtures, prerelease completeness
fixtures, card fast checks and browser coverage against the additive backend. It may
release before the cutover because all new calls are capability-detected and the
legacy fallback is covered by the released fixtures.

### Phase 3 — backend cutover

11. **One orchestrator:** refactor
    `custom_components/growspace_manager/vision_checkup_scheduler.py` so it owns
    timing and delegates one capture at a time: persist checkup and capture, call local vision,
    compare, assemble fresh environmental evidence, fuse, optionally explain, store,
    and serialize. It stops requiring an AI task, stops appending
    `vision_checkup_history`, stops the cloud severity notification path, and never
    falls back to the old prompt. Update
    `custom_components/growspace_manager/services/vision_checkup.py`,
    `custom_components/growspace_manager/websocket/vision.py`,
    `custom_components/growspace_manager/sensor/vision.py`,
    `custom_components/growspace_manager/services.yaml`,
    `custom_components/growspace_manager/strings.json`,
    `custom_components/growspace_manager/translations/en.json` and their
    unit/integration tests.
12. **Compatibility proof:** regenerate the three Vision fixtures from the live V1
    producer, run the released-card fixture check against the additive compatibility
    response, then run the dual-contract card against the cutover backend. The old
    history command remains frozen and the trigger shim remains additive.

Phase 3 passes the full backend and card gates, a real HA browser run with a
multi-camera partial result, and an upgrade fixture containing ten legacy results.
The timeline must remain readable, the App status and model must be visible, and no
legacy claim may enter a V1 comparison, fusion, trend or explainer input.

## Rejected alternatives

- **One aggregate verdict per growspace:** rejected because the evidence, failure and
  provenance boundaries are per capture; aggregation would invent a policy not
  supplied by any model.
- **Mutate or copy legacy rows into SQLite:** rejected by ADR 0041; they lack capture
  identity and assert claims V1 intentionally cannot make.
- **Keep or rename severity:** rejected because fusion already provides the domain
  state and presentation mapping; a second field can disagree and the cloud-era enum
  cannot express the V1 `info`/`warning` semantics honestly.
- **Put endpoint, token or thresholds on `VisionCheckupConfig`:** rejected because
  connection is integration-wide, the token is secret, and policy versions—not user
  inputs—define comparability.
- **Cut the producer over in the first backend release:** rejected because the
  installed card could trigger local work but could not display its result.
- **Card-driven health checks:** rejected because runtime ownership and credentials
  belong to the integration, not a presentation client.
