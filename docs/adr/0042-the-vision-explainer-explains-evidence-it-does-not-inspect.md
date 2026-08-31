# The Vision Explainer explains evidence; it does not inspect

**Status:** Accepted

Decided on 2026-08-31 in
[hub#71](https://github.com/Venosta-web/growspace_manager_workspace/issues/71), after
the strict Vision boundary
([hub#67](https://github.com/Venosta-web/growspace_manager_workspace/issues/67)), the
measured symptom limits
([hub#68](https://github.com/Venosta-web/growspace_manager_workspace/issues/68)), the
Evidence Fusion state machine ([ADR 0040](./0040-evidence-fusion-reports-observations-not-plant-health.md)),
and the evidence store ([ADR 0041](./0041-home-assistant-owns-vision-evidence-in-a-dedicated-store.md)).

The cloud LLM stage is demoted from diagnostician to explainer. It receives the
Evidence Fusion Outcome, the visual evidence, the environmental evidence and the
temporal trend, each labelled with its origin, and it produces prose. It produces no
verdict, no severity and no machine-readable symptom claim.

## The failure being fixed

`VisionCheckupScheduler._build_vision_prompt` interpolated the full environment block
— sensor readings, Bayesian stress and mold probabilities _with their reasons_, and
the moisture-band interpretation — directly above "Analyze the attached camera
image(s)". The model was told the plant was probably stressed and then asked what it
saw, and duly reported petiole reddening and leaf curl on a visibly healthy canopy.

The existing MOISTURE INTERPRETATION RULE is a prose patch for exactly that failure
mode on exactly one sensor. More prose does not fix it: **a rule the model may ignore
is not an invariant.**

## Two passes that cannot see each other's inputs

The explainer is two calls, not one prompt:

- the **Visual Observation Pass** receives the photographs and the light window. It
  has no parameter through which environmental evidence, a fusion state, a trend or a
  previous narrative could arrive;
- the **Evidence Explanation Pass** receives the observation text, the fusion outcome,
  both evidence channels and the trend — and no image.

Contamination is therefore impossible by construction rather than by instruction, and
the binding rule's second sentence ("You have not seen an image") is _true_ rather than
aspirational. The rule reads in full:

> Environmental measurements and risk evaluations describe the growspace, not the
> plant's appearance. You have not seen an image. Every statement about what the plant
> looks like must come from the OBSERVATION block above, quoted or paraphrased from it
> and nothing else. Never write that an environmental measurement is visible,
> apparent, or showing on the plant.

The split pays off three more times. The observation is carried into the report
verbatim from the first pass and the second pass never returns it, so the explanation
cannot revise what was seen. Removing the image from V1 later is a deletion of one
call rather than an edit to prose. And the contamination test becomes a deterministic
assertion with no model in the loop.

A single call with an output-side validator was rejected: a scan for leaked
measurement vocabulary is a guard with false negatives, defeated by paraphrase, and it
would have been the only thing standing between the two evidence channels.

## The timing labels were themselves contamination

The previous prompt described the mid checkup as the "peak transpiration period" and
the late one as an "end-of-day stress check". That is framing, not scheduling: it told
the model what to expect before it had looked. The observation pass states the clock
position and nothing more.

## Inputs and their origins

The explanation pass renders five labelled blocks: the fusion outcome (`decided by
Growspace Manager, not by you`), the observation and where it came from, the visual
evidence (`how far this camera's view has moved from its own recent history`), the
environmental evidence (`this growspace's Bayesian evaluation of its own sensors`),
and the trend.

**The trend is measurements only** — earlier scored comparisons and their fusion
states. Previous explainer narratives are never fed back in: a hallucinated symptom
would otherwise become tomorrow's established history.

Environmental evidence arrives as the normalized verdict and the Evaluation Snapshots'
reasons, never raw sensor values, per ADR 0040. Environmental observations remain
structurally forbidden from the Growspace Vision request.

## Output schema

Three schemas, in `domain/vision_explainer_prompt.py`:

| schema                      | fields                                                |
| --------------------------- | ----------------------------------------------------- |
| `VISION_OBSERVATION_SCHEMA` | `observation`                                         |
| `VISION_EXPLANATION_SCHEMA` | `environmental_risk`, `hypothesis`, `recommendations` |
| `VISION_EXPLAINER_SCHEMA`   | all four — the stored report                          |

`severity` is gone from all three. Severity is an Evidence Fusion output and the
explainer must not be able to overrule it; the cleanest enforcement is that there is
no field to write it into. `issues_detected` is gone too: a symptom keyword list is a
machine-readable health claim, and hub#68 settled that V1 has no validated classifier
to stand behind one. The explainer may still _describe_ what it sees in prose — that
is the one thing a VLM can contribute that the local channel cannot — but a
description is not a taxonomy, and only a taxonomy gets consumed by downstream logic.

Empty values are legal and meaningful. An empty `hypothesis` is the honest output when
the evidence supports none.

**Contradiction is not suppressed.** Nothing stops the explanation from writing
something the fusion state does not support. The prompt instructs that the state is
given and must be explained rather than revised, and the presentation carries the rest:
the severity badge and the state come from fusion, the narrative renders as attributed
commentary subordinate to them. A contradiction detector was rejected because we have
no way to validate one.

## Degradation

With no AI task configured there is no report, no error and no empty state. The
evidence rendering _is_ the report: the fusion state, the visual verdict with its
confidence, and the Bayesian reasons are complete without any LLM, and all of them
already read as human language. An absent explainer is a configuration, not a
degradation.

Whether the observation pass runs at all is `ai_settings.vision_explainer_sees_image`,
default `true`. When it is off — or when it fails — the observation is derived from the
Visual Comparison Result, recorded as `observation_source = 'visual_comparison_only'`,
and it says outright that no photograph was read and that nothing was assessed about
how the plants look. A report can never imply an inspection that did not happen. A
failure of the _explanation_ pass stores nothing: a report is the four fields together
or it is not a report.

## Storage

A tenth table, `vision_explainer_report`, in the evidence store of ADR 0041, keyed by
`capture_id` with the same cascade and durability as every other evidence row. The
frozen `vision_checkup_history` keeps its existing rows and stops receiving new ones;
it is not migrated, exactly as ADR 0041 decided. `VISION_EVIDENCE_SCHEMA_VERSION`
stays at 1 because the store implementation is deferred and no database file has ever
been created.

The fusion outcome is **snapshotted** into the report rather than joined from the
comparison result. A narrative written against `environmental_risk` is uninterpretable
once the fusion transition table moves underneath it — the same reasoning that put
`scoring_policy_version` on a comparison result, and the same conclusion: the
reconstruction is expensive and the text is free.

## Validation

`tests/domain/test_vision_explainer_prompt.py` guards the invariant in three layers:

1. **The sweep** — hold the photograph and timing fixed, move every environmental
   input across its range (verdict × stress reasons × mold reasons × fusion state ×
   visual outcome), and assert the observation prompt is byte-identical every time.
   This is hub#71's literal acceptance criterion.
2. **The vocabulary scan** — assert no environmental term reaches that prompt by any
   route. Matching is by whole word, because `ec` and `ph` are real measurements that
   also live inside `each` and `photograph`. Digits are deliberately not forbidden:
   the grid sector labels and the photograph count are numerals with no environmental
   meaning.
3. **The signature** — assert the pass has no parameter through which environmental
   evidence could arrive. Layers 1 and 2 prove the builder ignores what it is handed;
   this proves it is handed none, so reintroducing the failure requires a visible
   signature change that fails the test.

A live-model test is not in CI. It would be measuring the model, not the boundary, and
the boundary is the thing this decision is about.

## Named home and what is deferred

`domain/vision_explainer_prompt.py` holds the frozen input value objects, both prompt
builders, the observation fallback and the three schemas. Pure: no Home Assistant
import, no clocks, no I/O, following the `plant_lifecycle.py` and `evidence_fusion.py`
precedents.

`domain/evidence_fusion.py` is created here with its **enums only** —
`EnvironmentalVerdict`, `EvidenceFusionState`, `ConfidenceQualifier`,
`EvidenceCoverage`. ADR 0040 named that module and deferred it; the explainer needs the
vocabulary now, and defining it twice would guarantee drift. `fuse_evidence(...)` and
its value objects stay deferred exactly as ADR 0040 decided.

Deferred to
[hub#73](https://github.com/Venosta-web/growspace_manager_workspace/issues/73): every
call site. Fetching the fusion outcome, assembling the trend, issuing either
`ai_task.async_generate_data` call, writing the report row, and the card's migration
off `severity` and `issues_detected`. The same line ADR 0040 and ADR 0041 drew.

**One change does land in the live path**, because it had no such dependency: the
`CANOPY COVERAGE: n% … (calculated via HSV color filtering)` line is deleted from
`_build_vision_prompt`. The statistic varies 31.5% inside one fixed camera's healthy
bucket (hub#68), so stating it as a measured fact beside the image handed the model a
quantity to reason from that does not mean what it appears to mean. This absorbs
[hub#76](https://github.com/Venosta-web/growspace_manager_workspace/issues/76).

The MOISTURE INTERPRETATION RULE deliberately **stays** until the two-pass builder is
wired in. Weak as it is, it is the only counterweight currently standing between the
sensor block and the image; removing it before the structural replacement lands would
make contamination worse, not better.

## Considered options

- **More prose in one prompt** — rejected as the failure mode itself.
- **A single call with an output-side contamination validator** — rejected: a guard
  with false negatives, defeated by paraphrase.
- **Keeping `severity` and instructing the model not to overrule fusion** — rejected;
  a field that exists gets written to.
- **A structured `hypothesis` with machine-readable supporting evidence** — rejected as
  a symptom taxonomy by another name.
- **Feeding previous explainer narratives in as trend** — rejected: it turns a
  hallucination into established history.
- **Suppressing an explanation that contradicts the fusion state** — rejected; the
  detector would be unvalidatable, and presentation already carries the weight.
- **Removing the image from V1 outright** — not taken. The map's settled position is
  that the explainer may still see it, with removal as a later flag-flip; the two-pass
  split makes that flip a deletion rather than a rewrite.
