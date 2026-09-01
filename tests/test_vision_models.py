"""The Growspace Vision V1 parser, driven by the frozen contract fixtures.

`tests/fixtures/vision/growspace-vision/v1/` is a verbatim copy of the Vision
repository's own fixtures, including its `manifest.json`. Walking the manifest
rather than naming files means a fixture added upstream is exercised the moment
it is re-vendored, and the negative fixtures — the ones carrying `symptoms`,
`chlorosis`, `drooping`, or a Home Assistant-owned `anomaly_score` — become an
executable statement that V1 cannot grow those outputs.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

import pytest

from custom_components.growspace_manager.exceptions import VisionProtocolError
from custom_components.growspace_manager.models.vision_evidence import LightState
from custom_components.growspace_manager.vision_models import (
    AnalysisStatus,
    AnalyzeMetadata,
    ModelIdentity,
    ModelState,
    QualityReason,
    VisionErrorCode,
    format_captured_at,
    parse_analysis,
    parse_error,
    parse_health,
    parse_info,
    parse_models,
)

FIXTURES = Path(__file__).parent / "fixtures" / "vision" / "growspace-vision" / "v1"

# The manifest names a component schema per fixture; this maps each to the one
# parser that owns it. A schema appearing upstream with no entry here fails
# loudly rather than being skipped.
_PARSERS = {
    "HealthResponse": parse_health,
    "InfoResponse": parse_info,
    "ModelsResponse": parse_models,
    "AnalyzeResponse": parse_analysis,
    "ErrorResponse": parse_error,
}


def _load(relative: str) -> Any:
    return json.loads((FIXTURES / relative).read_text(encoding="utf-8"))


def _manifest() -> dict[str, list[dict[str, str]]]:
    return json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))


def _cases(section: str) -> list[dict[str, str]]:
    return _manifest()[section]


def _ids(entries: list[dict[str, str]]) -> list[str]:
    return [entry["file"] for entry in entries]


@pytest.mark.parametrize("entry", _cases("valid"), ids=_ids(_cases("valid")))
def test_every_valid_fixture_parses(entry: dict[str, str]) -> None:
    """Each published valid fixture is accepted by the parser that owns it."""
    schema = entry["schema"]
    if schema == "AnalyzeMetadata":
        pytest.skip("request fixture; covered by the metadata round-trip test")
    assert schema in _PARSERS, f"no parser owns component schema {schema}"
    _PARSERS[schema](_load(entry["file"]))


@pytest.mark.parametrize("entry", _cases("invalid"), ids=_ids(_cases("invalid")))
def test_every_invalid_fixture_is_refused(entry: dict[str, str]) -> None:
    """Each published invalid fixture is a contract violation, not a tolerated extra.

    The request-side fixtures (`vpd`, `temperature`) have no inbound parser —
    they are proved by the metadata round-trip instead, which cannot emit those
    keys at all.
    """
    schema = entry["schema"]
    if schema == "AnalyzeMetadata":
        pytest.skip("request fixture; the metadata builder cannot emit these keys")
    with pytest.raises(VisionProtocolError):
        _PARSERS[schema](_load(entry["file"]))


def test_analyzed_fixture_yields_an_embedding_and_no_reasons() -> None:
    """An accepted frame carries its model, its vector and an empty reason list."""
    analysis = parse_analysis(_load("valid/analyze-response-analyzed.json"))

    assert analysis.status is AnalysisStatus.ANALYZED
    assert analysis.accepted
    assert analysis.model == ModelIdentity(
        model_id="dinov2-vit-s-14-int8-onnx", model_version="1.0.0"
    )
    assert analysis.embedding is not None
    assert analysis.embedding.dimension == 384
    assert len(analysis.embedding.values) == 384
    assert analysis.quality.accepted
    assert analysis.quality.reasons == ()


def test_rejected_fixture_is_a_result_and_not_an_error() -> None:
    """A quality rejection is a 200 with every reason that held and no embedding."""
    analysis = parse_analysis(_load("valid/analyze-response-rejected.json"))

    assert analysis.status is AnalysisStatus.REJECTED
    assert not analysis.accepted
    assert analysis.embedding is None
    assert analysis.model is None
    assert analysis.quality.reasons == (
        QualityReason.TOO_DARK,
        QualityReason.LIGHT_STATE_MISMATCH,
    )
    assert analysis.quality.signals.mean_luminance == pytest.approx(3.4)


def test_info_fixture_reports_the_frozen_v1_bootstrap() -> None:
    """`/info` is the negotiation surface, so its declared versions survive parsing."""
    info = parse_info(_load("valid/info.json"))

    assert info.service_version == "1.0.0"
    assert info.supported_schema_versions == (1,)
    assert info.capabilities.single_image_analysis
    assert not info.capabilities.batch_analysis
    assert not info.capabilities.service_scoring
    assert info.limits.max_concurrency == 1
    assert info.limits.max_queue_depth == 0


def test_models_fixture_reports_a_loaded_model() -> None:
    """A model's identity and dimension are what pin a Baseline Bucket."""
    (model,) = parse_models(_load("valid/models.json"))

    assert model.identity.model_id == "dinov2-vit-s-14-int8-onnx"
    assert model.identity.model_version == "1.0.0"
    assert model.embedding_dimension == 384
    assert model.state is ModelState.LOADED
    assert model.is_loaded


