"""Where the Vision endpoint comes from, and what the status cache says about it.

Two mechanisms and no silent third: Supervisor pull discovery, and a manual
endpoint. The tests that matter most here are the ones proving the *absence* of
a fallback — manual mode never consults discovery, and switching back to
automatic does not leave a dormant credential behind.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import (
    CONF_VISION_ACCESS_TOKEN,
    CONF_VISION_CONNECTION_MODE,
    CONF_VISION_ENDPOINT_URL,
    VISION_SETTINGS_KEY,
)
from custom_components.growspace_manager.exceptions import VisionNotConfiguredError
from custom_components.growspace_manager.vision_connection import (
    VisionAvailability,
    VisionConnection,
    VisionConnectionSource,
    VisionUnavailableReason,
)
from homeassistant.core import HomeAssistant

from .vision_app_double import TOKEN, FakeVisionApp

DISCOVERED_TOKEN = "token-the-app-generated"


def _manual(url: str, token: str = TOKEN) -> dict[str, Any]:
    return {
        VISION_SETTINGS_KEY: {
            CONF_VISION_CONNECTION_MODE: "manual",
            CONF_VISION_ENDPOINT_URL: url,
            CONF_VISION_ACCESS_TOKEN: token,
        }
    }


def _automatic() -> dict[str, Any]:
    return {VISION_SETTINGS_KEY: {CONF_VISION_CONNECTION_MODE: "automatic"}}


@contextmanager
def _supervisor(
    *,
    slugs: list[str] | None = None,
    state: Any = None,
    discovery: dict[str, Any] | Exception | None = None,
):
    """Stand in for a Supervisor holding some installed Apps.

    `slugs` are the composed Supervisor slugs of the installed Apps, `state` the
    Core `AddonState` of the matched one, and `discovery` the payload it
    published — or the `AddonError` raised when it published none.
    """
    from homeassistant.components.hassio import AddonInfo, AddonState

    supervisor = MagicMock()
    supervisor.addons.list = AsyncMock(
        return_value=[MagicMock(slug=slug) for slug in (slugs or [])]
    )

    manager = MagicMock()
    manager.async_get_addon_info = AsyncMock(
        return_value=AddonInfo(
            available=True,
            hostname="local-growspace-vision",
            options={},
            state=state or AddonState.RUNNING,
            update_available=False,
            version="1.0.0",
        )
    )
    if isinstance(discovery, Exception):
        manager.async_get_addon_discovery_info = AsyncMock(side_effect=discovery)
    else:
        manager.async_get_addon_discovery_info = AsyncMock(return_value=discovery or {})

    with (
        patch(
            "custom_components.growspace_manager.vision_connection.is_hassio",
            return_value=True,
        ),
        patch(
            "homeassistant.components.hassio.get_supervisor_client",
            return_value=supervisor,
        ),
        patch("homeassistant.components.hassio.AddonManager", return_value=manager),
    ):
        yield


@pytest.fixture
async def served_app(
    aiohttp_client: Callable[..., Any], socket_enabled: None
) -> tuple[FakeVisionApp, str, int]:
    """Serve a healthy Growspace Vision App and report its host and port."""
    app = FakeVisionApp()
    test_client = await aiohttp_client(app.create_app())
    return app, test_client.server.host, test_client.server.port


async def test_supervisor_discovery_yields_a_ready_status(
    hass: HomeAssistant, served_app: tuple[FakeVisionApp, str, int]
) -> None:
    """The published `{host, port, token}` is all the integration needs."""
    app, host, port = served_app
    app.token = DISCOVERED_TOKEN

    with _supervisor(
        slugs=["a1b2c3d4_growspace_vision"],
        discovery={"host": host, "port": port, "token": DISCOVERED_TOKEN},
    ):
        connection = VisionConnection(hass, _automatic)
        status = await connection.async_refresh()

    assert status.availability is VisionAvailability.READY
    assert status.connection_source is VisionConnectionSource.SUPERVISOR
    assert status.service_version == "1.0.0"
    assert status.vision_schema_version == 1
    assert status.model is not None
    assert status.model.id == "dinov2-vit-s-14-int8-onnx"
    assert status.model.dimension == 384


async def test_the_app_slug_is_matched_by_suffix_not_hard_coded(
    hass: HomeAssistant, served_app: tuple[FakeVisionApp, str, int]
) -> None:
    """Supervisor prefixes the slug with a hash of the App repository URL.

    That prefix differs between a store install and a side-loaded one and
    changes if the repository URL changes, so hard-coding the composed slug
    would work on exactly one machine.
    """
    app, host, port = served_app
    app.token = DISCOVERED_TOKEN

    with _supervisor(
        slugs=["local_growspace_vision"],
        discovery={"host": host, "port": port, "token": DISCOVERED_TOKEN},
    ):
        status = await VisionConnection(hass, _automatic).async_refresh()

    assert status.availability is VisionAvailability.READY


async def test_no_installed_app_reports_not_installed(hass: HomeAssistant) -> None:
    """An absent App is a distinct reason from a stopped one."""
    with _supervisor(slugs=["core_mosquitto"]):
        status = await VisionConnection(hass, _automatic).async_refresh()

    assert status.availability is VisionAvailability.UNAVAILABLE
    assert status.reason is VisionUnavailableReason.NOT_INSTALLED


async def test_a_stopped_app_reports_not_running(hass: HomeAssistant) -> None:
    """A stopped App is fixable by starting it, and says so."""
    from homeassistant.components.hassio import AddonState

    with _supervisor(slugs=["local_growspace_vision"], state=AddonState.NOT_RUNNING):
        status = await VisionConnection(hass, _automatic).async_refresh()

    assert status.reason is VisionUnavailableReason.NOT_RUNNING


async def test_a_running_app_with_no_discovery_payload_reports_not_configured(
    hass: HomeAssistant,
) -> None:
    """A running App that published nothing leaves Home Assistant no endpoint.

    Supervisor discovery reads are Core-only, which is what makes the payload
    a safe place for the token — but it only helps once the App actually pushes
    one.
    """
    from homeassistant.components.hassio import AddonError

    with _supervisor(
        slugs=["local_growspace_vision"],
        discovery=AddonError("no discovery info"),
    ):
        status = await VisionConnection(hass, _automatic).async_refresh()

    assert status.reason is VisionUnavailableReason.NOT_CONFIGURED


async def test_an_incomplete_discovery_payload_reports_not_configured(
    hass: HomeAssistant,
) -> None:
    """A payload without a token cannot open anything but `/health`."""
    with _supervisor(
        slugs=["local_growspace_vision"],
        discovery={"host": "growspace-vision", "port": 8099},
    ):
        status = await VisionConnection(hass, _automatic).async_refresh()

    assert status.reason is VisionUnavailableReason.NOT_CONFIGURED


async def test_automatic_mode_off_supervisor_reports_not_configured(
    hass: HomeAssistant,
) -> None:
    """On Home Assistant Container there is no Supervisor to pull from.

    `AddonManager` is never constructed there: its constructor reads
    `hass.data` that only `hassio` sets up, and would raise `KeyError` before
    its own error handling could run.
    """
    with patch(
        "custom_components.growspace_manager.vision_connection.is_hassio",
        return_value=False,
    ):
        status = await VisionConnection(hass, _automatic).async_refresh()

    assert status.reason is VisionUnavailableReason.NOT_CONFIGURED
    assert status.connection_source is VisionConnectionSource.SUPERVISOR


async def test_manual_mode_never_consults_discovery(
    hass: HomeAssistant, served_app: tuple[FakeVisionApp, str, int]
) -> None:
    """A manual endpoint is exclusive.

    Falling back to a discovered App would send captures to a service the
    grower did not choose, and the mistake would be invisible: the checkups
    would simply work.
    """
    _app, host, port = served_app
    options = _manual(f"http://{host}:{port}")

    with _supervisor(
        slugs=["local_growspace_vision"],
        discovery={"host": "somewhere-else", "port": 8099, "token": "other"},
    ):
        connection = VisionConnection(hass, lambda: options)
        endpoint = await connection.async_resolve_endpoint()
        status = await connection.async_refresh()

    assert endpoint.base_url == f"http://{host}:{port}"
    assert endpoint.token == TOKEN
    assert status.availability is VisionAvailability.READY
    assert status.connection_source is VisionConnectionSource.MANUAL


async def test_a_manual_endpoint_without_a_token_is_invalid(
    hass: HomeAssistant,
) -> None:
    """Every endpoint but `/health` needs a token, so a blank one is misconfiguration."""
    connection = VisionConnection(hass, lambda: _manual("http://vision.local", ""))

    with pytest.raises(VisionNotConfiguredError):
        await connection.async_resolve_endpoint()


async def test_a_manual_endpoint_that_is_down_reports_unreachable(
    hass: HomeAssistant,
    socket_enabled: None,
) -> None:
    """Nothing listening is a transport failure, reported as unreachable."""
    connection = VisionConnection(hass, lambda: _manual("http://127.0.0.1:1"))

    status = await connection.async_refresh()

    assert status.availability is VisionAvailability.UNAVAILABLE
    assert status.reason is VisionUnavailableReason.UNREACHABLE
    assert status.connection_source is VisionConnectionSource.MANUAL


async def test_an_app_sharing_no_schema_is_incompatible(
    hass: HomeAssistant, served_app: tuple[FakeVisionApp, str, int]
) -> None:
    """Incompatible is its own availability, not a flavour of unavailable."""
    app, host, port = served_app
    app.info["supported_schema_versions"] = [2]

    status = await VisionConnection(
        hass, lambda: _manual(f"http://{host}:{port}")
    ).async_refresh()

    assert status.availability is VisionAvailability.INCOMPATIBLE
    assert status.reason is VisionUnavailableReason.SCHEMA_MISMATCH


async def test_an_app_with_no_loaded_model_reports_model_unavailable(
    hass: HomeAssistant, served_app: tuple[FakeVisionApp, str, int]
) -> None:
    """The App answered; it simply has nothing to analyze with."""
    app, host, port = served_app
    app.models["models"][0]["state"] = "unavailable"

    status = await VisionConnection(
        hass, lambda: _manual(f"http://{host}:{port}")
    ).async_refresh()

    assert status.reason is VisionUnavailableReason.MODEL_UNAVAILABLE


async def test_a_pinned_model_survives_into_negotiation(
    hass: HomeAssistant, served_app: tuple[FakeVisionApp, str, int]
) -> None:
    """A pin from stored evidence is honoured, or the connection refuses."""
    from custom_components.growspace_manager.vision_models import ModelIdentity

    app, host, port = served_app
    app.models["models"][0]["model_version"] = "2.0.0"
    connection = VisionConnection(hass, lambda: _manual(f"http://{host}:{port}"))
    connection.pin_model(
        ModelIdentity(model_id="dinov2-vit-s-14-int8-onnx", model_version="1.0.0")
    )

    status = await connection.async_refresh()

    assert status.reason is VisionUnavailableReason.MODEL_UNAVAILABLE


async def test_the_status_cache_stands_until_its_ttl_expires(
    hass: HomeAssistant, served_app: tuple[FakeVisionApp, str, int]
) -> None:
    """Reading the status is free; only a stale cache costs a round trip."""
    _app, host, port = served_app
    connection = VisionConnection(hass, lambda: _manual(f"http://{host}:{port}"))

    await connection.async_refresh()
    assert not connection.is_stale

    with patch.object(
        connection, "async_refresh", AsyncMock(wraps=connection.async_refresh)
    ) as refresh:
        await connection.async_refresh_if_stale()
        assert refresh.call_count == 0

        connection._refreshed_at -= timedelta(seconds=3600)
        assert connection.is_stale
        await connection.async_refresh_if_stale()
        assert refresh.call_count == 1


async def test_an_unprobed_connection_starts_stale_and_unavailable(
    hass: HomeAssistant,
) -> None:
    """Before the first probe there is nothing to report but "not configured"."""
    connection = VisionConnection(hass, dict)

    assert connection.is_stale
    assert connection.status.availability is VisionAvailability.UNAVAILABLE
    assert connection.status.reason is VisionUnavailableReason.NOT_CONFIGURED
    assert connection.negotiated is None


async def test_shutdown_drops_the_negotiated_session(
    hass: HomeAssistant, served_app: tuple[FakeVisionApp, str, int]
) -> None:
    """The shared `aiohttp` session belongs to Home Assistant and is not closed."""
    _app, host, port = served_app
    connection = VisionConnection(hass, lambda: _manual(f"http://{host}:{port}"))
    await connection.async_refresh()
    assert connection.negotiated is not None

    await connection.async_shutdown()

    assert connection.negotiated is None
    assert connection.is_stale
