"""The only HTTP client for a Growspace Vision App.

Nothing else in the integration talks to the App.  This module owns
negotiation, model selection, the bearer token, the integration-side timeout,
and the mapping from a transport or typed service failure to one of the
`VisionError` types in `exceptions`.

Two rules run through all of it, both from ADR 0003 (Vision):

* **A failure is a failure.**  Any non-2xx response, any timeout, any
  unparsable body raises.  There is no empty, normal or healthy substitute
  result, and nothing retries automatically — a `429 busy` is normal load, and
  still ends this capture.
* **A rejection is not a failure.**  A quality-rejected frame is a 200 with no
  embedding, returned as an ordinary `VisionAnalysis`.  The caller records it
  as unusable rather than treating it as an error.

Pure I/O boundary: it holds no baselines, no history and no policy.  Which
model to pin is the caller's decision; this module only refuses to change it
silently.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from typing import TYPE_CHECKING, Final

import aiohttp

from .exceptions import (
    VisionAuthError,
    VisionBusyError,
    VisionIncompatibleError,
    VisionModelUnavailableError,
    VisionProtocolError,
    VisionServiceError,
    VisionTransportError,
)
from .models.vision_evidence import LightState
from .vision_models import (
    SUPPORTED_SCHEMA_VERSIONS,
    AnalyzeMetadata,
    ModelDescriptor,
    ModelIdentity,
    ServiceInfo,
    VisionAnalysis,
    VisionErrorCode,
    parse_analysis,
    parse_error,
    parse_health,
    parse_info,
    parse_models,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

_LOGGER = logging.getLogger(__name__)

VISION_TOTAL_TIMEOUT_SECONDS: Final = 15
"""The integration's half of the operational contract.

