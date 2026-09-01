"""The Growspace Vision connection options step.

The step probes before it saves, so a wrong endpoint or token is a form error
rather than a scheduled checkup that fails silently hours later. It also decides
what is *not* stored: switching back to automatic drops the manual credentials
instead of keeping them out of sight.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.config_handlers.ai_config_handler import (
    AIConfigHandler,
)
from custom_components.growspace_manager.const import (
    CONF_VISION_ACCESS_TOKEN,
    CONF_VISION_CONNECTION_MODE,
    CONF_VISION_ENDPOINT_URL,
    VISION_SETTINGS_KEY,
)
from custom_components.growspace_manager.exceptions import (
    VisionAuthError,
    VisionIncompatibleError,
    VisionModelUnavailableError,
    VisionNotConfiguredError,
    VisionTransportError,
)

PROBE = (
    "custom_components.growspace_manager.config_handlers.ai_config_handler"
    ".AIConfigHandler._async_probe_vision"
)

MANUAL_INPUT = {
    CONF_VISION_CONNECTION_MODE: "manual",
    CONF_VISION_ENDPOINT_URL: "http://vision.local:8099",
    CONF_VISION_ACCESS_TOKEN: "a-secret",
}


def _make_handler(options: dict[str, Any] | None = None) -> AIConfigHandler:
    coordinator = MagicMock()
    coordinator.options = dict(options or {})
    coordinator.services.save = AsyncMock()
    coordinator.vision_connection.async_refresh = AsyncMock()

    config_entry = MagicMock()
    config_entry.options = dict(options or {})
    config_entry.runtime_data = coordinator

    flow = MagicMock()
    flow.hass = MagicMock()
    flow.config_entry = config_entry
    flow.async_show_form = MagicMock(
        side_effect=lambda **kw: {
            "type": "form",
            "step_id": kw.get("step_id"),
            "errors": kw.get("errors"),
            "data_schema": kw.get("data_schema"),
        }
    )
    flow.async_create_entry = MagicMock(
        side_effect=lambda **kw: {"type": "create_entry", "data": kw.get("data")}
    )
    flow.async_abort = MagicMock(
        side_effect=lambda **kw: {"type": "abort", "reason": kw.get("reason")}
    )
    return AIConfigHandler(flow)


async def test_the_form_is_shown_without_input() -> None:
    """The step opens on its own form, not on a saved entry."""
    handler = _make_handler()

    result = await handler.async_step_configure_vision()

    assert result["step_id"] == "configure_vision"
    assert result["errors"] == {}


async def test_a_working_manual_endpoint_is_saved() -> None:
    """A probed connection is persisted and the live status is refreshed."""
    handler = _make_handler()

    with patch(PROBE, AsyncMock()):
        result = await handler.async_step_configure_vision(dict(MANUAL_INPUT))

    assert result["type"] == "create_entry"
    assert result["data"][VISION_SETTINGS_KEY] == MANUAL_INPUT
    coordinator = handler.config_entry.runtime_data
    coordinator.services.save.assert_awaited_once()
    coordinator.vision_connection.async_refresh.assert_awaited_once()


async def test_switching_to_automatic_clears_the_manual_credentials() -> None:
    """No dormant secret is kept for a connection the grower stopped using.

    Keeping them would also give the integration something to quietly fall back
    to, which is exactly the silent behaviour manual mode exists to prevent.
    """
    handler = _make_handler({VISION_SETTINGS_KEY: dict(MANUAL_INPUT)})

    with patch(PROBE, AsyncMock()):
        result = await handler.async_step_configure_vision(
            {
                CONF_VISION_CONNECTION_MODE: "automatic",
                CONF_VISION_ENDPOINT_URL: "http://vision.local:8099",
                CONF_VISION_ACCESS_TOKEN: "a-secret",
            }
        )

    saved = result["data"][VISION_SETTINGS_KEY]
    assert saved == {CONF_VISION_CONNECTION_MODE: "automatic"}
    assert CONF_VISION_ACCESS_TOKEN not in saved
    assert CONF_VISION_ENDPOINT_URL not in saved


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (VisionNotConfiguredError("nothing to connect to"), "vision_not_configured"),
        (VisionAuthError("bad token", status=401), "vision_invalid_auth"),
        (VisionIncompatibleError("no shared schema"), "vision_incompatible"),
        (VisionModelUnavailableError("no model"), "vision_model_unavailable"),
        (VisionTransportError("nothing listening"), "vision_cannot_connect"),
    ],
)
async def test_each_probe_failure_becomes_its_own_form_error(
    failure: Exception, expected: str
) -> None:
    """The grower is told which thing to fix, not just that something broke."""
    handler = _make_handler()

    with patch(PROBE, AsyncMock(side_effect=failure)):
        result = await handler.async_step_configure_vision(dict(MANUAL_INPUT))

    assert result["type"] == "form"
    assert result["errors"] == {"base": expected}


async def test_a_failed_probe_saves_nothing() -> None:
    """A rejected connection must not become the stored one."""
    handler = _make_handler()

    with patch(PROBE, AsyncMock(side_effect=VisionTransportError("down"))):
        await handler.async_step_configure_vision(dict(MANUAL_INPUT))

    handler.config_entry.runtime_data.services.save.assert_not_awaited()


async def test_the_step_aborts_before_the_integration_is_loaded() -> None:
    """With no coordinator there is nothing to save into."""
    handler = _make_handler()
    handler.config_entry.runtime_data = None

    result = await handler.async_step_configure_vision()

    assert result == {"type": "abort", "reason": "setup_error"}


async def test_an_unexpected_probe_failure_is_reported_as_unreachable() -> None:
    """A URL `aiohttp` refuses outright must not escape as a raw traceback."""
    handler = _make_handler()
    handler.hass = MagicMock()

    with patch(
        "custom_components.growspace_manager.vision_connection"
        ".VisionConnection.async_resolve_endpoint",
        AsyncMock(side_effect=RuntimeError("boom")),
    ):
        result = await handler.async_step_configure_vision(dict(MANUAL_INPUT))

    assert result["errors"] == {"base": "vision_cannot_connect"}
