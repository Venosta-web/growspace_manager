"""Tests for the Vision Explainer prompt.

The load-bearing tests here are the contamination tests.  The stage this module
replaces reported petiole reddening and leaf curl on a visibly healthy canopy
because the environmental block sat directly above "Analyze the attached camera
image(s)".  Three layers guard against its return, in increasing strength:

1. **The sweep** — hold the photograph fixed, move every environmental input
   across its range, and assert the Visual Observation Pass prompt does not move.
   This is the ticket's literal acceptance criterion.
2. **The vocabulary scan** — assert no environmental term reaches that prompt by
   any route, including one added later through a field that exists today.
3. **The signature** — assert the pass has no parameter through which
   environmental evidence could arrive at all.  Layers 1 and 2 prove the builder
   ignores what it is given; this one proves it cannot be given it, so
   contamination requires a visible signature change that fails this test.
"""

from __future__ import annotations

import dataclasses
import inspect
import itertools

import pytest

from custom_components.growspace_manager.domain.evidence_fusion import (
    ConfidenceQualifier,
    EnvironmentalVerdict,
    EvidenceCoverage,
    EvidenceFusionState,
)
from custom_components.growspace_manager.domain.vision_explainer_prompt import (
    ENVIRONMENTAL_VOCABULARY,
    VISION_EXPLAINER_SCHEMA,
    VISION_EXPLANATION_SCHEMA,
    VISION_OBSERVATION_SCHEMA,
    EnvironmentalEvidence,
    ExplanationPassInput,
    FusionSummary,
    ObservationPassInput,
    TrendEntry,
    VisualEvidence,
    build_explanation_prompt,
    build_observation_prompt,
    environmental_terms_in,
    observation_from_visual_comparison,
)
from custom_components.growspace_manager.models.vision_evidence import (
    BaselineState,
    ComparisonOutcome,
    ComparisonVerdict,
    LightWindow,
    ObservationSource,
)

# Every environmental state the fusion inputs can take, as the sweep ranges over
# them.  Reasons are drawn from the real Bayesian vocabulary so that a leak would
# be recognisable in the failure output.
_STRESS_REASONS = (
    (),
    ("VPD 1.8 kPa is above the flower-stage band",),
    ("Soil moisture 12% is below the acceptable band", "Leaf temperature high"),
)
_MOLD_REASONS = (
    (),
    ("Humidity 78% with lights off for 4 hours",),
)


def _environments() -> list[EnvironmentalEvidence]:
    """Return the full environmental input range."""
    return [
        EnvironmentalEvidence(verdict=verdict, stress_reasons=stress, mold_reasons=mold)
        for verdict, stress, mold in itertools.product(
            EnvironmentalVerdict, _STRESS_REASONS, _MOLD_REASONS
        )
    ]


def _visuals() -> list[VisualEvidence]:
    """Return a representative range of Visual Comparison Results."""
    return [
        VisualEvidence(
            outcome=ComparisonOutcome.SCORED,
            verdict=verdict,
            anomaly_score=score,
            comparison_confidence=1.0,
            baseline_state=BaselineState.READY,
        )
        for verdict, score in (
            (ComparisonVerdict.NORMAL, 0.40),
            (ComparisonVerdict.UNCERTAIN, 0.93),
            (ComparisonVerdict.MATERIAL_SCENE_CHANGE, 1.0),
        )
    ] + [
        VisualEvidence(
            outcome=ComparisonOutcome.MONITORING,
            baseline_state=BaselineState.MONITORING,
            samples_collected=11,
            samples_required=30,
        ),
        VisualEvidence(
            outcome=ComparisonOutcome.UNAVAILABLE,
            unavailable_reasons=("vision_unavailable", "frame_rejected"),
        ),
    ]


def _fusions() -> list[FusionSummary]:
    """Return the full fusion outcome range, available and not."""
    return [
        FusionSummary(
            state=state,
            confidence=ConfidenceQualifier.CONFIRMED,
            coverage=EvidenceCoverage.COMPLETE,
        )
        for state in EvidenceFusionState
    ] + [FusionSummary(unavailable_reasons=("baseline_monitoring",))]


# --- Layer 1: the sweep -----------------------------------------------------


def test_observation_prompt_does_not_move_when_the_environment_does():
    """The ticket's acceptance criterion.

    Hold the photograph and its timing fixed; sweep every environmental input
    across its range.  The Visual Observation Pass prompt must be byte-identical
    every time, because none of those inputs can reach it.
    """
    fixed = ObservationPassInput(light_window=LightWindow.MID, photograph_count=1)
    baseline = build_observation_prompt(fixed)

    for environment, visual, fusion in itertools.product(
        _environments(), _visuals(), _fusions()
    ):
        # The explanation pass is what varies; the observation pass shares its
        # world and must be untouched by it.
        build_explanation_prompt(
            ExplanationPassInput(
                observation="A canopy.",
                observation_source=ObservationSource.IMAGE_PASS,
                fusion=fusion,
                environment=environment,
                visual=visual,
                trend=(
                    TrendEntry(
                        evaluated_at="2026-08-30T06:00:00+00:00",
                        verdict=ComparisonVerdict.NORMAL,
                        anomaly_score=0.2,
                        fusion_state=EvidenceFusionState.NO_DETECTED_CHANGE,
                    ),
                ),
            )
        )
        assert build_observation_prompt(fixed) == baseline


