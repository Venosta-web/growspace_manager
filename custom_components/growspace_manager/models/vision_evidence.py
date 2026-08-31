"""Records of the Vision Evidence Store.

Growspace Vision is stateless (ADR 0003), so Home Assistant owns every artifact of a
Vision Checkup: its envelope, each capture, image files, Visual Embedding, Visual
Comparison Result, Baseline Bucket, fusion outcome, report, and grower labels.
These are the row shapes of ``growspace_vision.db`` — see ADR 0041 and
``data_access/vision_evidence_schema.py``.

They are plain frozen records with no behaviour.  Vocabulary is enforced by the
schema's ``CHECK`` constraints and kept in step with these enums by
``tests/test_vision_evidence_schema.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FramingEpochReason(StrEnum):
    """Why a camera's Framing Epoch began.

    There is no detector reason.  V1 has no automatic camera-move detection: the
    structural signature cannot separate a camera move from a lens occlusion, and a
    boundary drawn from it would re-learn an occluded view as normal (ADR 0005,
    amending ADR 0004).  Only a grower or a run/model boundary starts an epoch.
    """

    INITIAL = "initial"
    MANUAL_RESTART = "manual_restart"
    GROW_RUN_BOUNDARY = "grow_run_boundary"
    MODEL_VERSION_CHANGE = "model_version_change"


class GrowRunRefSource(StrEnum):
    """Whether a growspace's run identity is a surrogate or a real Grow Run."""

    SURROGATE = "surrogate"
    GROW_RUN = "grow_run"


class LightWindow(StrEnum):
    """The scheduled point in the light cycle a capture belongs to.

    ``MANUAL`` is a capture with no stable light window.  It may be scored, but it
    is never admitted to a Baseline Bucket — see ``BaselineBucket``.
    """

    EARLY = "early"
    MID = "mid"
    LATE = "late"
    MANUAL = "manual"


class LightState(StrEnum):
    """Home Assistant's view of the grow light at capture time."""

    ON = "on"
    OFF = "off"
    UNKNOWN = "unknown"


class CaptureTrigger(StrEnum):
    """What caused a capture to be taken."""

    SCHEDULED = "scheduled"
    MANUAL = "manual"


class CheckupStatus(StrEnum):
    """The operational outcome of a multi-camera Vision Checkup."""

    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class AnalysisState(StrEnum):
    """How far a capture got through its Vision Analysis."""

    PENDING = "pending"
    ANALYZED = "analyzed"
    REJECTED = "rejected"
    FAILED = "failed"


class CaptureFileVariant(StrEnum):
    """Which rendering of a capture an image file holds."""

    RAW = "raw"
    PROCESSED = "processed"


class FileDeletionReason(StrEnum):
    """Why an image file is no longer on disk."""

    RETENTION = "retention"
    GROWSPACE_DELETED = "growspace_deleted"
    USER_REQUESTED = "user_requested"


class EmbeddingSource(StrEnum):
    """Whether an embedding was derived at capture time or from a retained image."""

    LIVE = "live"
    RE_EMBEDDED = "re_embedded"


class BaselineState(StrEnum):
    """The comparison readiness of a Baseline Bucket (ADR 0004)."""

    MONITORING = "monitoring"
    READY = "ready"
    STALE = "stale"


class AdmissionPhase(StrEnum):
    """Under which rule a capture was admitted to a Baseline Bucket.

    ``BOOTSTRAP`` admits every eligible capture until the bucket is ready;
    ``NORMAL`` admits only a capture whose verdict was ``normal``.
    """

    BOOTSTRAP = "bootstrap"
    NORMAL = "normal"


class ComparisonOutcome(StrEnum):
    """What a Visual Comparison Result was able to produce."""

    SCORED = "scored"
    MONITORING = "monitoring"
    UNAVAILABLE = "unavailable"


class ComparisonVerdict(StrEnum):
    """The scene-change verdict of a scored comparison.

    It describes departure from recent scene history, never plant health (hub#68).
    """

    NORMAL = "normal"
    UNCERTAIN = "uncertain"
    MATERIAL_SCENE_CHANGE = "material_scene_change"


