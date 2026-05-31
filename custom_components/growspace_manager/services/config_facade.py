"""Config sub-facade for the Growspace Manager integration.

Covers nutrient presets, IPM presets, EC ramp curves, and strain library.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from custom_components.growspace_manager.models import (
    ECRampCurve,
    IPMPreset,
    NutrientPreset,
)

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
    from custom_components.growspace_manager.strain_library import StrainLibrary

_LOGGER = logging.getLogger(__name__)


class ConfigFacade:
    """Facade for nutrient/IPM/EC preset and strain library operations."""

    def __init__(self, coordinator: GrowspaceCoordinator) -> None:
        """Initialise the facade with the coordinator."""
        self._coordinator = coordinator

    # -------------------------------------------------------------------------
    # Strain library
    # -------------------------------------------------------------------------

    @property
    def strain_library(self) -> StrainLibrary | None:
        """Expose the StrainLibrary; callers that need deep access use this."""
        return self._coordinator.strain_library

    def get_strain_options(self) -> list[str]:
        """Return a sorted list of unique strain names."""
        if not self._coordinator.strain_library:
            return []
        return sorted(self._coordinator.strain_library.get_all().keys())

    def export_strain_library(self) -> list[str]:
        """Export all strains from the library."""
        return self.get_strain_options()

    async def clear_strains(self) -> int:
        """Remove all strains from the library."""
        if not self._coordinator.strain_library:
            return 0
        return await self._coordinator.strain_library.clear()

    # -------------------------------------------------------------------------
    # EC ramp curves
    # -------------------------------------------------------------------------

    @property
    def ec_ramp_curves(self) -> dict[str, Any]:
        """Return all EC ramp curves keyed by curve ID."""
        return self._coordinator.nutrient_manager.ec_ramp_curves

    async def save_ec_ramp_curve(
        self,
        growspace_id: str | None = None,
        name: str | None = None,
        points: list[dict[str, Any]] | None = None,
        curve_id: str | None = None,
        **kwargs: Any,
    ) -> ECRampCurve:
        """Save an EC ramp curve."""
        if growspace_id is None:
            gids = list(self._coordinator.growspaces.keys())
            if not gids:
                raise ValueError("No growspaces available to save EC ramp curve")
            growspace_id = gids[0]
            _LOGGER.warning(
                "Legacy call to save_ec_ramp_curve missing growspace_id. Using default: %s",
                growspace_id,
            )
        if name is None or points is None:
            raise TypeError("save_ec_ramp_curve() missing required arguments")
        return await self._coordinator.nutrient_manager.async_save_ec_ramp_curve(
            growspace_id, name, points, curve_id
        )

    async def remove_ec_ramp_curve(
        self, growspace_id: str | None, curve_id: str
    ) -> None:
        """Remove an EC ramp curve."""
        await self._coordinator.nutrient_manager.async_remove_ec_ramp_curve(curve_id)

    # -------------------------------------------------------------------------
    # Nutrient presets
    # -------------------------------------------------------------------------

    async def save_nutrient_preset(
        self,
        name: str,
        nutrients: list[dict[str, Any]],
        stage: str | None = None,
        min_days_in_stage: int | None = None,
        preset_id: str | None = None,
    ) -> NutrientPreset:
        """Create or update a nutrient preset."""
        return await self._coordinator.nutrient_manager.async_save_nutrient_preset(
            name, nutrients, stage, min_days_in_stage, preset_id
        )

    async def remove_nutrient_preset(self, preset_id: str) -> None:
        """Remove a nutrient preset."""
        await self._coordinator.nutrient_manager.async_remove_nutrient_preset(preset_id)

    def get_applicable_presets(self, plant_id: str) -> list[NutrientPreset]:
        """Return all nutrient presets applicable to a plant."""
        return self._coordinator.nutrient_manager.get_applicable_presets(plant_id)

    def get_nutrient_serialization_data(self) -> dict[str, Any]:
        """Return serialized nutrient data for WebSocket consumers."""
        return self._coordinator.nutrient_manager.get_serialization_data()

    # -------------------------------------------------------------------------
    # IPM presets
    # -------------------------------------------------------------------------

    async def save_ipm_preset(
        self,
        name: str,
        preset_type: str | None = None,
        items: list[dict[str, Any]] | None = None,
        stage: str | None = None,
        min_days_in_stage: int | None = None,
        preset_id: str | None = None,
        **kwargs: Any,
    ) -> IPMPreset:
        """Create or update an IPM preset."""
        if preset_type is None and "type" in kwargs:
            preset_type = kwargs["type"]
        if preset_type is None:
            raise TypeError(
                "save_ipm_preset() missing 1 required positional argument: 'preset_type'"
            )
        if items is None:
            raise TypeError(
                "save_ipm_preset() missing 1 required positional argument: 'items'"
            )
        return await self._coordinator.ipm_service.async_save_ipm_preset(
            name, preset_type, items, stage, min_days_in_stage, preset_id
        )

    async def remove_ipm_preset(self, preset_id: str) -> None:
        """Remove an IPM preset."""
        await self._coordinator.ipm_service.async_remove_ipm_preset(preset_id)
