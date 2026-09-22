"""The global [[Irrigation Recipe]] library.

Recipes are global, exactly as nutrient presets are: one saved from any
growspace is listed from every other, because portability between tents is the
entire point of the object (ADR-0045). The library owns storage and identity;
``domain/irrigation_recipe.py`` owns what a recipe's contents mean.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
import logging
from typing import TYPE_CHECKING, Any
import uuid

from custom_components.growspace_manager.const import IrrigationRecipeKind
from custom_components.growspace_manager.domain.ec_state import resolve_feed_stage_week
from custom_components.growspace_manager.domain.irrigation_recipe import (
    RecipeCaptureError,
    RecipeEditError,
    capture_crop_steering,
    capture_provenance,
    capture_schedule,
    edit_recipe,
)
from custom_components.growspace_manager.domain.plant_metrics import count_live_plants
from custom_components.growspace_manager.exceptions import (
    EntityNotFoundError,
    GrowspaceNotFoundError,
)
from custom_components.growspace_manager.models.irrigation_recipe import (
    IrrigationRecipe,
)
import homeassistant.util.dt as dt_util

if TYPE_CHECKING:
    from custom_components.growspace_manager.data_access.growspace_repository import (
        GrowspaceRepository,
    )

_LOGGER = logging.getLogger(__name__)


class IrrigationRecipeLibrary:
    """Stores, lists and removes grower-authored Irrigation Recipes."""

    def __init__(
        self,
        repository: GrowspaceRepository,
        save_callback: Callable[[], Awaitable[None]],
    ) -> None:
        """Initialise the library over the shared repository."""
        self.repository = repository
        self.save_callback = save_callback
        self.recipes: dict[str, IrrigationRecipe] = {}

    def load_data(self, recipes: dict[str, IrrigationRecipe]) -> None:
        """Replace the library contents (called by StorageManager on load)."""
        self.recipes = recipes

    async def async_save_from_growspace(
        self,
        growspace_id: str,
        name: str,
        kind: IrrigationRecipeKind,
        recipe_id: str | None = None,
    ) -> IrrigationRecipe:
        """Capture one growspace's irrigation settings as a named recipe.

        The capture runs to completion before anything is stored, so a refused
        save — a Seconds Mode growspace missing the flow rate or pot volume its
        percent must be derived from — leaves no partial recipe behind.
        """
        growspace = self.repository.get_growspace(growspace_id)
        if growspace is None:
            raise GrowspaceNotFoundError(f"Growspace {growspace_id} not found")

        plants = self.repository.get_growspace_plants(growspace_id)
        strategy = growspace.irrigation_strategy
        config = growspace.irrigation_config
        stage, week = resolve_feed_stage_week(plants)

        crop_steering = None
        schedule = None
        if kind is IrrigationRecipeKind.CROP_STEERING:
            crop_steering = capture_crop_steering(
                strategy, config, live_plant_count=count_live_plants(plants)
            )
        else:
            schedule = capture_schedule(config)

        existing = self.recipes.get(recipe_id) if recipe_id else None
        recipe = IrrigationRecipe(
            id=recipe_id or str(uuid.uuid4()),
            name=name,
            kind=kind,
            provenance=capture_provenance(strategy, config, stage=stage, week=week),
            crop_steering=crop_steering,
            schedule=schedule,
            created_at=existing.created_at
            if existing is not None
            else dt_util.utcnow().isoformat(),
        )
        self.recipes[recipe.id] = recipe

        await self.save_callback()
        _LOGGER.info(
            "Saved %s irrigation recipe '%s' from growspace '%s' (id=%s)",
            kind.value,
            name,
            growspace_id,
            recipe.id,
        )
        return recipe

    def get_recipe(self, recipe_id: str) -> IrrigationRecipe:
        """Return one recipe by id.

        Recipes are held by reference everywhere they are used, so callers get
        the library's own object rather than a copy: editing a recipe is meant
        to be visible to everything pointing at it.

        Raises:
            EntityNotFoundError: when no recipe carries that id.
        """
        recipe = self.recipes.get(recipe_id)
        if recipe is None:
            raise EntityNotFoundError(f"Irrigation recipe '{recipe_id}' not found")
        return recipe

    async def async_update_recipe(
        self,
        recipe_id: str,
        *,
        name: str | None = None,
        crop_steering: Mapping[str, Any] | None = None,
        schedule: Mapping[str, Any] | None = None,
    ) -> IrrigationRecipe:
        """Edit one stored recipe in place — rename it, correct its values.

        The edit is validated in full by ``edit_recipe`` before anything is
        written, so a refusal leaves the library exactly as it was.

        The stored object is then mutated rather than replaced, because
        ``get_recipe`` hands out the library's own instance precisely so that
        editing a recipe is visible to everything pointing at it. Only the
        three fields an edit can reach are copied across; ``id``, ``kind``,
        ``created_at`` and the provenance are the same objects afterwards
        because nothing here can touch them.

        Editing changes no growspace. Applying a recipe is a by-value stamp
        (ADR-0045), so a growspace holds the numbers rather than a live link —
        which is exactly what makes a recipe safe to edit. What a grower does
        see afterwards is drift, because ``recipe_has_drifted`` re-resolves the
        recipe against the live fields and the growspace no longer holds what
        the recipe now says.

        Raises:
            EntityNotFoundError: when no recipe carries that id.
            RecipeEditError: when the payload cannot become an edit.
        """
        recipe = self.get_recipe(recipe_id)
        edited = edit_recipe(
            recipe, name=name, crop_steering=crop_steering, schedule=schedule
        )
        recipe.name = edited.name
        recipe.crop_steering = edited.crop_steering
        recipe.schedule = edited.schedule

        await self.save_callback()
        _LOGGER.info("Edited irrigation recipe '%s' (id=%s)", recipe.name, recipe_id)
        return recipe

    async def async_remove_recipe(self, recipe_id: str) -> None:
        """Remove a recipe from the library."""
        recipe = self.recipes.pop(recipe_id, None)
        if recipe is None:
            raise EntityNotFoundError(f"Irrigation recipe '{recipe_id}' not found")

        await self.save_callback()
        _LOGGER.info("Removed irrigation recipe '%s' (id=%s)", recipe.name, recipe_id)

    def serialized_recipes(self) -> dict[str, dict[str, Any]]:
        """Return the library keyed by recipe id, ready for the wire."""
        return {rid: recipe.to_dict() for rid, recipe in self.recipes.items()}

    def get_serialization_data(self) -> dict[str, Any]:
        """Return the library under the key the config document stores it at."""
        return {"irrigation_recipes": self.serialized_recipes()}


__all__ = ["IrrigationRecipeLibrary", "RecipeCaptureError", "RecipeEditError"]