class ObservationSource(StrEnum):
    """Where a Vision Explainer Report's observation text came from.

    ``VISUAL_COMPARISON_ONLY`` is the honest record that no photograph was read —
    because the Visual Observation Pass is switched off, or because it failed.  A
    report can then never imply an inspection that did not happen.
    """

    IMAGE_PASS = "image_pass"
    VISUAL_COMPARISON_ONLY = "visual_comparison_only"


class LabelKind(StrEnum):
    """Which kind of feedback a label carries.

    ``COMPARISON_CORRECTION`` corrects a verdict the model actually made.
    ``OBSERVATION`` asserts something the model never claimed, so it has no model
    output to correct — V1 emits no health or symptom claim.
    """

    COMPARISON_CORRECTION = "comparison_correction"
    OBSERVATION = "observation"


@dataclass(frozen=True, slots=True, kw_only=True)
class FramingEpoch:
    """A period in which one camera's framing is treated as materially unchanged."""

    epoch_id: str
    growspace_id: str
    camera_id: str
    started_at: str
    reason: FramingEpochReason
    # The structural correlation observed when the epoch was started, where one was
    # known.  Evidence for "why did this camera's baseline reset", never its trigger.
    detector_evidence: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class GrowRunRef:
    """The run identity a growspace's captures are attributed to."""

    growspace_id: str
    grow_run_id: str
    started_at: str
    source: GrowRunRefSource


@dataclass(frozen=True, slots=True, kw_only=True)
class VisionCheckup:
    """One growspace-level observation task grouping capture-specific evidence."""

    checkup_id: str
    growspace_id: str
    growspace_name: str
    trigger_source: CaptureTrigger
    light_window: LightWindow
    started_at: str
    completed_at: str | None = None
    status: CheckupStatus | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class VisionCapture:
    """One Camera Snapshot taken for a Vision Checkup.

    Recorded before the Growspace Vision call, so a rejected or failed analysis
    still leaves its image tracked and prunable.
    """

    capture_id: str
    checkup_id: str
    growspace_id: str
    growspace_name: str
    camera_id: str
    grow_run_id: str
    framing_epoch_id: str
    captured_at: str
    light_window: LightWindow
    light_state: LightState
    trigger_source: CaptureTrigger
    analysis_state: AnalysisState
    created_at: str
    content_sha256: str | None = None
    analysis_error_code: str | None = None
    request_id: str | None = None
    vision_schema_version: int | None = None
    service_version: str | None = None
    quality_mean_luminance: float | None = None
    quality_clipped_pixel_fraction: float | None = None
    quality_mean_absolute_gradient: float | None = None
    quality_reasons: tuple[str, ...] = ()
    quality_structural_correlation: float | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class VisionCaptureFile:
    """One image file belonging to a capture.

    ``relative_path`` is relative to the resolved image root and never a public URL.
    The record outlives its file: a pruned image is distinguishable from an image
    that never existed.
    """

    capture_id: str
    variant: CaptureFileVariant
    relative_path: str
    byte_size: int
    content_type: str
    deleted_at: str | None = None
    deletion_reason: FileDeletionReason | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class VisionEmbedding:
    """A Visual Embedding, keyed by the model that produced it.

    ``values_f32`` holds the vector exactly as the service returned it — float32 and
    not unit-normalized.  Re-embedding under a new encoder adds a record rather than
    replacing one.
    """

    capture_id: str
    model_id: str
    model_version: str
    dimension: int
    values_f32: bytes
    derived_at: str
    source: EmbeddingSource


