"""Data contracts and schemas for the Growspace Manager coordinator."""

from __future__ import annotations

from typing import Any, TypedDict

from .growspace import Growspace
from .ipm import IPMPreset
from .nutrient import NutrientInventory, NutrientPreset
from .plant import Plant

__all__ = ["GrowspaceCoordinatorData"]


class GrowspaceCoordinatorData(TypedDict):
    """Data contract for the Growspace Coordinator."""

    growspaces: dict[str, Growspace]
    plants: dict[str, Plant]
    nutrient_presets: dict[str, NutrientPreset]
    notifications_sent: dict[str, dict[str, dict[str, bool]]]
    notifications_enabled: dict[str, bool]
    _version: str
    serialized_growspaces: dict[str, dict[str, Any]]
    air_exchange_recommendations: dict[str, str]
    ipm_presets: dict[str, IPMPreset]
    nutrient_inventory: NutrientInventory
