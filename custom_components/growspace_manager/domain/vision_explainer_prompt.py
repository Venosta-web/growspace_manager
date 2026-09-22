"""The Vision Explainer — the optional cloud stage that explains evidence.

The stage this module replaces interpolated sensor readings, Bayesian stress and
mold probabilities *with their reasons*, and a moisture-band interpretation
directly above "Analyze the attached camera image(s)".  The model was told the
plant was probably stressed and then asked what it saw, and duly reported petiole
reddening and leaf curl on a visibly healthy canopy.  The MOISTURE INTERPRETATION
RULE was a prose patch for exactly that failure on exactly one sensor.

The fix is structural.  The explainer runs as two calls that cannot see each
other's inputs:

* the **Visual Observation Pass** receives the photograph and the timing, and
  nothing else.  It has no parameter through which environmental evidence could
  reach it, so contamination requires a signature change rather than a lapse of
  instruction-following;
* the **Evidence Explanation Pass** receives the observation text, the Evidence
  Fusion Outcome, both evidence channels and the trend — and no photograph.  Its
  binding rule ("You have not seen an image") is therefore true rather than
  aspirational.

The observation is carried into the report verbatim from the first pass; the
second pass never returns it and so cannot revise it.

What the explainer may not do: emit a severity (severity is an Evidence Fusion
output — ADR 0040), emit a machine-readable symptom vocabulary (hub#68 — there is
no validated classifier behind such a claim), or revise the fusion state.

Pure module: no hass, no I/O, no clocks.  See ADR 0042.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

import voluptuous as vol

from custom_components.growspace_manager.domain.evidence_fusion import (
    ConfidenceQualifier,
    EnvironmentalVerdict,
    EvidenceCoverage,
    EvidenceFusionState,
)
from custom_components.growspace_manager.models.vision_evidence import (
    BaselineState,
    ComparisonOutcome,
    ComparisonVerdict,
    LightWindow,
    ObservationSource,
)

# Every word that names an environmental measurement, an evaluation of one, or a
# piece of environmental equipment.  The Visual Observation Pass prompt must
# contain none of them: see ``tests/domain/test_vision_explainer_prompt.py``,
# which scans the built prompt against this list.
#
# Matching is by whole word, not substring — "ec" and "ph" are real measurements
# and also live inside "each" and "photograph".  Digits are deliberately *not*
# forbidden: the grid sector labels and the photograph count are numerals that
# carry no environmental meaning.
ENVIRONMENTAL_VOCABULARY: tuple[str, ...] = (
    "bayesian",
    "celsius",
    "co2",
    "deficiency",
    "dehumidifier",
    "dli",
    "dryback",
    "ec",
    "evaluation",
    "exhaust",
    "fahrenheit",
    "fan",
    "feed",
    "humidifier",
    "humidity",
    "irrigation",
    "kpa",
    "lux",
    "measurement",
    "moisture",
    "mold",
    "mould",
    "nutrient",
    "overwatering",
    "ph",
    "ppfd",
    "ppm",
    "probability",
    "reading",
    "readings",
    "reservoir",
    "runoff",
    "sensor",
    "sensors",
    "stress",
    "substrate",
    "temperature",
    "threshold",
    "transpiration",
    "underwatering",
    "vpd",
    "watering",
)

# Neutral descriptions of when a checkup was taken.  The strings the previous
# prompt used were themselves interpretive — "peak transpiration period" and
# "end-of-day stress check" told the model what to expect to see before it had
# looked.  Scheduling metadata states the clock position and nothing more.
_TIMING_DESCRIPTIONS: dict[LightWindow, str] = {
    LightWindow.EARLY: "1 hour after the lights turned on",
    LightWindow.MID: "6 hours into the light cycle",
    LightWindow.LATE: "1 hour before the lights turn off",
    LightWindow.MANUAL: "on request, outside the scheduled checkup times",
}

_GRID_REFERENCE = (
    "GRID REFERENCE: each photograph carries a 4x4 grid overlay, labelled A1-A4 "
    "across the top row through D1-D4 across the bottom row. When you name "
    "something, say where it is by naming the sector or sectors it appears in.\n\n"
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ObservationPassInput:
    """Everything the Visual Observation Pass is allowed to know.

    There is deliberately no field here through which environmental evidence, a
    fusion state, a trend or a previous narrative could arrive.  That absence is
    the invariant; the prompt's wording is only its restatement.
    """

    light_window: LightWindow
    photograph_count: int
    grid_overlay: bool = True


@dataclass(frozen=True, slots=True, kw_only=True)
class EnvironmentalEvidence:
    """The normalized environmental verdict and the reasons behind it.

    Reasons come from the stress and mold Evaluation Snapshots, never from raw
    sensor values (ADR 0040).
    """

    verdict: EnvironmentalVerdict
    stress_reasons: tuple[str, ...] = ()
    mold_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class VisualEvidence:
    """The Visual Comparison Result, as the explainer sees it.

    A verdict here describes departure from this camera's own recent history. It
    is not a health measurement and never becomes one.
    """

    outcome: ComparisonOutcome
    verdict: ComparisonVerdict | None = None
    anomaly_score: float | None = None
    comparison_confidence: float | None = None
    baseline_state: BaselineState | None = None
    samples_collected: int | None = None
    samples_required: int | None = None
    unavailable_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class TrendEntry:
    """One earlier scored comparison, for the temporal picture.

    Measurements only.  Previous explainer narratives are never fed back in: a
    hallucinated symptom would otherwise become tomorrow's established history.
    """

    evaluated_at: str
    verdict: ComparisonVerdict | None = None
    anomaly_score: float | None = None
    fusion_state: EvidenceFusionState | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class FusionSummary:
    """The Evidence Fusion Outcome the explanation must explain, not revise."""

    state: EvidenceFusionState | None = None
    confidence: ConfidenceQualifier | None = None
    coverage: EvidenceCoverage | None = None
    unavailable_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class ExplanationPassInput:
    """Everything the Evidence Explanation Pass receives.

    No image and no image attachment: the pass is text-only by construction.
    """

    observation: str
    observation_source: ObservationSource
    fusion: FusionSummary
    environment: EnvironmentalEvidence
    visual: VisualEvidence
    trend: tuple[TrendEntry, ...] = ()


# The structured output of each call, and of the stored report.
#
# The explanation pass does not return ``observation``: the report's observation is
# the observation pass's own words, carried across unchanged, so the second call
# has no opportunity to revise what was seen.  There is no ``severity`` field and
# no symptom keyword list in any of the three.
VISION_OBSERVATION_SCHEMA = vol.Schema({vol.Required("observation"): str})

VISION_EXPLANATION_SCHEMA = vol.Schema(
    {
        vol.Required("environmental_risk"): str,
        vol.Required("hypothesis"): str,
        vol.Required("recommendations"): [str],
    }
)

VISION_EXPLAINER_SCHEMA = vol.Schema(
    {
        vol.Required("observation"): str,
        vol.Required("environmental_risk"): str,
        vol.Required("hypothesis"): str,
        vol.Required("recommendations"): [str],
    }
)


def build_observation_prompt(inputs: ObservationPassInput) -> str:
    """Build the Visual Observation Pass prompt.

    The returned text is a function of the photograph count, the light window and
    whether the image carries a grid overlay. Nothing else can reach it.
    """
    photographs = "photograph" if inputs.photograph_count == 1 else "photographs"
    timing = _TIMING_DESCRIPTIONS.get(inputs.light_window, "at an unrecorded time")
    grid = _GRID_REFERENCE if inputs.grid_overlay else ""

    return (
        "You are describing what is visible in one or more photographs of a "
        "cannabis growspace canopy.\n\n"
        "You are given the attached photographs and nothing else. You have no "
        "other information about this growspace, and you must not guess at any.\n\n"
        f"TIMING: {inputs.photograph_count} {photographs}, taken {timing}.\n\n"
        f"{grid}"
        "Describe what you can see:\n"
        "1. Leaf posture: drooping, curling up or down, cupping, folding, wilting\n"
        "2. Leaf colour: yellowing, browning, purpling, bleaching, mottling, "
        "spotting, dead tissue\n"
        "3. Surfaces: webbing, powder, film, insects, holes, chewed edges, trails\n"
        "4. Canopy: height variation, density, gaps, uniformity, colour consistency\n"
        "5. Anything else visible, including the pots, the medium surface, and any "
        "equipment in frame\n\n"
        "Describe only what is visible in the photographs. Do not name a cause or "
        "a diagnosis. Do not say whether the plants are healthy or unhealthy. Do "
        "not recommend anything.\n\n"
        "If something is unclear, or a photograph is too dark, blurred or "
        "obstructed to judge, say so rather than guessing. Describing little is a "
        "correct answer when little is visible.\n\n"
        "Return your description as structured data:\n"
        "- observation: one paragraph describing what is visible"
        + (", naming grid sectors" if inputs.grid_overlay else "")
        + ".\n"
    )


def build_explanation_prompt(inputs: ExplanationPassInput) -> str:
    """Build the Evidence Explanation Pass prompt.

    Every block is labelled with where it came from, because the explanation's
    whole job is to keep those origins apart.
    """
    source = (
        "read from the attached photographs by a separate pass"
        if inputs.observation_source is ObservationSource.IMAGE_PASS
        else "derived from the scene-change comparison; no photograph was read"
    )

    return (
        "You are writing the explanation section of a growspace report.\n\n"
        "You have not seen any photograph. Every statement in this report about "
        "what the plants look like must come from the OBSERVATION block below.\n\n"
        f"EVIDENCE FUSION OUTCOME (decided by Growspace Manager, not by you):\n"
        f"{_render_fusion(inputs.fusion)}\n\n"
        f"OBSERVATION ({source}):\n{inputs.observation.strip() or '  (none)'}\n\n"
        "VISUAL EVIDENCE (how far this camera's view has moved from its own recent "
        f"history):\n{_render_visual(inputs.visual)}\n\n"
        "ENVIRONMENTAL EVIDENCE (this growspace's Bayesian evaluation of its own "
        f"sensors):\n{_render_environment(inputs.environment)}\n\n"
        f"TREND (earlier scored comparisons, newest first):\n"
        f"{_render_trend(inputs.trend)}\n\n"
        "RULES\n"
        "1. Environmental measurements and risk evaluations describe the "
        "growspace, not the plant's appearance. You have not seen an image. Every "
        "statement about what the plant looks like must come from the OBSERVATION "
        "block above, quoted or paraphrased from it and nothing else. Never write "
        "that an environmental measurement is visible, apparent, or showing on the "
        "plant.\n"
        "2. The visual evidence reports how far this scene has moved from its own "
        "recent history. It is not a measure of plant health. A material scene "
        "change is as likely to be a camera move, an occlusion, a harvest or new "
        "growth as anything wrong.\n"
        "3. The fusion outcome is given. Explain it; do not revise it, do not "
        "contradict it, and do not assign a severity of your own.\n"
        "4. A hypothesis is a candidate explanation, not a finding. Write it "
        "conditionally, and say what would confirm or rule it out.\n"
        "5. Empty is a valid answer. Return an empty hypothesis when the evidence "
        "supports none, and an empty recommendation list when no action is "
        "warranted.\n\n"
        "Return structured data:\n"
        "- environmental_risk: what the environmental evidence says about the "
        "growspace's conditions, in plain prose. Say so plainly when it is "
        "unavailable.\n"
        "- hypothesis: a candidate explanation that connects the evidence above, "
        "or an empty string.\n"
        "- recommendations: specific actions worth taking, or an empty list.\n"
    )


def observation_from_visual_comparison(visual: VisualEvidence) -> str:
    """Return the observation text used when no photograph was read.

    Used both when the Visual Observation Pass is switched off and when it fails.
    It states what the scene-change comparison found and, explicitly, that nothing
    looked at the plants — so a report can never imply an inspection that did not
    happen.
    """
    preamble = "No photograph was read for this checkup. "

    scored_descriptions: dict[ComparisonVerdict, str] = {
        ComparisonVerdict.NORMAL: (
            "this camera's view is consistent with its own recent history"
        ),
        ComparisonVerdict.UNCERTAIN: (
            "this camera's view sits in the uncertain range between its recent "
            "history and a material change"
        ),
        ComparisonVerdict.MATERIAL_SCENE_CHANGE: (
            "this camera's view has departed materially from its own recent history"
        ),
    }

    if visual.outcome is ComparisonOutcome.SCORED:
        described = (
            scored_descriptions[visual.verdict]
            if visual.verdict is not None
            else "this camera's view was scored without a verdict"
        )
        return (
            f"{preamble}The scene-change comparison found that {described}. "
            "That is a statement about the scene, not about the plants: no "
            "assessment of how the plants look was made."
        )

    if visual.outcome is ComparisonOutcome.MONITORING:
        collected = visual.samples_collected
        required = visual.samples_required
        progress = (
            f" ({collected} of {required} captures collected)"
            if collected is not None and required is not None
            else ""
        )
        return (
            f"{preamble}This camera's baseline is still being collected"
            f"{progress}, so no scene-change comparison was made either. Nothing "
            "was assessed about how the plants look."
        )

    reasons = ", ".join(visual.unavailable_reasons) or "no reason recorded"
    return (
        f"{preamble}No scene-change comparison was available either ({reasons}). "
        "Nothing was assessed about how the plants look."
    )


def _render_fusion(fusion: FusionSummary) -> str:
    """Render the fusion outcome block."""
    if fusion.state is None:
        reasons = ", ".join(fusion.unavailable_reasons) or "no reason recorded"
        return f"  Unavailable: {reasons}"
    lines = [f"  State: {fusion.state.value}"]
    if fusion.confidence is not None:
        lines.append(f"  Confidence: {fusion.confidence.value}")
    if fusion.coverage is not None:
        lines.append(f"  Evidence coverage: {fusion.coverage.value}")
    return "\n".join(lines)


def _render_visual(visual: VisualEvidence) -> str:
    """Render the visual evidence block."""
    if visual.outcome is ComparisonOutcome.UNAVAILABLE:
        reasons = ", ".join(visual.unavailable_reasons) or "no reason recorded"
        return f"  Unavailable: {reasons}"

    if visual.outcome is ComparisonOutcome.MONITORING:
        collected = visual.samples_collected
        required = visual.samples_required
        progress = (
            f" — {collected} of {required} captures collected"
            if collected is not None and required is not None
            else ""
        )
        return (
            f"  Baseline not yet valid{progress}. No comparison was made; this is "
            "not a finding of no change."
        )

    lines = [f"  Verdict: {visual.verdict.value if visual.verdict else 'none'}"]
    if visual.anomaly_score is not None:
        lines.append(
            f"  Anomaly score: {visual.anomaly_score:.2f} "
            "(rank against this camera's own recent history, 0 to 1)"
        )
    if visual.comparison_confidence is not None:
        lines.append(f"  Comparison confidence: {visual.comparison_confidence:.2f}")
    if visual.baseline_state is not None:
        lines.append(f"  Baseline: {visual.baseline_state.value}")
    return "\n".join(lines)


def _render_environment(environment: EnvironmentalEvidence) -> str:
    """Render the environmental evidence block."""
    if environment.verdict is EnvironmentalVerdict.UNAVAILABLE:
        return (
            "  Unavailable — no fresh evaluation with sufficient observations. "
            "This is not evidence of normal conditions."
        )
    if environment.verdict is EnvironmentalVerdict.WITHIN_EVALUATED_RANGE:
        return "  Within evaluated range — no active stress or mold evaluation."

    lines = ["  Risk — at least one active evaluation."]
    lines.extend(f"    Plant stress: {reason}" for reason in environment.stress_reasons)
    lines.extend(f"    Mold risk: {reason}" for reason in environment.mold_reasons)
    return "\n".join(lines)


def _render_trend(trend: tuple[TrendEntry, ...]) -> str:
    """Render the trend block."""
    if not trend:
        return "  No earlier comparisons recorded."
    lines = []
    for entry in trend:
        parts = [entry.evaluated_at]
        parts.append(entry.verdict.value if entry.verdict else "not scored")
        if entry.anomaly_score is not None:
            parts.append(f"score {entry.anomaly_score:.2f}")
        if entry.fusion_state is not None:
            parts.append(entry.fusion_state.value)
        lines.append(f"  {' — '.join(parts)}")
    return "\n".join(lines)


def environmental_terms_in(text: str) -> tuple[str, ...]:
    """Return every environmental term appearing as a whole word in ``text``.

    Exposed so the contamination test and any future guard share one definition of
    what counts as environmental vocabulary.
    """
    lowered = text.lower()
    return tuple(
        term
        for term in ENVIRONMENTAL_VOCABULARY
        if re.search(rf"\b{re.escape(term)}\b", lowered)
    )