@dataclass(frozen=True, slots=True, kw_only=True)
class BaselineBucket:
    """The rolling recent history a Visual Embedding is compared against.

    One bucket per camera, light window, Grow Run, model version and Framing Epoch
    (ADR 0004).  A ``LightWindow.MANUAL`` capture never has one.
    """

    bucket_id: str
    growspace_id: str
    camera_id: str
    light_window: LightWindow
    grow_run_id: str
    model_id: str
    model_version: str
    framing_epoch_id: str
    state: BaselineState
    scoring_policy_version: int
    created_at: str
    member_count: int = 0
    members_required: int = 30
    centroid: bytes | None = None
    calibration_distances: bytes | None = None
    last_admitted_at: str | None = None
    recomputed_at: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class BaselineMember:
    """One capture's membership of a Baseline Bucket.

    Membership is recorded when it is decided, not derived later: admission depends
    on the bucket's state at the time, so recomputing it would re-decide it.
    Eviction is retained rather than deleted so the rolling window stays auditable.
    """

    bucket_id: str
    capture_id: str
    admitted_at: str
    admission_phase: AdmissionPhase
    evicted_at: str | None = None
    evicted_by_capture_id: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class VisualComparisonResult:
    """Home Assistant's interpretation of one Vision Analysis against its baseline.

    ``admitted_to_baseline`` is an explicit fact, not something inferred from the
    verdict: a manual capture can be scored ``normal`` and still never be admitted.
    """

    result_id: str
    capture_id: str
    evaluated_at: str
    outcome: ComparisonOutcome
    trigger_source: CaptureTrigger
    model_id: str
    model_version: str
    scoring_policy_version: int
    bucket_id: str | None = None
    baseline_state: BaselineState | None = None
    samples_collected: int | None = None
    samples_required: int | None = None
    raw_distance: float | None = None
    anomaly_score: float | None = None
    verdict: ComparisonVerdict | None = None
    comparison_confidence: float | None = None
    admitted_to_baseline: bool = False
    unavailable_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class VisionFusionOutcome:
    """Capture-specific normalized environmental evidence and fusion result."""

    outcome_id: str
    capture_id: str
    evaluated_at: str
    scoring_policy_version: int
    environmental_verdict: str
    environmental_evaluated_at: str | None = None
    stress_reasons: tuple[str, ...] = ()
    mold_reasons: tuple[str, ...] = ()
    fusion_state: str | None = None
    fusion_confidence: str | None = None
    fusion_coverage: str | None = None
    unavailable_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class VisionLabel:
    """Grower feedback anchored on a capture.

    Append-only: a revision supersedes its predecessor rather than overwriting it.
    Training eligibility is derived at export time, never stored — it depends on
    whether the image still exists and which model version is current.  What is
    stored is an explicit human exclusion.
    """

    label_id: str
    capture_id: str
    label_kind: LabelKind
    created_at: str
    author: str
    model_verdict: ComparisonVerdict | None = None
    model_anomaly_score: float | None = None
    model_id: str | None = None
    model_version: str | None = None
    scoring_policy_version: int | None = None
    corrected_verdict: ComparisonVerdict | None = None
    symptom_labels: tuple[str, ...] = ()
    note: str | None = None
    observed_from: str | None = None
    observed_to: str | None = None
    excluded: bool = False
    exclusion_reason: str | None = None
    superseded_by: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class VisionExplainerReport:
    """The Vision Explainer's four-field narrative for one capture.

    ``observation`` is the Visual Observation Pass's own words, carried across
    unchanged; the Evidence Explanation Pass never returns it and so cannot revise
    it.  There is no severity — severity is an Evidence Fusion output (ADR 0040) —
    and no symptom vocabulary, because V1 has no validated classifier to stand
    behind one (hub#68).

    The fusion outcome is snapshotted rather than referenced.  A narrative written
    against ``environmental_risk`` becomes uninterpretable once the fusion
    transition table moves underneath it, and text costs nothing to keep.
    """

    report_id: str
    capture_id: str
    created_at: str
    ai_task_entity_id: str
    observation_source: ObservationSource
    scoring_policy_version: int
    observation: str
    environmental_risk: str
    hypothesis: str
    recommendations: tuple[str, ...] = ()
    fusion_state: str | None = None
    fusion_confidence: str | None = None
    fusion_coverage: str | None = None
    fusion_unavailable_reasons: tuple[str, ...] = ()
