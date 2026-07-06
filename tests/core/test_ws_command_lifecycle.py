"""Unit tests for the WS Command Lifecycle (ADR-0027).

The registration wrapper owns resolve → execute → send_result → error
mapping for every command, so those behaviours are tested once here — handler
tests assert on returned payloads and raised typed exceptions instead of mock
connections.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import voluptuous as vol

from custom_components.growspace_manager.exceptions import (
    CoordinatorNotReadyError,
    GrowspaceError,
    PlantNotFoundError,
    RateLimitedError,
)
from custom_components.growspace_manager.websocket._common import (
    DEFAULT_WS_ERROR_MAP,
    WSCommand,
    register_ws_command,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

_SCHEMA = vol.Schema({}, extra=vol.ALLOW_EXTRA)


def _registered_wrapper(hass: HomeAssistant, command: WSCommand) -> Any:
    """Register the command and capture the wrapper handed to websocket_api."""
    with patch(
        "custom_components.growspace_manager.websocket._common.websocket_api"
    ) as ws_api:
        ws_api.async_response = lambda func: func
        register_ws_command(hass, command)
        return ws_api.async_register_command.call_args[0][2]


async def test_async_payload_is_sent_as_result(hass: HomeAssistant) -> None:
    """The handler's return value becomes the send_result payload."""

    async def handler(hass: HomeAssistant, coordinator: Any, msg: dict) -> dict:
        return {"echo": msg["value"]}

    wrapper = _registered_wrapper(
        hass, WSCommand("growspace_manager/test", handler, _SCHEMA)
    )
    connection = MagicMock()
    with patch(
        "custom_components.growspace_manager.websocket._common.GrowspaceCoordinator"
    ) as coord_cls:
        coord_cls.get_for_service_call.return_value = MagicMock()
        await wrapper(hass, connection, {"id": 5, "value": 42})

    connection.send_result.assert_called_once_with(5, {"echo": 42})


async def test_sync_handler_registers_and_sends(hass: HomeAssistant) -> None:
    """sync=True commands run through the callback wrapper."""

    def handler(hass: HomeAssistant, coordinator: Any, msg: dict) -> dict:
        return {"ok": True}

    wrapper = _registered_wrapper(
        hass, WSCommand("growspace_manager/test", handler, _SCHEMA, sync=True)
    )
    connection = MagicMock()
    with patch(
        "custom_components.growspace_manager.websocket._common.GrowspaceCoordinator"
    ) as coord_cls:
        coord_cls.get_for_service_call.return_value = MagicMock()
        wrapper(hass, connection, {"id": 1})

    connection.send_result.assert_called_once_with(1, {"ok": True})


@pytest.mark.parametrize(
    ("resolve", "expected_accessor"),
    [
        ("targeted", "get_for_service_call"),
        ("any", "get_any"),
    ],
)
async def test_resolve_modes(
    hass: HomeAssistant, resolve: str, expected_accessor: str
) -> None:
    """resolve='targeted' uses id-based lookup; 'any' uses get_any."""
    seen: dict[str, Any] = {}

    async def handler(hass: HomeAssistant, coordinator: Any, msg: dict) -> None:
        seen["coordinator"] = coordinator

    wrapper = _registered_wrapper(
        hass, WSCommand("growspace_manager/test", handler, _SCHEMA, resolve=resolve)
    )
    connection = MagicMock()
    with patch(
        "custom_components.growspace_manager.websocket._common.GrowspaceCoordinator"
    ) as coord_cls:
        expected = MagicMock()
        getattr(coord_cls, expected_accessor).return_value = expected
        await wrapper(hass, connection, {"id": 1})

    assert seen["coordinator"] is expected


@pytest.mark.parametrize(
    ("raised", "expected_code"),
    [
        (PlantNotFoundError("Plant 'p9' not found"), "entity_not_found"),
        (CoordinatorNotReadyError("no instance loaded"), "coordinator_not_ready"),
        (RateLimitedError("rate_limited"), "rate_limited"),
        (ServiceValidationError("bad input"), "validation_failed"),
        (GrowspaceError("domain failure"), "validation_failed"),
        (ValueError("bad value"), "validation_failed"),
        (RuntimeError("boom"), "internal_error"),
    ],
)
async def test_error_map_produces_typed_codes(
    hass: HomeAssistant, raised: Exception, expected_code: str
) -> None:
    """Raised exceptions map to the Typed Error Codes vocabulary (ADR-0005)."""

    async def handler(hass: HomeAssistant, coordinator: Any, msg: dict) -> None:
        raise raised

    wrapper = _registered_wrapper(
        hass, WSCommand("growspace_manager/test", handler, _SCHEMA)
    )
    connection = MagicMock()
    with patch(
        "custom_components.growspace_manager.websocket._common.GrowspaceCoordinator"
    ) as coord_cls:
        coord_cls.get_for_service_call.return_value = MagicMock()
        await wrapper(hass, connection, {"id": 7})

    connection.send_result.assert_not_called()
    connection.send_error.assert_called_once_with(7, expected_code, str(raised))


async def test_resolution_failure_maps_before_handler_runs(
    hass: HomeAssistant,
) -> None:
    """A coordinator-resolution failure never reaches the handler."""
    ran: list[bool] = []

    async def handler(hass: HomeAssistant, coordinator: Any, msg: dict) -> None:
        ran.append(True)

    wrapper = _registered_wrapper(
        hass, WSCommand("growspace_manager/test", handler, _SCHEMA)
    )
    connection = MagicMock()
    with patch(
        "custom_components.growspace_manager.websocket._common.GrowspaceCoordinator"
    ) as coord_cls:
        coord_cls.get_for_service_call.side_effect = CoordinatorNotReadyError(
            "No Growspace Manager instance is currently loaded."
        )
        await wrapper(hass, connection, {"id": 3})

    assert not ran
    connection.send_error.assert_called_once_with(
        3,
        "coordinator_not_ready",
        "No Growspace Manager instance is currently loaded.",
    )


async def test_custom_error_map_overrides_default(hass: HomeAssistant) -> None:
    """A WSCommand-level error_map replaces the default table."""
    custom_map = ((Exception, "validation_failed", False, "fixed message"),)

    async def handler(hass: HomeAssistant, coordinator: Any, msg: dict) -> None:
        raise RuntimeError("original")

    wrapper = _registered_wrapper(
        hass,
        WSCommand("growspace_manager/test", handler, _SCHEMA, error_map=custom_map),
    )
    connection = MagicMock()
    with patch(
        "custom_components.growspace_manager.websocket._common.GrowspaceCoordinator"
    ) as coord_cls:
        coord_cls.get_for_service_call.return_value = MagicMock()
        await wrapper(hass, connection, {"id": 9})

    connection.send_error.assert_called_once_with(
        9, "validation_failed", "fixed message"
    )


def test_default_map_covers_the_full_typed_vocabulary() -> None:
    """The default table emits exactly the five codes the card types."""
    codes = {row[1] for row in DEFAULT_WS_ERROR_MAP}
    assert codes == {
        "entity_not_found",
        "coordinator_not_ready",
        "rate_limited",
        "validation_failed",
        "internal_error",
    }
