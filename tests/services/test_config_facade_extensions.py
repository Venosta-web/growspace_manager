"""Tests for new ConfigFacade methods (get_inventory, update_stock, remove_stock)."""

from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.services.config_facade import ConfigFacade


def _make_coordinator() -> MagicMock:
    coordinator = MagicMock()
    coordinator.nutrient_manager = MagicMock()
    coordinator.nutrient_manager.inventory_service = MagicMock()
    coordinator.ipm_service = MagicMock()
    coordinator.strain_library = None
    return coordinator


# ---------------------------------------------------------------------------
# get_inventory
# ---------------------------------------------------------------------------


def test_get_inventory_delegates_to_inventory_service() -> None:
    """get_inventory returns the result from inventory_service.get_inventory."""
    inventory = MagicMock()
    coordinator = _make_coordinator()
    coordinator.nutrient_manager.inventory_service.get_inventory.return_value = inventory
    facade = ConfigFacade(coordinator)

    result = facade.get_inventory()

    assert result is inventory
    coordinator.nutrient_manager.inventory_service.get_inventory.assert_called_once_with()


def test_get_inventory_returns_none_when_no_inventory_service() -> None:
    """get_inventory returns None when inventory_service is None."""
    coordinator = _make_coordinator()
    coordinator.nutrient_manager.inventory_service = None
    facade = ConfigFacade(coordinator)

    assert facade.get_inventory() is None


# ---------------------------------------------------------------------------
# update_stock
# ---------------------------------------------------------------------------


def test_update_stock_delegates_to_inventory_service() -> None:
    """update_stock forwards all kwargs to inventory_service.update_stock."""
    coordinator = _make_coordinator()
    facade = ConfigFacade(coordinator)

    facade.update_stock(
        nutrient_id="n1",
        name="Grow A",
        current_ml=500.0,
        initial_ml=1000.0,
    )

    coordinator.nutrient_manager.inventory_service.update_stock.assert_called_once_with(
        nutrient_id="n1",
        name="Grow A",
        current_ml=500.0,
        initial_ml=1000.0,
    )


def test_update_stock_is_noop_when_no_inventory_service() -> None:
    """update_stock does nothing when inventory_service is None."""
    coordinator = _make_coordinator()
    coordinator.nutrient_manager.inventory_service = None
    facade = ConfigFacade(coordinator)

    facade.update_stock(nutrient_id="n1", name="X", current_ml=1.0, initial_ml=2.0)


# ---------------------------------------------------------------------------
# remove_stock
# ---------------------------------------------------------------------------


def test_remove_stock_delegates_to_inventory_service() -> None:
    """remove_stock forwards the nutrient_id to inventory_service.remove_stock."""
    coordinator = _make_coordinator()
    facade = ConfigFacade(coordinator)

    facade.remove_stock("n1")

    coordinator.nutrient_manager.inventory_service.remove_stock.assert_called_once_with(
        "n1"
    )


def test_remove_stock_is_noop_when_no_inventory_service() -> None:
    """remove_stock does nothing when inventory_service is None."""
    coordinator = _make_coordinator()
    coordinator.nutrient_manager.inventory_service = None
    facade = ConfigFacade(coordinator)

    facade.remove_stock("n1")
