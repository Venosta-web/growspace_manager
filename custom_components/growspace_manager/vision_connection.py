"""Where the Growspace Vision endpoint comes from, and whether it is usable.

This is the integration's only import of Home Assistant's Supervisor
`AddonManager`.  That API is explicitly `quality_scale: internal` and its
`Addon*` symbols are mid-rename to `App*`, so it is confined here: a rename
upstream is a one-file change rather than a scattered break.

Two connection modes, and no silent third (ADR 0043):

* **automatic** pulls `{host, port, token}` from Supervisor App discovery.  It
  is a *pull*, not a push, and that is not a style preference: this
  integration declares `single_config_entry`, and Core aborts a `SOURCE_HASSIO`
  discovery flow with `single_instance_allowed` *before* the flow class is
  constructed, so `async_step_hassio` can never run.  Waiting to be told would
  wait forever.
* **manual** uses the configured endpoint and token and nothing else.  An
  unreachable manual endpoint never falls back to a discovered App, because
  falling back would silently point captures at a service the grower did not
  choose.

`VisionStatus` is a cache with a TTL.  Reading it is free; refreshing it costs
an `/info` and a `/models` round trip.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
import logging
from typing import TYPE_CHECKING, Any, Final

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.hassio import is_hassio
from homeassistant.util.dt import utcnow

from .const import (
    CONF_VISION_ACCESS_TOKEN,
    CONF_VISION_CONNECTION_MODE,
    CONF_VISION_ENDPOINT_URL,
    DEFAULT_VISION_CONNECTION_MODE,
    VISION_APP_SLUG,
    VISION_SETTINGS_KEY,
    VISION_STATUS_TTL_SECONDS,
)
from .exceptions import (
    VisionIncompatibleError,
    VisionModelUnavailableError,
    VisionNotConfiguredError,
    VisionTransportError,
)
from .vision_client import GrowspaceVisionClient, VisionSession

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from homeassistant.core import HomeAssistant

    from .vision_models import ModelIdentity

_LOGGER = logging.getLogger(__name__)

_STATUS_TTL: Final = timedelta(seconds=VISION_STATUS_TTL_SECONDS)
_APP_NAME: Final = "Growspace Vision"
_APP_SLUG_SUFFIX: Final = f"_{VISION_APP_SLUG}"


class VisionConnectionMode(StrEnum):
    """How the endpoint is obtained."""

    AUTOMATIC = "automatic"
    MANUAL = "manual"


class VisionConnectionSource(StrEnum):
    """Where the endpoint in use actually came from."""

    SUPERVISOR = "supervisor"
    MANUAL = "manual"


class VisionAvailability(StrEnum):
    """Whether a Vision Checkup can run right now."""

    READY = "ready"
    UNAVAILABLE = "unavailable"
    INCOMPATIBLE = "incompatible"


class VisionUnavailableReason(StrEnum):
    """Why Vision is not ready.

    ``NOT_CONFIGURED`` covers both halves of the same gap: manual mode with no
    endpoint entered, and an installed, running App that has published no
    discovery payload for Home Assistant to read.
    """

    NOT_INSTALLED = "not_installed"
    NOT_RUNNING = "not_running"
    NOT_CONFIGURED = "not_configured"
    UNREACHABLE = "unreachable"
    SCHEMA_MISMATCH = "schema_mismatch"
    MODEL_UNAVAILABLE = "model_unavailable"


@dataclass(frozen=True, slots=True, kw_only=True)
class VisionEndpoint:
    """One resolved endpoint and the bearer token that opens it.

    ``token`` never leaves the integration: it is not in the config-entry data
    the card can read, not in diagnostics, and not in a log line.
    """

    base_url: str
    token: str
    source: VisionConnectionSource


@dataclass(frozen=True, slots=True, kw_only=True)
class VisionModelSummary:
    """The negotiated model, as the status projection presents it."""

    id: str
    version: str
    dimension: int


@dataclass(frozen=True, slots=True, kw_only=True)
class VisionStatus:
    """The cached answer to "can we run a checkup, and against what?".

    A projection, not evidence.  It is what `get_vision_status` reads and what
    the card renders read-only; it never carries the token.
    """

    availability: VisionAvailability
    connection_source: VisionConnectionSource
    reason: VisionUnavailableReason | None = None
    service_version: str | None = None
    vision_schema_version: int | None = None
    model: VisionModelSummary | None = None

    @property
    def is_ready(self) -> bool:
        """Return whether a checkup may run against this App."""
        return self.availability is VisionAvailability.READY


class VisionConnection:
    """Resolves the endpoint, negotiates once, and caches the outcome."""

    def __init__(
        self,
        hass: HomeAssistant,
        options: Callable[[], Mapping[str, Any]],
    ) -> None:
        """Bind to the live options mapping rather than a snapshot of it.

        The options flow rewrites connection settings in place, so a snapshot
        taken at construction would keep pointing at the old App.
        """
        self._hass = hass
        self._options = options
        self._status = VisionStatus(
            availability=VisionAvailability.UNAVAILABLE,
            connection_source=VisionConnectionSource.SUPERVISOR,
            reason=VisionUnavailableReason.NOT_CONFIGURED,
        )
        self._negotiated: VisionSession | None = None
        self._pinned_model: ModelIdentity | None = None
        self._refreshed_at: datetime | None = None

    @property
    def status(self) -> VisionStatus:
        """Return the cached status without touching the network."""
        return self._status

    @property
    def negotiated(self) -> VisionSession | None:
        """Return the negotiated schema and model, if the last probe succeeded."""
        return self._negotiated

    @property
    def is_stale(self) -> bool:
        """Return whether the cache is old enough to re-probe before acting."""
        if self._refreshed_at is None:
            return True
        return utcnow() - self._refreshed_at > _STATUS_TTL

    def pin_model(self, model: ModelIdentity | None) -> None:
        """Require future negotiations to keep using one model.

        Set from stored evidence, so a Baseline Bucket's model cannot be
        swapped out from under it by an App update.  An absent pin means the
        next negotiation picks the App's loaded model and records it.
        """
        self._pinned_model = model

    async def async_refresh(self) -> VisionStatus:
        """Re-resolve the endpoint and re-negotiate, caching the outcome.

        Never raises: an unusable App is a status, not an exception, because
        every caller of this wants to report the reason rather than fail.
        """
        self._refreshed_at = utcnow()
        try:
            endpoint = await self.async_resolve_endpoint()
        except VisionNotConfiguredError as err:
            self._set_unavailable(_reason_of(err), self._configured_source())
            return self._status

        client = self.build_client(endpoint)
        try:
            session = await client.async_negotiate(pinned_model=self._pinned_model)
        except VisionIncompatibleError:
            self._negotiated = None
            self._status = VisionStatus(
                availability=VisionAvailability.INCOMPATIBLE,
                connection_source=endpoint.source,
                reason=VisionUnavailableReason.SCHEMA_MISMATCH,
            )
        except VisionModelUnavailableError:
            self._set_unavailable(
                VisionUnavailableReason.MODEL_UNAVAILABLE, endpoint.source
            )
        except VisionTransportError:
            self._set_unavailable(VisionUnavailableReason.UNREACHABLE, endpoint.source)
        except Exception:  # noqa: BLE001 - any other failure is still "unusable"
            _LOGGER.debug("Growspace Vision probe failed", exc_info=True)
            self._set_unavailable(VisionUnavailableReason.UNREACHABLE, endpoint.source)
        else:
            self._negotiated = session
            self._status = VisionStatus(
                availability=VisionAvailability.READY,
                connection_source=endpoint.source,
                service_version=session.service_version,
                vision_schema_version=session.schema_version,
                model=VisionModelSummary(
                    id=session.model.model_id,
                    version=session.model.model_version,
                    dimension=session.embedding_dimension,
                ),
            )
        return self._status

    async def async_refresh_if_stale(self) -> VisionStatus:
        """Refresh only when the cache has aged past its TTL."""
        if self.is_stale:
            return await self.async_refresh()
        return self._status

    async def async_resolve_endpoint(self) -> VisionEndpoint:
        """Return the endpoint the configured mode selects, or raise.

        Manual mode is exclusive by design: it does not consult discovery, so a
        typo in a manual endpoint surfaces as a failure rather than as captures
        quietly going to a different service.
        """
        settings = self._vision_settings()
        mode = _mode_of(settings)
        if mode is VisionConnectionMode.MANUAL:
            return _manual_endpoint(settings)
        return await self._async_supervisor_endpoint()

    def build_client(self, endpoint: VisionEndpoint) -> GrowspaceVisionClient:
        """Build a client bound to one endpoint on Home Assistant's session."""
        return GrowspaceVisionClient(
            async_get_clientsession(self._hass),
            base_url=endpoint.base_url,
            token=endpoint.token,
        )

    async def async_shutdown(self) -> None:
        """Drop the cached negotiation.

        There is no socket to close: the client borrows Home Assistant's shared
        `aiohttp` session and must not close it.
        """
        self._negotiated = None
        self._refreshed_at = None

    async def _async_supervisor_endpoint(self) -> VisionEndpoint:
        """Pull the App's published `{host, port, token}` through Supervisor."""
        if not is_hassio(self._hass):
            raise VisionNotConfiguredError(
                "Supervisor is not available; configure a manual Growspace Vision "
                "endpoint instead"
            )

        # Imported here, and only here: `hassio` is an `after_dependencies`, so
        # on Home Assistant Container it is never set up and constructing an
        # AddonManager would raise KeyError before its own error handling.
        # Everything below stays in Core's `AddonInfo`/`AddonState` vocabulary
        # rather than `aiohasupervisor`'s, whose models are not a public API.
        from homeassistant.components.hassio import (  # noqa: PLC0415
            AddonError,
            AddonManager,
            AddonState,
        )

        slug = await self._async_installed_app_slug()
        manager = AddonManager(self._hass, _LOGGER, _APP_NAME, slug)
        try:
            info = await manager.async_get_addon_info()
        except AddonError as err:
            raise VisionNotConfiguredError(
                f"Supervisor could not describe the {_APP_NAME} App: {err}",
                reason=VisionUnavailableReason.NOT_INSTALLED,
            ) from err
        if info.state is not AddonState.RUNNING:
            raise VisionNotConfiguredError(
                f"The {_APP_NAME} App is not running",
                reason=VisionUnavailableReason.NOT_RUNNING,
            )

        try:
            config = await manager.async_get_addon_discovery_info()
        except AddonError as err:
            raise VisionNotConfiguredError(
                f"The {_APP_NAME} App has published no endpoint for Home Assistant"
            ) from err
        return _discovered_endpoint(config)

    async def _async_installed_app_slug(self) -> str:
        """Find the installed App's Supervisor slug, or say it is absent.

        Supervisor composes the slug as `{repository}_{config slug}`, where the
        repository part is `local` for a side-loaded App and an eight-character
        hash of the repository URL for a store install.  It is therefore
        discovered by suffix and never hard-coded: a hard-coded slug would work
        on exactly one machine.
        """
        from homeassistant.components.hassio import (  # noqa: PLC0415
            get_supervisor_client,
        )

        try:
            installed = await get_supervisor_client(self._hass).addons.list()
        except Exception as err:
            raise VisionNotConfiguredError(
                f"Supervisor did not list its Apps: {err}"
            ) from err

        for app in installed:
            if app.slug == VISION_APP_SLUG or app.slug.endswith(_APP_SLUG_SUFFIX):
                return str(app.slug)
        raise VisionNotConfiguredError(
            f"The {_APP_NAME} App is not installed",
            reason=VisionUnavailableReason.NOT_INSTALLED,
        )

    def _vision_settings(self) -> Mapping[str, Any]:
        settings = self._options().get(VISION_SETTINGS_KEY)
        return settings if isinstance(settings, dict) else {}

    def _configured_source(self) -> VisionConnectionSource:
        if _mode_of(self._vision_settings()) is VisionConnectionMode.MANUAL:
            return VisionConnectionSource.MANUAL
        return VisionConnectionSource.SUPERVISOR

    def _set_unavailable(
        self, reason: VisionUnavailableReason, source: VisionConnectionSource
    ) -> None:
        self._negotiated = None
        self._status = VisionStatus(
            availability=VisionAvailability.UNAVAILABLE,
            connection_source=source,
            reason=reason,
        )


