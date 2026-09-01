"""The Growspace Vision client, against a contract-faithful App.

These run over real HTTP against `tests/vision_app_double.py`, so the request
shape is proved and not assumed: a metadata part the App cannot parse, a
missing `schema_version` query, or a model identity that is not one of the
App's own would fail here rather than in production.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import aiohttp
import pytest

from custom_components.growspace_manager.exceptions import (
    VisionAuthError,
    VisionBusyError,
    VisionIncompatibleError,
    VisionModelUnavailableError,
    VisionProtocolError,
    VisionServiceError,
    VisionTransportError,
)
from custom_components.growspace_manager.models.vision_evidence import LightState
from custom_components.growspace_manager.vision_client import GrowspaceVisionClient
from custom_components.growspace_manager.vision_models import (
    AnalysisStatus,
    ModelIdentity,
    QualityReason,
)

from .vision_app_double import TOKEN, FakeVisionApp, load_fixture

CAPTURED_AT = datetime(2026, 8, 31, 8, 30, tzinfo=UTC)
IMAGE = b"\xff\xd8\xff\xe0 not really a jpeg, the App double does not decode"
PRODUCTION_MODEL = ModelIdentity(
    model_id="dinov2-vit-s-14-int8-onnx", model_version="1.0.0"
)


@pytest.fixture
def app() -> FakeVisionApp:
    """Return a healthy Growspace Vision App double."""
    return FakeVisionApp()


@pytest.fixture
async def client(
    app: FakeVisionApp,
    aiohttp_client: Callable[..., Any],
    socket_enabled: None,
) -> GrowspaceVisionClient:
    """Serve the double and return a client bound to it."""
    test_client = await aiohttp_client(app.create_app())
    return GrowspaceVisionClient(
        test_client.session,
        base_url=str(test_client.make_url("")),
        token=TOKEN,
    )


async def _analyze(client: GrowspaceVisionClient, **overrides: Any) -> Any:
    session = await client.async_negotiate()
    return await client.async_analyze(
        session=session,
        image=IMAGE,
        content_type="image/jpeg",
        camera_id="camera.growcam_sog",
        growspace_id="growspace-sog-01",
        captured_at=CAPTURED_AT,
        light_state=LightState.ON,
        **overrides,
    )


async def test_health_is_unauthenticated(
    app: FakeVisionApp, client: GrowspaceVisionClient
) -> None:
    """`/health` is the Supervisor watchdog's endpoint and carries no token.

    Sending one would be harmless but would hide a real deployment property:
    the watchdog cannot attach headers, so readiness must not require them.
    """
    app.token = "a-different-token"

    await client.async_check_health()

    assert app.authorization is None


async def test_every_other_endpoint_carries_the_bearer_token(
    app: FakeVisionApp, client: GrowspaceVisionClient
) -> None:
    """The per-install token authenticates `/info`, `/models` and `/analyze`."""
    await client.async_get_info()

    assert app.authorization == f"Bearer {TOKEN}"


async def test_a_rejected_token_is_an_auth_failure(
    app: FakeVisionApp, client: GrowspaceVisionClient
) -> None:
    """401 is typed, so the status projection can say "check the token"."""
    app.token = "the-app-rotated-its-token"

    with pytest.raises(VisionAuthError):
        await client.async_get_info()


async def test_negotiation_selects_the_highest_shared_schema(
    app: FakeVisionApp, client: GrowspaceVisionClient
) -> None:
    """An App offering more than V1 still gets V1, the highest exact intersection."""
    app.info["supported_schema_versions"] = [1, 2, 3]

    session = await client.async_negotiate()

    assert session.schema_version == 1
    assert app.requested_schema_version == "1"


async def test_no_shared_schema_is_incompatible_not_unreachable(
    app: FakeVisionApp, client: GrowspaceVisionClient
) -> None:
    """An App that dropped V1 is still discoverable through the frozen bootstrap.

    That is the whole reason `/info` is permanently V1-shaped: the integration
    can tell "you need to upgrade" apart from "nothing answered".
    """
    app.info["supported_schema_versions"] = [2]

    with pytest.raises(VisionIncompatibleError):
        await client.async_negotiate()


async def test_negotiation_reports_the_loaded_model(
    client: GrowspaceVisionClient,
) -> None:
    """The session carries the exact identity later requests must copy."""
    session = await client.async_negotiate()

    assert session.model == PRODUCTION_MODEL
    assert session.embedding_dimension == 384
    assert session.service_version == "1.0.0"


async def test_a_pinned_model_that_went_away_refuses_rather_than_substitutes(
    app: FakeVisionApp, client: GrowspaceVisionClient
) -> None:
    """Silently switching models would invalidate every Baseline Bucket.

    Embeddings from different model versions are not comparable, so the choice
    to move belongs to whoever owns the baselines — never to a negotiation that
    found something else loaded.
    """
    app.models["models"] = [
        {
            "model_id": "dinov2-vit-s-14-int8-onnx",
            "model_version": "2.0.0",
            "embedding_dimension": 384,
            "state": "loaded",
        }
    ]

    with pytest.raises(VisionModelUnavailableError):
        await client.async_negotiate(pinned_model=PRODUCTION_MODEL)


async def test_a_pinned_model_that_is_unavailable_refuses(
    app: FakeVisionApp, client: GrowspaceVisionClient
) -> None:
    """A known model whose state is `unavailable` cannot serve an analysis."""
    app.models["models"][0]["state"] = "unavailable"

    with pytest.raises(VisionModelUnavailableError):
        await client.async_negotiate(pinned_model=PRODUCTION_MODEL)


async def test_no_loaded_model_refuses(
    app: FakeVisionApp, client: GrowspaceVisionClient
) -> None:
    """An App with nothing loaded is unusable even though `/models` answered."""
    app.models["models"][0]["state"] = "unavailable"

    with pytest.raises(VisionModelUnavailableError):
        await client.async_negotiate()


async def test_analyze_sends_the_closed_two_part_multipart_request(
    app: FakeVisionApp, client: GrowspaceVisionClient
) -> None:
    """The App parses exactly two named parts with the declared content types."""
    await _analyze(client)

    assert app.analyze_image == IMAGE
    assert app.image_content_type == "image/jpeg"
    assert app.metadata_content_type == "application/json"
    assert app.analyze_metadata == load_fixture("valid/analyze-metadata.json")


async def test_analyze_returns_the_embedding_for_an_accepted_frame(
    client: GrowspaceVisionClient,
) -> None:
    """An accepted frame yields its model-versioned vector and empty reasons."""
    analysis = await _analyze(client)

    assert analysis.status is AnalysisStatus.ANALYZED
    assert analysis.model == PRODUCTION_MODEL
    assert analysis.embedding is not None
    assert analysis.embedding.dimension == 384


async def test_a_quality_rejection_is_a_result_and_not_an_exception(
    app: FakeVisionApp, client: GrowspaceVisionClient
) -> None:
    """An unusable frame is first-class evidence, so it must not raise.

    Raising would erase the attempt; the capture has to stay recorded as
    rejected with the reasons that held.
    """
    app.analysis = load_fixture("valid/analyze-response-rejected.json")

    analysis = await _analyze(client)

    assert analysis.status is AnalysisStatus.REJECTED
    assert analysis.embedding is None
    assert QualityReason.TOO_DARK in analysis.quality.reasons


async def test_busy_is_a_typed_failure_and_is_not_retried(
    app: FakeVisionApp, client: GrowspaceVisionClient
) -> None:
    """429 is normal load, and still ends this capture.

    The App runs one inference with no queue, so a retry here would just take
    the next slot from whoever is using it. Home Assistant owns the scheduling.
    """
    app.fail_analyze_with = (429, "busy", "the inference slot is occupied")

    with pytest.raises(VisionBusyError) as raised:
        await _analyze(client)

    assert raised.value.status == 429
    assert raised.value.request_id == "0d86ed8c-aa20-41f9-a680-4f79a7a76582"


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (413, "image_too_large"),
        (415, "unsupported_image_format"),
        (422, "invalid_request"),
        (500, "internal_failure"),
    ],
)
async def test_every_other_typed_error_raises_with_its_code(
    app: FakeVisionApp,
    client: GrowspaceVisionClient,
    status: int,
    code: str,
) -> None:
    """Any non-2xx means the service failed; none of them yields a result."""
    app.fail_analyze_with = (status, code, "failed")

    with pytest.raises(VisionServiceError) as raised:
        await _analyze(client)

    assert raised.value.status == status
    assert raised.value.code == code


async def test_model_not_loaded_is_its_own_failure(
    app: FakeVisionApp, client: GrowspaceVisionClient
) -> None:
    """503 is distinct from an unknown model, which is an invalid request."""
    app.fail_analyze_with = (503, "model_not_loaded", "the model is unavailable")

    with pytest.raises(VisionModelUnavailableError):
        await _analyze(client)


async def test_a_non_json_error_body_still_fails(
    app: FakeVisionApp, client: GrowspaceVisionClient
) -> None:
    """A proxy's HTML error page is a failure that cannot name its code."""
    app.fail_analyze_with = (502, "internal_failure", "bad gateway")
    app.unparseable_error = True

    with pytest.raises(VisionServiceError) as raised:
        await _analyze(client)

    assert raised.value.status == 502
    assert raised.value.code is None


