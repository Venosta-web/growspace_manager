"""Plant mutation WebSocket handlers."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import (
    ATTR_AMOUNT,
    ATTR_AROMA,
    ATTR_CBD_PERCENTAGE,
    ATTR_COL,
    ATTR_DRY_WEIGHT,
    ATTR_GROWSPACE_ID,
    ATTR_INTERNODAL_SPACING,
    ATTR_KEEPER,
    ATTR_MOLD_RESISTANCE,
    ATTR_MOTHER_PLANT_ID,
    ATTR_NUM_CLONES,
    ATTR_NUTRIENTS,
    ATTR_PEST_RESISTANCE,
    ATTR_PHENOTYPE,
    ATTR_PLANT1_ID,
    ATTR_PLANT2_ID,
    ATTR_PLANT_ID,
    ATTR_PLANTS_PER_ROW,
    ATTR_PRESET_ID,
    ATTR_RESIN,
    ATTR_ROW,
    ATTR_ROWS,
    ATTR_SEED_BATCH_ID,
    ATTR_START_NUMBER,
    ATTR_STRAIN,
    ATTR_STRUCTURE,
    ATTR_TARGET_GROWSPACE_ID,
    ATTR_TERPENE_INTENSITY,
    ATTR_TERPENE_PROFILE,
    ATTR_THC_PERCENTAGE,
    ATTR_TRANSITION_DATE,
    ATTR_TRIM_WEIGHT,
    ATTR_VIGOR,
    ATTR_WET_WEIGHT,
    ATTR_YIELD_POTENTIAL,
    CANONICAL_ID_MOTHER,
    DATE_FIELDS,
    DOMAIN,
)
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.exceptions import (
    GrowspaceError,
    GrowspaceNotFoundError,
    PlantNotFoundError,
)
from custom_components.growspace_manager.utils import parse_date_field
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from ._common import WSCommand

_LOGGER = logging.getLogger(__name__)

_OPT_DATE = vol.Any(str, None)

WS_TYPE_WATER_PLANT = f"{DOMAIN}/water_plant"
SCHEMA_WS_WATER_PLANT = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_WATER_PLANT,
        vol.Required(ATTR_PLANT_ID): str,
        vol.Required(ATTR_AMOUNT): vol.Any(float, int),
        vol.Optional(ATTR_NUTRIENTS): dict,
        vol.Optional(ATTR_PRESET_ID): str,
    }
)

WS_TYPE_ADD_PLANT = f"{DOMAIN}/add_plant"
SCHEMA_WS_ADD_PLANT = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_ADD_PLANT,
        vol.Required(ATTR_GROWSPACE_ID): str,
        vol.Required(ATTR_ROW): int,
        vol.Required(ATTR_COL): int,
        vol.Required(ATTR_STRAIN): str,
        vol.Optional(ATTR_PHENOTYPE): str,
        vol.Optional(ATTR_SEED_BATCH_ID): str,
        vol.Optional("veg_start"): _OPT_DATE,
        vol.Optional("flower_start"): _OPT_DATE,
        vol.Optional("seedling_start"): _OPT_DATE,
        vol.Optional("mother_start"): _OPT_DATE,
        vol.Optional("clone_start"): _OPT_DATE,
        vol.Optional("dry_start"): _OPT_DATE,
        vol.Optional("cure_start"): _OPT_DATE,
    }
)

WS_TYPE_ADD_PLANTS = f"{DOMAIN}/add_plants"
SCHEMA_WS_ADD_PLANTS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_ADD_PLANTS,
        vol.Required(ATTR_GROWSPACE_ID): str,
        vol.Required(ATTR_STRAIN): str,
        vol.Required(ATTR_AMOUNT): vol.All(int, vol.Range(min=1)),
        vol.Optional(ATTR_START_NUMBER): int,
        vol.Optional(ATTR_PHENOTYPE): str,
        vol.Optional(ATTR_SEED_BATCH_ID): str,
        vol.Optional("veg_start"): _OPT_DATE,
        vol.Optional("flower_start"): _OPT_DATE,
        vol.Optional("seedling_start"): _OPT_DATE,
        vol.Optional("mother_start"): _OPT_DATE,
        vol.Optional("clone_start"): _OPT_DATE,
        vol.Optional("dry_start"): _OPT_DATE,
        vol.Optional("cure_start"): _OPT_DATE,
    }
)

WS_TYPE_UPDATE_PLANT = f"{DOMAIN}/update_plant"
SCHEMA_WS_UPDATE_PLANT = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_UPDATE_PLANT,
        vol.Required(ATTR_PLANT_ID): str,
    },
    extra=vol.ALLOW_EXTRA,
)

WS_TYPE_REMOVE_PLANT = f"{DOMAIN}/remove_plant"
SCHEMA_WS_REMOVE_PLANT = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_REMOVE_PLANT,
        vol.Required(ATTR_PLANT_ID): str,
    }
)

WS_TYPE_HARVEST_PLANT = f"{DOMAIN}/harvest_plant"
SCHEMA_WS_HARVEST_PLANT = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_HARVEST_PLANT,
        vol.Required(ATTR_PLANT_ID): str,
        vol.Optional(ATTR_TARGET_GROWSPACE_ID): vol.Any(str, None),
        vol.Optional(ATTR_TRANSITION_DATE): _OPT_DATE,
        vol.Optional(ATTR_WET_WEIGHT): vol.Any(float, int, None),
        vol.Optional(ATTR_DRY_WEIGHT): vol.Any(float, int, None),
        vol.Optional(ATTR_TRIM_WEIGHT): vol.Any(float, int, None),
        vol.Optional(ATTR_THC_PERCENTAGE): vol.Any(float, int, None),
        vol.Optional(ATTR_CBD_PERCENTAGE): vol.Any(float, int, None),
        vol.Optional(ATTR_TERPENE_PROFILE): vol.Any(str, None),
    }
)

WS_TYPE_MOVE_PLANT = f"{DOMAIN}/move_plant"
SCHEMA_WS_MOVE_PLANT = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_MOVE_PLANT,
        vol.Required(ATTR_PLANT_ID): str,
        vol.Required(ATTR_TARGET_GROWSPACE_ID): str,
        vol.Optional(ATTR_TRANSITION_DATE): _OPT_DATE,
    }
)

WS_TYPE_MOVE_CLONE = f"{DOMAIN}/move_clone"
SCHEMA_WS_MOVE_CLONE = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_MOVE_CLONE,
        vol.Required(ATTR_PLANT_ID): str,
        vol.Required(ATTR_TARGET_GROWSPACE_ID): str,
        vol.Optional(ATTR_TRANSITION_DATE): _OPT_DATE,
    }
)

WS_TYPE_SWITCH_PLANTS = f"{DOMAIN}/switch_plants"
SCHEMA_WS_SWITCH_PLANTS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_SWITCH_PLANTS,
        vol.Required(ATTR_PLANT1_ID): str,
        vol.Required(ATTR_PLANT2_ID): str,
    }
)

WS_TYPE_SET_PLANT_LAYOUT = f"{DOMAIN}/set_plant_layout"
SCHEMA_WS_SET_PLANT_LAYOUT = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_SET_PLANT_LAYOUT,
        vol.Required(ATTR_GROWSPACE_ID): str,
        vol.Required("expected_layout_revision"): vol.All(int, vol.Range(min=0)),
        vol.Optional(ATTR_ROWS): vol.All(int, vol.Range(min=1)),
        vol.Optional(ATTR_PLANTS_PER_ROW): vol.All(int, vol.Range(min=1)),
        vol.Required("placements"): [
            {
                vol.Required(ATTR_PLANT_ID): str,
                vol.Required(ATTR_ROW): vol.All(int, vol.Range(min=1)),
                vol.Required(ATTR_COL): vol.All(int, vol.Range(min=1)),
            }
        ],
    }
)

WS_TYPE_TAKE_CLONE = f"{DOMAIN}/take_clone"
SCHEMA_WS_TAKE_CLONE = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_TAKE_CLONE,
        vol.Required(ATTR_MOTHER_PLANT_ID): str,
        vol.Optional(ATTR_NUM_CLONES): vol.All(int, vol.Range(min=1)),
        vol.Optional(ATTR_TARGET_GROWSPACE_ID): str,
        vol.Optional(ATTR_TRANSITION_DATE): _OPT_DATE,
    }
)

WS_TYPE_SCORE_PLANT = f"{DOMAIN}/score_plant"
SCHEMA_WS_SCORE_PLANT = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_SCORE_PLANT,
        vol.Required(ATTR_PLANT_ID): str,
        vol.Optional(ATTR_VIGOR): vol.Any(int, None),
        vol.Optional(ATTR_STRUCTURE): vol.Any(int, None),
        vol.Optional(ATTR_AROMA): vol.Any(int, None),
        vol.Optional(ATTR_RESIN): vol.Any(int, None),
        vol.Optional(ATTR_PEST_RESISTANCE): vol.Any(int, None),
        vol.Optional(ATTR_INTERNODAL_SPACING): vol.Any(int, None),
        vol.Optional(ATTR_TERPENE_INTENSITY): vol.Any(int, None),
        vol.Optional(ATTR_MOLD_RESISTANCE): vol.Any(int, None),
        vol.Optional(ATTR_YIELD_POTENTIAL): vol.Any(int, None),
        vol.Optional(ATTR_KEEPER): vol.Any(bool, None),
        vol.Optional("notes"): vol.Any(str, None),
    }
)

WS_TYPE_LOG_DRYING_WEIGHT = f"{DOMAIN}/log_drying_weight"
SCHEMA_WS_LOG_DRYING_WEIGHT = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_LOG_DRYING_WEIGHT,
        vol.Required(ATTR_PLANT_ID): str,
        vol.Required("weight_grams"): vol.Any(float, int),
        vol.Optional("date"): _OPT_DATE,
    }
)

WS_TYPE_LOG_MOISTURE_READING = f"{DOMAIN}/log_moisture_reading"
SCHEMA_WS_LOG_MOISTURE_READING = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_LOG_MOISTURE_READING,
        vol.Required(ATTR_PLANT_ID): str,
        vol.Required("moisture_percent"): vol.All(
            vol.Any(float, int), vol.Range(min=0, max=100)
        ),
        vol.Optional("date"): _OPT_DATE,
    }
)

WS_TYPE_SET_VISUAL_TAG = f"{DOMAIN}/set_visual_tag"
SCHEMA_WS_SET_VISUAL_TAG = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_SET_VISUAL_TAG,
        vol.Required(ATTR_PLANT_ID): str,
        vol.Required("visual_tag"): vol.Any(str, None),
    }
)

WS_TYPE_UPDATE_HARVEST_METRICS = f"{DOMAIN}/update_harvest_metrics"
SCHEMA_WS_UPDATE_HARVEST_METRICS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_UPDATE_HARVEST_METRICS,
        vol.Required(ATTR_PLANT_ID): str,
        vol.Optional(ATTR_WET_WEIGHT): vol.Any(float, int, None),
        vol.Optional(ATTR_DRY_WEIGHT): vol.Any(float, int, None),
        vol.Optional(ATTR_TRIM_WEIGHT): vol.Any(float, int, None),
        vol.Optional(ATTR_THC_PERCENTAGE): vol.Any(float, int, None),
        vol.Optional(ATTR_CBD_PERCENTAGE): vol.Any(float, int, None),
        vol.Optional(ATTR_TERPENE_PROFILE): vol.Any(str, None),
    }
)

WS_TYPE_PRINT_LABEL = f"{DOMAIN}/print_label"
SCHEMA_WS_PRINT_LABEL = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_PRINT_LABEL,
        vol.Optional(ATTR_PLANT_ID): str,
        vol.Optional(ATTR_STRAIN): str,
        vol.Optional(ATTR_PHENOTYPE): str,
        vol.Optional("breeder"): str,
        vol.Optional("lineage"): str,
        vol.Optional("breeder_logo"): str,
        vol.Optional("device_id"): str,
        vol.Optional("preview"): bool,
        vol.Optional("base_url"): str,
        vol.Optional("fields"): dict,
        vol.Optional("density"): vol.In(["low", "normal", "high"]),
        vol.Optional("qr_target"): vol.In(["web", "deeplink"]),
        vol.Optional("label_size"): str,
    }
)


def _parse_date_kwargs(msg: dict[str, Any]) -> dict[str, Any]:
    """Extract and parse optional date fields from a WS message."""
    add_date_fields = [f for f in DATE_FIELDS if f != "transition_date"]
    return {f: parse_date_field(msg[f]) for f in add_date_fields if f in msg}


async def websocket_water_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> Any:
    """Water a plant."""
    await coordinator.services.plants.water_plant(
        plant_id=msg[ATTR_PLANT_ID],
        amount=msg[ATTR_AMOUNT],
        nutrients=msg.get(ATTR_NUTRIENTS),
        preset_id=msg.get(ATTR_PRESET_ID),
    )


async def websocket_add_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> Any:
    """Add a single plant to a growspace."""
    growspace_id: str = msg[ATTR_GROWSPACE_ID]

    if growspace_id not in coordinator.growspaces:
        raise GrowspaceNotFoundError(f"Growspace '{growspace_id}' not found")

    parsed_dates = _parse_date_kwargs(msg)
    if growspace_id == CANONICAL_ID_MOTHER and not parsed_dates.get("mother_start"):
        parsed_dates["mother_start"] = dt_util.utcnow()

    seed_batch_id = msg.get(ATTR_SEED_BATCH_ID)
    batch = (
        coordinator.services.genetics.seed_batch_by_id(seed_batch_id)
        if seed_batch_id
        else None
    )

    await coordinator.services.plants.add_plant(
        growspace_id=growspace_id,
        strain=msg[ATTR_STRAIN],
        row=msg[ATTR_ROW],
        col=msg[ATTR_COL],
        phenotype=msg.get(ATTR_PHENOTYPE, ""),
        seed_batch_id=seed_batch_id,
        generation=batch.generation if batch else "",
        **parsed_dates,
    )


async def websocket_add_plants(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> Any:
    """Batch-add plants to a growspace."""
    growspace_id: str = msg[ATTR_GROWSPACE_ID]
    strain: str = msg[ATTR_STRAIN]
    amount: int = msg[ATTR_AMOUNT]

    if growspace_id not in coordinator.growspaces:
        raise GrowspaceNotFoundError(f"Growspace '{growspace_id}' not found")

    free_row, free_col = coordinator.validator.find_first_available_position(
        growspace_id
    )
    if free_row is None or free_col is None:
        raise ServiceValidationError(f"Growspace '{growspace_id}' is full")

    parsed_dates = _parse_date_kwargs(msg)
    if growspace_id == CANONICAL_ID_MOTHER and not parsed_dates.get("mother_start"):
        parsed_dates["mother_start"] = dt_util.utcnow()

    start_number: int = msg.get(ATTR_START_NUMBER, 1)
    base_phenotype: str | None = msg.get(ATTR_PHENOTYPE)
    seed_batch_id: str | None = msg.get(ATTR_SEED_BATCH_ID)
    batch = (
        coordinator.services.genetics.seed_batch_by_id(seed_batch_id)
        if seed_batch_id
        else None
    )
    generation = batch.generation if batch else ""

    plants_added = 0
    for i in range(amount):
        current_number = start_number + i
        phenotype = (
            f"{base_phenotype} #{current_number}"
            if base_phenotype
            else f"{strain} #{current_number}"
        )
        row, col = coordinator.validator.find_first_available_position(growspace_id)
        if row is None or col is None:
            _LOGGER.warning(
                "Growspace %s full after %d plants; stopping batch",
                growspace_id,
                plants_added,
            )
            break
        try:
            await coordinator.services.plants.add_plant(
                growspace_id=growspace_id,
                strain=strain,
                row=row,
                col=col,
                phenotype=phenotype,
                seed_batch_id=seed_batch_id,
                generation=generation,
                **parsed_dates,
            )
            plants_added += 1
        except GrowspaceError as err:
            _LOGGER.error("Batch add stopped at plant %d: %s", i + 1, err)
            break

    return {"plants_added": plants_added}


async def websocket_update_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> Any:
    """Update attributes on a plant."""
    plant_id: str = msg[ATTR_PLANT_ID]
    coordinator.validator.validate_plant_exists(plant_id)

    skip_keys = {"id", "type", ATTR_PLANT_ID}
    update_data: dict[str, Any] = {}
    for k, v in msg.items():
        if k in skip_keys:
            continue
        if v is None and k not in DATE_FIELDS:
            continue
        if k in DATE_FIELDS:
            update_data[k] = parse_date_field(v)
        else:
            update_data[k] = v

    if update_data:
        await coordinator.services.plants.update_plant(plant_id, **update_data)


async def websocket_remove_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> Any:
    """Remove a plant from its growspace."""
    plant_id: str = msg[ATTR_PLANT_ID]

    if plant_id not in coordinator.plants:
        raise PlantNotFoundError(f"Plant '{plant_id}' not found")

    await coordinator.services.plants.remove_plant(plant_id)


async def websocket_harvest_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> Any:
    """Harvest a plant, optionally with yield metrics."""
    plant_id: str = msg[ATTR_PLANT_ID]

    if plant_id not in coordinator.plants:
        raise PlantNotFoundError(f"Plant '{plant_id}' not found")

    transition_date_str: str | None = msg.get(ATTR_TRANSITION_DATE)
    transition_date: str | None = None
    if transition_date_str:
        parsed = parse_date_field(transition_date_str)
        if parsed:
            transition_date = parsed.isoformat()
        else:
            raise ServiceValidationError(
                f"Invalid transition_date: {transition_date_str}"
            )

    await coordinator.services.plants.transition_plant(
        plant_id=plant_id,
        target_growspace_id=msg.get(ATTR_TARGET_GROWSPACE_ID),
        target_growspace_name=None,
        transition_date=transition_date,
        wet_weight=msg.get(ATTR_WET_WEIGHT),
        dry_weight=msg.get(ATTR_DRY_WEIGHT),
        trim_weight=msg.get(ATTR_TRIM_WEIGHT),
        thc_percentage=msg.get(ATTR_THC_PERCENTAGE),
        cbd_percentage=msg.get(ATTR_CBD_PERCENTAGE),
        terpene_profile=msg.get(ATTR_TERPENE_PROFILE),
    )


async def websocket_move_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> Any:
    """Transplant a non-clone plant to a different growspace."""
    plant_id: str = msg[ATTR_PLANT_ID]
    target_growspace_id: str = msg[ATTR_TARGET_GROWSPACE_ID]

    if plant_id not in coordinator.plants:
        raise PlantNotFoundError(f"Plant '{plant_id}' not found")

    transition_date_str: str | None = msg.get(ATTR_TRANSITION_DATE)
    transition_date: str | None = None
    if transition_date_str:
        parsed = parse_date_field(transition_date_str)
        if parsed:
            transition_date = parsed.isoformat()

    await coordinator.services.plants.transition_plant(
        plant_id=plant_id,
        target_growspace_id=target_growspace_id,
        target_growspace_name=None,
        transition_date=transition_date,
    )


async def websocket_move_clone(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> Any:
    """Promote a clone to the next growth stage in a target growspace."""
    plant_id: str = msg[ATTR_PLANT_ID]
    target_growspace_id: str = msg[ATTR_TARGET_GROWSPACE_ID]

    transition_date_str: str | None = msg.get(ATTR_TRANSITION_DATE)
    # Keep the full datetime (no .date() truncation): the manager's Lifecycle
    # Timestamp seam stores it with its time preserved (ADR-0013).
    transition_date = (
        (parse_date_field(transition_date_str) or dt_util.utcnow())
        if transition_date_str
        else dt_util.utcnow()
    )

    await coordinator.services.plants.promote_clone(
        clone_id=plant_id,
        target_growspace_id=target_growspace_id,
        transition_date=transition_date,
    )


async def websocket_switch_plants(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> Any:
    """Swap the grid positions of two plants."""
    plant1_id: str = msg[ATTR_PLANT1_ID]
    plant2_id: str = msg[ATTR_PLANT2_ID]

    if plant1_id not in coordinator.plants:
        raise PlantNotFoundError(f"Plant '{plant1_id}' not found")
    if plant2_id not in coordinator.plants:
        raise PlantNotFoundError(f"Plant '{plant2_id}' not found")

    await coordinator.services.plants.switch_plants(plant1_id, plant2_id)


async def websocket_set_plant_layout(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Commit and return an authoritative complete Plant Layout."""
    return await coordinator.services.plants.set_plant_layout(
        msg[ATTR_GROWSPACE_ID],
        msg["expected_layout_revision"],
        msg["placements"],
        rows=msg.get(ATTR_ROWS),
        plants_per_row=msg.get(ATTR_PLANTS_PER_ROW),
    )


