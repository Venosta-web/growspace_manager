"""Growspace Manager."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging
from typing import TYPE_CHECKING, Any
import uuid

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.util import slugify

from ..const import (
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
from ..events import (
    EVENT_GROWSPACE_ADDED,
    EVENT_GROWSPACE_REMOVED,
    EVENT_GROWSPACE_UPDATED,
    async_fire_growspace_event,
)
from ..exceptions import GrowspaceNotFoundError
from ..models import EnvironmentConfig, Growspace, GrowspaceType, Subarea
from ..view_model_builder import ViewModelBuilder

if TYPE_CHECKING:
    from ..data_access.growspace_repository import GrowspaceRepository
    from ..data_access.notification_state import NotificationState
    from ..growspace_validator import GrowspaceValidator

_LOGGER = logging.getLogger(__name__)


class GrowspaceManager:
    """Handles all growspace CRUD operations and management logic."""

    def __init__(
        self,
        hass: HomeAssistant,
        repository: GrowspaceRepository,
        notification_state: NotificationState,
        validator: GrowspaceValidator,
        view_model_builder: ViewModelBuilder,
        save_callback: Callable[[], Awaitable[None]],
        lock: asyncio.Lock,
    ) -> None:
        """Initialize the growspace manager."""
        self.hass = hass
        self.repository = repository
        self.notification_state = notification_state
        self.validator = validator
        self.view_model_builder = view_model_builder
        self.save_callback = save_callback
        self.lock = lock
        self.cache: Any = None  # To be injected if needed

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
        """Add a new growspace."""
        async with self.lock:
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

            if dimensions is not None:
                growspace_kwargs["dimensions"] = dimensions
            if environment_config is not None:
                growspace_kwargs["environment_config"] = environment_config
            if irrigation_config is not None:
                growspace_kwargs["irrigation_config"] = irrigation_config

            growspace = Growspace.from_dict(growspace_kwargs)
            self.repository.add_growspace(growspace)

            # Enable notifications by default for new growspace
            self.notification_state.enabled[growspace_id] = True

            await self.save_callback()

            # Delegate device registration to here or keep in coordinator?
            # Original service didn't do device registry. Coordinator did.
            # I will keep it pure for now to match the service, and maybe move
            # device registration logic here later or let coordinator handle it
            # to decouple Manager from HA specifics like Device Registry?
            # Actually, `remove_growspace` DOES handle device registry removal (lines 173-182 in service).
            # So `add_growspace` SHOULD probably handle device registry creation too for symmetry.
            # But `add_growspace` in service DID NOT have `device_registry` logic.
            # I will keep it as is (matching Service) for step 1 of refactor.

            async_fire_growspace_event(self.hass, EVENT_GROWSPACE_ADDED, growspace)
            return growspace

    async def remove_growspace(self, growspace_id: str) -> None:
        """Remove a growspace and all plants contained within it."""
        async with self.lock:
            self.validator.validate_growspace_exists(growspace_id)

            # Remove all plants in this growspace
            plants_to_remove = [
                p.plant_id for p in self.repository.get_growspace_plants(growspace_id)
            ]

            for plant_id in plants_to_remove:
                self.repository.remove_plant(plant_id)
                self.notification_state.sent.pop(plant_id, None)

            growspace = self.repository.require_growspace(growspace_id)
            growspace_name = growspace.name
            self.repository.remove_growspace(growspace_id)

            # Remove notification state
            self.notification_state.enabled.pop(growspace_id, None)

            # Remove device from registry
            try:
                dev_reg = dr.async_get(self.hass)
                device = dev_reg.async_get_device(identifiers={(DOMAIN, growspace_id)})
                if device:
                    dev_reg.async_remove_device(device.id)
                    _LOGGER.debug("Removed device for growspace %s", growspace_id)
            except Exception:
                _LOGGER.exception(
                    "Error removing device for growspace %s", growspace_id
                )

            await self.save_callback()

            _LOGGER.info(
                "Removed growspace %s (%s) and %d plants",
                growspace_id,
                growspace_name,
                len(plants_to_remove),
            )
            async_fire_growspace_event(self.hass, EVENT_GROWSPACE_REMOVED, growspace)

    async def update_growspace(
        self, growspace_id: str, **kwargs: dict[str, Any]
    ) -> Growspace:
        """Update a growspace."""
        async with self.lock:
            if not self.repository.has_growspace(growspace_id):
                raise GrowspaceNotFoundError(f"Growspace {growspace_id} not found")

            growspace = self.repository.require_growspace(growspace_id)
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

                await self.save_callback()
                async_fire_growspace_event(
                    self.hass, EVENT_GROWSPACE_UPDATED, growspace
                )
            else:
                _LOGGER.debug("No changes detected for growspace %s", growspace_id)

            return growspace

    async def add_subarea(self, growspace_id: str, name: str) -> Subarea:
        """Add a named subarea to a growspace."""
        async with self.lock:
            if not self.repository.has_growspace(growspace_id):
                raise GrowspaceNotFoundError(f"Growspace {growspace_id} not found")
            subarea = Subarea(id=str(uuid.uuid4()), name=name.strip())
            self.repository.require_growspace(growspace_id).subareas.append(subarea)
            await self.save_callback()
            return subarea

    async def update_subarea(
        self, growspace_id: str, subarea_id: str, environment_config: dict[str, Any]
    ) -> Subarea:
        """Update a subarea's environment config."""
        async with self.lock:
            if not self.repository.has_growspace(growspace_id):
                raise GrowspaceNotFoundError(f"Growspace {growspace_id} not found")
            growspace = self.repository.require_growspace(growspace_id)
            subarea = next((s for s in growspace.subareas if s.id == subarea_id), None)
            if not subarea:
                raise ServiceValidationError(f"Subarea {subarea_id} not found")
            subarea.environment_config = EnvironmentConfig.from_dict(environment_config)
            await self.save_callback()
            return subarea

    async def remove_subarea(self, growspace_id: str, subarea_id: str) -> None:
        """Remove a subarea from a growspace."""
        async with self.lock:
            if not self.repository.has_growspace(growspace_id):
                raise GrowspaceNotFoundError(f"Growspace {growspace_id} not found")
            growspace = self.repository.require_growspace(growspace_id)
            before = len(growspace.subareas)
            growspace.subareas = [s for s in growspace.subareas if s.id != subarea_id]
            if len(growspace.subareas) == before:
                raise ServiceValidationError(f"Subarea {subarea_id} not found")
            await self.save_callback()

    def get_subareas(self, growspace_id: str) -> list[Subarea]:
        """Return all subareas for a growspace."""
        if not self.repository.has_growspace(growspace_id):
            raise GrowspaceNotFoundError(f"Growspace {growspace_id} not found")
        return list(self.repository.require_growspace(growspace_id).subareas)

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
        """Log a warning if any plants are outside the new grid boundaries after a resize."""
        # Get all plants in this growspace
        plants_to_check = self.repository.get_growspace_plants(growspace_id)
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
        """Generate a unique growspace name."""
        existing_names = {gs.name.lower() for gs in self.repository.get_all_growspaces()}
        name = base_name
        counter = 1

        while name.lower() in existing_names:
            name = f"{base_name} {counter}"
            counter += 1

        return name

    def get_growspace_options(self) -> dict[str, str]:
        """Return growspaces for dropdown selection."""
        return self.repository.get_growspace_options()

    def get_sorted_growspace_options(self) -> list[tuple[str, str]]:
        """Return a sorted list of growspaces for dropdown selection."""
        return self.repository.get_sorted_growspace_options()

    def ensure_special_growspace(
        self,
        growspace_id: str,
        name: str,
        rows: int = DEFAULT_ROWS,
        plants_per_row: int = DEFAULT_PLANTS_PER_ROW,
        growspace_type: GrowspaceType = GrowspaceType.FLOWER,
        update_data: bool = True,
    ) -> str:
        """Ensure a special growspace (e.g., 'dry', 'cure') exists."""
        canonical_id = growspace_id
        if growspace_id.lower() in ["dry", "drying"]:
            canonical_id = "dry"
        elif growspace_id.lower() in ["cure", "curing"]:
            canonical_id = "cure"
        elif growspace_id.lower() in ["mother", "mothers"]:
            canonical_id = "mother"
        elif growspace_id.lower() in ["clone", "clones"]:
            canonical_id = "clone"
        elif growspace_id.lower() in ["veg", "vegetative"]:
            canonical_id = "veg"

        if not self.repository.has_growspace(canonical_id):
            self._create_special_growspace(
                canonical_id, name, rows, plants_per_row, growspace_type
            )
            self.notification_state.enabled[canonical_id] = True
            if self.cache:
                self.cache.invalidate(canonical_id)
        else:
            self._update_special_growspace_name(canonical_id, name)
            gs = self.repository.require_growspace(canonical_id)
            if gs.growspace_type != growspace_type:
                gs.growspace_type = growspace_type
            if self.cache:
                self.cache.invalidate(canonical_id)

        return canonical_id

    def _create_special_growspace(
        self,
        canonical_id: str,
        canonical_name: str,
        rows: int,
        plants_per_row: int,
        growspace_type: GrowspaceType,
    ) -> None:
        """Create a new special growspace."""
        self.repository.add_growspace(Growspace(
            id=canonical_id,
            name=canonical_name,
            rows=rows,
            plants_per_row=plants_per_row,
            growspace_type=growspace_type,
        ))
        _LOGGER.info(
            "Created canonical growspace: %s with name '%s'",
            canonical_id,
            canonical_name,
        )

    def _update_special_growspace_name(
        self, canonical_id: str, canonical_name: str
    ) -> None:
        """Update the name of an existing special growspace."""
        if not self.repository.has_growspace(canonical_id):
            _LOGGER.debug(
                "Special growspace %s not found, skipping name update", canonical_id
            )
            return
        existing = self.repository.require_growspace(canonical_id)
        if existing.name != canonical_name:
            existing.name = canonical_name
            _LOGGER.info(
                "Updated growspace name: %s -> '%s'", canonical_id, canonical_name
            )

    def ensure_mother_growspace(self) -> str:
        """Ensure the 'mother' growspace exists."""
        return self.ensure_special_growspace(
            PlantStage.MOTHER,
            "mother",
            rows=DEFAULT_ROWS,
            plants_per_row=DEFAULT_PLANTS_PER_ROW,
            growspace_type=GrowspaceType.MOTHER,
        )

    async def ensure_default_growspaces(self) -> None:
        """Ensure that the default special growspaces exist."""
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
            self.ensure_special_growspace(
                growspace_id,
                name,
                rows,
                plants_per_row,
                growspace_type=gs_type,
                update_data=False,
            )

        if self.view_model_builder is not None:
            self.view_model_builder.build_data_property()

    def ensure_calculated_sensors(self) -> None:
        """Ensure default calculated sensors are configured."""
        for growspace in self.repository.get_all_growspaces():
            env_config = growspace.environment_config
            if not env_config:
                continue

            updated = False
            temps = env_config.temperature_sensors
            hums = env_config.humidity_sensors
            vpds = env_config.vpd_sensors

            if not temps and env_config.temperature_sensor:
                temps = [env_config.temperature_sensor]
                updated = True
            if not hums and env_config.humidity_sensor:
                hums = [env_config.humidity_sensor]
                updated = True
            if not vpds and env_config.vpd_sensor:
                vpds = [env_config.vpd_sensor]
                updated = True

            num_pairs = min(len(temps), len(hums))
            if num_pairs == 0:
                continue

            while len(vpds) < num_pairs:
                vpds.append(None)

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
                if len(vpds) > 0:
                    env_config.vpd_sensor = vpds[0]
                if self.cache:
                    self.cache.invalidate(growspace.id)

    def get_canonical_special(self, gs_id: str) -> tuple[str, str]:
        """Return the canonical ID and name for a special growspace.

        This helps resolve handling linked entities or names for special growspaces.

        Args:
            gs_id: The growspace ID to look up.

        Returns:
            A tuple containing the canonical ID and canonical name.
        """
        if gs_id in {"dry", "dry_room"}:
            return "dry", "Dry Room"
        if gs_id in {"cure", "cure_room"}:
            return "cure", "Cure Room"
        if gs_id in {"clone", "clone_room"}:
            return "clone", "Clone Room"
        if gs_id in {"mother", "mother_room"}:
            return "mother", "Mother Room"
        growspace = self.repository.get_growspace(gs_id)
        if growspace:
            return gs_id, growspace.name
        return gs_id, gs_id

    # Aliases for compatibility
    async def async_add_growspace(self, *args: Any, **kwargs: Any) -> Growspace:
        """Alias for add_growspace."""
        return await self.add_growspace(*args, **kwargs)

    async def async_remove_growspace(self, growspace_id: str) -> None:
        """Alias for remove_growspace."""
        await self.remove_growspace(growspace_id)

    async def async_update_growspace(self, *args: Any, **kwargs: Any) -> Growspace:
        """Alias for update_growspace."""
        return await self.update_growspace(*args, **kwargs)

    async def async_log_drain_reading(
        self,
        growspace_id: str,
        feed_ec: float,
        drain_ec: float,
        drain_volume_ml: float | None = None,
        feed_volume_ml: float | None = None,
    ) -> None:
        """Log a drain EC reading for a growspace."""
        from homeassistant.util import dt as dt_util
        from ..models import DrainReading

        growspace = self.repository.get_growspace(growspace_id)
        if not growspace:
            raise GrowspaceNotFoundError(growspace_id)

        reading = DrainReading(
            timestamp=dt_util.now().isoformat(),
            feed_ec=feed_ec,
            drain_ec=drain_ec,
            drain_volume_ml=drain_volume_ml,
            feed_volume_ml=feed_volume_ml,
        )

        drain_config = growspace.drain_config
        drain_config.readings.append(reading)

        # Enforce rolling window
        if len(drain_config.readings) > drain_config.max_readings:
            drain_config.readings = drain_config.readings[-drain_config.max_readings :]

        await self.save_callback()

        # Fire alert if drain EC delta exceeds threshold
        ec_delta = drain_ec - feed_ec
        if drain_config.enabled and ec_delta > drain_config.max_ec_delta:
            _LOGGER.warning(
                "Drain EC alert for %s: drain=%.2f, feed=%.2f, delta=%.2f exceeds threshold %.2f",
                growspace_id,
                drain_ec,
                feed_ec,
                ec_delta,
                drain_config.max_ec_delta,
            )
            # Use notification manager if available on coordinator
            # GrowspaceManager doesn't have direct access to notification manager,
            # but it has hass. We'll use the coordinator via a weakref or just pass it in?
            # Actually, coordinator is not in GrowspaceManager.
            # But we can fire an event.
            self.hass.bus.async_fire(
                "growspace_manager_drain_ec_alert",
                {
                    "growspace_id": growspace_id,
                    "growspace_name": growspace.name,
                    "ec_delta": ec_delta,
                    "drain_ec": drain_ec,
                    "feed_ec": feed_ec,
                    "threshold": drain_config.max_ec_delta,
                },
            )

    async def async_configure_drain_monitoring(
        self,
        growspace_id: str,
        enabled: bool | None = None,
        max_ec_delta: float | None = None,
        target_runoff_percent: float | None = None,
    ) -> None:
        """Configure drain EC monitoring settings for a growspace."""
        growspace = self.repository.get_growspace(growspace_id)
        if not growspace:
            raise GrowspaceNotFoundError(growspace_id)

        drain_config = growspace.drain_config
        if enabled is not None:
            drain_config.enabled = enabled
        if max_ec_delta is not None:
            drain_config.max_ec_delta = max_ec_delta
        if target_runoff_percent is not None:
            drain_config.target_runoff_percent = target_runoff_percent

        await self.save_callback()

    async def async_reset_water_tracking(self, growspace_id: str) -> None:
        """Reset water usage counters for a growspace."""
        from homeassistant.util import dt as dt_util
        from ..models import WaterUsageData

        growspace = self.repository.get_growspace(growspace_id)
        if not growspace:
            raise GrowspaceNotFoundError(growspace_id)

        growspace.water_usage = WaterUsageData(
            cycle_start_date=dt_util.now().date().isoformat()
        )
        await self.save_callback()
        _LOGGER.info("Reset water tracking for growspace %s", growspace_id)

    async def async_configure_tank(
        self,
        growspace_id: str,
        tank_entity: str,
        *,
        volume_liters: float | None = None,
    ) -> None:
        """Update runtime configuration for an irrigation tank."""
        growspace = self.repository.get_growspace(growspace_id)
        if not growspace:
            raise GrowspaceNotFoundError(growspace_id)

        tank = next(
            (
                t
                for t in growspace.environment_config.irrigation_tanks
                if t.sensor_entity == tank_entity
            ),
            None,
        )
        if tank is None:
            return

        if volume_liters is not None:
            tank.volume_liters = volume_liters
            await self.save_callback()

    async def ensure_special_growspaces(self) -> None:
        """Alias for ensure_default_growspaces."""
        await self.ensure_default_growspaces()