async def test_a_client_timeout_has_the_same_no_write_semantics(
    app: FakeVisionApp,
    aiohttp_client: Callable[..., Any],
    socket_enabled: None,
) -> None:
    """An integration-side timeout has no response body and still raises.

    It must not be mistakable for an empty or normal result: nothing may be
    written for a capture whose analysis never came back.
    """
    test_client = await aiohttp_client(app.create_app())
    client = GrowspaceVisionClient(
        test_client.session,
        base_url=str(test_client.make_url("")),
        token=TOKEN,
        timeout_seconds=0.15,
    )
    app.delay_seconds = 1.0

    with pytest.raises(VisionTransportError):
        await _analyze(client)


async def test_an_unreachable_endpoint_is_a_transport_failure(
    socket_enabled: None,
) -> None:
    """Nothing listening is a failure, not an unhealthy-looking success."""
    async with aiohttp.ClientSession() as session:
        client = GrowspaceVisionClient(
            session,
            base_url="http://127.0.0.1:1",
            token=TOKEN,
            timeout_seconds=1,
        )

        with pytest.raises(VisionTransportError):
            await client.async_get_info()


async def test_a_response_carrying_a_forbidden_output_is_refused(
    app: FakeVisionApp, client: GrowspaceVisionClient
) -> None:
    """`anomaly_score` is Home Assistant's to compute, never the App's to send.

    Accepting it would let a service-side temporal claim into evidence that the
    contract says only history can produce.
    """
    app.analysis = load_fixture("invalid/response-anomaly-score.json")

    with pytest.raises(VisionProtocolError):
        await _analyze(client)


