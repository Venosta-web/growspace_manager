"""Tests for websocket/plant.py handlers."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.exceptions import GrowspaceError
from custom_components.growspace_manager.websocket.plant import (
    websocket_add_plant,
    websocket_add_plants,
    websocket_harvest_plant,
    websocket_log_drying_weight,
    websocket_log_moisture_reading,
    websocket_move_clone,
    websocket_move_plant,
    websocket_print_label,
    websocket_remove_plant,
    websocket_score_plant,
    websocket_set_visual_tag,
    websocket_switch_plants,
    websocket_take_clone,
    websocket_update_harvest_metrics,
    websocket_update_plant,
    websocket_water_plant,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

_PATCH = "custom_components.growspace_manager.websocket.plant"
_GET_COORD = f"{_PATCH}.GrowspaceCoordinator.get_for_service_call"
_FIXED_NOW = datetime(2026, 1, 12, 12, 0, 0, tzinfo=timezone.utc)
_FIXED_DT = datetime(2026, 1, 10, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def mock_connection() -> MagicMock:
    conn = MagicMock()
    conn.send_result = MagicMock()
    conn.send_error = MagicMock()
    return conn


@pytest.fixture
def mock_coordinator() -> MagicMock:
    coordinator = MagicMock()
    coordinator.growspaces = {}
    coordinator.plants = {}
    coordinator.validator = MagicMock()
    coordinator.validator.validate_plant_exists = MagicMock()
    coordinator.validator.find_first_available_position = MagicMock(return_value=(0, 0))
    coordinator._genetics_manager = MagicMock()
    coordinator._genetics_manager.seed_batches = {}
    svc = MagicMock()
    svc.water_plant = AsyncMock()
    svc.add_plant = AsyncMock()
    svc.update_plant = AsyncMock()
    svc.remove_plant = AsyncMock()
    svc.transition_plant = AsyncMock()
    svc.promote_clone = AsyncMock()
    svc.switch_plants = AsyncMock()
    svc.take_clones = AsyncMock()
    svc.score_plant = AsyncMock()
    svc.log_drying_weight = AsyncMock()
    svc.log_moisture_reading = AsyncMock()
    svc.set_visual_tag = AsyncMock()
    svc.update_harvest_metrics = AsyncMock()
    coordinator.services.plants = svc
    return coordinator


# ---------------------------------------------------------------------------
# websocket_water_plant
# ---------------------------------------------------------------------------


async def test_water_plant_success(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    msg = {"id": 1, "plant_id": "p1", "amount": 500.0}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_water_plant(hass, mock_connection, msg)
    mock_coordinator.services.plants.water_plant.assert_awaited_once_with(
        plant_id="p1", amount=500.0, nutrients=None, preset_id=None
    )
    mock_connection.send_result.assert_called_once_with(1)


async def test_water_plant_validation_error(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    msg = {"id": 1, "plant_id": "p1", "amount": 500.0}
    with patch(_GET_COORD, side_effect=ServiceValidationError("not loaded")):
        await websocket_water_plant(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(1, "validation_failed", "not loaded")


async def test_water_plant_generic_error(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.services.plants.water_plant.side_effect = RuntimeError("boom")
    msg = {"id": 1, "plant_id": "p1", "amount": 500.0}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_water_plant(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(1, "unknown_error", "boom")


# ---------------------------------------------------------------------------
# websocket_add_plant — complex: CANONICAL_ID_MOTHER, seed_batch, GrowspaceError
# ---------------------------------------------------------------------------


async def test_add_plant_success(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.growspaces = {"tent1": MagicMock()}
    msg = {"id": 2, "growspace_id": "tent1", "row": 0, "col": 0, "strain": "OG Kush"}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_add_plant(hass, mock_connection, msg)
    mock_coordinator.services.plants.add_plant.assert_awaited_once()
    mock_connection.send_result.assert_called_once_with(2)


async def test_add_plant_growspace_not_found(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    msg = {"id": 3, "growspace_id": "missing", "row": 0, "col": 0, "strain": "OG Kush"}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_add_plant(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(
        3, "validation_failed", "Growspace 'missing' not found"
    )


async def test_add_plant_mother_growspace_auto_sets_mother_start(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.growspaces = {"mother": MagicMock()}
    msg = {"id": 4, "growspace_id": "mother", "row": 0, "col": 0, "strain": "Clone Queen"}
    with (
        patch(_GET_COORD, return_value=mock_coordinator),
        patch(f"{_PATCH}.dt_util.utcnow", return_value=_FIXED_NOW),
    ):
        await websocket_add_plant(hass, mock_connection, msg)
    call_kwargs = mock_coordinator.services.plants.add_plant.call_args[1]
    assert call_kwargs["mother_start"] == _FIXED_NOW


async def test_add_plant_seed_batch_passes_generation(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.growspaces = {"tent1": MagicMock()}
    mock_batch = MagicMock()
    mock_batch.generation = "F2"
    mock_coordinator.services.genetics.seed_batch_by_id.return_value = mock_batch
    msg = {
        "id": 5, "growspace_id": "tent1", "row": 0, "col": 0,
        "strain": "OG Kush", "seed_batch_id": "batch1",
    }
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_add_plant(hass, mock_connection, msg)
    call_kwargs = mock_coordinator.services.plants.add_plant.call_args[1]
    assert call_kwargs["generation"] == "F2"
    assert call_kwargs["seed_batch_id"] == "batch1"


async def test_add_plant_growspace_error_becomes_validation_error(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.growspaces = {"tent1": MagicMock()}
    mock_coordinator.services.plants.add_plant.side_effect = GrowspaceError("grid full")
    msg = {"id": 6, "growspace_id": "tent1", "row": 0, "col": 0, "strain": "OG Kush"}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_add_plant(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(6, "validation_failed", "grid full")


async def test_add_plant_generic_error(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.growspaces = {"tent1": MagicMock()}
    mock_coordinator.services.plants.add_plant.side_effect = RuntimeError("crash")
    msg = {"id": 7, "growspace_id": "tent1", "row": 0, "col": 0, "strain": "OG Kush"}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_add_plant(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(7, "unknown_error", "crash")


# ---------------------------------------------------------------------------
# websocket_add_plants — complex: batch loop, early-stop, partial count
# ---------------------------------------------------------------------------


async def test_add_plants_success(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.growspaces = {"tent1": MagicMock()}
    # Initial check + 2 loop iterations
    mock_coordinator.validator.find_first_available_position.side_effect = [
        (0, 0), (0, 0), (0, 1)
    ]
    msg = {"id": 10, "growspace_id": "tent1", "strain": "OG Kush", "amount": 2}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_add_plants(hass, mock_connection, msg)
    mock_connection.send_result.assert_called_once_with(10, {"plants_added": 2})


async def test_add_plants_growspace_not_found(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    msg = {"id": 11, "growspace_id": "missing", "strain": "OG Kush", "amount": 3}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_add_plants(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(
        11, "validation_failed", "Growspace 'missing' not found"
    )


async def test_add_plants_growspace_full_at_start(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.growspaces = {"tent1": MagicMock()}
    mock_coordinator.validator.find_first_available_position.return_value = (None, None)
    msg = {"id": 12, "growspace_id": "tent1", "strain": "OG Kush", "amount": 2}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_add_plants(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(
        12, "validation_failed", "Growspace 'tent1' is full"
    )


async def test_add_plants_stops_when_growspace_fills_mid_batch(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.growspaces = {"tent1": MagicMock()}
    # Initial check passes; first loop slot exists; second loop finds it full
    mock_coordinator.validator.find_first_available_position.side_effect = [
        (0, 0), (0, 0), (None, None)
    ]
    msg = {"id": 13, "growspace_id": "tent1", "strain": "OG Kush", "amount": 3}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_add_plants(hass, mock_connection, msg)
    mock_connection.send_result.assert_called_once_with(13, {"plants_added": 1})


async def test_add_plants_growspace_error_stops_batch_with_partial_count(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.growspaces = {"tent1": MagicMock()}
    mock_coordinator.validator.find_first_available_position.side_effect = [
        (0, 0), (0, 0), (0, 1)
    ]
    mock_coordinator.services.plants.add_plant.side_effect = [
        None,  # plant 1 succeeds
        GrowspaceError("conflict"),  # plant 2 fails → break
    ]
    msg = {"id": 14, "growspace_id": "tent1", "strain": "OG Kush", "amount": 3}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_add_plants(hass, mock_connection, msg)
    mock_connection.send_result.assert_called_once_with(14, {"plants_added": 1})


async def test_add_plants_generic_error(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.growspaces = {"tent1": MagicMock()}
    mock_coordinator.validator.find_first_available_position.return_value = (0, 0)
    mock_coordinator.services.plants.add_plant.side_effect = RuntimeError("crash")
    msg = {"id": 15, "growspace_id": "tent1", "strain": "OG Kush", "amount": 1}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_add_plants(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(15, "unknown_error", "crash")


# ---------------------------------------------------------------------------
# websocket_update_plant — complex: None-dropping, date parsing, empty update
# ---------------------------------------------------------------------------


async def test_update_plant_success_with_regular_field(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    msg = {
        "id": 20, "type": "growspace_manager/update_plant",
        "plant_id": "p1", "strain": "New Strain",
    }
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_update_plant(hass, mock_connection, msg)
    mock_coordinator.services.plants.update_plant.assert_awaited_once_with(
        "p1", strain="New Strain"
    )
    mock_connection.send_result.assert_called_once_with(20)


async def test_update_plant_none_non_date_field_is_silently_dropped(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    msg = {
        "id": 21, "type": "growspace_manager/update_plant",
        "plant_id": "p1", "strain": None,
    }
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_update_plant(hass, mock_connection, msg)
    mock_coordinator.services.plants.update_plant.assert_not_awaited()
    mock_connection.send_result.assert_called_once_with(21)


async def test_update_plant_date_field_none_is_passed_through(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    msg = {
        "id": 22, "type": "growspace_manager/update_plant",
        "plant_id": "p1", "veg_start": None,
    }
    with (
        patch(_GET_COORD, return_value=mock_coordinator),
        patch(f"{_PATCH}.parse_date_field", return_value=None),
    ):
        await websocket_update_plant(hass, mock_connection, msg)
    mock_coordinator.services.plants.update_plant.assert_awaited_once_with("p1", veg_start=None)


async def test_update_plant_date_field_with_value_is_parsed(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    msg = {
        "id": 23, "type": "growspace_manager/update_plant",
        "plant_id": "p1", "veg_start": "2026-01-10",
    }
    with (
        patch(_GET_COORD, return_value=mock_coordinator),
        patch(f"{_PATCH}.parse_date_field", return_value=_FIXED_DT),
    ):
        await websocket_update_plant(hass, mock_connection, msg)
    mock_coordinator.services.plants.update_plant.assert_awaited_once_with("p1", veg_start=_FIXED_DT)


async def test_update_plant_validation_error(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.validator.validate_plant_exists.side_effect = ServiceValidationError("not found")
    msg = {
        "id": 24, "type": "growspace_manager/update_plant",
        "plant_id": "p1", "strain": "X",
    }
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_update_plant(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(24, "validation_failed", "not found")


async def test_update_plant_generic_error(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.services.plants.update_plant.side_effect = RuntimeError("crash")
    msg = {
        "id": 25, "type": "growspace_manager/update_plant",
        "plant_id": "p1", "strain": "X",
    }
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_update_plant(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(25, "unknown_error", "crash")


# ---------------------------------------------------------------------------
# websocket_harvest_plant — complex: transition_date parsing, invalid date
# ---------------------------------------------------------------------------


async def test_harvest_plant_success_no_metrics(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.plants = {"p1": MagicMock()}
    msg = {"id": 30, "plant_id": "p1"}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_harvest_plant(hass, mock_connection, msg)
    mock_coordinator.services.plants.transition_plant.assert_awaited_once_with(
        plant_id="p1",
        target_growspace_id=None,
        target_growspace_name=None,
        transition_date=None,
        wet_weight=None,
        dry_weight=None,
        trim_weight=None,
        thc_percentage=None,
        cbd_percentage=None,
        terpene_profile=None,
    )
    mock_connection.send_result.assert_called_once_with(30)


async def test_harvest_plant_success_with_valid_transition_date(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.plants = {"p1": MagicMock()}
    msg = {"id": 31, "plant_id": "p1", "transition_date": "2026-01-10"}
    with (
        patch(_GET_COORD, return_value=mock_coordinator),
        patch(f"{_PATCH}.parse_date_field", return_value=_FIXED_DT),
    ):
        await websocket_harvest_plant(hass, mock_connection, msg)
    call_kwargs = mock_coordinator.services.plants.transition_plant.call_args[1]
    assert call_kwargs["transition_date"] == _FIXED_DT.isoformat()


async def test_harvest_plant_invalid_transition_date_sends_error(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.plants = {"p1": MagicMock()}
    msg = {"id": 32, "plant_id": "p1", "transition_date": "not-a-date"}
    with (
        patch(_GET_COORD, return_value=mock_coordinator),
        patch(f"{_PATCH}.parse_date_field", return_value=None),
    ):
        await websocket_harvest_plant(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(
        32, "validation_failed", "Invalid transition_date: not-a-date"
    )


async def test_harvest_plant_not_found(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    msg = {"id": 33, "plant_id": "missing"}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_harvest_plant(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(
        33, "validation_failed", "Plant 'missing' not found"
    )


async def test_harvest_plant_generic_error(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.plants = {"p1": MagicMock()}
    mock_coordinator.services.plants.transition_plant.side_effect = RuntimeError("crash")
    msg = {"id": 34, "plant_id": "p1"}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_harvest_plant(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(34, "unknown_error", "crash")


# ---------------------------------------------------------------------------
# websocket_move_clone — complex: date fallback, GrowspaceError/ValueError
# ---------------------------------------------------------------------------


async def test_move_clone_success_with_transition_date(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    msg = {
        "id": 40, "plant_id": "clone1", "target_growspace_id": "veg",
        "transition_date": "2026-01-10",
    }
    with (
        patch(_GET_COORD, return_value=mock_coordinator),
        patch(f"{_PATCH}.parse_date_field", return_value=_FIXED_DT),
    ):
        await websocket_move_clone(hass, mock_connection, msg)
    mock_coordinator.services.plants.promote_clone.assert_awaited_once_with(
        clone_id="clone1",
        target_growspace_id="veg",
        transition_date=_FIXED_DT,
    )
    mock_connection.send_result.assert_called_once_with(40)


async def test_move_clone_success_no_transition_date_uses_utcnow(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    msg = {"id": 41, "plant_id": "clone1", "target_growspace_id": "veg"}
    with (
        patch(_GET_COORD, return_value=mock_coordinator),
        patch(f"{_PATCH}.dt_util.utcnow", return_value=_FIXED_NOW),
    ):
        await websocket_move_clone(hass, mock_connection, msg)
    call_kwargs = mock_coordinator.services.plants.promote_clone.call_args[1]
    assert call_kwargs["transition_date"] == _FIXED_NOW


async def test_move_clone_unparseable_date_falls_back_to_utcnow(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    msg = {
        "id": 42, "plant_id": "clone1", "target_growspace_id": "veg",
        "transition_date": "bad-date",
    }
    with (
        patch(_GET_COORD, return_value=mock_coordinator),
        patch(f"{_PATCH}.parse_date_field", return_value=None),
        patch(f"{_PATCH}.dt_util.utcnow", return_value=_FIXED_NOW),
    ):
        await websocket_move_clone(hass, mock_connection, msg)
    call_kwargs = mock_coordinator.services.plants.promote_clone.call_args[1]
    assert call_kwargs["transition_date"] == _FIXED_NOW


@pytest.mark.parametrize("error", [GrowspaceError("bad"), ValueError("bad")])
async def test_move_clone_domain_error_is_validation_failed(
    hass: HomeAssistant,
    mock_connection: MagicMock,
    mock_coordinator: MagicMock,
    error: Exception,
) -> None:
    mock_coordinator.services.plants.promote_clone.side_effect = error
    msg = {"id": 43, "plant_id": "clone1", "target_growspace_id": "veg"}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_move_clone(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(43, "validation_failed", "bad")


async def test_move_clone_generic_error(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.services.plants.promote_clone.side_effect = RuntimeError("crash")
    msg = {"id": 44, "plant_id": "clone1", "target_growspace_id": "veg"}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_move_clone(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(44, "unknown_error", "crash")


# ---------------------------------------------------------------------------
# websocket_take_clone — complex: mother lookup, domain error re-raise
# ---------------------------------------------------------------------------


async def test_take_clone_success(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.plants = {"mother1": MagicMock()}
    msg = {"id": 50, "mother_plant_id": "mother1"}
    with (
        patch(_GET_COORD, return_value=mock_coordinator),
        patch(f"{_PATCH}.dt_util.utcnow", return_value=_FIXED_NOW),
    ):
        await websocket_take_clone(hass, mock_connection, msg)
    mock_coordinator.services.plants.take_clones.assert_awaited_once_with(
        mother_plant_id="mother1",
        num_clones=1,
        target_growspace_id=None,
        transition_date=_FIXED_NOW,
    )
    mock_connection.send_result.assert_called_once_with(50)


async def test_take_clone_mother_not_found(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    msg = {"id": 51, "mother_plant_id": "missing"}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_take_clone(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(
        51, "validation_failed", "Mother plant 'missing' not found"
    )


@pytest.mark.parametrize("error", [GrowspaceError("clone limit"), ValueError("bad range")])
async def test_take_clone_domain_error_is_validation_failed(
    hass: HomeAssistant,
    mock_connection: MagicMock,
    mock_coordinator: MagicMock,
    error: Exception,
) -> None:
    mock_coordinator.plants = {"mother1": MagicMock()}
    mock_coordinator.services.plants.take_clones.side_effect = error
    msg = {"id": 52, "mother_plant_id": "mother1"}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_take_clone(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(52, "validation_failed", str(error))


async def test_take_clone_generic_error(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.plants = {"mother1": MagicMock()}
    mock_coordinator.services.plants.take_clones.side_effect = RuntimeError("crash")
    msg = {"id": 53, "mother_plant_id": "mother1"}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_take_clone(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(53, "unknown_error", "crash")


# ---------------------------------------------------------------------------
# Passthrough handlers — happy path + error skeleton
# ---------------------------------------------------------------------------


async def test_remove_plant_success(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.plants = {"p1": MagicMock()}
    msg = {"id": 60, "plant_id": "p1"}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_remove_plant(hass, mock_connection, msg)
    mock_coordinator.services.plants.remove_plant.assert_awaited_once_with("p1")
    mock_connection.send_result.assert_called_once_with(60)


async def test_remove_plant_not_found(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    msg = {"id": 61, "plant_id": "missing"}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_remove_plant(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(
        61, "validation_failed", "Plant 'missing' not found"
    )


async def test_remove_plant_generic_error(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.plants = {"p1": MagicMock()}
    mock_coordinator.services.plants.remove_plant.side_effect = RuntimeError("crash")
    msg = {"id": 62, "plant_id": "p1"}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_remove_plant(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(62, "unknown_error", "crash")


async def test_move_plant_delegates_to_transition_plant(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.plants = {"p1": MagicMock()}
    msg = {"id": 63, "plant_id": "p1", "target_growspace_id": "flower"}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_move_plant(hass, mock_connection, msg)
    mock_coordinator.services.plants.transition_plant.assert_awaited_once()
    mock_connection.send_result.assert_called_once_with(63)


async def test_move_plant_not_found(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    msg = {"id": 64, "plant_id": "missing", "target_growspace_id": "flower"}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_move_plant(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(
        64, "validation_failed", "Plant 'missing' not found"
    )


async def test_switch_plants_success(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.plants = {"p1": MagicMock(), "p2": MagicMock()}
    msg = {"id": 65, "plant1_id": "p1", "plant2_id": "p2"}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_switch_plants(hass, mock_connection, msg)
    mock_coordinator.services.plants.switch_plants.assert_awaited_once_with("p1", "p2")
    mock_connection.send_result.assert_called_once_with(65)


async def test_switch_plants_plant1_not_found(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.plants = {"p2": MagicMock()}
    msg = {"id": 66, "plant1_id": "missing", "plant2_id": "p2"}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_switch_plants(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(
        66, "validation_failed", "Plant 'missing' not found"
    )


async def test_switch_plants_plant2_not_found(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.plants = {"p1": MagicMock()}
    msg = {"id": 67, "plant1_id": "p1", "plant2_id": "missing"}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_switch_plants(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(
        67, "validation_failed", "Plant 'missing' not found"
    )


async def test_score_plant_success(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.plants = {"p1": MagicMock()}
    msg = {"id": 68, "plant_id": "p1", "vigor": 8, "keeper": True}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_score_plant(hass, mock_connection, msg)
    mock_coordinator.services.plants.score_plant.assert_awaited_once()
    mock_connection.send_result.assert_called_once_with(68)


async def test_score_plant_not_found(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    msg = {"id": 69, "plant_id": "missing"}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_score_plant(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(
        69, "validation_failed", "Plant 'missing' not found"
    )


async def test_log_drying_weight_success(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    msg = {"id": 70, "plant_id": "p1", "weight_grams": 85.5}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_log_drying_weight(hass, mock_connection, msg)
    mock_coordinator.services.plants.log_drying_weight.assert_awaited_once_with(
        plant_id="p1", weight_grams=85.5, date=None
    )
    mock_connection.send_result.assert_called_once_with(70)


async def test_log_drying_weight_generic_error(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.services.plants.log_drying_weight.side_effect = RuntimeError("crash")
    msg = {"id": 71, "plant_id": "p1", "weight_grams": 85.5}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_log_drying_weight(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(71, "unknown_error", "crash")


async def test_log_moisture_reading_success(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    msg = {"id": 72, "plant_id": "p1", "moisture_percent": 11.5}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_log_moisture_reading(hass, mock_connection, msg)
    mock_coordinator.services.plants.log_moisture_reading.assert_awaited_once_with(
        plant_id="p1", moisture_percent=11.5, date=None
    )
    mock_connection.send_result.assert_called_once_with(72)


async def test_log_moisture_reading_generic_error(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.services.plants.log_moisture_reading.side_effect = RuntimeError("crash")
    msg = {"id": 73, "plant_id": "p1", "moisture_percent": 11.5}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_log_moisture_reading(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(73, "unknown_error", "crash")


async def test_set_visual_tag_success(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    msg = {"id": 74, "plant_id": "p1", "visual_tag": "red velcro"}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_set_visual_tag(hass, mock_connection, msg)
    mock_coordinator.services.plants.set_visual_tag.assert_awaited_once_with(
        plant_id="p1", visual_tag="red velcro"
    )
    mock_connection.send_result.assert_called_once_with(74)


async def test_set_visual_tag_generic_error(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.services.plants.set_visual_tag.side_effect = RuntimeError("crash")
    msg = {"id": 75, "plant_id": "p1", "visual_tag": "red velcro"}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_set_visual_tag(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(75, "unknown_error", "crash")


async def test_update_harvest_metrics_success(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    msg = {"id": 76, "plant_id": "p1", "dry_weight": 42.0}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_update_harvest_metrics(hass, mock_connection, msg)
    mock_coordinator.services.plants.update_harvest_metrics.assert_awaited_once_with(
        plant_id="p1",
        wet_weight=None,
        dry_weight=42.0,
        trim_weight=None,
        thc_percentage=None,
        cbd_percentage=None,
        terpene_profile=None,
    )
    mock_connection.send_result.assert_called_once_with(76)


async def test_update_harvest_metrics_generic_error(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.services.plants.update_harvest_metrics.side_effect = RuntimeError("crash")
    msg = {"id": 77, "plant_id": "p1", "dry_weight": 42.0}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_update_harvest_metrics(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(77, "unknown_error", "crash")


async def test_add_plants_mother_growspace_auto_sets_mother_start(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.growspaces = {"mother": MagicMock()}
    mock_coordinator.validator.find_first_available_position.side_effect = [
        (0, 0), (0, 0)
    ]
    msg = {"id": 16, "growspace_id": "mother", "strain": "Clone Queen", "amount": 1}
    with (
        patch(_GET_COORD, return_value=mock_coordinator),
        patch(f"{_PATCH}.dt_util.utcnow", return_value=_FIXED_NOW),
    ):
        await websocket_add_plants(hass, mock_connection, msg)
    call_kwargs = mock_coordinator.services.plants.add_plant.call_args[1]
    assert call_kwargs["mother_start"] == _FIXED_NOW


async def test_move_plant_with_valid_transition_date(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.plants = {"p1": MagicMock()}
    msg = {"id": 82, "plant_id": "p1", "target_growspace_id": "flower", "transition_date": "2026-01-10"}
    with (
        patch(_GET_COORD, return_value=mock_coordinator),
        patch(f"{_PATCH}.parse_date_field", return_value=_FIXED_DT),
    ):
        await websocket_move_plant(hass, mock_connection, msg)
    call_kwargs = mock_coordinator.services.plants.transition_plant.call_args[1]
    assert call_kwargs["transition_date"] == _FIXED_DT.isoformat()
    mock_connection.send_result.assert_called_once_with(82)


async def test_move_plant_generic_error(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.plants = {"p1": MagicMock()}
    mock_coordinator.services.plants.transition_plant.side_effect = RuntimeError("crash")
    msg = {"id": 83, "plant_id": "p1", "target_growspace_id": "flower"}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_move_plant(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(83, "unknown_error", "crash")


async def test_move_clone_service_validation_error(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    msg = {"id": 45, "plant_id": "clone1", "target_growspace_id": "veg"}
    with patch(_GET_COORD, side_effect=ServiceValidationError("not loaded")):
        await websocket_move_clone(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(45, "validation_failed", "not loaded")


async def test_switch_plants_generic_error(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.plants = {"p1": MagicMock(), "p2": MagicMock()}
    mock_coordinator.services.plants.switch_plants.side_effect = RuntimeError("crash")
    msg = {"id": 84, "plant1_id": "p1", "plant2_id": "p2"}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_switch_plants(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(84, "unknown_error", "crash")


async def test_score_plant_generic_error(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.plants = {"p1": MagicMock()}
    mock_coordinator.services.plants.score_plant.side_effect = RuntimeError("crash")
    msg = {"id": 85, "plant_id": "p1"}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_score_plant(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(85, "unknown_error", "crash")


async def test_log_drying_weight_validation_error(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.services.plants.log_drying_weight.side_effect = ServiceValidationError("invalid")
    msg = {"id": 86, "plant_id": "p1", "weight_grams": 50.0}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_log_drying_weight(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(86, "validation_failed", "invalid")


async def test_log_moisture_reading_validation_error(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.services.plants.log_moisture_reading.side_effect = ServiceValidationError("invalid")
    msg = {"id": 87, "plant_id": "p1", "moisture_percent": 50.0}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_log_moisture_reading(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(87, "validation_failed", "invalid")


async def test_set_visual_tag_validation_error(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.services.plants.set_visual_tag.side_effect = ServiceValidationError("invalid")
    msg = {"id": 88, "plant_id": "p1", "visual_tag": "red"}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_set_visual_tag(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(88, "validation_failed", "invalid")


async def test_update_harvest_metrics_validation_error(
    hass: HomeAssistant, mock_connection: MagicMock, mock_coordinator: MagicMock
) -> None:
    mock_coordinator.services.plants.update_harvest_metrics.side_effect = ServiceValidationError("invalid")
    msg = {"id": 89, "plant_id": "p1", "dry_weight": 42.0}
    with patch(_GET_COORD, return_value=mock_coordinator):
        await websocket_update_harvest_metrics(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(89, "validation_failed", "invalid")


async def test_print_label_success(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    mock_hass = MagicMock()
    mock_hass.services = MagicMock()
    mock_hass.services.async_call = AsyncMock()
    msg = {"id": 78, "type": "growspace_manager/print_label", "plant_id": "p1"}
    await websocket_print_label(mock_hass, mock_connection, msg)
    mock_hass.services.async_call.assert_awaited_once_with(
        "growspace_manager", "print_label", {"plant_id": "p1"}, blocking=True
    )
    mock_connection.send_result.assert_called_once_with(78)


async def test_print_label_validation_error(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    mock_hass = MagicMock()
    mock_hass.services = MagicMock()
    mock_hass.services.async_call = AsyncMock(side_effect=ServiceValidationError("no printer"))
    msg = {"id": 79, "type": "growspace_manager/print_label", "plant_id": "p1"}
    await websocket_print_label(mock_hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(79, "validation_failed", "no printer")


async def test_print_label_generic_error(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    mock_hass = MagicMock()
    mock_hass.services = MagicMock()
    mock_hass.services.async_call = AsyncMock(side_effect=RuntimeError("crash"))
    msg = {"id": 80, "type": "growspace_manager/print_label", "plant_id": "p1"}
    await websocket_print_label(mock_hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once_with(80, "unknown_error", "crash")