def _mode_of(settings: Mapping[str, Any]) -> VisionConnectionMode:
    raw = settings.get(CONF_VISION_CONNECTION_MODE, DEFAULT_VISION_CONNECTION_MODE)
    try:
        return VisionConnectionMode(raw)
    except ValueError:
        return VisionConnectionMode(DEFAULT_VISION_CONNECTION_MODE)


def _manual_endpoint(settings: Mapping[str, Any]) -> VisionEndpoint:
    """Build the manually configured endpoint, or say what is missing.

    An unauthenticated manual endpoint is an invalid configuration, not a
    permitted convenience: every endpoint but `/health` requires the token.
    """
    url = str(settings.get(CONF_VISION_ENDPOINT_URL) or "").strip()
    token = str(settings.get(CONF_VISION_ACCESS_TOKEN) or "").strip()
    if not url or not token:
        raise VisionNotConfiguredError(
            "A manual Growspace Vision connection needs both an endpoint URL and an "
            "access token"
        )
    return VisionEndpoint(
        base_url=url, token=token, source=VisionConnectionSource.MANUAL
    )


def _discovered_endpoint(config: Mapping[str, Any]) -> VisionEndpoint:
    """Read `{host, port, token}` out of the App's discovery payload."""
    host = str(config.get("host") or "").strip()
    port = config.get("port")
    token = str(config.get("token") or "").strip()
    if not host or not isinstance(port, int) or isinstance(port, bool) or not token:
        raise VisionNotConfiguredError(
            f"The {_APP_NAME} App published an incomplete discovery payload"
        )
    return VisionEndpoint(
        base_url=f"http://{host}:{port}",
        token=token,
        source=VisionConnectionSource.SUPERVISOR,
    )


def _reason_of(error: VisionNotConfiguredError) -> VisionUnavailableReason:
    """Classify why no endpoint could be resolved."""
    if error.reason is None:
        return VisionUnavailableReason.NOT_CONFIGURED
    return VisionUnavailableReason(error.reason)
