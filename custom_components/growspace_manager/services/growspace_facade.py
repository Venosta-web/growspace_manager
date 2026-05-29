"""Growspace sub-facade for the Growspace Manager integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from custom_components.growspace_manager.const import (
    ATTR_DRAIN_TIMES,
    ATTR_IRRIGATION_TIMES,
    DOMAIN,
    SPECIAL_GROWSPACES,
    VERSION,
)
from custom_components.growspace_manager.domain.stage_calculator import (
    determine_coordinator_stage,
)
from custom_components.growspace_manager.exceptions import GrowspaceNotFoundError
from custom_components.growspace_manager.models import (
    DrainReading,
    ECTargetRange,
    Growspace,
    IrrigationConfig,
    Subarea,
    WaterUsageData,
)
from custom_components.growspace_manager.tank_water_tracker import TankWaterTracker
from custom_components.growspace_manager.utils import (
    generate_growspace_overview_unique_id,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util, slugify

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


class GrowspaceFacade:
    """Facade for all growspace-level operations."""

    def __init__(self, coordinator: GrowspaceCoordinator) -> None:
        self._coordinator = coordinator
        self._tank_water_trackers: dict[str, dict[str, TankWaterTracker]] = {}

    # -------------------------------------------------------------------------
    # CRUD
    # -------------------------------------------------------------------------

    @property
    def growspaces(self) -> dict[str, Growspace]:
        """Return all growspaces keyed by ID."""
        return self._coordinator.growspaces

    def get_growspace(self, growspace_id: str) -> Growspace | None:
        """Return a growspace by ID."""
        return self._coordinator.data_repository.get_growspace(growspace_id)

    def get_all_growspaces(self) -> dict[str, Growspace]:
        """Return all growspaces keyed by ID."""
        return {gs.id: gs for gs in self._coordinator.data_repository.get_all_growspaces()}

    def get_sorted_growspace_options(self) -> list[tuple[str, str]]:
        """Return a sorted list of (growspace_id, name) tuples."""
        return self._coordinator.growspace_manager.get_sorted_growspace_options()

    def get_canonical_special(self, gs_id: str) -> tuple[str, str]:
        """Return the canonical ID and name for a special growspace."""
        return self._coordinator.growspace_manager.get_canonical_special(gs_id)

    async def add_growspace(self, **kwargs: Any) -> Growspace:
        """Add a new growspace and register its HA device."""
        growspace = await self._coordinator.growspace_manager.add_growspace(**kwargs)
        device_registry = dr.async_get(self._coordinator.hass)
        device_registry.async_get_or_create(
            config_entry_id=self._coordinator.config_entry.entry_id,
            identifiers={(DOMAIN, growspace.id)},
            name=growspace.name,
            model=growspace.growspace_type.value
            if growspace.growspace_type
            else "Growspace",
            manufacturer="Growspace Manager",
            sw_version=VERSION,
        )
        await self._coordinator.subsystem_manager.async_setup_growspace_sub_coordinators(
            growspace.id, growspace
        )
        _LOGGER.info("Added growspace %s (%s)", growspace.name, growspace.id)
        return growspace

    async def update_growspace(self, growspace_id: str, **kwargs: Any) -> Growspace:
        """Update an existing growspace and sync its HA device name if changed."""
        growspace = await self._coordinator.growspace_manager.update_growspace(
            growspace_id, **kwargs
        )
        if "name" in kwargs:
            device_registry = dr.async_get(self._coordinator.hass)
            if device := device_registry.async_get_device(
                identifiers={(DOMAIN, growspace_id)}
            ):
                device_registry.async_update_device(device.id, name=kwargs["name"])
        _LOGGER.info("Updated growspace %s", growspace_id)
        return growspace

    async def remove_growspace(self, growspace_id: str) -> None:
        """Remove a growspace."""
        await self._coordinator.growspace_manager.remove_growspace(growspace_id)

    def ensure_special_growspace(self, *args: Any, **kwargs: Any) -> Any:
        """Ensure a special growspace exists; delegates to GrowspaceManager."""
        return self._coordinator.growspace_manager.ensure_special_growspace(
            *args, **kwargs
        )

    # -------------------------------------------------------------------------
    # Subareas
    # -------------------------------------------------------------------------

    def get_subareas(self, growspace_id: str) -> list[Subarea]:
        """Return all subareas for a growspace."""
        return self._coordinator.growspace_manager.get_subareas(growspace_id)

    async def add_subarea(self, growspace_id: str, name: str) -> Any:
        """Add a named subarea to a growspace."""
        subarea = await self._coordinator.growspace_manager.add_subarea(
            growspace_id, name
        )
        _LOGGER.info("Added subarea %s to growspace %s", name, growspace_id)
        return subarea

    async def update_subarea(
        self, growspace_id: str, subarea_id: str, environment_config: dict[str, Any]
    ) -> Any:
        """Update a subarea's environment config."""
        result = await self._coordinator.growspace_manager.update_subarea(
            growspace_id, subarea_id, environment_config
        )
        _LOGGER.info("Updated subarea %s in growspace %s", subarea_id, growspace_id)
        return result

    async def remove_subarea(self, growspace_id: str, subarea_id: str) -> None:
        """Remove a subarea from a growspace."""
        await self._coordinator.growspace_manager.remove_subarea(
            growspace_id, subarea_id
        )
        _LOGGER.info("Removed subarea %s from growspace %s", subarea_id, growspace_id)

    # -------------------------------------------------------------------------
    # Plants query
    # -------------------------------------------------------------------------

    def get_growspace_plants(self, growspace_id: str) -> list[Any]:
        """Return all plants in a growspace."""
        return self._coordinator.data_repository.get_growspace_plants(growspace_id)

    def get_growspace_grid(self, growspace_id: str) -> list[list[str | None]]:
        """Return a 2D grid of plant IDs for a growspace."""
        return self._coordinator.data_repository.get_growspace_grid(growspace_id)

    # -------------------------------------------------------------------------
    # Lighting
    # -------------------------------------------------------------------------

    async def async_set_lighting_schedule(
        self,
        growspace_id: str,
        veg_hours: int,
        flower_hours: int,
        dli_veg: float | None = None,
    ) -> None:
        """Set the lighting schedule for a growspace."""
        if growspace_id not in self._coordinator.growspaces:
            raise ServiceValidationError(f"Growspace '{growspace_id}' not found")
        growspace = self._coordinator.growspaces[growspace_id]
        growspace.environment_config.veg_day_hours = int(veg_hours)
        growspace.environment_config.flower_day_hours = int(flower_hours)
        if dli_veg is not None:
            growspace.environment_config.dli_target_veg = float(dli_veg)
        await self._coordinator.async_commit()
        await self._coordinator.async_request_refresh()
        _LOGGER.info(
            "Lighting schedule updated for %s: Veg=%sh, Flower=%sh, DLI=%s",
            growspace.name,
            veg_hours,
            flower_hours,
            dli_veg,
        )

    async def set_lighting_schedule(
        self,
        growspace_id: str,
        veg_hours: int,
        flower_hours: int,
        dli_veg: float | None = None,
    ) -> None:
        """Compatibility alias for async_set_lighting_schedule."""
        await self.async_set_lighting_schedule(
            growspace_id, veg_hours, flower_hours, dli_veg
        )

    # -------------------------------------------------------------------------
    # Irrigation
    # -------------------------------------------------------------------------

    async def update_irrigation_config(
        self, growspace_id: str, user_input: dict[str, Any]
    ) -> None:
        """Update irrigation configuration for a growspace."""
        growspace = self._coordinator.growspaces.get(growspace_id)
        if not growspace:
            raise GrowspaceNotFoundError(f"Growspace {growspace_id} not found")
        if user_input.get("clear"):
            growspace.irrigation_config = IrrigationConfig()
            growspace.irrigation_strategy.enabled = False
            _LOGGER.info("Cleared irrigation config for %s", growspace_id)
            await self._coordinator.async_commit()
            return
        if "use_vwc_steering" in user_input:
            growspace.irrigation_strategy.enabled = bool(
                user_input.pop("use_vwc_steering")
            )
        updated_settings = {
            k: v
            for k, v in user_input.items()
            if k not in [ATTR_IRRIGATION_TIMES, ATTR_DRAIN_TIMES, "growspace_id_read_only"]
        }
        for pump_key in ("irrigation_pump_entity", "drain_pump_entity"):
            if pump_key in updated_settings and not updated_settings[pump_key]:
                updated_settings[pump_key] = None
        for k, v in updated_settings.items():
            if hasattr(growspace.irrigation_config, k):
                setattr(growspace.irrigation_config, k, v)
            elif hasattr(growspace.irrigation_strategy, k):
                setattr(growspace.irrigation_strategy, k, v)
        self._coordinator.cache.invalidate(growspace_id)
        await self._coordinator.async_commit()
        await self._coordinator.async_request_refresh()
        _LOGGER.info("Updated irrigation config for %s", growspace_id)

    async def set_irrigation_settings(
        self, growspace_id: str, settings: dict[str, Any]
    ) -> None:
        """Set irrigation settings for a growspace."""
        await self.update_irrigation_config(growspace_id, settings)

    async def set_irrigation_strategy(
        self, growspace_id: str, strategy: dict[str, Any]
    ) -> None:
        """Set irrigation strategy for a growspace."""
        await self.update_irrigation_config(growspace_id, strategy)

    async def set_ec_target_range(
        self,
        growspace_id: str,
        stage: str,
        feed_ec_min: float,
        feed_ec_max: float,
    ) -> None:
        """Upsert a feed EC target range for a specific stage."""
        growspace = self._coordinator.growspaces.get(growspace_id)
        if not growspace:
            raise GrowspaceNotFoundError(f"Growspace {growspace_id} not found")
        ranges = growspace.irrigation_config.ec_target_ranges
        for existing in ranges:
            if existing.stage == stage:
                existing.feed_ec_min = feed_ec_min
                existing.feed_ec_max = feed_ec_max
                break
        else:
            ranges.append(ECTargetRange(stage=stage, feed_ec_min=feed_ec_min, feed_ec_max=feed_ec_max))
        self._coordinator.cache.invalidate(growspace_id)
        await self._coordinator.async_commit()
        await self._coordinator.async_request_refresh()

    async def add_irrigation_schedule_item(
        self,
        growspace_id: str,
        schedule_key: str,
        time_str: str,
        duration_minutes: int | None = None,
    ) -> None:
        """Add a schedule item to a growspace."""
        irrigation_coord = await self._get_irrigation_coordinator(growspace_id)
        if duration_minutes is None:
            item_type = "irrigation" if "irrigation" in schedule_key.lower() else "drain"
            duration_minutes = irrigation_coord.get_default_duration(item_type)
        await irrigation_coord.async_add_schedule_item(
            schedule_key, time_str, duration_minutes
        )

    async def remove_irrigation_schedule_item(
        self, growspace_id: str, schedule_key: str, time_str: str
    ) -> None:
        """Remove a schedule item from a growspace."""
        irrigation_coord = await self._get_irrigation_coordinator(growspace_id)
        await irrigation_coord.async_remove_schedule_item(schedule_key, time_str)

    async def _get_irrigation_coordinator(self, growspace_id: str) -> Any:
        if growspace_id not in self._coordinator.irrigation_coordinators:
            growspace = self._coordinator.growspaces.get(growspace_id)
            if growspace:
                await self._coordinator.subsystem_manager.async_setup_growspace_sub_coordinators(
                    growspace_id, growspace
                )
            if growspace_id not in self._coordinator.irrigation_coordinators:
                raise ServiceValidationError(
                    f"Growspace '{growspace_id}' not found or has no irrigation setup."
                )
        return self._coordinator.irrigation_coordinators[growspace_id]

    async def water_growspace(
        self,
        growspace_id: str,
        amount_per_plant: float | None = None,
        nutrients: dict[str, float] | None = None,
        preset_id: str | None = None,
        amount: float | None = None,
    ) -> int:
        """Record a watering event for all plants in a growspace."""
        return await self._coordinator._watering_service.async_water_growspace(
            growspace_id, amount_per_plant, nutrients, preset_id, amount
        )

    # -------------------------------------------------------------------------
    # Drain and water tracking
    # -------------------------------------------------------------------------

    async def log_drain_reading(
        self,
        growspace_id: str,
        feed_ec: float,
        drain_ec: float,
        drain_volume_ml: float | None = None,
        feed_volume_ml: float | None = None,
    ) -> None:
        """Log a drain EC reading for a growspace."""
        growspace = self._coordinator.growspaces.get(growspace_id)
        if not growspace:
            raise ServiceValidationError(f"Growspace '{growspace_id}' not found")
        reading = DrainReading(
            timestamp=dt_util.now().isoformat(),
            feed_ec=feed_ec,
            drain_ec=drain_ec,
            drain_volume_ml=drain_volume_ml,
            feed_volume_ml=feed_volume_ml,
        )
        drain_config = growspace.drain_config
        drain_config.readings.append(reading)
        if len(drain_config.readings) > drain_config.max_readings:
            drain_config.readings = drain_config.readings[-drain_config.max_readings :]
        await self._coordinator.async_commit()
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
            await self._coordinator.notification_manager.async_send_notification(
                growspace_id,
                f"⚠️ High drain EC in {growspace.name}",
                f"Drain EC delta ({ec_delta:.2f}) exceeds threshold ({drain_config.max_ec_delta:.2f}).",
                tier="drain_ec",
            )

    async def configure_drain_monitoring(
        self,
        growspace_id: str,
        enabled: bool | None = None,
        max_ec_delta: float | None = None,
        target_runoff_percent: float | None = None,
    ) -> None:
        """Configure drain EC monitoring settings."""
        growspace = self._coordinator.growspaces.get(growspace_id)
        if not growspace:
            raise ServiceValidationError(f"Growspace '{growspace_id}' not found")
        drain_config = growspace.drain_config
        if enabled is not None:
            drain_config.enabled = enabled
        if max_ec_delta is not None:
            drain_config.max_ec_delta = max_ec_delta
        if target_runoff_percent is not None:
            drain_config.target_runoff_percent = target_runoff_percent
        await self._coordinator.async_commit()

    async def reset_water_tracking(self, growspace_id: str) -> None:
        """Reset water usage counters for a growspace."""
        growspace = self._coordinator.growspaces.get(growspace_id)
        if not growspace:
            raise ServiceValidationError(f"Growspace '{growspace_id}' not found")
        growspace.water_usage = WaterUsageData(
            cycle_start_date=dt_util.now().date().isoformat()
        )
        await self._coordinator.async_commit()
        _LOGGER.info("Reset water tracking for growspace %s", growspace_id)

    async def configure_tank(
        self,
        growspace_id: str,
        tank_entity: str,
        *,
        volume_liters: float | None = None,
    ) -> None:
        """Update runtime configuration for an irrigation tank."""
        growspace = self.get_growspace(growspace_id)
        if growspace is None:
            return
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
            await self._coordinator.async_commit()

    # -------------------------------------------------------------------------
    # Tank water trackers
    # -------------------------------------------------------------------------

    def get_tank_tracker(
        self, growspace_id: str, tank_entity: str
    ) -> TankWaterTracker | None:
        """Return the TankWaterTracker for a tank, or None if not configured."""
        growspace = self.get_growspace(growspace_id)
        if growspace is None:
            _LOGGER.debug("No growspace found for %s", growspace_id)
            return None
        tank = next(
            (
                t
                for t in growspace.environment_config.irrigation_tanks
                if t.sensor_entity == tank_entity
            ),
            None,
        )
        if tank is None:
            _LOGGER.debug(
                "No tank found for entity %s in growspace %s", tank_entity, growspace_id
            )
            return None
        if tank.volume_liters is None:
            _LOGGER.debug(
                "Tank %s in growspace %s has no volume defined",
                tank_entity,
                growspace_id,
            )
            return None
        gs_trackers = self._tank_water_trackers.setdefault(growspace_id, {})
        if tank_entity not in gs_trackers:
            _LOGGER.debug(
                "Creating new TankWaterTracker for %s in %s", tank_entity, growspace_id
            )

            def _stage_resolver(gid: str = growspace_id) -> str:
                plants = self.get_growspace_plants(gid)
                return determine_coordinator_stage(plants).value

            gs_trackers[tank_entity] = TankWaterTracker(tank, stage_resolver=_stage_resolver)
        return gs_trackers[tank_entity]

    def get_all_trackers_for_growspace(
        self, growspace_id: str
    ) -> dict[str, TankWaterTracker]:
        """Return all cached tank water trackers for a growspace."""
        return self._tank_water_trackers.get(growspace_id, {})

    async def async_unsubscribe_all_trackers(self) -> None:
        """Unsubscribe all tank water trackers on shutdown."""
        for gs_trackers in self._tank_water_trackers.values():
            for tracker in gs_trackers.values():
                await tracker.async_unsubscribe()
        self._tank_water_trackers.clear()

    # -------------------------------------------------------------------------
    # Payload and entity helpers
    # -------------------------------------------------------------------------

    def get_growspace_data(self, growspace_id: str | None = None) -> dict[str, Any]:
        """Return full data for a growspace (or all) for WebSocket consumers."""
        if growspace_id:
            if growspace_id not in self._coordinator.growspaces:
                return {}
            return self.build_growspace_payload(growspace_id)
        return {
            gid: self.build_growspace_payload(gid)
            for gid in self._coordinator.growspaces
        }

    def build_growspace_payload(self, growspace_id: str) -> dict[str, Any]:
        """Build the full JSON payload for a growspace."""
        return self._coordinator.view_model_builder.build_serialized_growspace(
            growspace_id
        )

    def guess_overview_entity_id(self, growspace_id: str) -> str:
        """Best-effort guess of the overview sensor entity ID for a growspace."""
        unique_id = generate_growspace_overview_unique_id(growspace_id)
        registry: er.EntityRegistry = er.async_get(self._coordinator.hass)
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
        if entity_id:
            return entity_id  # type: ignore[no-any-return]
        for special_def in SPECIAL_GROWSPACES.values():
            canonical_id = special_def["canonical_id"]
            if growspace_id == canonical_id or growspace_id in special_def.get(
                "aliases", []
            ):
                canonical_uid = generate_growspace_overview_unique_id(str(canonical_id))
                eid = registry.async_get_entity_id("sensor", DOMAIN, canonical_uid)
                if eid:
                    return eid
                return f"sensor.{canonical_id}"
        growspace = self.get_growspace(growspace_id)
        name = getattr(growspace, "name", growspace_id) if growspace else growspace_id
        slug = slugify(str(name).replace(" ", "_"))
        return f"sensor.{slug}"

    def handle_position_update(
        self,
        plant_id: str,
        plant: Any,
        force_position: bool,
        kwargs: dict[str, Any],
    ) -> None:
        """Validate and apply a plant position update."""
        new_row = kwargs.get("row")
        new_col = kwargs.get("col")
        if new_row is not None or new_col is not None:
            growspace_id = plant.growspace_id
            if new_row is None:
                new_row = plant.row
            if new_col is None:
                new_col = plant.col
            self._coordinator.validator.validate_position_bounds(
                growspace_id, new_row, new_col
            )
            if not force_position:
                self._coordinator.validator.validate_position_not_occupied(
                    growspace_id, new_row, new_col, plant_id
                )

    def validate_plants_after_growspace_resize(
        self, growspace_id: str, new_rows: int, new_plants_per_row: int
    ) -> None:
        """Trigger background validation of plants after resizing a growspace."""
        self._coordinator.config_entry.async_create_background_task(
            self._coordinator.hass,
            self._coordinator.growspace_manager._validate_plants_after_growspace_resize(  # noqa: SLF001
                growspace_id, new_rows, new_plants_per_row
            ),
            f"validate_plants_{growspace_id}",
        )

    async def update_options(self, options: dict[str, Any]) -> None:
        """Update integration options and save."""
        if hasattr(self._coordinator, "options"):
            self._coordinator.options.update(options)
        new_options = self._coordinator.config_entry.options.copy()
        new_options.update(options)
        self._coordinator.hass.config_entries.async_update_entry(
            self._coordinator.config_entry, options=new_options
        )
        await self._coordinator.async_commit()
        _LOGGER.info("Integration options updated: %s", options)
