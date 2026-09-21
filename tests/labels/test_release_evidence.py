"""Physical evidence gates production printing (hub issue #230).

A profile's product-verified claim is honoured only with a complete, current
Release Evidence Record. Everything short of that is advertised, judged and
refused as provisional -- and a shipped profile making a claim its record
cannot back is a release failure rather than something to demote quietly.
"""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from custom_components.growspace_manager.labels.canonical import (
    NIIMBOT_B1_50X30,
    PROFILES,
)
from custom_components.growspace_manager.labels.canonical.evidence import (
    EvidenceDimension,
    current_dependencies,
    evidence_problems,
)
from custom_components.growspace_manager.labels.canonical.profiles import (
    ProfileEvidence,
)
from tests.labels.support import complete_evidence, product_verified

CAPABILITY_FIXTURE = (
    Path(__file__).parent.parent
    / "fixtures"
    / "contract"
    / "label_template_capability_v1.json"
)

CLAIMED = replace(NIIMBOT_B1_50X30, evidence=ProfileEvidence.PRODUCT_VERIFIED)


def _problems(**changes: object) -> tuple[str, ...]:
    record = replace(complete_evidence(CLAIMED), **changes)  # type: ignore[arg-type]
    return replace(CLAIMED, evidence_record=record).evidence_problems


def _with_result(dimension: EvidenceDimension, **changes: object) -> tuple[str, ...]:
    record = complete_evidence(CLAIMED)
    results = dict(record.results)
    results[dimension] = replace(results[dimension], **changes)  # type: ignore[arg-type]
    return _problems(results=results)


# ---------------------------------------------------------------------------
# What certifies a claim
# ---------------------------------------------------------------------------


def test_a_complete_current_record_certifies_the_claim() -> None:
    certified = product_verified(NIIMBOT_B1_50X30)
    assert certified.evidence_problems == ()
    assert certified.effective_evidence is ProfileEvidence.PRODUCT_VERIFIED
    assert certified.authorizes_production is True


def test_a_claim_without_a_record_is_provisional() -> None:
    assert CLAIMED.evidence_problems == ("evidence.record_missing",)
    assert CLAIMED.effective_evidence is ProfileEvidence.PROVISIONAL
    assert CLAIMED.authorizes_production is False


def test_a_provisional_profile_has_nothing_to_prove() -> None:
    assert NIIMBOT_B1_50X30.evidence_problems == ()
    assert NIIMBOT_B1_50X30.authorizes_production is False


def test_a_record_for_another_profile_does_not_transfer() -> None:
    assert "evidence.record_for_another_profile" in _problems(
        profile_id="growspace.profile.niimbot-b21.50x30.v1"
    )


def test_moving_the_measured_geometry_invalidates_the_record() -> None:
    record = complete_evidence(CLAIMED)
    moved = replace(CLAIMED, safe_area_inset_mm=1.5, evidence_record=record)
    assert "evidence.profile_changed" in moved.evidence_problems


def test_a_record_from_a_superseded_procedure_does_not_count() -> None:
    assert "evidence.procedure_superseded" in _problems(procedure="old")


@pytest.mark.parametrize(
    "field",
    [
        "printer_model",
        "firmware",
        "driver",
        "stock",
        "operator",
        "reviewed_by",
        "recorded_on",
        "reference",
    ],
)
def test_every_identity_of_the_combination_is_required(field: str) -> None:
    assert f"evidence.{field}_missing" in _problems(**{field: " "})


@pytest.mark.parametrize("dependency", sorted(current_dependencies()))
def test_a_dependency_change_returns_the_profile_to_provisional(
    dependency: str,
) -> None:
    record = complete_evidence(CLAIMED)
    stale = {**record.dependencies, dependency: "something-else"}
    problems = _problems(dependencies=stale)
    assert problems == (f"evidence.dependency_changed.{dependency}",)


def test_explicit_dependencies_are_what_a_record_is_held_to() -> None:
    record = complete_evidence(CLAIMED)
    assert evidence_problems(
        record,
        profile_id=CLAIMED.id,
        profile_definition=CLAIMED.definition_digest,
        rotations=(0,),
        densities=("normal",),
        dependencies={**record.dependencies, "compiler": "next"},
    ) == ("evidence.dependency_changed.compiler",)


