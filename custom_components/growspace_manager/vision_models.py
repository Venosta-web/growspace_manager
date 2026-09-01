"""The Growspace Vision V1 wire vocabulary, and the only parser of it.

The normative contract is `contracts/growspace-vision/v1/openapi.json` in the
Growspace Vision repository; its frozen fixtures are vendored under
`tests/fixtures/vision/growspace-vision/v1/`.  ADR 0003 (Vision) makes that
boundary deliberately strict: **every object is closed**.  An unknown key, a
missing key, a wrong type, a non-finite number or an out-of-range value is a
contract violation and raises `VisionProtocolError` — it is never tolerated,
defaulted or dropped.

That strictness is the whole point.  V1 must not be able to grow a symptom
field, a plant-health judgment or a Home Assistant-owned temporal score
(`anomaly_score`, `change_score`, `trend`) without a new integer schema
version, so a response carrying one fails here rather than reaching the
evidence store.

Pure module: no hass, no I/O, no network.  ``vision_client`` speaks HTTP and
calls in here to turn bytes into these records.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
import math
from typing import Final

from .exceptions import VisionProtocolError
from .models.vision_evidence import LightState

VISION_SCHEMA_VERSION: Final = 1
"""The one analysis schema version this integration implements."""

SUPPORTED_SCHEMA_VERSIONS: Final = (VISION_SCHEMA_VERSION,)
"""Versions offered to `/info` negotiation, highest exact intersection wins."""

VISION_SERVICE_NAME: Final = "growspace_manager_vision"
"""The constant `service_name` a Growspace Vision App reports from `/info`."""

MAX_EMBEDDING_DIMENSION: Final = 4096
_MAX_OPAQUE_LENGTH: Final = 128
_MAX_MESSAGE_LENGTH: Final = 512
_MAX_IDENTIFIER_LENGTH: Final = 255


class AnalysisStatus(StrEnum):
    """The two outcomes of a successful `POST /analyze`.

    ``REJECTED`` is a first-class result, not an error: the frame was unusable
    and the App says so in a 200 response.  ``ANALYZED`` says only that an
    embedding was produced — never that the scene is normal or healthy.
    """

    ANALYZED = "analyzed"
    REJECTED = "rejected"


class QualityReason(StrEnum):
    """Why the App's absolute frame-quality floor rejected a frame (ADR 0005).

    Every reason that holds is reported, so a dark frame captured during a lit
    window carries both ``TOO_DARK`` and ``LIGHT_STATE_MISMATCH``.
    """

    TOO_DARK = "too_dark"
    OVEREXPOSED = "overexposed"
    LOW_DETAIL = "low_detail"
    LIGHT_STATE_MISMATCH = "light_state_mismatch"


class ModelState(StrEnum):
    """Whether a described model can currently serve an analysis."""

    LOADED = "loaded"
    UNAVAILABLE = "unavailable"


class VisionErrorCode(StrEnum):
    """The closed set of typed error codes a non-2xx response may carry."""

    UNAUTHORIZED = "unauthorized"
    UNSUPPORTED_IMAGE_FORMAT = "unsupported_image_format"
    IMAGE_TOO_LARGE = "image_too_large"
    INVALID_REQUEST = "invalid_request"
    UNSUPPORTED_SCHEMA_VERSION = "unsupported_schema_version"
    MODEL_NOT_LOADED = "model_not_loaded"
    BUSY = "busy"
    INTERNAL_FAILURE = "internal_failure"


@dataclass(frozen=True, slots=True, kw_only=True)
class Capabilities:
    """What an App declares it can do, all constant in V1."""

    single_image_analysis: bool
    batch_analysis: bool
    embeddings: bool
    service_scoring: bool
    regions: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class OperationalLimits:
    """The App-owned half of the operational contract."""

    max_image_bytes: int
    max_decoded_pixels: int
    max_concurrency: int
    max_queue_depth: int
    inference_timeout_seconds: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ServiceInfo:
    """The permanently frozen `/info` negotiation bootstrap.

    It stays parseable as V1 even when the App no longer supports V1 analysis,
    which is what lets an incompatible App report itself rather than look
    unreachable.
    """

    schema_version: int
    service_name: str
    service_version: str
    supported_schema_versions: tuple[int, ...]
    capabilities: Capabilities
    limits: OperationalLimits


@dataclass(frozen=True, slots=True, kw_only=True)
class ModelIdentity:
    """The opaque `(model_id, model_version)` pair copied between requests.

    A changed ``model_version`` does not change the wire schema, but it starts a
    new Baseline Bucket: embeddings from different model versions are never
    compared (ADR 0003).
    """

    model_id: str
    model_version: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ModelDescriptor:
    """One bundled model as `/models` describes it."""

    identity: ModelIdentity
    embedding_dimension: int
    state: ModelState

    @property
    def is_loaded(self) -> bool:
        """Return whether this model can serve an analysis right now."""
        return self.state is ModelState.LOADED


@dataclass(frozen=True, slots=True, kw_only=True)
class VisualEmbedding:
    """The vector an accepted frame produced."""

    dimension: int
    values: tuple[float, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class QualitySignals:
    """The three raw single-frame measurements, returned on every 200.

    They describe one frame only.  History-relative rails belong to Home
    Assistant, which is why the App returns the numbers rather than a verdict.
    """

    mean_luminance: float
    clipped_pixel_fraction: float
    mean_absolute_gradient: float


@dataclass(frozen=True, slots=True, kw_only=True)
class FrameQualityResult:
    """One frame's measurements and every floor reason that held."""

    signals: QualitySignals
    reasons: tuple[QualityReason, ...]

    @property
    def accepted(self) -> bool:
        """Return whether the absolute floor admitted this frame."""
        return not self.reasons


