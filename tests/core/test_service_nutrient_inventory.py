"""Tests for the Nutrient Inventory Service."""

from datetime import datetime
from unittest.mock import patch

import pytest

from custom_components.growspace_manager.models import NutrientInventory, NutrientStock
from custom_components.growspace_manager.services.nutrient_inventory import (
    NutrientInventoryService,
)


@pytest.fixture
def mock_inventory():
    """Return a mock inventory."""
    inventory = NutrientInventory()
    inventory.stocks = {
        "n1": NutrientStock(
            nutrient_id="n1",
            name="Grow A",
            current_ml=500.0,
            initial_ml=1000.0,
            last_updated="2024-01-01T00:00:00",
        ),
        "n2": NutrientStock(
            nutrient_id="n2",
            name="Bloom B",
            current_ml=100.0,
            initial_ml=1000.0,
            last_updated="2024-01-01T00:00:00",
        ),
    }
    return inventory


def test_init_and_get_inventory(mock_inventory) -> None:
    """Test initialization and retrieving inventory."""
    service = NutrientInventoryService(mock_inventory)
    assert service.get_inventory() == mock_inventory


def test_update_stock(mock_inventory) -> None:
    """Test updating or creating a stock."""
    service = NutrientInventoryService(mock_inventory)

    # Test creating new stock
    with patch(
        "custom_components.growspace_manager.services.nutrient_inventory.dt_util"
    ) as mock_dt:
        mock_dt.utcnow.return_value = datetime(2024, 2, 1, 12, 0, 0)

        service.update_stock(
            nutrient_id="n3", name="CalMag", current_ml=250.0, initial_ml=500.0
        )

        assert "n3" in mock_inventory.stocks
        stock = mock_inventory.stocks["n3"]
        assert stock.name == "CalMag"
        assert stock.current_ml == 250.0
        assert stock.initial_ml == 500.0
        assert stock.last_updated == "2024-02-01T12:00:00"

    # Test updating existing stock
    service.update_stock(
        nutrient_id="n1", name="Grow A (New)", current_ml=600.0, initial_ml=1000.0
    )
    assert mock_inventory.stocks["n1"].name == "Grow A (New)"
    assert mock_inventory.stocks["n1"].current_ml == 600.0


def test_deduct_usage_success(mock_inventory) -> None:
    """Test successfully deducting usage."""
    service = NutrientInventoryService(mock_inventory)

    with patch(
        "custom_components.growspace_manager.services.nutrient_inventory.dt_util"
    ) as mock_dt:
        mock_dt.utcnow.return_value = datetime(2024, 2, 1, 12, 0, 0)

        # Deduct 50ml from Grow A (starts at 500)
        service.deduct_usage("Grow A", 50.0)

        assert mock_inventory.stocks["n1"].current_ml == 450.0
        assert mock_inventory.stocks["n1"].last_updated == "2024-02-01T12:00:00"



def test_deduct_usage_case_insensitive(mock_inventory) -> None:
    """Test deduction is case insensitive."""
    service = NutrientInventoryService(mock_inventory)

    # Deduct from "bloom b" (starts at 100)
    service.deduct_usage("bloom b", 10.0)

    assert mock_inventory.stocks["n2"].current_ml == 90.0


def test_deduct_usage_not_found(mock_inventory) -> None:
    """Test deduction when nutrient is not found."""
    service = NutrientInventoryService(mock_inventory)

    # Logic just logs a warning, so we verify state doesn't change
    service.deduct_usage("Unknown Nutrient", 50.0)

    assert list(mock_inventory.stocks.keys()) == ["n1", "n2"]
    assert mock_inventory.stocks["n1"].current_ml == 500.0


def test_deduct_usage_min_zero(mock_inventory) -> None:
    """Test deduction doesn't go below zero."""
    service = NutrientInventoryService(mock_inventory)

    # Deduct 600ml from Grow A (starts at 500)
    service.deduct_usage("Grow A", 600.0)

    assert mock_inventory.stocks["n1"].current_ml == 0.0


def test_remove_stock(mock_inventory) -> None:
    """Test removing a stock."""
    service = NutrientInventoryService(mock_inventory)

    service.remove_stock("n1")
    assert "n1" not in mock_inventory.stocks
    assert "n2" in mock_inventory.stocks


def test_remove_stock_not_found(mock_inventory) -> None:
    """Test removing a non-existent stock does nothing (no error)."""
    service = NutrientInventoryService(mock_inventory)

    service.remove_stock("n999")
    assert len(mock_inventory.stocks) == 2