def test_error_fixture_carries_its_typed_code() -> None:
    """A typed error keeps its code and request id for the failure that follows."""
    error = parse_error(_load("valid/error-model-not-loaded.json"))

    assert error.code is VisionErrorCode.MODEL_NOT_LOADED
    assert error.request_id == "ae30a0bd-a639-4685-969d-f4e3ad05ecde"


def test_metadata_round_trips_to_the_published_request_fixture() -> None:
    """What this integration sends is byte-for-key identical to the frozen request."""
    metadata = AnalyzeMetadata(
        schema_version=1,
        camera_id="camera.growcam_sog",
        growspace_id="growspace-sog-01",
        captured_at=datetime(2026, 8, 31, 8, 30, tzinfo=UTC),
        light_state=LightState.ON,
        model=ModelIdentity(
            model_id="dinov2-vit-s-14-int8-onnx", model_version="1.0.0"
        ),
    )

    assert metadata.to_wire() == _load("valid/analyze-metadata.json")


def test_metadata_cannot_carry_an_environmental_observation() -> None:
    """The wire object is built key by key, so `vpd` has nowhere to enter.

    Issue #68's constraint is structural rather than a review convention: the
    only non-image observation V1 permits is `light_state`.
    """
    metadata = AnalyzeMetadata(
        schema_version=1,
        camera_id="camera.growcam_sog",
        growspace_id="growspace-sog-01",
        captured_at=datetime(2026, 8, 31, 8, 30, tzinfo=UTC),
        light_state=LightState.UNKNOWN,
        model=ModelIdentity(model_id="m", model_version="1"),
    )
    forbidden = {"vpd", "temperature", "humidity", "symptoms"}

    assert forbidden.isdisjoint(metadata.to_wire())


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (datetime(2026, 8, 31, 8, 30, tzinfo=UTC), "2026-08-31T08:30:00Z"),
        (datetime(2026, 8, 31, 8, 30), "2026-08-31T08:30:00Z"),
        (
            datetime.fromisoformat("2026-08-31T10:30:00+02:00"),
            "2026-08-31T08:30:00Z",
        ),
    ],
)
def test_captured_at_is_always_z_suffixed_utc(moment: datetime, expected: str) -> None:
    """The contract pattern is anchored on a literal `Z`, so `+00:00` is refused."""
    assert format_captured_at(moment) == expected


def test_an_unknown_key_anywhere_is_refused() -> None:
    """V1 objects are closed, so even a harmless addition fails."""
    body = _load("valid/analyze-response-analyzed.json")
    body["confidence"] = 0.9

    with pytest.raises(VisionProtocolError, match="unknown key"):
        parse_analysis(body)