@dataclass(frozen=True, slots=True, kw_only=True)
class VisionAnalysis:
    """One completed Vision Analysis.

    ``model`` and ``embedding`` are present exactly when ``status`` is
    ``ANALYZED``; the parser enforces that, so a caller that checks ``accepted``
    may rely on both.
    """

    schema_version: int
    request_id: str
    status: AnalysisStatus
    quality: FrameQualityResult
    model: ModelIdentity | None = None
    embedding: VisualEmbedding | None = None

    @property
    def accepted(self) -> bool:
        """Return whether the App produced an embedding for this frame."""
        return self.status is AnalysisStatus.ANALYZED


@dataclass(frozen=True, slots=True, kw_only=True)
class VisionErrorBody:
    """The typed body of a non-2xx response.

    ``message`` is a safe summary by contract: no token, path, traceback or
    image bytes.  It is still service-authored text, so treat it as opaque.
    """

    schema_version: int
    code: VisionErrorCode
    message: str
    request_id: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class AnalyzeMetadata:
    """The closed metadata part of one `/analyze` request.

    The only non-image observation V1 permits is ``light_state``.  There is no
    room here for temperature, humidity or VPD, and adding one would be a
    contract violation rather than an enrichment.
    """

    schema_version: int
    camera_id: str
    growspace_id: str
    captured_at: datetime
    light_state: LightState
    model: ModelIdentity

    def to_wire(self) -> dict[str, object]:
        """Render the exact closed object the App validates."""
        return {
            "schema_version": self.schema_version,
            "camera_id": self.camera_id,
            "growspace_id": self.growspace_id,
            "captured_at": format_captured_at(self.captured_at),
            "light_state": str(self.light_state),
            "model_id": self.model.model_id,
            "model_version": self.model.model_version,
        }


def format_captured_at(moment: datetime) -> str:
    """Render a capture time as the `Z`-suffixed UTC RFC 3339 stamp V1 requires.

    The contract pattern is anchored on a literal ``Z``, so a `+00:00` offset —
    what `datetime.isoformat()` produces for an aware UTC value — is rejected by
    the App.  A naive value is treated as already UTC, matching the rest of the
    integration's stored timestamps.
    """
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC).replace(tzinfo=None)
    return f"{moment.isoformat(timespec='seconds')}Z"


def parse_health(payload: object) -> None:
    """Validate the unauthenticated `/health` body, or raise.

    Readiness is the whole payload: a ready App has one shape and there is
    nothing further to return.
    """
    body = _closed_object(
        payload, required=("schema_version", "status"), where="health"
    )
    _schema_version(body, where="health")
    _const_string(body, "status", "ready", where="health")


