"""Config sub-facade for the Growspace Manager integration.

Covers nutrient presets, IPM presets, EC ramp curves, Irrigation Recipes and
Programs, and the strain library.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import logging
from typing import TYPE_CHECKING, Any

from custom_components.growspace_manager.const import (
    ATTR_GROWSPACE_ID,
    ATTR_ITEMS,
    ATTR_MIN_DAYS_IN_STAGE,
    ATTR_NAME,
    ATTR_NOTES,
    ATTR_PLANT_IDS,
    ATTR_PRESET_ID,
    ATTR_STAGE,
    ATTR_TYPE,
    GrowspaceService,
    IrrigationRecipeKind,
)
from custom_components.growspace_manager.models import (
    ECRampCurve,
    IPMPreset,
    IrrigationProgram,
    IrrigationRecipe,
    NutrientPreset,
)
from custom_components.growspace_manager.schemas import (
    APPLY_IPM_SCHEMA,
    REMOVE_IPM_PRESET_SCHEMA,
    SAVE_IPM_PRESET_SCHEMA,
)
from homeassistant.core import HomeAssistant, ServiceCall

from ._definition import ServiceDefinition
from .utils import handle_service_errors

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
        return self._coordinator._strain_library

    def get_strain_options(self) -> list[str]:
        """Return a sorted list of unique strain names."""
        if not self._coordinator._strain_library:
            return []
        return sorted(self._coordinator._strain_library.get_all().keys())

    def export_strain_library(self) -> list[str]:
        """Export all strains from the library."""
        return self.get_strain_options()

    async def clear_strains(self) -> int:
        """Remove all strains from the library."""
        if not self._coordinator._strain_library:
            return 0
        return await self._coordinator._strain_library.clear()

    # -------------------------------------------------------------------------
    # EC ramp curves
    # -------------------------------------------------------------------------

    @property
    def ec_ramp_curves(self) -> dict[str, Any]:
        """Return all EC ramp curves keyed by curve ID."""
        return self._coordinator._nutrient_manager.ec_ramp_curves

    async def save_ec_ramp_curve(
        self,
        growspace_id: str,
        name: str,
        stage: str,
        points: list[dict[str, Any]],
        curve_id: str | None = None,
    ) -> ECRampCurve:
        """Save one growspace's EC ramp curve for a stage.

        Every parameter is required and named exactly as the manager names it,
        and the manager is called **by keyword**. The signature previously ended
        in ``**kwargs`` and omitted ``stage`` entirely, so the handler's ``stage``
        was swallowed and dropped while the remaining arguments were passed
        positionally into a differing signature — every curve was stored corrupt
        (workspace#108). A mismatched call now raises ``TypeError``.
        """
        return await self._coordinator._nutrient_manager.async_save_ec_ramp_curve(
            growspace_id=growspace_id,
            name=name,
            stage=stage,
            points=points,
            curve_id=curve_id,
        )

    async def remove_ec_ramp_curve(self, curve_id: str) -> None:
        """Remove an EC ramp curve."""
        await self._coordinator._nutrient_manager.async_remove_ec_ramp_curve(curve_id)

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
        week: int = 1,
        ec_target: float | None = None,
        ph_target: float | None = None,
    ) -> NutrientPreset:
        """Create or update a nutrient preset."""
        return await self._coordinator._nutrient_manager.async_save_nutrient_preset(
            name,
            nutrients,
            stage,
            min_days_in_stage,
            preset_id,
            week,
            ec_target,
            ph_target,
        )

    async def remove_nutrient_preset(self, preset_id: str) -> None:
        """Remove a nutrient preset."""
        await self._coordinator._nutrient_manager.async_remove_nutrient_preset(
            preset_id
        )

    def get_applicable_presets(self, plant_id: str) -> list[NutrientPreset]:
        """Return all nutrient presets applicable to a plant."""
        return self._coordinator._nutrient_manager.get_applicable_presets(plant_id)

    def get_nutrient_serialization_data(self) -> dict[str, Any]:
        """Return serialized nutrient data for WebSocket consumers."""
        return self._coordinator._nutrient_manager.get_serialization_data()

    # -------------------------------------------------------------------------
    # Irrigation Recipes
    # -------------------------------------------------------------------------

    async def save_irrigation_recipe(
        self,
        growspace_id: str,
        name: str,
        kind: IrrigationRecipeKind,
        recipe_id: str | None = None,
    ) -> IrrigationRecipe:
        """Save a growspace's current irrigation settings as a named recipe."""
        return await self._coordinator._recipe_library.async_save_from_growspace(
            growspace_id, name, kind, recipe_id
        )

    async def update_irrigation_recipe(
        self,
        recipe_id: str,
        *,
        name: str | None = None,
        crop_steering: Mapping[str, Any] | None = None,
        schedule: Mapping[str, Any] | None = None,
    ) -> IrrigationRecipe:
        """Edit a stored recipe in place — rename it, correct its values."""
        return await self._coordinator._recipe_library.async_update_recipe(
            recipe_id, name=name, crop_steering=crop_steering, schedule=schedule
        )

    async def remove_irrigation_recipe(self, recipe_id: str) -> None:
        """Remove a recipe from the global Irrigation Recipe library."""
        await self._coordinator._recipe_library.async_remove_recipe(recipe_id)

    def find_irrigation_recipe(self, recipe_id: str) -> IrrigationRecipe | None:
        """Return one recipe by id, or None when the library has no such id.

        The forgiving lookup, for readers that must degrade rather than fail:
        deleting a recipe leaves references to it dangling by design, so a
        growspace can outlive the recipe it names (ADR-0045).
        """
        return self._coordinator._recipe_library.recipes.get(recipe_id)

    def get_irrigation_recipes(self) -> dict[str, dict[str, Any]]:
        """Return the serialized global Irrigation Recipe library.

        Global, so the answer does not depend on which growspace asked.
        """
        return self._coordinator._recipe_library.serialized_recipes()

    # -------------------------------------------------------------------------
    # Irrigation Programs
    # -------------------------------------------------------------------------

    async def save_irrigation_program(
        self,
        name: str,
        slots: Iterable[Mapping[str, Any]],
        program_id: str | None = None,
    ) -> IrrigationProgram:
        """Save a named plan of ``(stage, week)`` slots."""
        return await self._coordinator._program_library.async_save_program(
            name, slots, program_id
        )

    async def remove_irrigation_program(self, program_id: str) -> None:
        """Remove a program from the global Irrigation Program library."""
        await self._coordinator._program_library.async_remove_program(program_id)

    def find_irrigation_program(self, program_id: str) -> IrrigationProgram | None:
        """Return one program by id, or None when the library has no such id.

        The forgiving lookup, for readers that must degrade rather than fail:
        removing a program leaves a growspace's binding dangling by design, so
        a growspace can outlive the program it names (ADR-0045).
        """
        return self._coordinator._program_library.programs.get(program_id)

    def get_irrigation_programs(self) -> dict[str, dict[str, Any]]:
        """Return the serialized global Irrigation Program library.

        Global, so the answer does not depend on which growspace asked.
        """
        return self._coordinator._program_library.serialized_programs()

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

    # -------------------------------------------------------------------------
    # Nutrient inventory
    # -------------------------------------------------------------------------

    def get_inventory(self) -> Any | None:
        """Return the current nutrient inventory, or None if not configured."""
        svc = self._coordinator._nutrient_manager.inventory_service
        if svc is None:
            return None
        return svc.get_inventory()

    def update_stock(self, **kwargs: Any) -> None:
        """Update or create a nutrient stock entry."""
        svc = self._coordinator._nutrient_manager.inventory_service
        if svc is None:
            return
        svc.update_stock(**kwargs)

    def remove_stock(self, nutrient_id: str) -> None:
        """Remove a nutrient stock entry."""
        svc = self._coordinator._nutrient_manager.inventory_service
        if svc is None:
            return
        svc.remove_stock(nutrient_id)

    # -------------------------------------------------------------------------
    # Service call adapters
    # -------------------------------------------------------------------------

    @handle_service_errors
    async def save_ipm_preset_from_call(
        self, hass: HomeAssistant, call: ServiceCall
    ) -> None:
        """Unpack a save_ipm_preset ServiceCall and delegate to save_ipm_preset."""
        await self.save_ipm_preset(
            name=call.data[ATTR_NAME],
            preset_type=call.data[ATTR_TYPE],
            items=call.data[ATTR_ITEMS],
            stage=call.data.get(ATTR_STAGE),
            min_days_in_stage=call.data.get(ATTR_MIN_DAYS_IN_STAGE),
            preset_id=call.data.get(ATTR_PRESET_ID),
        )

    @handle_service_errors
    async def remove_ipm_preset_from_call(
        self, hass: HomeAssistant, call: ServiceCall
    ) -> None:
        """Unpack a remove_ipm_preset ServiceCall and delegate to remove_ipm_preset."""
        await self.remove_ipm_preset(call.data[ATTR_PRESET_ID])

    @handle_service_errors
    async def apply_ipm_from_call(self, hass: HomeAssistant, call: ServiceCall) -> None:
        """Unpack an apply_ipm ServiceCall and delegate to PlantFacade.apply_ipm."""
        await self._coordinator.services.plants.apply_ipm(
            preset_id=call.data[ATTR_PRESET_ID],
            growspace_id=call.data.get(ATTR_GROWSPACE_ID),
            plant_ids=call.data.get(ATTR_PLANT_IDS),
            notes=call.data.get(ATTR_NOTES),
        )


async def _handle_save_ipm_preset(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, call: ServiceCall
) -> None:
    await coordinator.services.config.save_ipm_preset_from_call(hass, call)


async def _handle_remove_ipm_preset(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, call: ServiceCall
) -> None:
    await coordinator.services.config.remove_ipm_preset_from_call(hass, call)


async def _handle_apply_ipm(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, call: ServiceCall
) -> None:
    await coordinator.services.config.apply_ipm_from_call(hass, call)


SERVICES: list[ServiceDefinition] = [
    ServiceDefinition(
        GrowspaceService.SAVE_IPM_PRESET,
        _handle_save_ipm_preset,
        SAVE_IPM_PRESET_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.REMOVE_IPM_PRESET,
        _handle_remove_ipm_preset,
        REMOVE_IPM_PRESET_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.APPLY_IPM,
        _handle_apply_ipm,
        APPLY_IPM_SCHEMA,
    ),
]