Deliberately longer than the App's own 10-second inference deadline, so an
App-side deadline arrives as `500 internal_failure` with a request id rather
than as a blind client timeout.
"""

_ANALYZE_CONTENT_TYPES: Final = frozenset({"image/jpeg", "image/png"})


@dataclass(frozen=True, slots=True, kw_only=True)
class VisionSession:
    """The outcome of one negotiation: what to send on every `/analyze`.

    Held by the caller and passed back in, so a capture cannot silently drift
    onto a different schema or model between negotiation and analysis.
    """

    schema_version: int
    service_version: str
    model: ModelIdentity
    embedding_dimension: int


class GrowspaceVisionClient:
    """Talks V1 to one Growspace Vision App."""

    def __init__(
        self,
        http_session: aiohttp.ClientSession,
        *,
        base_url: str,
        token: str,
        timeout_seconds: float = VISION_TOTAL_TIMEOUT_SECONDS,
    ) -> None:
        """Bind the client to one endpoint and its per-install bearer token.

        `http_session` is Home Assistant's shared `aiohttp` session; it is
        borrowed, never closed here. It is deliberately not called `session` —
        in this module that word means a negotiated `VisionSession`.
        """
        self._http = http_session
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async def async_check_health(self) -> None:
        """Probe the unauthenticated readiness endpoint, raising if not ready.

        `/health` stays ready while the sole inference slot is occupied: a busy
        App is loaded, not unhealthy.
        """
        payload = await self._request("GET", "/health", authenticated=False)
        parse_health(payload)

    async def async_get_info(self) -> ServiceInfo:
        """Read the frozen `/info` negotiation bootstrap."""
        return parse_info(await self._request("GET", "/info"))

    async def async_get_models(
        self, schema_version: int
    ) -> tuple[ModelDescriptor, ...]:
        """List the models usable with one negotiated analysis schema."""
        payload = await self._request(
            "GET", "/models", params={"schema_version": str(schema_version)}
        )
        return parse_models(payload)

    async def async_negotiate(
        self, *, pinned_model: ModelIdentity | None = None
    ) -> VisionSession:
        """Agree a schema version and a model with the App.

        The schema is the **highest exact intersection** of what `/info`
        advertises and what this integration implements; no shared version
        makes Vision incompatible rather than unreachable, so the caller can
        say why.

        `pinned_model` is honoured or refused, never substituted.  A pinned
        model that has gone away raises rather than quietly moving the
        integration onto a model whose embeddings are not comparable with the
        Baseline Buckets already built from the old one.
        """
        info = await self.async_get_info()
        shared = set(info.supported_schema_versions) & set(SUPPORTED_SCHEMA_VERSIONS)
        if not shared:
            raise VisionIncompatibleError(
                f"Growspace Vision {info.service_version} supports analysis schema "
                f"{sorted(info.supported_schema_versions)}; this integration supports "
                f"{sorted(SUPPORTED_SCHEMA_VERSIONS)}"
            )
        schema_version = max(shared)

        models = await self.async_get_models(schema_version)
        chosen = _select_model(models, pinned_model)
        return VisionSession(
            schema_version=schema_version,
            service_version=info.service_version,
            model=chosen.identity,
            embedding_dimension=chosen.embedding_dimension,
        )

    async def async_analyze(
        self,
        *,
        session: VisionSession,
        image: bytes,
        content_type: str,
        camera_id: str,
        growspace_id: str,
        captured_at: datetime,
        light_state: LightState,
    ) -> VisionAnalysis:
        """Analyze exactly one frame, returning its accepted or rejected result.

        The negotiated session supplies the schema and model identity, so the
        request always copies an exact loaded pair rather than a remembered
        one.
        """
        if content_type not in _ANALYZE_CONTENT_TYPES:
            raise VisionProtocolError(
                f"Growspace Vision accepts JPEG or PNG, not {content_type!r}"
            )
        metadata = AnalyzeMetadata(
            schema_version=session.schema_version,
            camera_id=camera_id,
            growspace_id=growspace_id,
            captured_at=captured_at,
            light_state=light_state,
            model=session.model,
        )
        form = aiohttp.FormData()
        form.add_field(
            "metadata",
            _dump_json(metadata.to_wire()),
            content_type="application/json",
        )
        form.add_field("image", image, content_type=content_type, filename="capture")

        analysis = parse_analysis(await self._request("POST", "/analyze", data=form))
        _verify_analysis_matches(analysis, session)
        return analysis

    async def _request(
        self,
        method: str,
        path: str,
        *,
        authenticated: bool = True,
        params: Mapping[str, str] | None = None,
        data: aiohttp.FormData | None = None,
    ) -> object:
        """Perform one request and return its decoded JSON body, or raise."""
        headers = {"Accept": "application/json"}
        if authenticated:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            async with self._http.request(
                method,
                f"{self._base_url}{path}",
                headers=headers,
                params=params,
                data=data,
                timeout=self._timeout,
            ) as response:
                body = await response.read()
                if response.status >= 400:
                    raise _service_error(response.status, body)
                if response.status != 200:
                    raise VisionServiceError(
                        f"Growspace Vision answered {response.status} for {path}",
                        status=response.status,
                    )
                return _decode_json(body)
        except TimeoutError as err:
            # No response body, but exactly the same no-write semantics as an
            # App-side failure.
            raise VisionTransportError(
                f"Growspace Vision did not answer {path} within "
                f"{VISION_TOTAL_TIMEOUT_SECONDS}s"
            ) from err
        except aiohttp.ClientError as err:
            raise VisionTransportError(
                f"Growspace Vision could not be reached at {path}: {err}"
            ) from err


def _select_model(
    models: tuple[ModelDescriptor, ...], pinned: ModelIdentity | None
) -> ModelDescriptor:
    """Choose the model to analyze with, or refuse.

    With nothing pinned this takes the sole loaded model.  V1 bundles exactly
    one, so several is not an expected shape; picking the highest identity
    keeps it deterministic across restarts, which matters because an
    unannounced change of model would invalidate every Baseline Bucket.
    """
    if pinned is not None:
        for model in models:
            if model.identity == pinned:
                if not model.is_loaded:
                    raise VisionModelUnavailableError(
                        f"Model {pinned.model_id} {pinned.model_version} is loaded "
                        "nowhere on this App"
                    )
                return model
        raise VisionModelUnavailableError(
            f"Model {pinned.model_id} {pinned.model_version} is no longer offered "
            "by this App"
        )

    loaded = [model for model in models if model.is_loaded]
    if not loaded:
        raise VisionModelUnavailableError("This App has no loaded model")
    if len(loaded) > 1:
        _LOGGER.debug(
            "Growspace Vision offers %d loaded models; taking the highest identity",
            len(loaded),
        )
    return max(
        loaded,
        key=lambda model: (model.identity.model_id, model.identity.model_version),
    )


def _verify_analysis_matches(analysis: VisionAnalysis, session: VisionSession) -> None:
    """Refuse a 200 that answered for a schema or model we did not request."""
    if analysis.schema_version != session.schema_version:
        raise VisionProtocolError(
            f"Growspace Vision answered schema {analysis.schema_version} for a "
            f"schema {session.schema_version} request"
        )
    if not analysis.accepted:
        return
    if analysis.model != session.model:
        raise VisionProtocolError(
            "Growspace Vision answered with a different model than the request selected"
        )
    if analysis.embedding is None or analysis.embedding.dimension != (
        session.embedding_dimension
    ):
        raise VisionProtocolError(
            f"Growspace Vision returned an embedding that is not "
            f"{session.embedding_dimension}-dimensional"
        )


def _service_error(
    status: int, body: bytes
) -> VisionServiceError | VisionModelUnavailableError:
    """Map a non-2xx response onto its typed error."""
    code: VisionErrorCode | None = None
    request_id: str | None = None
    detail = f"HTTP {status}"
    try:
        error = parse_error(_decode_json(body))
    except VisionProtocolError:
        # A non-2xx that is not even a V1 error body is still a failure; it
        # just cannot say which one.
        _LOGGER.debug("Growspace Vision returned an unparsable %d body", status)
    else:
        code = error.code
        request_id = error.request_id
        detail = f"{error.code} ({error.message})"

    message = f"Growspace Vision failed: {detail}"
    if code is VisionErrorCode.BUSY or status == 429:
        return VisionBusyError(
            "Growspace Vision is already analyzing another frame",
            status=status,
            code=code,
            request_id=request_id,
        )
    if code is VisionErrorCode.UNAUTHORIZED or status == 401:
        return VisionAuthError(
            "Growspace Vision rejected the configured access token",
            status=status,
            code=code,
            request_id=request_id,
        )
    if code is VisionErrorCode.MODEL_NOT_LOADED or status == 503:
        return VisionModelUnavailableError(message)
    return VisionServiceError(message, status=status, code=code, request_id=request_id)


def _decode_json(body: bytes) -> object:
    """Decode a response body, treating anything unparsable as a violation."""
    try:
        return json.loads(body)
    except (UnicodeDecodeError, ValueError) as err:
        raise VisionProtocolError("Growspace Vision returned a non-JSON body") from err


def _dump_json(payload: dict[str, object]) -> str:
    """Render the metadata part compactly and deterministically."""
    return json.dumps(payload, separators=(",", ":"))