def parse_info(payload: object) -> ServiceInfo:
    """Parse the `/info` negotiation bootstrap, or raise."""
    body = _closed_object(
        payload,
        required=(
            "schema_version",
            "service_name",
            "service_version",
            "supported_schema_versions",
            "capabilities",
            "limits",
        ),
        where="info",
    )
    versions = _int_array(body, "supported_schema_versions", where="info", minimum=1)
    if not versions:
        raise VisionProtocolError("info.supported_schema_versions is empty")
    if len(set(versions)) != len(versions):
        raise VisionProtocolError("info.supported_schema_versions repeats a version")
    return ServiceInfo(
        schema_version=_schema_version(body, where="info"),
        service_name=_const_string(
            body, "service_name", VISION_SERVICE_NAME, where="info"
        ),
        service_version=_string(body, "service_version", where="info"),
        supported_schema_versions=versions,
        capabilities=_parse_capabilities(body["capabilities"]),
        limits=_parse_limits(body["limits"]),
    )


def parse_models(payload: object) -> tuple[ModelDescriptor, ...]:
    """Parse the `/models` catalogue, or raise."""
    body = _closed_object(
        payload, required=("schema_version", "models"), where="models"
    )
    _schema_version(body, where="models")
    raw_models = body["models"]
    if not isinstance(raw_models, list) or not raw_models:
        raise VisionProtocolError("models.models must be a non-empty array")
    return tuple(_parse_model_descriptor(entry) for entry in raw_models)


def parse_analysis(payload: object) -> VisionAnalysis:
    """Parse a 200 `/analyze` body as either outcome, or raise.

    The two shapes are closed independently, so an ``analyzed`` body without an
    embedding and a ``rejected`` body carrying one are both contract violations
    — the second is exactly the leak this boundary exists to stop.
    """
    envelope = _require_mapping(payload, where="analyze")
    status_value = envelope.get("status")
    if status_value == AnalysisStatus.ANALYZED:
        return _parse_analyzed(payload)
    if status_value == AnalysisStatus.REJECTED:
        return _parse_rejected(payload)
    raise VisionProtocolError(
        f"analyze.status must be 'analyzed' or 'rejected', got {status_value!r}"
    )


def parse_error(payload: object) -> VisionErrorBody:
    """Parse the typed body of a non-2xx response, or raise."""
    body = _closed_object(
        payload,
        required=("schema_version", "error"),
        optional=("request_id",),
        where="error",
    )
    detail = _closed_object(body["error"], required=("code", "message"), where="error")
    code = _string(detail, "code", where="error")
    if code not in set(VisionErrorCode):
        raise VisionProtocolError(f"error.code {code!r} is not a V1 error code")
    return VisionErrorBody(
        schema_version=_schema_version(body, where="error"),
        code=VisionErrorCode(code),
        message=_string(
            detail, "message", where="error", maximum_length=_MAX_MESSAGE_LENGTH
        ),
        request_id=(
            _string(body, "request_id", where="error") if "request_id" in body else None
        ),
    )


def _parse_analyzed(payload: object) -> VisionAnalysis:
    body = _closed_object(
        payload,
        required=(
            "schema_version",
            "request_id",
            "status",
            "model",
            "embedding",
            "quality",
            "regions",
        ),
        where="analyze",
    )
    quality = _parse_quality(body["quality"])
    if quality.reasons:
        raise VisionProtocolError(
            "analyze.quality.reasons must be empty on an analyzed response"
        )
    _empty_regions(body)
    return VisionAnalysis(
        schema_version=_schema_version(body, where="analyze"),
        request_id=_string(body, "request_id", where="analyze"),
        status=AnalysisStatus.ANALYZED,
        quality=quality,
        model=_parse_model_identity(body["model"], where="analyze.model"),
        embedding=_parse_embedding(body["embedding"]),
    )


def _parse_rejected(payload: object) -> VisionAnalysis:
    body = _closed_object(
        payload,
        required=("schema_version", "request_id", "status", "quality", "regions"),
        where="analyze",
    )
    quality = _parse_quality(body["quality"])
    if not quality.reasons:
        raise VisionProtocolError(
            "analyze.quality.reasons must name at least one reason on a rejection"
        )
    _empty_regions(body)
    return VisionAnalysis(
        schema_version=_schema_version(body, where="analyze"),
        request_id=_string(body, "request_id", where="analyze"),
        status=AnalysisStatus.REJECTED,
        quality=quality,
    )


