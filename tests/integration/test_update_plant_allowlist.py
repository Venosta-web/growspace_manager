"""``update_plant`` accepts the fields a grower edits and refuses the rest (#804).

The manager copies every key a Plant has an attribute for straight onto it, so
the boundary is the only place a key like ``stage_history`` can be stopped. One
that got through was saved, failed validation on the next load, and cost the
Plant (#805). These tests hold both ends of that contract: every payload the
card sends today is still accepted, and anything else is refused by name
before a Plant is touched in memory or in storage.
"""

from __future__ import annotations

from datetime import timedelta
import json
from pathlib import Path
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from pytest_homeassistant_custom_component.typing import WebSocketGenerator
import voluptuous as vol

from custom_components.growspace_manager.const import DATE_FIELDS, STORAGE_KEY_PLANTS
from custom_components.growspace_manager.schemas import (
    UPDATE_PLANT_EDITABLE_FIELDS,
    UPDATE_PLANT_SCHEMA,
)
from custom_components.growspace_manager.websocket.plant import (
    SCHEMA_WS_UPDATE_PLANT,
    WS_TYPE_UPDATE_PLANT,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from tests.common import MockConfigEntry

FIXTURE_PATH = (
    Path(__file__).parents[1] / "fixtures" / "contract" / "update_plant_request_v1.json"
)
REGENERATION_COMMAND = (
    "../../.venv/bin/pytest tests/integration/test_update_plant_allowlist.py "
    "--regenerate-contract-fixture"
)

# Keys a Plant carries that no grower edits through update_plant. Each has an
# attribute on Plant, so before #804 every one of them was copied onto it.
NON_EDITABLE_KEYS = (
    "stage_history",
    "phenotype_score",
    "harvest_metrics",
    "drying_data",
    "created_at",
    "updated_at",
    "source_mother",
    "last_watered",
)
# The service has no WebSocket envelope, so ``type`` reached ``Plant.type``
# there; and ``notes``, though documented, was never a Plant attribute at all.
NON_EDITABLE_SERVICE_KEYS = (*NON_EDITABLE_KEYS, "type", "notes")

# What the card sends, mirrored from the card repository. Each shape names the
# code that builds it, so a card change that adds a field has an obvious place
# to land here too.
CARD_WS_PAYLOADS: dict[str, dict[str, Any]] = {
    # PlantUtils.mapDialogToApiPayload(edited, false): the plant overview dialog,
    # one plant. Dates go out verbatim as Lifecycle Timestamps, or null to clear.
    "plant_overview_single": {
        "strain": "Blue Dream",
        "phenotype": "Keeper #2",
        "row": 2,
        "col": 3,
        "seedling_start": "2026-08-01T09:00:00",
        "mother_start": None,
        "clone_start": None,
        "veg_start": "2026-08-15T09:00:00",
        "flower_start": None,
        "dry_start": None,
        "cure_start": None,
    },
    # PlantUtils.mapDialogToApiPayload(edited, true): a bulk edit carries dates only.
    "plant_overview_bulk": {"flower_start": "2026-09-01T18:30:00", "dry_start": None},
    # GrowspaceDialogHost._handleTransplant, through the plant slice's updatePlant.
    "transplant_dialog": {
        "row": 1,
        "col": 1,
        "growspace_id": "veg_tent",
        "veg_start": "2026-09-20",
    },
    # plant slice movePlant / growspace store moves: a new position and nothing else.
    "move": {"row": 2, "col": 1},
}

# growspace-view(-standard) _handleTransplantDrop calls the HA service instead.
CARD_SERVICE_PAYLOADS: dict[str, dict[str, Any]] = {
    "transplant_drop": {
        "growspace_id": "veg_tent",
        "row": 1,
        "col": 2,
        "veg_start": "2026-09-20",
    },
}


def _ws_message(**fields: Any) -> dict[str, Any]:
    """Return an update_plant WebSocket message for plant ``p1``."""
    return {"id": 1, "type": WS_TYPE_UPDATE_PLANT, "plant_id": "p1", **fields}


def _request_contract() -> dict[str, Any]:
    """Describe the update_plant request the schema actually enforces."""
    envelope = {"id", "type"}
    keys = [key for key in SCHEMA_WS_UPDATE_PLANT.schema if str(key) not in envelope]
    return {
        "command": WS_TYPE_UPDATE_PLANT,
        "required": sorted(str(k) for k in keys if isinstance(k, vol.Required)),
        "editable": sorted(str(k) for k in keys if isinstance(k, vol.Optional)),
        "clearable_with_null": sorted(DATE_FIELDS),
    }


# ---------------------------------------------------------------------------
# What the card sends is still accepted
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shape", sorted(CARD_WS_PAYLOADS))
def test_every_card_websocket_payload_is_accepted(shape: str) -> None:
    """Each payload the card builds today passes the WebSocket schema unchanged."""
    payload = CARD_WS_PAYLOADS[shape]

    assert SCHEMA_WS_UPDATE_PLANT(_ws_message(**payload)) == _ws_message(**payload)


@pytest.mark.parametrize("shape", sorted(CARD_SERVICE_PAYLOADS))
def test_every_card_service_payload_is_accepted(shape: str) -> None:
    """The card's service call still passes the service schema."""
    validated = UPDATE_PLANT_SCHEMA({"plant_id": "p1", **CARD_SERVICE_PAYLOADS[shape]})

    assert set(validated) == {"plant_id", *CARD_SERVICE_PAYLOADS[shape]}


def test_positions_arriving_as_text_are_read_as_numbers() -> None:
    """A row or column from a text input is still a position, not a string."""
    validated = SCHEMA_WS_UPDATE_PLANT(_ws_message(row="2", col="3"))

    assert (validated["row"], validated["col"]) == (2, 3)


def test_the_service_declares_every_editable_field() -> None:
    """Automations reach the same fields the card does."""
    declared = {str(key) for key in UPDATE_PLANT_SCHEMA.schema}

    assert set(UPDATE_PLANT_EDITABLE_FIELDS) <= declared


# ---------------------------------------------------------------------------
# Anything else is refused by name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", NON_EDITABLE_KEYS)
def test_websocket_schema_refuses_a_non_editable_key_by_name(key: str) -> None:
    """The refusal names the key, so a client can see what it got wrong."""
    with pytest.raises(vol.MultipleInvalid, match=rf"{key}"):
        SCHEMA_WS_UPDATE_PLANT(_ws_message(strain="Blue Dream", **{key: ["mother"]}))


@pytest.mark.parametrize("key", NON_EDITABLE_SERVICE_KEYS)
def test_service_schema_refuses_a_non_editable_key_by_name(key: str) -> None:
    """The service path had the same hole, and the card's transplant drop uses it."""
    with pytest.raises(vol.MultipleInvalid, match=rf"{key}"):
        UPDATE_PLANT_SCHEMA({"plant_id": "p1", key: ["mother"]})


def test_a_position_below_one_is_refused() -> None:
    """Grid positions are 1-based on the wire as everywhere else."""
    with pytest.raises(vol.MultipleInvalid):
        SCHEMA_WS_UPDATE_PLANT(_ws_message(row=0))


# ---------------------------------------------------------------------------
# End to end: a refused update leaves the Plant alone
# ---------------------------------------------------------------------------


async def _plant_on_disk(hass: HomeAssistant, init_integration: MockConfigEntry):
    """Add one plant and flush it, returning the coordinator and plant ID."""
    coordinator = init_integration.runtime_data
    growspace = await coordinator.services.growspaces.add_growspace(
        name="Allowlist Tent", rows=2, plants_per_row=2
    )
    plant = await coordinator.services.plants.add_plant(
        growspace_id=growspace.id, strain="OG Kush", row=1, col=1
    )
    await coordinator.storage_manager.async_force_save()
    return coordinator, plant.plant_id


def _stored_plant(hass_storage: dict[str, Any], plant_id: str) -> Any:
    """Return the persisted form of one plant, as the next load would read it."""
    return json.loads(
        json.dumps(hass_storage[STORAGE_KEY_PLANTS]["data"]["plants"][plant_id])
    )


async def test_stage_history_is_refused_and_the_plant_is_unchanged(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    hass_storage: dict[str, Any],
) -> None:
    """The #805 payload is refused, and nothing reaches memory or storage."""
    coordinator, plant_id = await _plant_on_disk(hass, init_integration)
    in_memory = coordinator.plants[plant_id].to_dict()
    on_disk = _stored_plant(hass_storage, plant_id)
    client = await hass_ws_client(hass)

    await client.send_json(
        {
            "id": 1,
            "type": WS_TYPE_UPDATE_PLANT,
            "plant_id": plant_id,
            "strain": "Blue Dream",
            "stage_history": ["mother"],
        }
    )
    response = await client.receive_json()
    # Let any debounced save that a mutation would have scheduled come due.
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=11))
    await hass.async_block_till_done()

    assert not response["success"]
    assert response["error"]["code"] == "invalid_format"
    assert "stage_history" in response["error"]["message"]
    assert coordinator.plants[plant_id].to_dict() == in_memory
    assert _stored_plant(hass_storage, plant_id) == on_disk