def test_a_missing_key_is_refused() -> None:
    """A dropped field is as much a version change as an added one."""
    body = _load("valid/info.json")
    del body["limits"]

    with pytest.raises(VisionProtocolError, match="missing limits"):
        parse_info(body)


def test_a_future_schema_version_is_refused() -> None:
    """A body stamped with another integer version is not a V1 body."""
    body = _load("valid/health-ready.json")
    body["schema_version"] = 2

    with pytest.raises(VisionProtocolError, match="schema_version"):
        parse_health(body)


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_a_non_finite_embedding_value_is_refused(literal: str) -> None:
    """Python's `json` decodes these JavaScript literals; the contract does not.

    Left alone they would reach the Baseline Bucket and poison every later
    cosine distance, so they are refused at the boundary rather than filtered
    downstream.
    """
    body = _load("valid/analyze-response-analyzed.json")
    body["embedding"] = json.loads(f'{{"dimension": 2, "values": [0.1, {literal}]}}')

    with pytest.raises(VisionProtocolError, match="finite"):
        parse_analysis(body)


def test_an_embedding_that_contradicts_its_dimension_is_refused() -> None:
    """`dimension` must equal `values.length`; a mismatch is not recoverable."""
    body = _load("valid/analyze-response-analyzed.json")
    body["embedding"] = {"dimension": 3, "values": [0.1, 0.2]}

    with pytest.raises(VisionProtocolError, match="dimension"):
        parse_analysis(body)


def test_an_analyzed_response_with_quality_reasons_is_refused() -> None:
    """An accepted frame has no reasons; anything else is a contradictory body."""
    body = _load("valid/analyze-response-analyzed.json")
    body["quality"]["reasons"] = ["too_dark"]

    with pytest.raises(VisionProtocolError, match="must be empty"):
        parse_analysis(body)


def test_a_rejection_with_no_reason_is_refused() -> None:
    """A rejection that will not say why is unusable evidence."""
    body = _load("valid/analyze-response-rejected.json")
    body["quality"]["reasons"] = []

    with pytest.raises(VisionProtocolError, match="at least one reason"):
        parse_analysis(body)


def test_a_populated_regions_array_is_refused() -> None:
    """`regions` is reserved for a later schema version and must be exactly []."""
    body = _load("valid/analyze-response-analyzed.json")
    body["regions"] = [{}]

    with pytest.raises(VisionProtocolError, match="regions"):
        parse_analysis(body)


def test_an_unknown_status_is_neither_outcome() -> None:
    """There is no third analysis outcome to fall through to."""
    body = _load("valid/analyze-response-analyzed.json")
    body["status"] = "queued"

    with pytest.raises(VisionProtocolError, match="status"):
        parse_analysis(body)


def test_an_unknown_quality_reason_is_refused() -> None:
    """A reason this integration cannot name would be stored as an unread string."""
    body = _load("valid/analyze-response-rejected.json")
    body["quality"]["reasons"] = ["blurry"]

    with pytest.raises(VisionProtocolError, match="unknown reason"):
        parse_analysis(body)


def test_a_foreign_service_name_is_refused() -> None:
    """`/info` identifies the service; anything else is not a Growspace Vision App."""
    body = _load("valid/info.json")
    body["service_name"] = "some_other_service"

    with pytest.raises(VisionProtocolError, match="service_name"):
        parse_info(body)


def test_an_empty_models_catalogue_is_refused() -> None:
    """`/models` promises at least one descriptor; an empty list is malformed."""
    body = _load("valid/models.json")
    body["models"] = []

    with pytest.raises(VisionProtocolError, match="non-empty"):
        parse_models(body)


def test_a_non_object_body_is_refused() -> None:
    """A bare array or string is not a V1 object."""
    with pytest.raises(VisionProtocolError, match="JSON object"):
        parse_info([1, 2, 3])


def _set(body: Any, path: str, value: Any) -> None:
    """Overwrite one dotted path inside a loaded fixture, in place."""
    *parents, key = path.split(".")
    target = body
    for step in parents:
        target = target[int(step)] if step.isdigit() else target[step]
    target[key] = value


