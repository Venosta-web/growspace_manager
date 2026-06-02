"""Nutrient Inventory Service."""

import logging

from custom_components.growspace_manager.models import NutrientInventory, NutrientStock
from homeassistant.util import dt as dt_util

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
        self,
        nutrient_id: str,
        name: str,
        current_ml: float,
        initial_ml: float,
        brand: str = "",
        type: str = "base",
        npk: str = "",
        dose_ml_l: float = 0.0,
        notes: str = "",
    ) -> None:
        """Update or create a nutrient stock."""
        self._inventory.stocks[nutrient_id] = NutrientStock(
            nutrient_id=nutrient_id,
            name=name,
            current_ml=current_ml,
            initial_ml=initial_ml,
            last_updated=dt_util.utcnow().isoformat(),
            brand=brand,
            type=type,
            npk=npk,
            dose_ml_l=dose_ml_l,
            notes=notes,
        )
        _LOGGER.debug(
            "Updated stock for %s (%s): %s/%s ml",
            name,
            nutrient_id,
            current_ml,
            initial_ml,
        )

    def deduct_usage(self, nutrient_id: str, amount_ml: float) -> None:
        """Deduct nutrient usage from stock by nutrient_id."""
        stock = self._inventory.stocks.get(nutrient_id)
        if stock is not None:
            stock.current_ml = max(0.0, stock.current_ml - amount_ml)
            stock.last_updated = dt_util.utcnow().isoformat()
            _LOGGER.debug(
                "Deducted %s ml from %s (%s). Remaining: %s ml",
                amount_ml,
                stock.name,
                nutrient_id,
                stock.current_ml,
            )
        else:
            _LOGGER.warning(
                "Could not find stock for nutrient_id %s to deduct %s ml",
                nutrient_id,
                amount_ml,
            )

    def deduct_nutrients(
        self, final_nutrients: dict[str, float], amount_liters: float
    ) -> None:
        """Deduct multiple nutrients based on water amount."""
        for name, conc in final_nutrients.items():
            total_ml = amount_liters * conc
            if total_ml > 0:
                self.deduct_usage(name, total_ml)

    def remove_stock(self, nutrient_id: str) -> None:
        """Remove a nutrient stock."""
        if nutrient_id in self._inventory.stocks:
            del self._inventory.stocks[nutrient_id]
            _LOGGER.debug("Removed stock for nutrient %s", nutrient_id)
