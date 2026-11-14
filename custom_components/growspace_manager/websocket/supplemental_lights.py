"""WebSocket API handlers for Supplemental Lights v1."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import voluptuous as vol

from custom_components.growspace_manager.actuator_driver import resolve_actuator_driver
from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.domain.environment_patch import (
    EnvironmentPatch,
)
from custom_components.growspace_manager.domain.light_schedule import (
    resolve_photoperiod_hours,
)
from custom_components.growspace_manager.domain.manual_override import Subsystem
from custom_components.growspace_manager.domain.supplemental_lights import (
    diff_released_outputs,
    find_duplicate_lighting_assignments,
    validate_supplemental_lights_for_save,
)
from custom_components.growspace_manager.exceptions import GrowspaceNotFoundError
from custom_components.growspace_manager.grow_light_coordinator import (
    build_growspace_supplemental_statuses,
)
from custom_components.growspace_manager.models.growspace import (
    SupplementalAnchor,
    SupplementalLight,
    SupplementalLightWindow,
)
from custom_components.growspace_manager.services.environment_patch_commit import (
    async_commit_environment_patch,
)
from homeassistant.components import websocket_api
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from ._common import WSCommand

WS_TYPE_SAVE_SUPPLEMENTAL_LIGHTS = f"{DOMAIN}/save_supplemental_lights"
WS_TYPE_GET_SUPPLEMENTAL_LIGHTS_STATUS = f"{DOMAIN}/get_supplemental_lights_status"

SCHEMA_WS_GET_SUPPLEMENTAL_LIGHTS_STATUS = (
    websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
        {
            vol.Required("type"): WS_TYPE_GET_SUPPLEMENTAL_LIGHTS_STATUS,
            vol.Required("growspace_id"): str,
        }
    )
)

_WINDOW_SCHEMA = vol.Schema(
    {
        vol.Optional("id", default=""): str,
        vol.Required("start_anchor"): vol.In(
            [SupplementalAnchor.LIGHTS_ON.value, SupplementalAnchor.LIGHTS_OFF.value]
        ),
        vol.Required("start_offset_minutes"): vol.Coerce(int),
        vol.Required("end_anchor"): vol.In(
            [SupplementalAnchor.LIGHTS_ON.value, SupplementalAnchor.LIGHTS_OFF.value]
        ),
        vol.Required("end_offset_minutes"): vol.Coerce(int),
    }
)

_LIGHT_SCHEMA = vol.Schema(
    {
        vol.Optional("id", default=""): str,
        vol.Required("entity_id"): str,
        vol.Optional("enabled", default=True): bool,
        vol.Optional("windows", default=list): [_WINDOW_SCHEMA],
    }
)

SCHEMA_WS_SAVE_SUPPLEMENTAL_LIGHTS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_SAVE_SUPPLEMENTAL_LIGHTS,
        vol.Required("growspace_id"): str,
        vol.Required("supplemental_lights"): [_LIGHT_SCHEMA],
        vol.Optional("release_anyway", default=False): bool,
    }
)


def _parse_lights(raw_lights: list[dict[str, Any]]) -> list[SupplementalLight]:
    parsed: list[SupplementalLight] = []
    for raw in raw_lights:
        windows = [
            SupplementalLightWindow(
                id=w.get("id") or str(uuid4())[:8],
                start_anchor=SupplementalAnchor(w["start_anchor"]),
                start_offset_minutes=int(w["start_offset_minutes"]),
                end_anchor=SupplementalAnchor(w["end_anchor"]),
                end_offset_minutes=int(w["end_offset_minutes"]),
            )
            for w in raw.get("windows", [])
        ]
        parsed.append(
            SupplementalLight(
                id=raw.get("id") or str(uuid4())[:8],
                entity_id=raw["entity_id"].strip(),
                enabled=bool(raw.get("enabled", True)),
                windows=windows,
            )
        )
    return parsed


async def websocket_save_supplemental_lights(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Validate, safely release, and save Supplemental Lights for a growspace."""
    growspace_id: str = msg["growspace_id"]
    growspace = coordinator.growspaces.get(growspace_id)
    if growspace is None:
        raise GrowspaceNotFoundError(f"Growspace {growspace_id} not found")

    next_lights = _parse_lights(msg["supplemental_lights"])

    if dupes := find_duplicate_lighting_assignments(
        coordinator.growspaces,
        growspace_id,
        [light.entity_id for light in next_lights],
        candidate_role="supplemental light",
    ):
        raise ServiceValidationError(dupes[0])

    env = growspace.environment_config
    plants = coordinator.services.growspaces.get_growspace_plants(growspace_id)
    photoperiod_hours = resolve_photoperiod_hours(
        plants, env.veg_day_hours, env.flower_day_hours, dt_util.now().date()
    )
    cycle_duration_minutes = round(photoperiod_hours * 60)
    if window_errors := validate_supplemental_lights_for_save(
        next_lights, cycle_duration_minutes
    ):
        raise ServiceValidationError(window_errors[0])

    released = diff_released_outputs(env.supplemental_lights, next_lights)
    release_anyway = bool(msg.get("release_anyway", False))
    if released:
        commands_allowed = coordinator.irrigation_safety.commands_allowed(
            growspace_id, Subsystem.LIGHTS
        )
        override = coordinator.irrigation_safety.override_for(
            growspace_id, Subsystem.LIGHTS
        )
        blockers: list[dict[str, str]] = []
        if not commands_allowed:
            for rel in released:
                if override is not None:
                    expires_local = dt_util.as_local(override.expires_at).strftime(
                        "%H:%M"
                    )
                    blockers.append(
                        {
                            "entity_id": rel.entity_id,
                            "reason": "manual_override",
                            "message": (
                                f"Lights manual override is active until {expires_local}; "
                                f"automation cannot switch off {rel.entity_id} before releasing it ({rel.reason})."
                            ),
                        }
                    )
                else:
                    blockers.append(
                        {
                            "entity_id": rel.entity_id,
                            "reason": "emergency_stop",
                            "message": (
                                f"Lights automation is inhibited; automation cannot switch off "
                                f"{rel.entity_id} before releasing it ({rel.reason})."
                            ),
                        }
                    )
        else:
            for rel in released:
                state = hass.states.get(rel.entity_id)
                if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                    state_label = state.state if state is not None else "unavailable"
                    blockers.append(
                        {
                            "entity_id": rel.entity_id,
                            "reason": "unreachable",
                            "message": (
                                f"{rel.entity_id} is {state_label} and could not be switched off "
                                f"before releasing it ({rel.reason})."
                            ),
                        }
                    )
                    continue
                driver = resolve_actuator_driver(hass, rel.entity_id)
                ok = await driver.turn_off() if driver is not None else False
                if not ok:
                    blockers.append(
                        {
                            "entity_id": rel.entity_id,
                            "reason": "off_failed",
                            "message": (
                                f"Failed to switch off {rel.entity_id} before releasing it ({rel.reason})."
                            ),
                        }
                    )

        if blockers and not release_anyway:
            return {"status": "needs_confirmation", "blockers": blockers}

    patch = EnvironmentPatch(values={"supplemental_lights": next_lights})
    await async_commit_environment_patch(hass, coordinator, growspace, patch)

    return {
        "status": "saved",
        "supplemental_lights": [
            light.to_dict()
            for light in growspace.environment_config.supplemental_lights
        ],
        "statuses": build_growspace_supplemental_statuses(hass, coordinator, growspace),
    }


async def websocket_get_supplemental_lights_status(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Return live Supplemental Lights config and status for a growspace."""
    growspace_id: str = msg["growspace_id"]
    growspace = coordinator.growspaces.get(growspace_id)
    if growspace is None:
        raise GrowspaceNotFoundError(f"Growspace {growspace_id} not found")
    return {
        "supplemental_lights": [
            light.to_dict()
            for light in growspace.environment_config.supplemental_lights
        ],
        "statuses": build_growspace_supplemental_statuses(hass, coordinator, growspace),
    }


COMMANDS = (
    WSCommand(
        WS_TYPE_SAVE_SUPPLEMENTAL_LIGHTS,
        websocket_save_supplemental_lights,
        SCHEMA_WS_SAVE_SUPPLEMENTAL_LIGHTS,
    ),
    WSCommand(
        WS_TYPE_GET_SUPPLEMENTAL_LIGHTS_STATUS,
        websocket_get_supplemental_lights_status,
        SCHEMA_WS_GET_SUPPLEMENTAL_LIGHTS_STATUS,
    ),
)