@pytest.mark.parametrize(
    ("parser", "fixture", "path", "value", "match"),
    [
        (parse_info, "valid/info.json", "supported_schema_versions", [], "empty"),
        (
            parse_info,
            "valid/info.json",
            "supported_schema_versions",
            [1, 1],
            "repeats a version",
        ),
        (
            parse_info,
            "valid/info.json",
            "supported_schema_versions",
            1,
            "must be an array",
        ),
        (
            parse_info,
            "valid/info.json",
            "supported_schema_versions",
            ["1"],
            "must hold integers",
        ),
        (
            parse_info,
            "valid/info.json",
            "supported_schema_versions",
            [0],
            "out-of-range",
        ),
        (parse_info, "valid/info.json", "service_version", 5, "must be a string"),
        (parse_info, "valid/info.json", "service_version", "", "1 to 255 characters"),
        (
            parse_info,
            "valid/info.json",
            "capabilities.batch_analysis",
            "false",
            "must be a boolean",
        ),
        (
            parse_models,
            "valid/models.json",
            "models.0.state",
            "warming",
            "is not a V1 state",
        ),
        (
            parse_models,
            "valid/models.json",
            "models.0.embedding_dimension",
            "384",
            "must be an integer",
        ),
        (
            parse_models,
            "valid/models.json",
            "models.0.embedding_dimension",
            0,
            "out of range",
        ),
        (
            parse_error,
            "valid/error-model-not-loaded.json",
            "error.code",
            "kettle_offline",
            "not a V1 error code",
        ),
        (
            parse_analysis,
            "valid/analyze-response-rejected.json",
            "quality.reasons",
            "too_dark",
            "must be an array",
        ),
        (
            parse_analysis,
            "valid/analyze-response-rejected.json",
            "quality.reasons",
            ["too_dark", "too_dark"],
            "repeats reason",
        ),
        (
            parse_analysis,
            "valid/analyze-response-rejected.json",
            "quality.signals.mean_luminance",
            "3.4",
            "must be a number",
        ),
        (
            parse_analysis,
            "valid/analyze-response-rejected.json",
            "quality.signals.mean_luminance",
            float("nan"),
            "must be finite",
        ),
        (
            parse_analysis,
            "valid/analyze-response-rejected.json",
            "quality.signals.mean_luminance",
            300,
            "out of range",
        ),
        (
            parse_analysis,
            "valid/analyze-response-analyzed.json",
            "embedding.values",
            "0.1",
            "must be an array",
        ),
        (
            parse_analysis,
            "valid/analyze-response-analyzed.json",
            "embedding.values",
            [0.1, "not a number"],
            "must hold numbers",
        ),
    ],
    ids=[
        "info-offers-no-schema-version",
        "info-repeats-a-schema-version",
        "info-schema-versions-not-an-array",
        "info-schema-versions-not-integers",
        "info-schema-version-below-one",
        "info-service-version-not-a-string",
        "info-service-version-empty",
        "info-capability-not-a-boolean",
        "models-unknown-state",
        "models-dimension-not-an-integer",
        "models-dimension-out-of-range",
        "error-unknown-code",
        "quality-reasons-not-an-array",
        "quality-reasons-repeated",
        "signal-not-a-number",
        "signal-not-finite",
        "signal-out-of-range",
        "embedding-values-not-an-array",
        "embedding-values-not-numbers",
    ],
)
def test_every_typed_field_refuses_its_malformation(
    parser: Any, fixture: str, path: str, value: Any, match: str
) -> None:
    """Each field is typed, ranged and enumerated at the boundary, not later.

    A wrong type reaching evidence would not fail here; it would fail much
    later, in whatever arithmetic or comparison first assumed the contract had
    been honoured, with nothing left to say which App sent it.
    """
    body = _load(fixture)
    _set(body, path, value)

    with pytest.raises(VisionProtocolError, match=match):
        parser(body)


def test_a_non_string_key_is_refused() -> None:
    """JSON cannot express one, but a decoder or a caller can hand one over."""
    with pytest.raises(VisionProtocolError, match="non-string key"):
        parse_info({1: "not a JSON object"})