async def test_a_response_for_another_model_is_refused(
    app: FakeVisionApp, client: GrowspaceVisionClient
) -> None:
    """An embedding from a model we did not ask for is not comparable."""
    app.analysis = load_fixture("valid/analyze-response-analyzed.json")
    app.analysis["model"]["model_version"] = "9.9.9"

    with pytest.raises(VisionProtocolError, match="different model"):
        await _analyze(client)


async def test_an_embedding_of_the_wrong_width_is_refused(
    app: FakeVisionApp, client: GrowspaceVisionClient
) -> None:
    """`/models` declared 384; a vector of another width contradicts the catalogue."""
    app.analysis = load_fixture("valid/analyze-response-analyzed.json")
    app.analysis["embedding"] = {"dimension": 2, "values": [0.1, 0.2]}

    with pytest.raises(VisionProtocolError, match="384-dimensional"):
        await _analyze(client)


async def test_a_non_image_content_type_never_reaches_the_app(
    app: FakeVisionApp, client: GrowspaceVisionClient
) -> None:
    """V1 accepts JPEG and PNG; anything else is refused before the round trip."""
    session = await client.async_negotiate()
    app.analyze_image = None

    with pytest.raises(VisionProtocolError):
        await client.async_analyze(
            session=session,
            image=IMAGE,
            content_type="image/webp",
            camera_id="camera.growcam_sog",
            growspace_id="growspace-sog-01",
            captured_at=CAPTURED_AT,
            light_state=LightState.ON,
        )

    assert app.analyze_image is None