@pytest.mark.parametrize("dimension", list(EvidenceDimension))
def test_every_dimension_of_the_matrix_must_be_run(
    dimension: EvidenceDimension,
) -> None:
    record = complete_evidence(CLAIMED)
    results = {key: value for key, value in record.results.items() if key != dimension}
    assert _problems(results=results) == (f"evidence.{dimension}.not_run",)


@pytest.mark.parametrize("dimension", list(EvidenceDimension))
def test_every_dimension_must_pass_measure_and_retain(
    dimension: EvidenceDimension,
) -> None:
    assert _with_result(dimension, passed=False) == (f"evidence.{dimension}.failed",)
    assert _with_result(dimension, measurements={}) == (
        f"evidence.{dimension}.unmeasured",
    )
    assert _with_result(dimension, artifacts=()) == (
        f"evidence.{dimension}.no_artifacts",
    )


def test_every_permitted_rotation_must_be_printed() -> None:
    wider = replace(CLAIMED, supported_element_rotations=(0, 90))
    record = complete_evidence(CLAIMED)
    assert (
        "evidence.rotation.incomplete"
        in replace(
            wider,
            evidence_record=replace(record, profile_definition=wider.definition_digest),
        ).evidence_problems
    )


def test_every_semantic_density_must_be_printed() -> None:
    assert _with_result(EvidenceDimension.DENSITY, covers=("normal",)) == (
        "evidence.density.incomplete",
    )


# ---------------------------------------------------------------------------
# What the product advertises and does
# ---------------------------------------------------------------------------


def test_an_unproven_claim_is_advertised_as_provisional_with_its_reasons() -> None:
    wire = CLAIMED.as_dict()
    assert wire["evidence"] == "provisional"
    assert wire["authorizes_production"] is False
    assert wire["evidence_invalidated_by"] == ["evidence.record_missing"]
    assert wire["evidence_reference"] is None


def test_a_certified_claim_advertises_its_record() -> None:
    wire = product_verified(NIIMBOT_B1_50X30).as_dict()
    assert wire["evidence"] == "product_verified"
    assert wire["authorizes_production"] is True
    assert wire["evidence_reference"] == "evidence/test-record"
    assert wire["evidence_recorded_at"] == "2026-09-21"
    assert wire["evidence_invalidated_by"] == []


def test_a_demoted_claim_keeps_its_declared_withdrawal_reasons() -> None:
    withdrawn = replace(CLAIMED, evidence_invalidated_by=("firmware 5.15",))
    assert withdrawn.as_dict()["evidence_invalidated_by"] == [
        "firmware 5.15",
        "evidence.record_missing",
    ]


def test_the_evidence_is_not_part_of_what_was_measured() -> None:
    """Attaching the record must not change the digest the record names."""
    assert product_verified(NIIMBOT_B1_50X30).definition_digest == (
        NIIMBOT_B1_50X30.definition_digest
    )


# ---------------------------------------------------------------------------
# The release gate on what ships
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", list(PROFILES.values()), ids=lambda p: p.id)
def test_no_shipped_profile_claims_more_than_its_record_proves(profile) -> None:  # type: ignore[no-untyped-def]
    """A claim the record cannot back is a release failure, not a demotion.

    Demotion is the runtime's fail-closed answer. Shipping it would publish a
    profile that says product-verified in source and provisional on the wire,
    and the release notes would be written from the wrong one.
    """
    assert profile.evidence_problems == ()
    assert profile.effective_evidence is profile.evidence


def test_the_advertised_capability_disables_production_without_evidence() -> None:
    envelope = json.loads(CAPABILITY_FIXTURE.read_text())
    for profile in envelope["catalogues"]["profiles"]:
        shipped = PROFILES[profile["id"]]
        assert profile["evidence"] == str(shipped.effective_evidence)
        assert profile["authorizes_production"] is shipped.authorizes_production
        if profile["evidence"] != "product_verified":
            assert profile["authorizes_production"] is False
