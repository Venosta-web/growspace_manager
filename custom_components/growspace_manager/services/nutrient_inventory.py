"""Nutrient Inventory Service."""

import logging
from datetime import datetime

from ..models import NutrientInventory, NutrientStock

_LOGGER = logging.getLogger(__name__)


class NutrientInventoryService:
    """Manages nutrient inventory tracking."""

    def __init__(self, inventory: NutrientInventory) -> None:
        """Initialize the service."""
        self._inventory = inventory

    def get_inventory(self) -> NutrientInventory:
        """Return the current inventory."""
        return self._inventory

    def update_stock(
        self, nutrient_id: str, name: str, current_ml: float, initial_ml: float
    ) -> None:
        """Update or create a nutrient stock."""
        self._inventory.stocks[nutrient_id] = NutrientStock(
            nutrient_id=nutrient_id,
            name=name,
            current_ml=current_ml,
            initial_ml=initial_ml,
            last_updated=datetime.now().isoformat(),
        )
        _LOGGER.debug(
            "Updated stock for %s (%s): %s/%s ml",
            name,
            nutrient_id,
            current_ml,
            initial_ml,
        )

    def deduct_usage(self, nutrient_name: str, amount_ml: float) -> None:
        """Deduct nutrient usage from stock.

        Matches by name since watering events use preset names.
        """
        # Find ID by name
        target_id = None
        for stock in self._inventory.stocks.values():
            if stock.name.lower() == nutrient_name.lower():
                target_id = stock.nutrient_id
                break

        if target_id:
            stock = self._inventory.stocks[target_id]
            stock.current_ml = max(0.0, stock.current_ml - amount_ml)
            stock.last_updated = datetime.now().isoformat()
            _LOGGER.debug(
                "Deducted %s ml from %s. Remaining: %s ml",
                amount_ml,
                nutrient_name,
                stock.current_ml,
            )
        else:
            _LOGGER.warning(
                "Could not find stock for nutrient %s to deduct %s ml",
                nutrient_name,
                amount_ml,
            )

    def remove_stock(self, nutrient_id: str) -> None:
        """Remove a nutrient stock."""
        if nutrient_id in self._inventory.stocks:
            del self._inventory.stocks[nutrient_id]
            _LOGGER.debug("Removed stock for nutrient %s", nutrient_id)