async def websocket_take_clone(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> Any:
    """Take clones from a mother plant."""
    mother_plant_id: str = msg[ATTR_MOTHER_PLANT_ID]

    if mother_plant_id not in coordinator.plants:
        raise PlantNotFoundError(f"Mother plant '{mother_plant_id}' not found")

    transition_date_str: str | None = msg.get(ATTR_TRANSITION_DATE)
    # Keep the full datetime (no .date() truncation): the manager's Lifecycle
    # Timestamp seam stores it with its time preserved (ADR-0013).
    transition_date = (
        (parse_date_field(transition_date_str) or dt_util.utcnow())
        if transition_date_str
        else dt_util.utcnow()
    )

    await coordinator.services.plants.take_clones(
        mother_plant_id=mother_plant_id,
        num_clones=msg.get(ATTR_NUM_CLONES, 1),
        target_growspace_id=msg.get(ATTR_TARGET_GROWSPACE_ID),
        transition_date=transition_date,
    )


async def websocket_score_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> Any:
    """Score phenotype traits on a plant."""
    plant_id: str = msg[ATTR_PLANT_ID]

    if plant_id not in coordinator.plants:
        raise PlantNotFoundError(f"Plant '{plant_id}' not found")

    await coordinator.services.plants.score_plant(
        plant_id=plant_id,
        vigor=msg.get(ATTR_VIGOR),
        structure=msg.get(ATTR_STRUCTURE),
        aroma=msg.get(ATTR_AROMA),
        resin=msg.get(ATTR_RESIN),
        pest_resistance=msg.get(ATTR_PEST_RESISTANCE),
        internodal_spacing=msg.get(ATTR_INTERNODAL_SPACING),
        terpene_intensity=msg.get(ATTR_TERPENE_INTENSITY),
        mold_resistance=msg.get(ATTR_MOLD_RESISTANCE),
        yield_potential=msg.get(ATTR_YIELD_POTENTIAL),
        keeper=msg.get(ATTR_KEEPER),
        notes=msg.get("notes"),
    )


async def websocket_log_drying_weight(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> Any:
    """Log a drying weight reading for a plant."""
    await coordinator.services.plants.log_drying_weight(
        plant_id=msg[ATTR_PLANT_ID],
        weight_grams=msg["weight_grams"],
        date=msg.get("date"),
    )


async def websocket_log_moisture_reading(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> Any:
    """Log a substrate moisture reading for a plant."""
    await coordinator.services.plants.log_moisture_reading(
        plant_id=msg[ATTR_PLANT_ID],
        moisture_percent=msg["moisture_percent"],
        date=msg.get("date"),
    )


async def websocket_set_visual_tag(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> Any:
    """Attach or clear a visual tag on a plant."""
    await coordinator.services.plants.set_visual_tag(
        plant_id=msg[ATTR_PLANT_ID],
        visual_tag=msg["visual_tag"],
    )


async def websocket_update_harvest_metrics(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> Any:
    """Persist harvest yield metrics on a plant."""
    await coordinator.services.plants.update_harvest_metrics(
        plant_id=msg[ATTR_PLANT_ID],
        wet_weight=msg.get(ATTR_WET_WEIGHT),
        dry_weight=msg.get(ATTR_DRY_WEIGHT),
        trim_weight=msg.get(ATTR_TRIM_WEIGHT),
        thc_percentage=msg.get(ATTR_THC_PERCENTAGE),
        cbd_percentage=msg.get(ATTR_CBD_PERCENTAGE),
        terpene_profile=msg.get(ATTR_TERPENE_PROFILE),
    )


async def websocket_print_label(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> Any:
    """Print a label for a plant or strain via the Niimbot service."""
    skip_keys = {"id", "type"}
    service_data = {k: v for k, v in msg.items() if k not in skip_keys}
    await hass.services.async_call(DOMAIN, "print_label", service_data, blocking=True)


COMMANDS: list[WSCommand] = [
    WSCommand(WS_TYPE_WATER_PLANT, websocket_water_plant, SCHEMA_WS_WATER_PLANT),
    WSCommand(WS_TYPE_ADD_PLANT, websocket_add_plant, SCHEMA_WS_ADD_PLANT),
    WSCommand(WS_TYPE_ADD_PLANTS, websocket_add_plants, SCHEMA_WS_ADD_PLANTS),
    WSCommand(WS_TYPE_UPDATE_PLANT, websocket_update_plant, SCHEMA_WS_UPDATE_PLANT),
    WSCommand(WS_TYPE_REMOVE_PLANT, websocket_remove_plant, SCHEMA_WS_REMOVE_PLANT),
    WSCommand(WS_TYPE_HARVEST_PLANT, websocket_harvest_plant, SCHEMA_WS_HARVEST_PLANT),
    WSCommand(WS_TYPE_MOVE_PLANT, websocket_move_plant, SCHEMA_WS_MOVE_PLANT),
    WSCommand(WS_TYPE_MOVE_CLONE, websocket_move_clone, SCHEMA_WS_MOVE_CLONE),
    WSCommand(WS_TYPE_SWITCH_PLANTS, websocket_switch_plants, SCHEMA_WS_SWITCH_PLANTS),
    WSCommand(
        WS_TYPE_SET_PLANT_LAYOUT,
        websocket_set_plant_layout,
        SCHEMA_WS_SET_PLANT_LAYOUT,
    ),
    WSCommand(WS_TYPE_TAKE_CLONE, websocket_take_clone, SCHEMA_WS_TAKE_CLONE),
    WSCommand(WS_TYPE_SCORE_PLANT, websocket_score_plant, SCHEMA_WS_SCORE_PLANT),
    WSCommand(
        WS_TYPE_LOG_DRYING_WEIGHT,
        websocket_log_drying_weight,
        SCHEMA_WS_LOG_DRYING_WEIGHT,
    ),
    WSCommand(
        WS_TYPE_LOG_MOISTURE_READING,
        websocket_log_moisture_reading,
        SCHEMA_WS_LOG_MOISTURE_READING,
    ),
    WSCommand(
        WS_TYPE_SET_VISUAL_TAG, websocket_set_visual_tag, SCHEMA_WS_SET_VISUAL_TAG
    ),
    WSCommand(
        WS_TYPE_UPDATE_HARVEST_METRICS,
        websocket_update_harvest_metrics,
        SCHEMA_WS_UPDATE_HARVEST_METRICS,
    ),
    WSCommand(
        WS_TYPE_PRINT_LABEL, websocket_print_label, SCHEMA_WS_PRINT_LABEL, resolve="any"
    ),
]