def _parse_capabilities(payload: object) -> Capabilities:
    body = _closed_object(
        payload,
        required=(
            "single_image_analysis",
            "batch_analysis",
            "embeddings",
            "service_scoring",
            "regions",
        ),
        where="info.capabilities",
    )
    return Capabilities(
        single_image_analysis=_bool(
            body, "single_image_analysis", where="capabilities"
        ),
        batch_analysis=_bool(body, "batch_analysis", where="capabilities"),
        embeddings=_bool(body, "embeddings", where="capabilities"),
        service_scoring=_bool(body, "service_scoring", where="capabilities"),
        regions=_bool(body, "regions", where="capabilities"),
    )


def _parse_limits(payload: object) -> OperationalLimits:
    body = _closed_object(
        payload,
        required=(
            "max_image_bytes",
            "max_decoded_pixels",
            "max_concurrency",
            "max_queue_depth",
            "inference_timeout_seconds",
        ),
        where="info.limits",
    )
    return OperationalLimits(
        max_image_bytes=_integer(body, "max_image_bytes", where="limits", minimum=0),
        max_decoded_pixels=_integer(
            body, "max_decoded_pixels", where="limits", minimum=0
        ),
        max_concurrency=_integer(body, "max_concurrency", where="limits", minimum=0),
        max_queue_depth=_integer(body, "max_queue_depth", where="limits", minimum=0),
        inference_timeout_seconds=_integer(
            body, "inference_timeout_seconds", where="limits", minimum=0
        ),
    )


def _parse_model_descriptor(payload: object) -> ModelDescriptor:
    body = _closed_object(
        payload,
        required=("model_id", "model_version", "embedding_dimension", "state"),
        where="models.models[]",
    )
    state = _string(body, "state", where="models.models[]")
    if state not in set(ModelState):
        raise VisionProtocolError(f"models.models[].state {state!r} is not a V1 state")
    return ModelDescriptor(
        identity=_parse_model_identity(body, where="models.models[]"),
        embedding_dimension=_integer(
            body,
            "embedding_dimension",
            where="models.models[]",
            minimum=1,
            maximum=MAX_EMBEDDING_DIMENSION,
        ),
        state=ModelState(state),
    )


def _parse_model_identity(payload: object, *, where: str) -> ModelIdentity:
    body = _require_mapping(payload, where=where)
    return ModelIdentity(
        model_id=_string(
            body, "model_id", where=where, maximum_length=_MAX_OPAQUE_LENGTH
        ),
        model_version=_string(
            body, "model_version", where=where, maximum_length=_MAX_OPAQUE_LENGTH
        ),
    )


def _parse_quality(payload: object) -> FrameQualityResult:
    body = _closed_object(
        payload, required=("signals", "reasons"), where="analyze.quality"
    )
    signals = _closed_object(
        body["signals"],
        required=(
            "mean_luminance",
            "clipped_pixel_fraction",
            "mean_absolute_gradient",
        ),
        where="analyze.quality.signals",
    )
    raw_reasons = body["reasons"]
    if not isinstance(raw_reasons, list):
        raise VisionProtocolError("analyze.quality.reasons must be an array")
    reasons: list[QualityReason] = []
    for reason in raw_reasons:
        if not isinstance(reason, str) or reason not in set(QualityReason):
            raise VisionProtocolError(
                f"analyze.quality.reasons carries unknown reason {reason!r}"
            )
        if QualityReason(reason) in reasons:
            raise VisionProtocolError(
                f"analyze.quality.reasons repeats reason {reason!r}"
            )
        reasons.append(QualityReason(reason))
    return FrameQualityResult(
        signals=QualitySignals(
            mean_luminance=_number(
                signals, "mean_luminance", where="signals", minimum=0, maximum=255
            ),
            clipped_pixel_fraction=_number(
                signals,
                "clipped_pixel_fraction",
                where="signals",
                minimum=0,
                maximum=1,
            ),
            mean_absolute_gradient=_number(
                signals,
                "mean_absolute_gradient",
                where="signals",
                minimum=0,
                maximum=255,
            ),
        ),
        reasons=tuple(reasons),
    )


