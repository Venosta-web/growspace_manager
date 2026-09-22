"""A contract-faithful stand-in for a Growspace Vision App.

Not a response stub. It is a real `aiohttp` server that enforces the parts of
the V1 contract the client has to satisfy — bearer auth on everything but
`/health`, the required `schema_version` query on `/models`, a closed
two-part multipart body on `/analyze`, and a model identity copied exactly from
`/models` — and answers with the frozen fixtures. That is what makes the client
tests prove the request shape and not just the response handling; a stub that
accepted any body would let a malformed multipart request pass forever.

Every failure mode the contract names can be armed on the instance, so busy,
auth, model and deadline semantics are exercised through real HTTP.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from aiohttp import web

FIXTURES = Path(__file__).parent / "fixtures" / "vision" / "growspace-vision" / "v1"

TOKEN = "test-vision-token"


def load_fixture(relative: str) -> Any:
    """Load one vendored contract fixture."""
    return json.loads((FIXTURES / relative).read_text(encoding="utf-8"))


class FakeVisionApp:
    """One in-process Growspace Vision App."""

    def __init__(self, *, token: str = TOKEN) -> None:
        """Start from a healthy App serving the published fixtures."""
        self.token = token
        self.info = load_fixture("valid/info.json")
        self.models = load_fixture("valid/models.json")
        self.analysis = load_fixture("valid/analyze-response-analyzed.json")

        # Armed failures, each named for the contract row it exercises.
        self.fail_analyze_with: tuple[int, str, str] | None = None
        self.fail_info_with: tuple[int, str, str] | None = None
        self.unparseable_error = False
        self.delay_seconds = 0.0

        # What the last request actually carried, for request-shape assertions.
        self.analyze_metadata: dict[str, Any] | None = None
        self.analyze_image: bytes | None = None
        self.metadata_content_type: str | None = None
        self.image_content_type: str | None = None
        self.authorization: str | None = None
        self.requested_schema_version: str | None = None

    def create_app(self) -> web.Application:
        """Build the ASGI-equivalent `aiohttp` application."""
        app = web.Application()
        app.router.add_get("/health", self._health)
        app.router.add_get("/info", self._info)
        app.router.add_get("/models", self._models)
        app.router.add_post("/analyze", self._analyze)
        return app

    async def _health(self, request: web.Request) -> web.StreamResponse:
        """Answer the one unauthenticated endpoint.

        It stays ready while the inference slot is occupied: a busy App is
        loaded, not unhealthy.
        """
        return web.json_response(load_fixture("valid/health-ready.json"))

    async def _info(self, request: web.Request) -> web.StreamResponse:
        denied = self._require_token(request)
        if denied is not None:
            return denied
        if self.fail_info_with is not None:
            return self._error(*self.fail_info_with)
        return web.json_response(self.info)

    async def _models(self, request: web.Request) -> web.StreamResponse:
        denied = self._require_token(request)
        if denied is not None:
            return denied
        self.requested_schema_version = request.query.get("schema_version")
        if self.requested_schema_version is None:
            return self._error(422, "invalid_request", "schema_version is required")
        if self.requested_schema_version not in {
            str(version) for version in self.info["supported_schema_versions"]
        }:
            return self._error(
                422, "unsupported_schema_version", "that schema is not supported"
            )
        return web.json_response(self.models)

    async def _analyze(self, request: web.Request) -> web.StreamResponse:
        denied = self._require_token(request)
        if denied is not None:
            return denied
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.fail_analyze_with is not None:
            return self._error(*self.fail_analyze_with)

        reader = await request.multipart()
        parts: dict[str, Any] = {}
        async for part in reader:
            if part.name == "metadata":
                self.metadata_content_type = part.headers.get("Content-Type")
                parts["metadata"] = json.loads(await part.read())
            elif part.name == "image":
                self.image_content_type = part.headers.get("Content-Type")
                parts["image"] = await part.read()
            else:
                return self._error(
                    422, "invalid_request", f"unexpected part {part.name}"
                )

        if set(parts) != {"metadata", "image"}:
            return self._error(
                422, "invalid_request", "metadata and image are required"
            )

        self.analyze_metadata = parts["metadata"]
        self.analyze_image = parts["image"]

        metadata = parts["metadata"]
        if metadata.get("schema_version") not in self.info["supported_schema_versions"]:
            return self._error(
                422, "unsupported_schema_version", "that schema is not supported"
            )
        offered = {
            (model["model_id"], model["model_version"])
            for model in self.models["models"]
        }
        if (metadata.get("model_id"), metadata.get("model_version")) not in offered:
            return self._error(422, "invalid_request", "unknown model")

        return web.json_response(self.analysis)

    def _require_token(self, request: web.Request) -> web.StreamResponse | None:
        self.authorization = request.headers.get("Authorization")
        if self.authorization != f"Bearer {self.token}":
            return self._error(401, "unauthorized", "token missing or invalid")
        return None

    def _error(self, status: int, code: str, message: str) -> web.StreamResponse:
        if self.unparseable_error:
            return web.Response(status=status, text="<html>gateway error</html>")
        return web.json_response(
            {
                "schema_version": 1,
                "request_id": "0d86ed8c-aa20-41f9-a680-4f79a7a76582",
                "error": {"code": code, "message": message},
            },
            status=status,
        )
