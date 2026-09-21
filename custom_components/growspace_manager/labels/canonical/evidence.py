"""[[Release Evidence Record]]: the physical proof a production profile needs.

CI can prove a raster is the one it was last time. It cannot prove a single
dot landed on paper. That proof is a person with a printer, a roll of stock, a
ruler and a phone, working through a fixed matrix -- and this module is the
shape the result of that work has to take before a [[Capability Profile]] may
authorize a production print.

A profile *claims* its evidence state. A claim of product-verified is honoured
only when a record is attached and the record is **complete** and **current**:

- complete: every dimension of the matrix was run, passed, left retained
  artifacts (rasters, photographs, scans) and covers everything the profile
  permits -- each element rotation and each semantic density it advertises;
- current: it was taken against this exact profile definition and the same
  compiler, renderer, adapter, fonts, QR model and safety policy that ship. A
  relevant dependency change is exactly the "firmware, stock, font, renderer,
  policy or mapping change" that returns a combination to provisional.

Anything short of that demotes the profile to provisional, names the reasons
in `evidence_invalidated_by`, and leaves production printing disabled. There
is no override: an unproven claim fails closed, and that is the whole point.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

#: The physical test procedure this record shape describes.
EVIDENCE_PROCEDURE_VERSION = "growspace.label-evidence-procedure.v1"


class EvidenceDimension(StrEnum):
    """One row of the physical matrix. Every one is required."""

    #: All four printable edges, the origin, feed alignment and repeated
    #: placement, measured against the profile's tolerances.
    EDGES = "edges"
    #: Every permitted element rotation and the stock orientation.
    ROTATION = "rotation"
    #: Every allowed font and style at the readable floor and the comfort
    #: threshold, with short, typical, long, accented and missing-glyph text.
    TEXT = "text"
    #: Shortest, typical and longest QR targets at every allowed size and
    #: error-correction level, scanned with the declared phone set.
    QR = "qr"
    #: High-contrast, grayscale, transparent and remote/embedded logos after
    #: canonical normalization.
    LOGO = "logo"
    #: Every semantic density at the device level the profile maps it to.
    DENSITY = "density"
    #: Repeated single prints: drift, first-page behaviour, missing bands.
    REPEATABILITY = "repeatability"
    #: A representative multi-record, multi-copy batch, with pacing and retry.
    BATCH = "batch"


@dataclass(frozen=True, slots=True)
class DimensionResult:
    """What one row of the matrix measured."""

    passed: bool
    #: The measured values, by name -- not a prose assertion that it looked
    #: right.
    measurements: Mapping[str, Any]
    #: Where the retained rasters, photographs and scans live.
    artifacts: tuple[str, ...]
    #: What this row exercised, where the profile says what must be: the
    #: rotations for `ROTATION`, the symbolic densities for `DENSITY`.
    covers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReleaseEvidenceRecord:
    """One reviewed physical evidence record for one Claimed Combination."""

    #: Where the record and its artifacts are kept.
    reference: str
    profile_id: str
    #: `CapabilityProfile.definition_digest` of the profile the prints were made with.
    profile_definition: str
    printer_model: str
    firmware: str
    #: The upstream printer integration and its version.
    driver: str
    stock: str
    procedure: str
    operator: str
    reviewed_by: str
    #: ISO date the matrix was run.
    recorded_on: str
    #: `current_dependencies()` as it was when the prints were made.
    dependencies: Mapping[str, str]
    results: Mapping[EvidenceDimension, DimensionResult]
    deviations: tuple[str, ...] = field(default_factory=tuple)


def current_dependencies() -> dict[str, str]:
    """The shipped identities a physical print depends on.

    Imported when asked rather than at module load: the modules that own these
    identities import the profile module, which imports this one.
    """
    from .catalogue import STYLE_TOKEN_CATALOGUE_VERSION  # noqa: PLC0415
    from .compiler import COMPILER_VERSION  # noqa: PLC0415
    from .fonts import TEXT_TOOLCHAIN_VERSION  # noqa: PLC0415
    from .qr import QR_MODEL_VERSION  # noqa: PLC0415
    from .result import ADAPTER_VERSION, RENDERER_VERSION  # noqa: PLC0415
    from .safety import SAFETY_POLICY_VERSION  # noqa: PLC0415

    return {
        "compiler": COMPILER_VERSION,
        "renderer": RENDERER_VERSION,
        "adapter": ADAPTER_VERSION,
        "text_toolchain": TEXT_TOOLCHAIN_VERSION,
        "style_tokens": STYLE_TOKEN_CATALOGUE_VERSION,
        "qr_model": QR_MODEL_VERSION,
        "safety_policy": SAFETY_POLICY_VERSION,
    }


def evidence_problems(
    record: ReleaseEvidenceRecord | None,
    *,
    profile_id: str,
    profile_definition: str,
    rotations: Iterable[int],
    densities: Iterable[str],
    dependencies: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Every reason one record cannot certify one profile, as stable codes.

    Empty means certified. The codes are what `evidence_invalidated_by`
    carries, so a card and a release note can both say which part of the
    matrix is missing without parsing a sentence.
    """
    if record is None:
        return ("evidence.record_missing",)
    problems: list[str] = []
    if record.profile_id != profile_id:
        problems.append("evidence.record_for_another_profile")
    if record.profile_definition != profile_definition:
        problems.append("evidence.profile_changed")
    if record.procedure != EVIDENCE_PROCEDURE_VERSION:
        problems.append("evidence.procedure_superseded")
    for name, value in (
        ("printer_model", record.printer_model),
        ("firmware", record.firmware),
        ("driver", record.driver),
        ("stock", record.stock),
        ("operator", record.operator),
        ("reviewed_by", record.reviewed_by),
        ("recorded_on", record.recorded_on),
        ("reference", record.reference),
    ):
        if not value.strip():
            problems.append(f"evidence.{name}_missing")

    current = current_dependencies() if dependencies is None else dependencies
    problems.extend(
        f"evidence.dependency_changed.{name}"
        for name in sorted(current)
        if record.dependencies.get(name) != current[name]
    )

    for dimension in EvidenceDimension:
        result = record.results.get(dimension)
        if result is None:
            problems.append(f"evidence.{dimension}.not_run")
            continue
        if not result.passed:
            problems.append(f"evidence.{dimension}.failed")
        if not result.measurements:
            problems.append(f"evidence.{dimension}.unmeasured")
        if not result.artifacts:
            problems.append(f"evidence.{dimension}.no_artifacts")

    required = {
        EvidenceDimension.ROTATION: {str(rotation) for rotation in rotations},
        EvidenceDimension.DENSITY: set(densities),
    }
    for dimension, needed in required.items():
        result = record.results.get(dimension)
        if result is not None and not needed <= set(result.covers):
            problems.append(f"evidence.{dimension}.incomplete")
    return tuple(problems)