def _parse_embedding(payload: object) -> VisualEmbedding:
    body = _closed_object(
        payload, required=("dimension", "values"), where="analyze.embedding"
    )
    dimension = _integer(
        body,
        "dimension",
        where="analyze.embedding",
        minimum=1,
        maximum=MAX_EMBEDDING_DIMENSION,
    )
    raw_values = body["values"]
    if not isinstance(raw_values, list):
        raise VisionProtocolError("analyze.embedding.values must be an array")
    values: list[float] = []
    for value in raw_values:
        # `json` happily decodes the JavaScript-only literals NaN, Infinity and
        # -Infinity, which are not valid JSON and not valid embedding values.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise VisionProtocolError("analyze.embedding.values must hold numbers")
        if not math.isfinite(value):
            raise VisionProtocolError("analyze.embedding.values must be finite")
        values.append(float(value))
    if len(values) != dimension:
        raise VisionProtocolError(
            f"analyze.embedding declares dimension {dimension} "
            f"but carries {len(values)} values"
        )
    return VisualEmbedding(dimension=dimension, values=tuple(values))


def _empty_regions(body: dict[str, object]) -> None:
    regions = body["regions"]
    if regions != []:
        raise VisionProtocolError("analyze.regions is reserved and must be []")


def _require_mapping(payload: object, *, where: str) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise VisionProtocolError(f"{where} must be a JSON object")
    for key in payload:
        if not isinstance(key, str):
            raise VisionProtocolError(f"{where} has a non-string key")
    return dict(payload)


def _closed_object(
    payload: object,
    *,
    required: tuple[str, ...],
    optional: tuple[str, ...] = (),
    where: str,
) -> dict[str, object]:
    """Return `payload` as a mapping holding exactly the permitted keys."""
    body = _require_mapping(payload, where=where)
    missing = sorted(set(required) - set(body))
    if missing:
        raise VisionProtocolError(f"{where} is missing {', '.join(missing)}")
    unknown = sorted(set(body) - set(required) - set(optional))
    if unknown:
        raise VisionProtocolError(
            f"{where} carries unknown key(s) {', '.join(unknown)}; "
            "V1 objects are closed"
        )
    return body


def _schema_version(body: dict[str, object], *, where: str) -> int:
    version = body["schema_version"]
    if version != VISION_SCHEMA_VERSION:
        raise VisionProtocolError(
            f"{where}.schema_version must be {VISION_SCHEMA_VERSION}, got {version!r}"
        )
    return VISION_SCHEMA_VERSION


def _const_string(
    body: dict[str, object], key: str, expected: str, *, where: str
) -> str:
    value = _string(body, key, where=where)
    if value != expected:
        raise VisionProtocolError(f"{where}.{key} must be {expected!r}, got {value!r}")
    return value


def _string(
    body: dict[str, object],
    key: str,
    *,
    where: str,
    maximum_length: int = _MAX_IDENTIFIER_LENGTH,
) -> str:
    value = body[key]
    if not isinstance(value, str):
        raise VisionProtocolError(f"{where}.{key} must be a string")
    if not value or len(value) > maximum_length:
        raise VisionProtocolError(
            f"{where}.{key} must be 1 to {maximum_length} characters"
        )
    return value


def _integer(
    body: dict[str, object],
    key: str,
    *,
    where: str,
    minimum: int,
    maximum: int | None = None,
) -> int:
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise VisionProtocolError(f"{where}.{key} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        raise VisionProtocolError(f"{where}.{key} is out of range")
    return value


def _number(
    body: dict[str, object],
    key: str,
    *,
    where: str,
    minimum: float,
    maximum: float,
) -> float:
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise VisionProtocolError(f"{where}.{key} must be a number")
    if not math.isfinite(value):
        raise VisionProtocolError(f"{where}.{key} must be finite")
    if value < minimum or value > maximum:
        raise VisionProtocolError(f"{where}.{key} is out of range")
    return float(value)


def _bool(body: dict[str, object], key: str, *, where: str) -> bool:
    value = body[key]
    if not isinstance(value, bool):
        raise VisionProtocolError(f"{where}.{key} must be a boolean")
    return value


def _int_array(
    body: dict[str, object], key: str, *, where: str, minimum: int
) -> tuple[int, ...]:
    value = body[key]
    if not isinstance(value, list):
        raise VisionProtocolError(f"{where}.{key} must be an array")
    entries: list[int] = []
    for entry in value:
        if isinstance(entry, bool) or not isinstance(entry, int):
            raise VisionProtocolError(f"{where}.{key} must hold integers")
        if entry < minimum:
            raise VisionProtocolError(f"{where}.{key} holds an out-of-range value")
        entries.append(entry)
    return tuple(entries)
