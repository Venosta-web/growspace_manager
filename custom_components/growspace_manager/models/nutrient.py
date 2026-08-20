"""Nutrient presets, feeding charts, and inventory models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from custom_components.growspace_manager.integration_types import NutrientMap
import homeassistant.util.dt as dt_util

from .base import BaseModel, BasePreset
from .types import NutrientPresetItem

__all__ = ["NutrientInventory", "NutrientPreset", "NutrientStock"]


@dataclass(slots=True, kw_only=True)
class NutrientPreset(BasePreset):
    """A reusable nutrient recipe with optional stage conditions.

    Attributes:
        id: Unique identifier for the preset.
        name: Human-readable name for the preset (e.g., "Late Bloom Mix").
        items: List of nutrients (NutrientPresetItem).
        stage: Optional plant stage this preset applies to.
        min_days_in_stage: Optional minimum days in stage before this preset applies.
        created_at: Timestamp when the preset was created.
    """

    items: list[NutrientPresetItem]
    week: int = 1
    ec_target: float | None = None
    ph_target: float | None = None

    @property
    def nutrients(self) -> list[NutrientPresetItem]:
        """Alias for items for backward compatibility."""
        return self.items

    @nutrients.setter
    def nutrients(self, value: list[NutrientPresetItem]) -> None:
        self.items = value

    @classmethod
    def __pre_deserialize__(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Rename 'nutrients' key to 'items' (storage uses 'nutrients') and delegate to base."""
        data = super().__pre_deserialize__(data)
        if "nutrients" in data and "items" not in data:
            data["items"] = data.pop("nutrients")
        return data

    def get_nutrient_map(self) -> NutrientMap:
        """Convert nutrients list to a dict[nutrient_id: dose_ml_l] for watering services."""
        return {n["nutrient_id"]: n["dose_ml_l"] for n in self.items}


@dataclass(slots=True)
class NutrientStock(BaseModel):
    """Tracks nutrient inventory levels."""

    nutrient_id: str
    name: str
    current_ml: float
    initial_ml: float
    last_updated: str = field(default_factory=lambda: dt_util.utcnow().isoformat())
    brand: str = ""
    type: str = "base"
    npk: str = ""
    dose_ml_l: float = 0.0
    notes: str = ""


@dataclass(slots=True)
class NutrientInventory(BaseModel):
    """Collection of nutrient stocks."""

    stocks: dict[str, NutrientStock] = field(default_factory=dict)
