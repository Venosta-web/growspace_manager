"""Irrigation analytics WebSocket handler."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import (
    DOMAIN,
    IrrigationRecipeKind,
    SteeringMode,
)
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.crop_steering_history import (
    CropSteeringHistoryAnalyzer,
)
from custom_components.growspace_manager.delivery_attempt_store import (
    DeliveryRecordUnreadable,
)
from custom_components.growspace_manager.domain.zone_edit import resolve_zone
from custom_components.growspace_manager.exceptions import GrowspaceNotFoundError
from custom_components.growspace_manager.schemas import (
    CROP_STEERING_RECIPE_VALUES_SCHEMA,
    PROGRAM_SLOT_SCHEMA,
    SCHEDULE_RECIPE_VALUES_SCHEMA,
)
from custom_components.growspace_manager.services.utils import WS_ERR_INTERNAL_ERROR
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.util import dt as dt_util

from ._common import DEFAULT_WS_ERROR_MAP, WSCommand, WSErrorMap

WS_TYPE_GET_IRRIGATION_ANALYTICS = f"{DOMAIN}/irrigation_analytics"
SCHEMA_WS_GET_IRRIGATION_ANALYTICS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_IRRIGATION_ANALYTICS,
        vol.Required("growspace_id"): str,
    }
)

WS_TYPE_GET_TANK_WATER_HISTORY = f"{DOMAIN}/get_tank_water_history"
SCHEMA_WS_GET_TANK_WATER_HISTORY = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_TANK_WATER_HISTORY,
        vol.Required("growspace_id"): str,
        vol.Required("range"): vol.In(["1h", "6h", "24h", "7d"]),
    }
)

WS_TYPE_GET_CROP_STEERING_HISTORY = f"{DOMAIN}/get_crop_steering_history"
SCHEMA_WS_GET_CROP_STEERING_HISTORY = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_CROP_STEERING_HISTORY,
        vol.Required("growspace_id"): str,
    }
)

WS_TYPE_GET_DELIVERY_ATTEMPTS = f"{DOMAIN}/get_delivery_attempts"
SCHEMA_WS_GET_DELIVERY_ATTEMPTS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_DELIVERY_ATTEMPTS,
        vol.Required("growspace_id"): str,
        # Home Assistant's local day; omitted, today.
        vol.Optional("date"): cv.date,
    }
)

# The store logged why it could not be read when it failed closed, so its
# refusal is answered without a second traceback.
_DELIVERY_ATTEMPTS_ERROR_MAP: WSErrorMap = (
    (DeliveryRecordUnreadable, WS_ERR_INTERNAL_ERROR, False, None),
    *DEFAULT_WS_ERROR_MAP,
)

WS_TYPE_APPLY_STEERING_MODE = f"{DOMAIN}/apply_steering_mode"
SCHEMA_WS_APPLY_STEERING_MODE = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_APPLY_STEERING_MODE,
        vol.Required("growspace_id"): str,
        vol.Required("steering_mode"): vol.In([m.value for m in SteeringMode]),
    }
)
SCHEMA_WS_APPLY_STEERING_MODE = SCHEMA_WS_APPLY_STEERING_MODE.extend(
    {vol.Optional("zone_id"): str}
)

WS_TYPE_GET_IRRIGATION_RECIPES = f"{DOMAIN}/get_irrigation_recipes"
SCHEMA_WS_GET_IRRIGATION_RECIPES = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_IRRIGATION_RECIPES,
    }
)

WS_TYPE_SAVE_IRRIGATION_RECIPE = f"{DOMAIN}/save_irrigation_recipe"
SCHEMA_WS_SAVE_IRRIGATION_RECIPE = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_SAVE_IRRIGATION_RECIPE,
        vol.Required("growspace_id"): str,
        vol.Required("name"): str,
        vol.Required("kind"): vol.In([k.value for k in IrrigationRecipeKind]),
        vol.Optional("recipe_id"): str,
    }
)
SCHEMA_WS_SAVE_IRRIGATION_RECIPE = SCHEMA_WS_SAVE_IRRIGATION_RECIPE.extend(
    {vol.Optional("zone_id"): str}
)

WS_TYPE_UPDATE_IRRIGATION_RECIPE = f"{DOMAIN}/update_irrigation_recipe"
SCHEMA_WS_UPDATE_IRRIGATION_RECIPE = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_UPDATE_IRRIGATION_RECIPE,
        vol.Required("recipe_id"): str,
        vol.Optional("name"): str,
        vol.Optional("crop_steering"): CROP_STEERING_RECIPE_VALUES_SCHEMA,
        vol.Optional("schedule"): SCHEDULE_RECIPE_VALUES_SCHEMA,
    }
)

WS_TYPE_REMOVE_IRRIGATION_RECIPE = f"{DOMAIN}/remove_irrigation_recipe"
SCHEMA_WS_REMOVE_IRRIGATION_RECIPE = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_REMOVE_IRRIGATION_RECIPE,
        vol.Required("recipe_id"): str,
    }
)

WS_TYPE_APPLY_IRRIGATION_RECIPE = f"{DOMAIN}/apply_irrigation_recipe"
SCHEMA_WS_APPLY_IRRIGATION_RECIPE = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_APPLY_IRRIGATION_RECIPE,
        vol.Required("growspace_id"): str,
        vol.Required("recipe_id"): str,
    }
)
SCHEMA_WS_APPLY_IRRIGATION_RECIPE = SCHEMA_WS_APPLY_IRRIGATION_RECIPE.extend(
    {vol.Optional("zone_id"): str}
)

WS_TYPE_GET_IRRIGATION_PROGRAMS = f"{DOMAIN}/get_irrigation_programs"
SCHEMA_WS_GET_IRRIGATION_PROGRAMS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_IRRIGATION_PROGRAMS,
    }
)

WS_TYPE_SAVE_IRRIGATION_PROGRAM = f"{DOMAIN}/save_irrigation_program"
SCHEMA_WS_SAVE_IRRIGATION_PROGRAM = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_SAVE_IRRIGATION_PROGRAM,
        vol.Required("name"): str,
        vol.Required("slots"): [PROGRAM_SLOT_SCHEMA],
        vol.Optional("program_id"): str,
    }
)

WS_TYPE_REMOVE_IRRIGATION_PROGRAM = f"{DOMAIN}/remove_irrigation_program"
SCHEMA_WS_REMOVE_IRRIGATION_PROGRAM = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_REMOVE_IRRIGATION_PROGRAM,
        vol.Required("program_id"): str,
    }
)

WS_TYPE_ASSIGN_IRRIGATION_PROGRAM = f"{DOMAIN}/assign_irrigation_program"
SCHEMA_WS_ASSIGN_IRRIGATION_PROGRAM = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_ASSIGN_IRRIGATION_PROGRAM,
        vol.Required("growspace_id"): str,
        # Omitted or null unbinds.
        vol.Optional("program_id"): vol.Any(None, str),
    }
)
SCHEMA_WS_ASSIGN_IRRIGATION_PROGRAM = SCHEMA_WS_ASSIGN_IRRIGATION_PROGRAM.extend(
    {vol.Optional("zone_id"): str}
)

_RANGE_CONFIG: dict[str, tuple[str, int]] = {
    "1h": ("24h", 4),
    "6h": ("24h", 24),
    "24h": ("24h", 96),
    "7d": ("7d", 168),
}


async def websocket_get_irrigation_analytics(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Return water consumption aggregated by growth stage for a growspace."""
    growspace_id: str = msg["growspace_id"]
    trackers = coordinator.services.growspaces.get_all_trackers_for_growspace(
        growspace_id
    )

    combined: dict[str, float] = {}
    for tracker in trackers.values():
        for stage, liters in tracker.get_stage_aggregates().items():
            combined[stage] = combined.get(stage, 0.0) + liters

    return {"growspace_id": growspace_id, "stage_aggregates": combined}


