"""Test Nutrient Inventory WebSocket commands."""

import logging
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.growspace_manager import (
    WS_TYPE_GET_NUTRIENT_INVENTORY,
    WS_TYPE_REMOVE_NUTRIENT_STOCK,
    WS_TYPE_UPDATE_NUTRIENT_STOCK,
)
from custom_components.growspace_manager.models import NutrientInventory, NutrientStock

_LOGGER = logging.getLogger(__name__)


@pytest.fixture
def mock_coordinator(hass: HomeAssistant):
    """Mock the GrowspaceCoordinator."""
    coordinator = MagicMock()
    coordinator.nutrient_inventory_service = MagicMock()

    # Setup inventory service mock
    inventory = NutrientInventory()
    inventory.stocks["test_nutrient"] = NutrientStock(
        nutrient_id="test_nutrient",
        name="Test Nutrient",
        current_ml=500.0,
        initial_ml=1000.0,
        last_updated="2023-01-01T00:00:00",
    )

    coordinator.nutrient_inventory_service.get_inventory.return_value = inventory
    coordinator.nutrient_inventory_service.update_stock.return_value = None
    coordinator.nutrient_inventory_service.remove_stock.return_value = None

    with patch(
        "custom_components.growspace_manager.coordinator.GrowspaceCoordinator.get_for_service_call",
        return_value=coordinator,
    ):
        # Register the websocket commands
        from custom_components.growspace_manager import _async_register_websocket_api

        _async_register_websocket_api(hass)
        yield coordinator


async def test_websocket_get_nutrient_inventory(
    hass: HomeAssistant, hass_ws_client, mock_coordinator
) -> None:
    """Test getting nutrient inventory."""
    client = await hass_ws_client(hass)

    await client.send_json(
        {
            "id": 1,
            "type": WS_TYPE_GET_NUTRIENT_INVENTORY,
        }
    )

    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"]["stocks"]["test_nutrient"]["name"] == "Test Nutrient"
    assert msg["result"]["stocks"]["test_nutrient"]["current_ml"] == 500.0


async def test_websocket_update_nutrient_stock(
    hass: HomeAssistant, hass_ws_client, mock_coordinator
) -> None:
    """Test updating nutrient stock."""
    client = await hass_ws_client(hass)

    await client.send_json(
        {
            "id": 1,
            "type": WS_TYPE_UPDATE_NUTRIENT_STOCK,
            "nutrient_id": "new_nutrient",
            "name": "New Nutrient",
            "current_ml": 100.0,
            "initial_ml": 200.0,
        }
    )

    msg = await client.receive_json()
    assert msg["success"]

    mock_coordinator.nutrient_inventory_service.update_stock.assert_called_with(
        nutrient_id="new_nutrient",
        name="New Nutrient",
        current_ml=100.0,
        initial_ml=200.0,
    )
    mock_coordinator.async_save.assert_called()


async def test_websocket_remove_nutrient_stock(
    hass: HomeAssistant, hass_ws_client, mock_coordinator
) -> None:
    """Test removing nutrient stock."""
    client = await hass_ws_client(hass)

    await client.send_json(
        {
            "id": 1,
            "type": WS_TYPE_REMOVE_NUTRIENT_STOCK,
            "nutrient_id": "test_nutrient",
        }
    )

    msg = await client.receive_json()
    assert msg["success"]

    mock_coordinator.nutrient_inventory_service.remove_stock.assert_called_with(
        "test_nutrient"
    )
    mock_coordinator.async_save.assert_called()
