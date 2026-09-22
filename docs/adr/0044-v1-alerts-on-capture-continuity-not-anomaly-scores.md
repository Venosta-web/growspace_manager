# ADR 0044 — V1 alerts on capture continuity, not Anomaly Scores

**Status:** Accepted

Decided on 2026-08-31 in
[workspace#75](https://github.com/Venosta-web/growspace_manager_workspace/issues/75),
after the scene-comparison limits, symptom-output boundary, Evidence Fusion and frame
quality policy were settled by workspace issues #62, #68, #69 and #74.

V1 sends one kind of new visual-system alert: a warning-level **Capture Continuity
Break** after three consecutive automatically scheduled captures from one camera are
non-comparable. An Anomaly Score, Visual Comparison Result or Evidence Fusion Outcome
never creates a plant-health alert or notification. Existing environmental stress and
mold alerts continue unchanged and fusion neither duplicates nor escalates them.

## Evidence permits an equipment claim, not a plant-health claim

The only available production corpus contains 109 frames from one camera and one
healthy Grow Run. It contains no real plant-health positive. Every real high-distance
population is camera- or scene-shaped: reframes, lens occlusion, harvest and lights-off.
The 35-frame stable Baseline Bucket produced no false `material_scene_change` verdict,
and the quality gate rejected all 13 lights-off frames with no rejection among 75 clean
frames. These measurements support the claim that captures have stopped matching the
camera's recent history. They do not support a claim about why, or about plant health.

Synthetic symptom perturbations remain engineering probes and regression inputs. They
are not product-efficacy evidence: localized synthetic chlorosis fired less than one
third of the time, and camera changes outranked plant perturbations. V1 therefore makes
no plant-health sensitivity claim.

## Alert boundary and lifecycle

The Capture Continuity Break from Growspace Vision ADR 0005 is evaluated per camera.
Only automatically scheduled captures participate; a manual capture neither advances
nor resets the streak. A scheduled capture is non-comparable when the Frame Quality
Gate rejects it or its Visual Comparison Result is `material_scene_change`.
`uncertain`, transport failures and unavailable comparisons do not advance the streak.

The third consecutive non-comparable capture:

- activates one Capture Continuity Break;
- creates one `capture_continuity_break` Triage Alert at `warning` severity; and
- sends one warning-tier Home Assistant notification.

Later captures in the same streak create no additional alert or notification. The
first automatically scheduled comparable capture clears the active condition and
re-arms a later streak. Clearing does not acknowledge the durable Triage Alert: it
remains in the Inbox until the grower resolves it, so a short recovery cannot erase an
equipment event before it is seen.

The alert identifies the camera, streak start, consecutive count, reason counts and
latest capture. It names no cause and carries no plant verdict, probability, Bayesian
evidence or AI-generated reasoning. Its canonical message is:

> Camera captures no longer match recent history. Inspect the camera, lens, lighting,
> and growspace. Restart the visual baseline only if the framing change was
> intentional.

## Triage Alert becomes a tagged union

The current Triage Alert contract assumes every record is a Bayesian stress or mold
transition. Reusing its required `bayesian_reasons`, probability and `ai_reasoning`
fields for an equipment condition would manufacture evidence. The V1 contract instead
becomes a tagged union with common identity, growspace, type, severity, title,
description, timestamps, condition status and resolution fields:

- `stress` and `mold` retain Bayesian evidence and optional AI enrichment;
- `capture_continuity_break` carries camera identity, streak evidence,
  `condition_active` and `cleared_at`, and cannot carry Bayesian or AI fields.

Condition status and grower acknowledgement are separate. A cleared equipment
condition may still have an unresolved Triage Alert. One alert is created per streak,
even when an earlier streak's alert has not yet been acknowledged.

## Fusion remains observe-only

ADR 0040's `critical_scene_issue` is renamed `persistent_visual_anomaly`. It remains
the observe-only Evidence Fusion State produced by two consecutive automatically
scheduled, full-confidence `material_scene_change` results. The old name suggested a
plant or safety urgency that the evidence does not establish.

The fusion state and Capture Continuity Break remain distinct. Fusion can show a
persistent visual observation after two scored analyses; the continuity condition
alerts after three non-comparable scheduled captures and also covers quality
rejections, for which no Visual Comparison Result exists.

No Anomaly Score threshold, `visual_anomaly`,
`concurrent_environmental_risk_and_visual_anomaly`, or
`persistent_visual_anomaly` outcome creates a Triage Alert or notification.
`environmental_risk` continues to reuse the existing stress or mold alert without
duplication, and coexistence with a visual anomaly does not escalate its severity.

## User-visible calibration boundary

Baseline readiness and plant-health calibration are separate concepts. Thirty
comparable captures can make a Baseline Bucket `ready`; they cannot validate detection
of a symptom that has never occurred. The visual evidence surface states the boundary
beside the evidence rather than hiding it in settings or dismissible onboarding:

- `monitoring`: **Building scene baseline: N of 30 comparable captures.**
- `ready`: **Scene-change monitoring only. Plant-health detection is not calibrated
  for this camera.**
- `stale`: **Scene baseline is stale. Comparisons resume after enough recent
  comparable captures.**

A single grower-confirmed event does not calibrate a camera and never removes the
disclosure.

## Acceptance claims

V1 acceptance tests and corpus replay may assert only that:

- visually unchanged evidence plus environmental risk produces `environmental_risk`,
  never visual stress;
- no Anomaly Score or visual/fused state creates a plant-health alert;
- environmental alerts are neither duplicated nor escalated by fusion;
- the third consecutive scheduled non-comparable capture creates exactly one
  continuity alert and notification;
- a scheduled comparable capture clears and re-arms the condition, while manual
  captures cannot manipulate the streak;
- the healthy stable bucket produces no scene-change or continuity alert;
- normal late-flower fade does not alert;
- the measured lights-off and sustained camera/occlusion sequences produce continuity
  breaks; and
- UI copy and notifications make no plant-health sensitivity claim.

Synthetic symptom perturbations may guard implementation behavior but cannot satisfy
an acceptance claim about detection sensitivity.

## Unlocking a later plant-health alert

Workspace issue #68's symptom-output gate still applies first: at least 30 dated,
grower-labelled real-positive frames for one named symptom across at least two Grow
Runs; worst-case AUC at least 0.90 against synthetic and real camera-event populations;
and sensitivity measured at a threshold with zero in-bucket false alarms.

An unsolicited plant-health alert has a stricter gate. It additionally requires:

1. at least 30 independently labelled positive **episodes**, so repeated frames of one
   event cannot masquerade as independent sensitivity evidence;
2. a prespecified alert threshold evaluated on held-out data;
3. at least 90% event-level sensitivity at that threshold;
4. zero false alert streaks over at least 3,300 comparable healthy scheduled captures,
   making the one-sided 95% upper false-alert bound approximately one per camera-year
   at three captures per day; and
5. a prospective shadow-mode period whose release evidence was not used to train or
   choose the threshold.

Until every criterion is met for a named symptom, its outputs and alerts remain absent.

## Considered options

- **Fully observe-only V1** was rejected because the corpus validates a narrower,
  useful equipment claim and sustained loss of comparable captures requires grower
  attention.
- **Alerting on one Anomaly Score** was rejected because every real high-score event in
  the healthy corpus was camera- or scene-shaped.
- **Alerting on persistent fusion states** was rejected because persistence changes
  confidence in scene departure, not its cause or plant-health meaning.
- **Provisional plant-health wording** was rejected because uncertainty copy cannot
  manufacture missing sensitivity evidence.
- **Synthetic-validated plant alerts** were rejected because synthetic symptoms test
  the perturbations we imagined, not how this camera photographs a real condition.