def test_observation_prompt_varies_only_with_its_own_inputs():
    """The sweep is not passing because the prompt is a constant."""
    one = build_observation_prompt(
        ObservationPassInput(light_window=LightWindow.EARLY, photograph_count=1)
    )
    two = build_observation_prompt(
        ObservationPassInput(light_window=LightWindow.LATE, photograph_count=2)
    )
    assert one != two


# --- Layer 2: the vocabulary scan -------------------------------------------


@pytest.mark.parametrize("light_window", list(LightWindow))
@pytest.mark.parametrize("grid_overlay", [True, False])
def test_observation_prompt_names_no_environmental_measurement(
    light_window, grid_overlay
):
    """No environmental term reaches the observation pass by any route."""
    prompt = build_observation_prompt(
        ObservationPassInput(
            light_window=light_window,
            photograph_count=2,
            grid_overlay=grid_overlay,
        )
    )
    assert environmental_terms_in(prompt) == ()


def test_timing_descriptions_carry_no_interpretation():
    """The old timing labels told the model what to expect before it looked.

    "peak transpiration period" and "end-of-day stress check" are framing, not
    scheduling.  Every light window's description must survive the scan.
    """
    for window in LightWindow:
        prompt = build_observation_prompt(
            ObservationPassInput(light_window=window, photograph_count=1)
        )
        assert environmental_terms_in(prompt) == ()


def test_the_vocabulary_scan_can_fail():
    """A leak is detectable — the scan is not vacuously true."""
    assert "vpd" in environmental_terms_in("VPD is 1.6 kPa")
    assert environmental_terms_in("a photograph of each canopy") == ()


# --- Layer 3: the signature -------------------------------------------------


def test_the_observation_pass_cannot_receive_environmental_evidence():
    """The invariant proper: there is no parameter to contaminate.

    Layers 1 and 2 prove the builder ignores environmental input it is handed.
    This proves it is handed none, so reintroducing the failure means changing a
    signature this test reads.
    """
    parameters = inspect.signature(build_observation_prompt).parameters
    assert list(parameters) == ["inputs"]
    assert parameters["inputs"].annotation == "ObservationPassInput"

    fields = {field.name for field in dataclasses.fields(ObservationPassInput)}
    assert fields == {"light_window", "photograph_count", "grid_overlay"}

    for name in fields:
        assert environmental_terms_in(name) == ()


def test_the_explanation_pass_receives_no_image():
    """Its binding rule is true, not aspirational: there is no image field."""
    fields = {field.name for field in dataclasses.fields(ExplanationPassInput)}
    assert not {"image", "images", "attachment", "attachments"} & fields


# --- The output schemas -----------------------------------------------------


def test_the_explainer_emits_no_severity():
    """Severity is an Evidence Fusion output; the LLM must not overrule it."""
    for schema in (
        VISION_OBSERVATION_SCHEMA,
        VISION_EXPLANATION_SCHEMA,
        VISION_EXPLAINER_SCHEMA,
    ):
        assert "severity" not in {str(key) for key in schema.schema}


def test_the_explainer_emits_no_symptom_vocabulary():
    """V1 has no validated classifier behind a machine-readable symptom claim."""
    keys = {str(key) for key in VISION_EXPLAINER_SCHEMA.schema}
    assert keys == {
        "observation",
        "environmental_risk",
        "hypothesis",
        "recommendations",
    }


def test_the_explanation_pass_cannot_revise_the_observation():
    """The report's observation is the observation pass's own words."""
    assert "observation" not in {str(key) for key in VISION_EXPLANATION_SCHEMA.schema}


def test_an_empty_explanation_is_valid():
    """Empty is an honest answer when the evidence supports nothing."""
    VISION_EXPLAINER_SCHEMA(
        {
            "observation": "The canopy fills the frame evenly.",
            "environmental_risk": "",
            "hypothesis": "",
            "recommendations": [],
        }
    )


# --- Degradation ------------------------------------------------------------


def test_a_report_without_a_photograph_says_so():
    """No report may imply an inspection that did not happen."""
    for visual in _visuals():
        text = observation_from_visual_comparison(visual)
        assert "No photograph was read" in text
        assert "how the plants look" in text or "not about the plants" in text


def test_monitoring_is_not_reported_as_no_change():
    """A baseline still collecting is not a finding of no change."""
    text = observation_from_visual_comparison(
        VisualEvidence(
            outcome=ComparisonOutcome.MONITORING,
            samples_collected=11,
            samples_required=30,
        )
    )
    assert "11 of 30" in text
    assert "no change" not in text.lower()


