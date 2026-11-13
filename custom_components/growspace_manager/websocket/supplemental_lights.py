"""Read and edit Supplemental Lights through the WebSocket command lifecycle."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from ..const import DOMAIN
from ..exceptions import CoordinatorNotReadyError
from ..models.supplemental_light import LightAnchor, SupplementalLight
from ._common import WS_MSG_USER, WSCommand

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from ..coordinator import GrowspaceCoordinator
    from ..supplemental_light_coordinator import SupplementalLightCoordinator

_GET = f"{DOMAIN}/get_supplemental_lights"
_SAVE = f"{DOMAIN}/save_supplemental_light"
_OUTPUT = vol.All(cv.entity_id, vol.Match(r"^(light|switch)\."))
_ENDPOINT = {
    vol.Required("anchor"): vol.In([anchor.value for anchor in LightAnchor]),
    vol.Required("offset_minutes"): vol.All(int, vol.Range(min=-1440, max=1440)),
}
_LIGHT = {
    vol.Required("entity_id"): _OUTPUT,
    vol.Required("enabled"): cv.boolean,
    vol.Required("windows"): vol.All(
        [{vol.Required("start"): _ENDPOINT, vol.Required("end"): _ENDPOINT}],
        vol.Length(min=1),
    ),
}


def _controller(
    coordinator: GrowspaceCoordinator, growspace_id: str
) -> SupplementalLightCoordinator:
    controller = coordinator.services.growspaces.get_supplemental_light_controller(
        growspace_id
    )
    if controller is None:
        raise CoordinatorNotReadyError("Supplemental Lights are still loading.")
    return controller


def _get(
    _hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    return _controller(coordinator, msg["growspace_id"]).status()


async def _save(
    _hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    if not msg[WS_MSG_USER].is_admin:
        raise ServiceValidationError(
            "Only an administrator can change Supplemental Lights."
        )
    light = SupplementalLight.from_dict(msg["light"]) if "light" in msg else None
    original = msg.get("original_entity")
    if light is None and original is None:
        raise ValueError("Choose a Supplemental Light to delete.")
    return await _controller(coordinator, msg["growspace_id"]).async_save(
        original, light, msg["release_anyway"]
    )


COMMANDS = [
    WSCommand(
        _GET,
        _get,
        websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
            {vol.Required("type"): _GET, vol.Required("growspace_id"): str}
        ),
        sync=True,
    ),
    WSCommand(
        _SAVE,
        _save,
        websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
            {
                vol.Required("type"): _SAVE,
                vol.Required("growspace_id"): str,
                vol.Optional("light"): _LIGHT,
                vol.Optional("original_entity"): _OUTPUT,
                vol.Optional("release_anyway", default=False): bool,
            }
        ),
        actor=True,
    ),
]
