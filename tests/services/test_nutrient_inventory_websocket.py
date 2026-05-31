"""Test Nutrient Inventory WebSocket commands."""

import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from custom_components.growspace_manager.models import NutrientInventory, NutrientStock
from custom_components.growspace_manager.websocket import (
    WS_TYPE_GET_NUTRIENT_INVENTORY,
    WS_TYPE_REMOVE_NUTRIENT_STOCK,
    WS_TYPE_UPDATE_NUTRIENT_STOCK,
    async_register_websocket_api,
)
from homeassistant.core import HomeAssistant

WebSocketGenerator = Any

_LOGGER = logging.getLogger(__name__)
# Register the websocket commands


@pytest.fixture
def mock_coordinator(hass: HomeAssistant):
    """Mock the GrowspaceCoordinator."""
    coordinator = MagicMock()
    coordinator.nutrient_manager.inventory_service = MagicMock()

    # Setup inventory service mock
    inventory = NutrientInventory()
    inventory.stocks["test_nutrient"] = NutrientStock(
        nutrient_id="test_nutrient",
        name="Test Nutrient",
        current_ml=500.0,
        initial_ml=1000.0,
        last_updated="2023-01-01T00:00:00",
    )

    coordinator.nutrient_manager.inventory_service.get_inventory.return_value = inventory
    coordinator.nutrient_manager.inventory_service.update_stock.return_value = None
    coordinator.nutrient_manager.inventory_service.remove_stock.return_value = None

    with patch(
        "custom_components.growspace_manager.coordinator.GrowspaceCoordinator.get_any",
        return_value=coordinator,
    ):
        async_register_websocket_api(hass)
        yield coordinator


async def test_websocket_get_nutrient_inventory(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, mock_coordinator
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
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, mock_coordinator
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

    mock_coordinator.nutrient_manager.inventory_service.update_stock.assert_called_with(
        nutrient_id="new_nutrient",
        name="New Nutrient",
        current_ml=100.0,
        initial_ml=200.0,
    )
    mock_coordinator.async_commit.assert_called()


async def test_websocket_remove_nutrient_stock(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, mock_coordinator
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

    mock_coordinator.nutrient_manager.inventory_service.remove_stock.assert_called_with(
        "test_nutrient"
    )
    mock_coordinator.async_commit.assert_called()
