"""Nutrient and IPM Manager."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict
import logging
from typing import TYPE_CHECKING, Any
import uuid

from custom_components.growspace_manager.models import (
    ECRampCurve,
    ECRampPoint,
    IPMPreset,
    IPMPresetItem,
    NutrientInventory,
    NutrientPreset,
    NutrientPresetItem,
)
from custom_components.growspace_manager.services.nutrient_inventory import (
    NutrientInventoryService,
)
import homeassistant.util.dt as dt_util

if TYPE_CHECKING:
    from custom_components.growspace_manager.data_access.growspace_repository import (
        GrowspaceRepository,
    )


_LOGGER = logging.getLogger(__name__)


class NutrientManager:
    """Manages nutrient presets, IPM presets, and inventory integration."""

    def __init__(
        self,
        repository: GrowspaceRepository,
        save_callback: Callable[[], Awaitable[None]],
    ) -> None:
        """Initialize the NutrientManager."""
        self.repository = repository
        self.save_callback = save_callback
        self.nutrient_presets: dict[str, NutrientPreset] = {}
        self.ipm_presets: dict[str, IPMPreset] = {}
        self.ec_ramp_curves: dict[str, ECRampCurve] = {}
        self.inventory_service: NutrientInventoryService | None = None
        self.inventory: NutrientInventory | None = None

    def load_data(
        self,
        nutrient_presets: dict[str, NutrientPreset],
        ipm_presets: dict[str, IPMPreset],
        inventory: NutrientInventory | None,
        ec_ramp_curves: dict[str, ECRampCurve] | None = None,
    ) -> None:
        """Load data into the manager."""
        self.nutrient_presets = nutrient_presets
        self.ipm_presets = ipm_presets
        if ec_ramp_curves is not None:
            self.ec_ramp_curves = ec_ramp_curves
        if inventory:
            self.inventory = inventory
            self.inventory_service = NutrientInventoryService(inventory)

    async def async_save_nutrient_preset(
        self,
        name: str,
        nutrients: list[dict[str, Any]],
        stage: str | None = None,
        min_days_in_stage: int | None = None,
        preset_id: str | None = None,
    ) -> NutrientPreset:
        """Create or update a nutrient preset."""
        if preset_id and preset_id in self.nutrient_presets:
            preset = self.nutrient_presets[preset_id]
            preset.name = name
            preset.items = [
                NutrientPresetItem(name=n["name"], dose_ml_l=n["dose_ml_l"])
                for n in nutrients
            ]
            preset.stage = stage
            preset.min_days_in_stage = min_days_in_stage
        else:
            # Create new
            pid = preset_id or str(uuid.uuid4())
            preset = NutrientPreset(
                id=pid,
                name=name,
                items=[
                    NutrientPresetItem(name=n["name"], dose_ml_l=n["dose_ml_l"])
                    for n in nutrients
                ],
                stage=stage,
                min_days_in_stage=min_days_in_stage,
                created_at=dt_util.now().isoformat(),
            )
            self.nutrient_presets[pid] = preset

        await self.save_callback()

        _LOGGER.info(
            "Saved nutrient preset '%s' with %d nutrients (id=%s)",
            name,
            len(nutrients),
            preset_id,
        )

        # Invalidate cache for all growspaces as presets are global
        # Invalidate cache for all growspaces as presets are global
        # self._coordinator.cache.invalidate() # Removed as coordinator is no longer directly used

        return preset

    async def async_remove_nutrient_preset(self, preset_id: str) -> None:
        """Remove a nutrient preset."""
        if preset_id not in self.nutrient_presets:
            raise KeyError(f"Nutrient preset '{preset_id}' not found")

        preset_name = self.nutrient_presets[preset_id].name
        if preset_id in self.nutrient_presets:
            self.nutrient_presets.pop(preset_id)
            await self.save_callback()

        # Invalidate cache
        # self._coordinator.cache.invalidate() # Removed as coordinator is no longer directly used

        _LOGGER.info("Removed nutrient preset '%s' (id=%s)", preset_name, preset_id)

    async def async_save_ipm_preset(
        self,
        name: str,
        type: str,
        items: list[dict[str, Any]],
        stage: str | None = None,
        min_days_in_stage: int | None = None,
        preset_id: str | None = None,
    ) -> IPMPreset:
        """Create or update an IPM preset."""
        if preset_id and preset_id in self.ipm_presets:
            preset = self.ipm_presets[preset_id]
            preset.name = name
            preset.type = type
            preset.items = [
                IPMPresetItem(
                    name=i["name"],
                    dose_amount=i["dose_amount"],
                    dose_unit=i["dose_unit"],
                )
                for i in items
            ]
            preset.stage = stage
            preset.min_days_in_stage = min_days_in_stage
        else:
            pid = preset_id or str(uuid.uuid4())
            preset = IPMPreset(
                id=pid,
                name=name,
                type=type,
                items=[
                    IPMPresetItem(
                        name=i["name"],
                        dose_amount=i["dose_amount"],
                        dose_unit=i["dose_unit"],
                    )
                    for i in items
                ],
                stage=stage,
                min_days_in_stage=min_days_in_stage,
                created_at=dt_util.now().isoformat(),
            )
            self.ipm_presets[pid] = preset

        await self.save_callback()
        _LOGGER.info("Saved IPM preset '%s' (id=%s)", name, preset_id)
        return preset

    async def async_remove_ipm_preset(self, preset_id: str) -> None:
        """Remove an IPM preset."""
        if preset_id not in self.ipm_presets:
            raise KeyError(f"IPM preset '{preset_id}' not found")

        preset_name = self.ipm_presets[preset_id].name
        if preset_id in self.ipm_presets:
            self.ipm_presets.pop(preset_id)
            await self.save_callback()
        _LOGGER.info("Removed IPM preset '%s' (id=%s)", preset_name, preset_id)

    async def async_save_ec_ramp_curve(
        self,
        name: str,
        stage: str,
        points: list[dict[str, Any]],
        curve_id: str | None = None,
    ) -> ECRampCurve:
        """Create or update an EC ramp curve."""
        if curve_id and curve_id in self.ec_ramp_curves:
            curve = self.ec_ramp_curves[curve_id]
            curve.name = name
            curve.stage = stage
            curve.points = [
                ECRampPoint(week=p["week"], ec_min=p["ec_min"], ec_max=p["ec_max"])
                for p in points
            ]
        else:
            cid = curve_id or str(uuid.uuid4())
            curve = ECRampCurve(
                id=cid,
                name=name,
                stage=stage,
                points=[
                    ECRampPoint(week=p["week"], ec_min=p["ec_min"], ec_max=p["ec_max"])
                    for p in points
                ],
                created_at=dt_util.now().isoformat(),
            )
            self.ec_ramp_curves[cid] = curve

        await self.save_callback()
        _LOGGER.info(
            "Saved EC ramp curve '%s' for stage %s with %d points",
            name,
            stage,
            len(points),
        )
        return curve

    async def async_remove_ec_ramp_curve(self, curve_id: str) -> None:
        """Remove an EC ramp curve."""
        if curve_id not in self.ec_ramp_curves:
            raise KeyError(f"EC ramp curve '{curve_id}' not found")

        curve_name = self.ec_ramp_curves[curve_id].name
        del self.ec_ramp_curves[curve_id]
        await self.save_callback()
        _LOGGER.info("Removed EC ramp curve '%s' (id=%s)", curve_name, curve_id)

    def get_applicable_presets(self, plant_id: str) -> list[NutrientPreset]:
        """Get all presets applicable to a plant based on its current stage and days."""
        # Validate plant existence via coordinator or pass plant object
        plant = self.repository.plants.get(plant_id)
        if not plant:
            raise ValueError(f"Plant {plant_id} not found")

        applicable: list[NutrientPreset] = []

        for preset in self.nutrient_presets.values():
            # If preset has no stage filter, it applies to all stages
            if preset.stage is not None:
                # Check if plant's current stage matches preset stage
                if str(plant.stage).lower() != str(preset.stage).lower():
                    continue

            # If preset has min_days_in_stage, check if plant meets it
            if preset.min_days_in_stage is not None:
                current_stage = str(plant.stage).lower()
                days_in_stage = plant.get_days_in_stage(current_stage)
                if days_in_stage < preset.min_days_in_stage:
                    continue

            applicable.append(preset)

        return applicable

    def resolve_nutrient_mix(
        self, nutrients: dict[str, float] | None, preset_id: str | None
    ) -> tuple[dict[str, float], str | None]:
        """Resolve final nutrient mix from optional preset and manual overrides."""
        final_nutrients: dict[str, float] = {}
        preset_name: str | None = None

        if preset_id:
            if preset_id not in self.nutrient_presets:
                raise KeyError(f"Nutrient preset '{preset_id}' not found")
            preset = self.nutrient_presets[preset_id]
            preset_name = preset.name
            final_nutrients.update(preset.get_nutrient_map())

        if nutrients:
            final_nutrients.update(nutrients)

        return final_nutrients, preset_name

    def deduct_from_inventory(
        self, final_nutrients: dict[str, float], amount_liters: float
    ) -> None:
        """Deduct nutrients from inventory if service is available."""
        if self.inventory_service:
            try:
                self.inventory_service.deduct_nutrients(final_nutrients, amount_liters)
            except Exception:
                _LOGGER.exception("Error deducting from inventory")

    def get_serialization_data(self) -> dict[str, Any]:
        """Return data for serialization."""
        # Convert presets to dict and ensure 'items' is serialized as 'nutrients'
        # for frontend compatibility
        nutrient_presets_serialized = {}
        for pid, preset in self.nutrient_presets.items():
            preset_dict = asdict(preset)
            # Convert 'items' to 'nutrients' for backward compatibility with frontend
            if "items" in preset_dict:
                preset_dict["nutrients"] = preset_dict.pop("items")
            nutrient_presets_serialized[pid] = preset_dict

        ipm_presets_serialized = {}
        for ipm_pid, ipm_preset in self.ipm_presets.items():
            ipm_preset_dict = asdict(ipm_preset)
            # IPM presets also use 'items', keep consistent
            if "items" in ipm_preset_dict:
                ipm_preset_dict["items"] = ipm_preset_dict["items"]
            ipm_presets_serialized[ipm_pid] = ipm_preset_dict

        ec_ramp_curves_serialized = {
            cid: asdict(curve) for cid, curve in self.ec_ramp_curves.items()
        }

        return {
            "nutrient_presets": nutrient_presets_serialized,
            "ipm_presets": ipm_presets_serialized,
            "nutrient_inventory": asdict(self.inventory) if self.inventory else {},
            "ec_ramp_curves": ec_ramp_curves_serialized,
        }
