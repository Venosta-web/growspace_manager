"""Growspace service for the Growspace Manager integration.

This service handles all growspace-related CRUD operations,
extracted from the coordinator to reduce complexity.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
import uuid

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

from custom_components.growspace_manager.const import (
    CANONICAL_ID_CLONE,
    CANONICAL_ID_CURE,
    CANONICAL_ID_DRY,
    CANONICAL_ID_MOTHER,
    CANONICAL_ID_VEG,
    DEFAULT_PLANTS_PER_ROW,
    DEFAULT_ROWS,
    DOMAIN,
    PlantStage,
)
from custom_components.growspace_manager.events import (
    EVENT_GROWSPACE_ADDED,
    EVENT_GROWSPACE_REMOVED,
    EVENT_GROWSPACE_UPDATED,
    async_fire_growspace_event,
)
from custom_components.growspace_manager.exceptions import GrowspaceNotFoundError
from custom_components.growspace_manager.models import Growspace, GrowspaceType
from homeassistant.helpers import device_registry as dr
from homeassistant.util import slugify

_LOGGER = logging.getLogger(__name__)


class GrowspaceService:
    """Handles all growspace CRUD operations."""

    def __init__(self, coordinator: GrowspaceCoordinator) -> None:
        """Initialize the growspace service.

        Args:
            coordinator: Reference to parent coordinator for accessing
                        shared resources.
        """
        self.coordinator = coordinator

    async def add_growspace(
        self,
        name: str,
        rows: int = DEFAULT_ROWS,
        plants_per_row: int = DEFAULT_PLANTS_PER_ROW,
        notification_target: str | None = None,
        device_id: str | None = None,
        growspace_type: GrowspaceType = GrowspaceType.FLOWER,
        dimensions: dict[str, Any] | None = None,
        environment_config: dict[str, Any] | None = None,
        irrigation_config: dict[str, Any] | None = None,
    ) -> Growspace:
        """Add a new growspace to the coordinator.

        Args:
            name: The display name for the new growspace.
            rows: The number of rows in the grid.
            plants_per_row: The number of plants per row.
            notification_target: The notification service to use (optional).
            device_id: The device ID to associate with the growspace (optional).
            growspace_type: The type of growspace.
            dimensions: Physical dimensions (optional).
            environment_config: Environment configuration (optional).
            irrigation_config: Irrigation configuration (optional).
        """
        async with self.coordinator.lock:
            # Normalize notification target
            if not notification_target or notification_target in ("None", "none", ""):
                _LOGGER.debug(
                    "No notification target provided for growspace '%s'", name
                )
                notification_target = None

            growspace_id = str(uuid.uuid4())

            # Build kwargs, omitting None values to let default factories work
            growspace_kwargs = {
                "id": growspace_id,
                "name": name.strip(),
                "rows": rows,
                "plants_per_row": plants_per_row,
                "notification_target": notification_target,
                "device_id": device_id,
                "growspace_type": growspace_type,
            }

            # Only add these if they're not None to preserve default factories
            if dimensions is not None:
                growspace_kwargs["dimensions"] = dimensions
            if environment_config is not None:
                growspace_kwargs["environment_config"] = environment_config
            if irrigation_config is not None:
                growspace_kwargs["irrigation_config"] = irrigation_config

            growspace = Growspace(**growspace_kwargs)
            self.coordinator.growspaces[growspace_id] = growspace

            # Enable notifications by default for new growspace
            self.coordinator.notifications_enabled[growspace_id] = True

            await self.coordinator.async_commit()

            async_fire_growspace_event(
                self.coordinator.hass, EVENT_GROWSPACE_ADDED, growspace
            )
            return growspace

    async def remove_growspace(self, growspace_id: str) -> None:
        """Remove a growspace and all plants contained within it.

        Args:
            growspace_id: The ID of the growspace to remove.
        """
        async with self.coordinator.lock:
            self.coordinator.validator.validate_growspace_exists(growspace_id)

            # Remove all plants in this growspace
            plants_to_remove = [
                plant_id
                for plant_id, plant in self.coordinator.plants.items()
                if plant.growspace_id == growspace_id
            ]

            for plant_id in plants_to_remove:
                self.coordinator.plants.pop(plant_id, None)
                self.coordinator.notifications_sent.pop(plant_id, None)

            growspace = self.coordinator.growspaces[growspace_id]
            growspace_name = growspace.name
            self.coordinator.growspaces.pop(growspace_id, None)

            # Remove notification state
            self.coordinator.notifications_enabled.pop(growspace_id, None)

            # Remove device from registry
            try:
                dev_reg = dr.async_get(self.coordinator.hass)
                device = dev_reg.async_get_device(identifiers={(DOMAIN, growspace_id)})
                if device:
                    dev_reg.async_remove_device(device.id)
                    _LOGGER.debug("Removed device for growspace %s", growspace_id)
            except Exception:
                _LOGGER.exception(
                    "Error removing device for growspace %s", growspace_id
                )

            await self.coordinator.async_commit()

            _LOGGER.info(
                "Removed growspace %s (%s) and %d plants",
                growspace_id,
                growspace_name,
                len(plants_to_remove),
            )
            async_fire_growspace_event(
                self.coordinator.hass, EVENT_GROWSPACE_REMOVED, growspace
            )

    async def update_growspace(
        self, growspace_id: str, **kwargs: dict[str, Any]
    ) -> None:
        """Update a growspace."""
        async with self.coordinator.lock:
            if growspace_id not in self.coordinator.growspaces:
                raise GrowspaceNotFoundError(f"Growspace {growspace_id} not found")

            growspace = self.coordinator.growspaces[growspace_id]
            changes: list[str] = []

            # Update structure
            struct_updated = self._update_growspace_structure(
                growspace, kwargs, changes
            )
            # Update config
            config_updated = self._update_growspace_config(growspace, kwargs, changes)

            updated = struct_updated or config_updated

            if updated:
                _LOGGER.info(
                    "Updated growspace %s (%s): %s",
                    growspace_id,
                    growspace.name,
                    ", ".join(changes),
                )

                # Validate plants if grid changed
                if "rows" in kwargs or "plants_per_row" in kwargs:
                    await self._validate_plants_after_growspace_resize(
                        growspace_id,
                        growspace.rows,
                        growspace.plants_per_row,
                    )

                await self.coordinator.async_commit()
                async_fire_growspace_event(
                    self.coordinator.hass, EVENT_GROWSPACE_UPDATED, growspace
                )
            else:
                _LOGGER.debug("No changes detected for growspace %s", growspace_id)

    def _update_growspace_structure(
        self, growspace: Growspace, kwargs: dict[str, Any], changes: list[str]
    ) -> bool:
        """Update growspace structure (dimensions)."""
        updated = False
        if "rows" in kwargs:
            rows = int(kwargs["rows"])
            if rows != growspace.rows:
                changes.append(f"rows: {growspace.rows} -> {rows}")
                growspace.rows = rows
                updated = True

        if "plants_per_row" in kwargs:
            ppr = int(kwargs["plants_per_row"])
            if ppr != growspace.plants_per_row:
                changes.append(f"plants_per_row: {growspace.plants_per_row} -> {ppr}")
                growspace.plants_per_row = ppr
                updated = True
        return updated

    def _update_growspace_config(
        self, growspace: Growspace, kwargs: dict[str, Any], changes: list[str]
    ) -> bool:
        """Update growspace configuration."""
        updated = False
        if "name" in kwargs:
            name = kwargs["name"]
            if name != growspace.name:
                changes.append(f"name: {growspace.name} -> {name}")
                growspace.name = name
                updated = True

        if "notification_target" in kwargs:
            nt = kwargs["notification_target"]
            nt = nt.strip() if nt else None
            current = growspace.notification_target
            if nt != current:
                changes.append(f"notification_target: {current} -> {nt}")
                growspace.notification_target = nt
                updated = True

        if "environment_config" in kwargs:
            growspace.environment_config = kwargs["environment_config"]
            changes.append("environment_config updated")
            updated = True

        if "irrigation_config" in kwargs:
            growspace.irrigation_config = kwargs["irrigation_config"]
            changes.append("irrigation_config updated")
            updated = True

        if "dimensions" in kwargs:
            growspace.dimensions = kwargs["dimensions"]
            changes.append("dimensions updated")
            updated = True

        return updated

    async def _validate_plants_after_growspace_resize(
        self, growspace_id: str, new_rows: int, new_plants_per_row: int
    ) -> None:
        """Log a warning if any plants are outside the new grid boundaries after a resize.

        Args:
            growspace_id: The ID of the growspace that was resized.
            new_rows: The new number of rows.
            new_plants_per_row: The new number of plants per row.
        """
        plants_to_check = self.coordinator.get_growspace_plants(growspace_id)
        invalid_plants = []

        invalid_plants = [
            plant
            for plant in plants_to_check
            if int(plant.row) > new_rows or int(plant.col) > new_plants_per_row
        ]

        if invalid_plants:
            _LOGGER.warning(
                "Growspace %s resized to %dx%d. Found %d plants outside new grid boundaries:",
                growspace_id,
                new_rows,
                new_plants_per_row,
                len(invalid_plants),
            )

            for plant in invalid_plants:
                _LOGGER.warning(
                    "  - Plant %s (%s) at position (%d,%d) is outside new grid",
                    plant.plant_id,
                    plant.strain,
                    plant.row,
                    plant.col,
                )

    def generate_unique_name(self, base_name: str) -> str:
        """Generate a unique growspace name by appending a counter if necessary.

        Args:
            base_name: The desired base name for the growspace.

        Returns:
            A unique name that does not conflict with existing growspace names.
        """
        existing_names = {
            gs.name.lower() for gs in self.coordinator.growspaces.values()
        }
        name = base_name
        counter = 1

        while name.lower() in existing_names:
            name = f"{base_name} {counter}"
            counter += 1

        return name

    def get_growspace_options(self) -> dict[str, str]:
        """Return growspaces for dropdown selection in the editor.

        Returns:
            A dictionary mapping growspace IDs to growspace names.
        """
        return {
            gs_id: getattr(gs, "name", gs_id)
            for gs_id, gs in self.coordinator.growspaces.items()
        }

    def get_sorted_growspace_options(self) -> list[tuple[str, str]]:
        """Return a sorted list of growspaces for dropdown selection.

        The list is sorted alphabetically by growspace name.

        Returns:
            A list of tuples, where each tuple contains a growspace ID and name.
        """
        return sorted(
            (
                (gs_id, getattr(gs, "name", gs_id))
                for gs_id, gs in self.coordinator.growspaces.items()
            ),
            key=lambda x: x[1].lower(),
        )

    def ensure_special_growspace(
        self,
        growspace_id: str,
        name: str,
        rows: int = DEFAULT_ROWS,
        plants_per_row: int = DEFAULT_PLANTS_PER_ROW,
        growspace_type: GrowspaceType = GrowspaceType.FLOWER,
        update_data: bool = True,
    ) -> str:
        """Ensure a special growspace (e.g., 'dry', 'cure') exists.

        If the growspace does not exist, it will be created with the specified
        parameters. This method also handles migration from legacy aliases.

        Args:
            growspace_id: The canonical ID for the special growspace.
            name: The canonical name for the special growspace.
            rows: The number of rows for the grid (if created).
            plants_per_row: The number of plants per row (if created).
            growspace_type: The type of growspace.
            update_data: Whether to update the data property after changes.

        Returns:
            The canonical ID of the special growspace.
        """
        # Get canonical form
        canonical_id, _ = self.coordinator.canonical_special(growspace_id)

        # Create or update the canonical growspace
        if canonical_id not in self.coordinator.growspaces:
            self._create_special_growspace(
                canonical_id, name, rows, plants_per_row, growspace_type
            )
            # Enable notifications by default for new special growspace
            self.coordinator.notifications_enabled[canonical_id] = True
            # Cache invalidation for new space
            self.coordinator.cache.invalidate(canonical_id)
        else:
            self._update_special_growspace_name(canonical_id, name)
            # Ensure type is correct even if existing (for migration)
            start_type = self.coordinator.growspaces[canonical_id].growspace_type
            if start_type != growspace_type:
                self.coordinator.growspaces[
                    canonical_id
                ].growspace_type = growspace_type
            # Name or Type changed -> Invalidate
            self.coordinator.cache.invalidate(canonical_id)

        if update_data:
            self.coordinator.data = (
                self.coordinator.view_model_builder.build_data_property()
            )
        return canonical_id

    def _create_special_growspace(
        self,
        canonical_id: str,
        canonical_name: str,
        rows: int,
        plants_per_row: int,
        growspace_type: GrowspaceType,
    ) -> None:
        """Create a new special growspace with the given parameters."""
        self.coordinator.growspaces[canonical_id] = Growspace(
            id=canonical_id,
            name=canonical_name,
            rows=rows,
            plants_per_row=plants_per_row,
            growspace_type=growspace_type,
        )
        _LOGGER.info(
            "Created canonical growspace: %s with name '%s'",
            canonical_id,
            canonical_name,
        )

    def _update_special_growspace_name(
        self, canonical_id: str, canonical_name: str
    ) -> None:
        """Update the name of an existing special growspace if it has changed."""
        existing = self.coordinator.growspaces[canonical_id]
        if existing.name != canonical_name:
            existing.name = canonical_name
            _LOGGER.info(
                "Updated growspace name: %s -> '%s'", canonical_id, canonical_name
            )

    def ensure_mother_growspace(self) -> str:
        """Ensure the 'mother' growspace exists, creating it if necessary.

        Returns:
            The ID of the mother growspace.
        """
        return self.ensure_special_growspace(
            PlantStage.MOTHER,
            "mother",
            rows=DEFAULT_ROWS,
            plants_per_row=DEFAULT_PLANTS_PER_ROW,
            growspace_type=GrowspaceType.MOTHER,
        )

    # =========================================================================
    # INITIALIZATION METHODS
    # =========================================================================

    async def ensure_default_growspaces(self) -> None:
        """Ensure that the default special growspaces (dry, cure, etc.) exist.

        Creates standard growspaces if they don't already exist:
        - dry, cure, mother, clone, veg
        """
        default_growspaces = [
            (
                CANONICAL_ID_DRY,
                "dry",
                DEFAULT_ROWS,
                DEFAULT_PLANTS_PER_ROW,
                GrowspaceType.DRY,
            ),
            (
                CANONICAL_ID_CURE,
                "cure",
                DEFAULT_ROWS,
                DEFAULT_PLANTS_PER_ROW,
                GrowspaceType.CURE,
            ),
            (
                CANONICAL_ID_MOTHER,
                "mother",
                DEFAULT_ROWS,
                DEFAULT_PLANTS_PER_ROW,
                GrowspaceType.MOTHER,
            ),
            (CANONICAL_ID_CLONE, "clone", 5, 5, GrowspaceType.CLONE),
            (CANONICAL_ID_VEG, "veg", 5, 5, GrowspaceType.VEG),
        ]

        for (
            growspace_id,
            name,
            rows,
            plants_per_row,
            gs_type,
        ) in default_growspaces:
            # Use the coordinator's method to ensure special growspaces
            self.ensure_special_growspace(
                growspace_id,
                name,
                rows,
                plants_per_row,
                growspace_type=gs_type,
                update_data=False,
            )

        self.coordinator.data = (
            self.coordinator.view_model_builder.build_data_property()
        )

    def ensure_calculated_sensors(self) -> None:
        """Ensure default calculated sensors are configured in growspace config.

        Automatically configures VPD sensors for growspaces that have
        temperature and humidity sensors but no VPD sensor configured.
        """

        for growspace in list(self.coordinator.growspaces.values()):
            env_config = growspace.environment_config
            if not env_config:
                continue

            # Work with plural lists
            temps = env_config.temperature_sensors
            hums = env_config.humidity_sensors
            vpds = env_config.vpd_sensors

            # Sync lengths if necessary (though migration should have handled it)
            if not temps and env_config.temperature_sensor:
                temps = [env_config.temperature_sensor]
            if not hums and env_config.humidity_sensor:
                hums = [env_config.humidity_sensor]
            if not vpds and env_config.vpd_sensor:
                vpds = [env_config.vpd_sensor]

            num_pairs = min(len(temps), len(hums))
            if num_pairs == 0:
                continue

            # Ensure vpd_sensors list is at least long enough
            # We don't want to overwrite explicitly configured sensors, so we pad with None
            while len(vpds) < num_pairs:
                vpds.append(None)

            updated = False
            for i in range(num_pairs):
                if (
                    temps[i]
                    and hums[i]
                    and (vpds[i] is None or "calculated_vpd" in vpds[i])
                ):
                    suffix = f" {i + 1}" if num_pairs > 1 else ""
                    calc_name = f"{growspace.name} Calculated VPD{suffix}"
                    expected_id = f"sensor.{slugify(calc_name)}"

                    if vpds[i] != expected_id:
                        vpds[i] = expected_id
                        updated = True
                        _LOGGER.info(
                            "Configured calculated VPD for %s (index %d)",
                            growspace.name,
                            i,
                        )

            if updated:
                env_config.vpd_sensors = vpds
                # Also update singular for backward compat if it was the first one
                if len(vpds) > 0:
                    env_config.vpd_sensor = vpds[0]

                # Config changed
                self.coordinator.cache.invalidate(growspace.id)
