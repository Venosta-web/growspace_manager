# ADR 0040 — Evidence fusion reports observations, not plant health

**Status:** Accepted

Decided on 2026-08-31 in
[workspace#69](https://github.com/Venosta-web/growspace_manager_workspace/issues/69),
after the strict Vision boundary and measured symptom limits were settled in
[workspace#67](https://github.com/Venosta-web/growspace_manager_workspace/issues/67),
[workspace#68](https://github.com/Venosta-web/growspace_manager_workspace/issues/68),
and
[Growspace Vision ADR 0004](https://github.com/Venosta-web/growspace_manager_vision/blob/2467a44fe46d0e281141c9d3dab175a805e67ac6/docs/adr/0004-rolling-empirical-baselines-report-scene-change.md).
Home Assistant will combine its current Bayesian environmental evaluations with its
own Visual Comparison Result. The fusion result reports only observed environmental
risk and departure from recent scene history. It never calls a plant healthy,
unhealthy, stressed, or visually symptomatic.

## Evidence boundaries

Environmental evidence comes from the current stress and mold Evaluation Snapshots,
not by evaluating raw target bands again. An adapter supplies each evaluation's
`evaluated_at` time and whether it had sufficient valid observations; the current
snapshot type does not yet preserve those facts. For a camera capture, an evaluation
is fresh only when it is the latest evaluation at or before the capture and is no more
than 30 minutes old, which is two coordinator intervals.

The normalized environmental verdict is:

- `risk` when any fresh, available stress or mold evaluation is active;
- `within_evaluated_range` only when fresh, available stress and mold evaluations both
  exist and are inactive;
- `unavailable` otherwise.

A zero probability produced from zero observations is unavailable, never evidence of
normal conditions. Fusion receives the normalized verdict and the snapshots' reasons,
not raw sensor values. Environmental observations remain structurally forbidden from
the Growspace Vision request.

Visual evidence comes from the Home Assistant-owned Visual Comparison Result, never
from the raw Anomaly Score or directly from a Growspace Vision response. Its available
verdict is `normal`, `uncertain`, or `material_scene_change`, with the Comparison
Confidence defined by Growspace Vision ADR 0004. The unavailable reasons are
`baseline_monitoring`, `baseline_stale`, `vision_unavailable`, and `frame_rejected`.
All reasons survive when more than one applies.

## Outcome model

The result is a tagged outcome:

- an available outcome contains exactly one Evidence Fusion State, a confidence
  qualifier (`confirmed` or `monitor`), and evidence coverage (`complete` or
  `partial`);
- an unavailable outcome contains the non-empty set of unavailable reasons.

The five Evidence Fusion States are:

1. `no_detected_change`
2. `environmental_risk`
3. `visual_anomaly`
4. `concurrent_environmental_risk_and_visual_anomaly`
5. `critical_scene_issue`

The concurrent state asserts co-occurrence, not correlation or causation. A normal
visual comparison means only that no material departure from recent scene history was
detected. It is not a healthy-plant verdict.

For the truth table, visual evidence is normalized as follows:

- **Unavailable:** any visual unavailable reason;
- **Normal:** verdict `normal`;
- **Monitor:** verdict `uncertain`, or `material_scene_change` with Comparison
  Confidence below `1`;
- **Confirmed:** `material_scene_change` with Comparison Confidence `1`, before
  persistence is met;
- **Persistent:** the same confirmed change after persistence is met.

Persistence is ignored for every visual input except `material_scene_change` with
Comparison Confidence `1`. This makes the function total even when a caller supplies
an irrelevant persistence flag.

| Environmental evidence | Visual unavailable                       | Visual normal                             | Visual monitor                          | Visual confirmed                                                        | Visual persistent                           |
| ---------------------- | ---------------------------------------- | ----------------------------------------- | --------------------------------------- | ----------------------------------------------------------------------- | ------------------------------------------- |
| Unavailable            | unavailable — preserve all reasons       | unavailable — environmental evidence      | `visual_anomaly`, monitor, partial      | `visual_anomaly`, confirmed, partial                                    | `critical_scene_issue`, confirmed, partial  |
| Within evaluated range | unavailable — visual evidence            | `no_detected_change`, confirmed, complete | `visual_anomaly`, monitor, complete     | `visual_anomaly`, confirmed, complete                                   | `critical_scene_issue`, confirmed, complete |
| Risk                   | `environmental_risk`, confirmed, partial | `environmental_risk`, confirmed, complete | `environmental_risk`, monitor, complete | `concurrent_environmental_risk_and_visual_anomaly`, confirmed, complete | `critical_scene_issue`, confirmed, complete |

The unavailable-environment/visual-monitor cell deliberately keeps a monitor-only
visual anomaly visible with partial coverage. Positive evidence from one channel is
not suppressed because the other channel failed. Conversely, `no_detected_change`
requires complete evidence from both channels. Low-confidence visual evidence never
produces the concurrent state.

## Persistence and precedence

`critical_scene_issue` requires two consecutive automatically scheduled
`material_scene_change` results with Comparison Confidence `1` for the same camera,
Grow Run, model version, and Framing Epoch. Each result must come from its light
window's ready Baseline Bucket, and the pair must occur within 24 hours. Any scheduled
normal, uncertain, rejected, or unavailable result breaks the streak. Manual checks
neither advance nor reset it.

Once persistence is met, `critical_scene_issue` takes precedence regardless of the
environmental verdict. V1 has no immediate critical path. Temporal tracking belongs to
the caller; the pure fusion function receives only `persistence_met: bool`.

## Triage and notification policy

V1 records and displays fusion outcomes but does not create a visual or fused Triage
Alert and does not send a visual notification. Workspace issue
[#75](https://github.com/Venosta-web/growspace_manager_workspace/issues/75) owns the
decision that can unlock those side effects.

- `no_detected_change` creates no alert.
- `environmental_risk` reuses the existing stress or mold Triage Alert and its existing
  severity; fusion does not duplicate it.
- `visual_anomaly` is observe-only and has presentation severity `info`.
- `concurrent_environmental_risk_and_visual_anomaly` retains the underlying
  environmental severity. Co-occurrence does not escalate it.
- `critical_scene_issue` reserves a future `visual_scene_change` Triage Alert with
  `warning` severity and a warning-tier notification. “Critical” describes fusion
  precedence and persistence, not plant danger, and the alert remains disabled until
  #75 explicitly enables it.

## Named home and testability

The future implementation belongs in
`custom_components/growspace_manager/domain/evidence_fusion.py`. It will expose enums,
frozen input/output value objects, and one total `fuse_evidence(...)` function. It must
not import Home Assistant or own clocks, history, persistence, storage, Triage Alerts,
or notifications. Those concerns remain in an outer orchestration layer, following
the `plant_lifecycle.py` and `environment_state_assembler.py` precedents.

Pure domain tests must cover every truth-table cell plus these invariants:

- unavailable evidence never becomes `no_detected_change`;
- a visually normal result plus environmental risk is `environmental_risk` and never a
  visual plant-health claim;
- monitor-only visual evidence never produces the concurrent or critical state;
- critical precedence is independent of the environmental verdict;
- persistence is ignored unless the visual verdict and confidence qualify;
- environmental fields remain invalid in the Growspace Vision request contract.

Production code is deferred until the Visual Comparison Result and HA-side storage
seams exist. This ADR fixes the interface and policy without creating speculative
plumbing against contracts that the surrounding roadmap has not implemented yet.

## Considered options

- **Raw environmental target bands** were rejected because they would duplicate the
  calibrated Bayesian policy and its stage-aware reasons.
- **Calling the absence of visual change “healthy”** was rejected because V1 has no
  validated plant-health classifier or symptom output.
- **`correlated_stress`** was rejected because simultaneous environmental risk and
  scene change do not establish correlation or causation.
- **Treating unavailable or zero-observation evidence as normal** was rejected because
  it creates false reassurance.
- **Immediate critical escalation** was rejected because a single material scene
  change can still be transient, manual, or camera-shaped.
- **Emitting alerts in this decision** was rejected because V1 sensitivity is not
  validated and workspace issue #75 owns the alerting gate.
