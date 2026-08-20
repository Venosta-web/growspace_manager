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

    # Setup inventory via the facade path
    inventory = NutrientInventory()
    inventory.stocks["test_nutrient"] = NutrientStock(
        nutrient_id="test_nutrient",
        name="Test Nutrient",
        current_ml=500.0,
        initial_ml=1000.0,
        last_updated="2023-01-01T00:00:00",
    )

    coordinator.services.config.get_inventory.return_value = inventory
    coordinator.services.config.update_stock.return_value = None
    coordinator.services.config.remove_stock.return_value = None

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
    """Test updating nutrient stock without new fields (backward-compatible)."""
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

    mock_coordinator.services.config.update_stock.assert_called_with(
        nutrient_id="new_nutrient",
        name="New Nutrient",
        current_ml=100.0,
        initial_ml=200.0,
        brand="",
        type="base",
        npk="",
        dose_ml_l=0.0,
        notes="",
    )
    mock_coordinator.async_commit.assert_called()


async def test_websocket_update_nutrient_stock_with_metadata(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, mock_coordinator
) -> None:
    """Test updating nutrient stock forwards all five new metadata fields."""
    client = await hass_ws_client(hass)

    await client.send_json(
        {
            "id": 1,
            "type": WS_TYPE_UPDATE_NUTRIENT_STOCK,
            "nutrient_id": "bloom_bottle",
            "name": "PK Booster",
            "current_ml": 300.0,
            "initial_ml": 1000.0,
            "brand": "Canna",
            "stock_type": "bloom",
            "npk": "0-15-14",
            "dose_ml_l": 1.5,
            "notes": "Use in week 5+",
        }
    )

    msg = await client.receive_json()
    assert msg["success"]

    mock_coordinator.services.config.update_stock.assert_called_with(
        nutrient_id="bloom_bottle",
        name="PK Booster",
        current_ml=300.0,
        initial_ml=1000.0,
        brand="Canna",
        type="bloom",
        npk="0-15-14",
        dose_ml_l=1.5,
        notes="Use in week 5+",
    )


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

    mock_coordinator.services.config.remove_stock.assert_called_with(
        "test_nutrient"
    )
    mock_coordinator.async_commit.assert_called()