def test_the_explanation_pass_works_without_a_photograph():
    """The image-off path is the same prompt, differently labelled."""
    prompt = build_explanation_prompt(
        ExplanationPassInput(
            observation=observation_from_visual_comparison(
                VisualEvidence(
                    outcome=ComparisonOutcome.SCORED,
                    verdict=ComparisonVerdict.NORMAL,
                    anomaly_score=0.3,
                    comparison_confidence=1.0,
                )
            ),
            observation_source=ObservationSource.VISUAL_COMPARISON_ONLY,
            fusion=FusionSummary(
                state=EvidenceFusionState.ENVIRONMENTAL_RISK,
                confidence=ConfidenceQualifier.CONFIRMED,
                coverage=EvidenceCoverage.COMPLETE,
            ),
            environment=EnvironmentalEvidence(
                verdict=EnvironmentalVerdict.RISK,
                stress_reasons=("VPD 1.8 kPa is above the flower-stage band",),
            ),
            visual=VisualEvidence(
                outcome=ComparisonOutcome.SCORED,
                verdict=ComparisonVerdict.NORMAL,
                anomaly_score=0.3,
                comparison_confidence=1.0,
            ),
        )
    )
    assert "no photograph was read" in prompt
    assert "You have not seen any photograph" in prompt


# --- The explanation prompt's own content -----------------------------------


def test_the_explanation_prompt_labels_every_evidence_origin():
    """Keeping origins apart is the whole job."""
    prompt = build_explanation_prompt(
        ExplanationPassInput(
            observation="Leaf tips curl downward in B2 and C3.",
            observation_source=ObservationSource.IMAGE_PASS,
            fusion=FusionSummary(
                state=EvidenceFusionState.CONCURRENT_ENVIRONMENTAL_RISK_AND_VISUAL_ANOMALY,
                confidence=ConfidenceQualifier.CONFIRMED,
                coverage=EvidenceCoverage.COMPLETE,
            ),
            environment=EnvironmentalEvidence(
                verdict=EnvironmentalVerdict.RISK,
                stress_reasons=("VPD 1.8 kPa is above the flower-stage band",),
                mold_reasons=("Humidity 78% with lights off for 4 hours",),
            ),
            visual=VisualEvidence(
                outcome=ComparisonOutcome.SCORED,
                verdict=ComparisonVerdict.MATERIAL_SCENE_CHANGE,
                anomaly_score=1.0,
                comparison_confidence=1.0,
                baseline_state=BaselineState.READY,
            ),
            trend=(
                TrendEntry(
                    evaluated_at="2026-08-30T12:00:00+00:00",
                    verdict=ComparisonVerdict.NORMAL,
                    anomaly_score=0.31,
                ),
            ),
        )
    )
    assert (
        "EVIDENCE FUSION OUTCOME (decided by Growspace Manager, not by you)" in prompt
    )
    assert "OBSERVATION (read from the attached photographs" in prompt
    assert "VISUAL EVIDENCE (how far this camera's view has moved" in prompt
    assert "ENVIRONMENTAL EVIDENCE (this growspace's Bayesian evaluation" in prompt
    assert "TREND (earlier scored comparisons" in prompt


def test_the_explanation_prompt_states_the_binding_rule():
    """The exact wording settled in hub#71."""
    prompt = build_explanation_prompt(
        ExplanationPassInput(
            observation="A canopy.",
            observation_source=ObservationSource.IMAGE_PASS,
            fusion=FusionSummary(unavailable_reasons=("vision_unavailable",)),
            environment=EnvironmentalEvidence(verdict=EnvironmentalVerdict.UNAVAILABLE),
            visual=VisualEvidence(
                outcome=ComparisonOutcome.UNAVAILABLE,
                unavailable_reasons=("vision_unavailable",),
            ),
        )
    )
    assert (
        "Environmental measurements and risk evaluations describe the growspace, "
        "not the plant's appearance. You have not seen an image."
    ) in prompt
    assert "do not assign a severity of your own" in prompt


def test_unavailable_environment_is_not_reported_as_normal():
    """A zero from zero observations is unavailable, never reassurance."""
    prompt = build_explanation_prompt(
        ExplanationPassInput(
            observation="A canopy.",
            observation_source=ObservationSource.IMAGE_PASS,
            fusion=FusionSummary(unavailable_reasons=("vision_unavailable",)),
            environment=EnvironmentalEvidence(verdict=EnvironmentalVerdict.UNAVAILABLE),
            visual=VisualEvidence(outcome=ComparisonOutcome.UNAVAILABLE),
        )
    )
    assert "This is not evidence of normal conditions." in prompt


def test_the_trend_carries_no_previous_narrative():
    """Feeding narratives back would make a hallucination into history."""
    fields = {field.name for field in dataclasses.fields(TrendEntry)}
    assert fields == {"evaluated_at", "verdict", "anomaly_score", "fusion_state"}


def test_every_environmental_term_is_lowercase_and_unique():
    """The scan lowercases its input, so an uppercase entry would never match."""
    assert list(ENVIRONMENTAL_VOCABULARY) == sorted(set(ENVIRONMENTAL_VOCABULARY))
    assert all(term == term.lower() for term in ENVIRONMENTAL_VOCABULARY)