async def websocket_get_tank_water_history(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Return pre-bucketed water consumption for qualifying tanks of a growspace."""
    growspace_id: str = msg["growspace_id"]
    range_key: str = msg["range"]
    empty = {"growspace_id": growspace_id, "range": range_key, "buckets": []}

    if coordinator.growspaces.get(growspace_id) is None:
        return empty

    trackers = coordinator.services.growspaces.get_all_trackers_for_growspace(
        growspace_id
    )
    history_key, bucket_count = _RANGE_CONFIG[range_key]

    raw_histories: list[list[dict[str, Any]]] = []
    for tracker in trackers.values():
        if history_key == "7d":
            raw_histories.append(tracker.get_history_7d()[-bucket_count:])
        else:
            raw_histories.append(tracker.get_history_24h()[-bucket_count:])

    if not raw_histories:
        return empty

    buckets: list[dict[str, Any]] = []
    for i, slot in enumerate(raw_histories[0]):
        total = sum(h[i]["liters_consumed"] for h in raw_histories)
        buckets.append({"timestamp": slot["bucket_start"], "liters": round(total, 4)})

    return {"growspace_id": growspace_id, "range": range_key, "buckets": buckets}


async def websocket_get_crop_steering_history(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Return bucketed crop steering sensor history for a growspace."""
    growspace_id: str = msg["growspace_id"]

    growspace = coordinator.growspaces.get(growspace_id)
    if growspace is None:
        raise GrowspaceNotFoundError(f"Growspace {growspace_id} not found")

    analyzer = CropSteeringHistoryAnalyzer(hass)
    history = await analyzer.async_get_history(growspace)

    return {"growspace_id": growspace_id, **history}


async def websocket_get_delivery_attempts(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Return one growspace's Delivery Attempts for one local day, oldest first.

    The day runs from local midnight to the next, which is 23 or 25 hours
    across a clock change, and both bounds are returned so the day timeline
    need not work them out again (ADR-0066). An attempt belongs to every day
    it touches, from its request to the latest moment it records; a merged run
    of suppressions carries its count, and its first and last request, whole.
    An unreadable record is refused rather than answered with an empty day.
    """
    growspace_id: str = msg["growspace_id"]
    if coordinator.growspaces.get(growspace_id) is None:
        raise GrowspaceNotFoundError(f"Growspace {growspace_id} not found")

    day = msg.get("date") or dt_util.now().date()
    starts_at = dt_util.start_of_local_day(day)
    ends_at = dt_util.start_of_local_day(day + timedelta(days=1))
    deliveries = await coordinator.deliveries.async_load(growspace_id)
    attempts = deliveries.between(starts_at, ends_at)

    return {
        "growspace_id": growspace_id,
        "date": day.isoformat(),
        "starts_at": starts_at.isoformat(),
        "ends_at": ends_at.isoformat(),
        "attempts": [attempt.as_dict() for attempt in attempts],
    }


async def websocket_apply_steering_mode(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Stamp a Steering Mode's preset values into the strategy (ADR-0012)."""
    growspace_id: str = msg["growspace_id"]
    mode = SteeringMode(msg["steering_mode"])

    await coordinator.services.growspaces.apply_steering_mode(
        growspace_id, mode, **({"zone_id": msg["zone_id"]} if "zone_id" in msg else {})
    )

    return {"growspace_id": growspace_id, "declared_steering_mode": mode.value}


def websocket_get_irrigation_recipes(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Return the global Irrigation Recipe library.

    Global, so it resolves through any coordinator and never takes a
    growspace: a recipe saved from one tent is listed from every other.
    """
    return coordinator.services.config.get_irrigation_recipes()


async def websocket_save_irrigation_recipe(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Save a growspace's current irrigation settings as a named recipe."""
    recipe = await coordinator.services.config.save_irrigation_recipe(
        growspace_id=msg["growspace_id"],
        name=msg["name"],
        kind=IrrigationRecipeKind(msg["kind"]),
        recipe_id=msg.get("recipe_id"),
        **({"zone_id": msg["zone_id"]} if "zone_id" in msg else {}),
    )
    return recipe.to_dict()


async def websocket_update_irrigation_recipe(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Rename a recipe and/or correct the values it stores.

    Returns the whole edited recipe so the library editor need not re-read the
    library to show what it now holds.
    """
    recipe = await coordinator.services.config.update_irrigation_recipe(
        msg["recipe_id"],
        name=msg.get("name"),
        crop_steering=msg.get("crop_steering"),
        schedule=msg.get("schedule"),
    )
    return recipe.to_dict()


async def websocket_remove_irrigation_recipe(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> None:
    """Remove a recipe from the global Irrigation Recipe library."""
    await coordinator.services.config.remove_irrigation_recipe(msg["recipe_id"])


async def websocket_apply_irrigation_recipe(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Stamp a saved Irrigation Recipe into a growspace (ADR-0045).

    Echoes back what was recorded, so the caller does not have to re-read the
    growspace to learn which recipe it now carries. ``warning`` is the
    media-mismatch notice: the apply succeeded and the values were **not**
    scaled, because pot size normalises across growspaces and media does not.
    """
    growspace_id = msg["growspace_id"]
    warning = await coordinator.services.growspaces.apply_irrigation_recipe(
        growspace_id,
        msg["recipe_id"],
        **({"zone_id": msg["zone_id"]} if "zone_id" in msg else {}),
    )
    strategy = resolve_zone(
        coordinator.growspaces[growspace_id], msg.get("zone_id")
    ).strategy
    return {
        "growspace_id": growspace_id,
        "applied_recipe": strategy.applied_recipe.to_dict()
        if strategy.applied_recipe
        else None,
        "recipe_applied_at": strategy.recipe_applied_at,
        "warning": warning,
    }


def websocket_get_irrigation_programs(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Return the global Irrigation Program library.

    Global, so it resolves through any coordinator and never takes a
    growspace: a plan authored for one tent is listed from every other.
    """
    return coordinator.services.config.get_irrigation_programs()


async def websocket_save_irrigation_program(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Save a plan of ``(stage, week)`` slots as a named Irrigation Program.

    Returns the whole stored program, so the editor sees the slots in the run
    order the library put them in rather than the order it sent them.
    """
    program = await coordinator.services.config.save_irrigation_program(
        name=msg["name"],
        slots=msg["slots"],
        program_id=msg.get("program_id"),
    )
    return program.to_dict()


async def websocket_remove_irrigation_program(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> None:
    """Remove a program from the global Irrigation Program library."""
    await coordinator.services.config.remove_irrigation_program(msg["program_id"])


async def websocket_assign_irrigation_program(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Bind a growspace to an Irrigation Program, or unbind it (ADR-0045).

    Binding only: no setpoint is written and no pump fires. Omitting
    ``program_id`` — or passing it as null — unbinds. Echoes back what the
    growspace now holds so the caller need not re-read it.
    """
    growspace_id = msg["growspace_id"]
    program_id = msg.get("program_id")
    await coordinator.services.growspaces.assign_irrigation_program(
        growspace_id,
        program_id,
        **({"zone_id": msg["zone_id"]} if "zone_id" in msg else {}),
    )
    strategy = resolve_zone(
        coordinator.growspaces[growspace_id], msg.get("zone_id")
    ).strategy
    return {
        "growspace_id": growspace_id,
        "irrigation_program_id": strategy.irrigation_program_id,
    }


COMMANDS: list[WSCommand] = [
    WSCommand(
        WS_TYPE_GET_IRRIGATION_ANALYTICS,
        websocket_get_irrigation_analytics,
        SCHEMA_WS_GET_IRRIGATION_ANALYTICS,
    ),
    WSCommand(
        WS_TYPE_GET_TANK_WATER_HISTORY,
        websocket_get_tank_water_history,
        SCHEMA_WS_GET_TANK_WATER_HISTORY,
    ),
    WSCommand(
        WS_TYPE_GET_CROP_STEERING_HISTORY,
        websocket_get_crop_steering_history,
        SCHEMA_WS_GET_CROP_STEERING_HISTORY,
    ),
    WSCommand(
        WS_TYPE_GET_DELIVERY_ATTEMPTS,
        websocket_get_delivery_attempts,
        SCHEMA_WS_GET_DELIVERY_ATTEMPTS,
        error_map=_DELIVERY_ATTEMPTS_ERROR_MAP,
    ),
    WSCommand(
        WS_TYPE_APPLY_STEERING_MODE,
        websocket_apply_steering_mode,
        SCHEMA_WS_APPLY_STEERING_MODE,
    ),
    WSCommand(
        WS_TYPE_GET_IRRIGATION_RECIPES,
        websocket_get_irrigation_recipes,
        SCHEMA_WS_GET_IRRIGATION_RECIPES,
        resolve="any",
        sync=True,
    ),
    WSCommand(
        WS_TYPE_SAVE_IRRIGATION_RECIPE,
        websocket_save_irrigation_recipe,
        SCHEMA_WS_SAVE_IRRIGATION_RECIPE,
    ),
    WSCommand(
        WS_TYPE_UPDATE_IRRIGATION_RECIPE,
        websocket_update_irrigation_recipe,
        SCHEMA_WS_UPDATE_IRRIGATION_RECIPE,
        resolve="any",
    ),
    WSCommand(
        WS_TYPE_REMOVE_IRRIGATION_RECIPE,
        websocket_remove_irrigation_recipe,
        SCHEMA_WS_REMOVE_IRRIGATION_RECIPE,
        resolve="any",
    ),
    WSCommand(
        WS_TYPE_APPLY_IRRIGATION_RECIPE,
        websocket_apply_irrigation_recipe,
        SCHEMA_WS_APPLY_IRRIGATION_RECIPE,
    ),
    WSCommand(
        WS_TYPE_GET_IRRIGATION_PROGRAMS,
        websocket_get_irrigation_programs,
        SCHEMA_WS_GET_IRRIGATION_PROGRAMS,
        resolve="any",
        sync=True,
    ),
    WSCommand(
        WS_TYPE_SAVE_IRRIGATION_PROGRAM,
        websocket_save_irrigation_program,
        SCHEMA_WS_SAVE_IRRIGATION_PROGRAM,
        resolve="any",
    ),
    WSCommand(
        WS_TYPE_REMOVE_IRRIGATION_PROGRAM,
        websocket_remove_irrigation_program,
        SCHEMA_WS_REMOVE_IRRIGATION_PROGRAM,
        resolve="any",
    ),
    WSCommand(
        WS_TYPE_ASSIGN_IRRIGATION_PROGRAM,
        websocket_assign_irrigation_program,
        SCHEMA_WS_ASSIGN_IRRIGATION_PROGRAM,
    ),
]