async def test_an_editable_update_still_lands(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """The allowlist narrows the command; it does not stop the card editing."""
    coordinator, plant_id = await _plant_on_disk(hass, init_integration)
    client = await hass_ws_client(hass)

    await client.send_json(
        {
            "id": 1,
            "type": WS_TYPE_UPDATE_PLANT,
            "plant_id": plant_id,
            "strain": "Blue Dream",
            "phenotype": "Keeper #2",
            "row": 2,
            "col": 2,
        }
    )
    response = await client.receive_json()

    assert response["success"], response
    plant = coordinator.plants[plant_id]
    assert (plant.genetics.strain_name, plant.genetics.phenotype_name) == (
        "Blue Dream",
        "Keeper #2",
    )
    assert (plant.row, plant.col) == (2, 2)


# ---------------------------------------------------------------------------
# The contract fixture the card checks its payloads against
# ---------------------------------------------------------------------------


def test_update_plant_request_contract_fixture(pytestconfig: pytest.Config) -> None:
    """The committed fixture is exactly what the schema enforces."""
    contract = _request_contract()

    if pytestconfig.getoption("regenerate_contract_fixture"):
        FIXTURE_PATH.write_text(
            f"{json.dumps(contract, indent=2, sort_keys=True)}\n", encoding="utf-8"
        )

    assert FIXTURE_PATH.exists(), (
        f"update_plant request contract fixture is missing. Regenerate it with: "
        f"{REGENERATION_COMMAND}"
    )
    assert contract == json.loads(FIXTURE_PATH.read_text(encoding="utf-8")), (
        "The update_plant request contract changed. Review the diff, then "
        f"regenerate with: {REGENERATION_COMMAND}"
    )
    assert contract["editable"] == sorted(UPDATE_PLANT_EDITABLE_FIELDS)
