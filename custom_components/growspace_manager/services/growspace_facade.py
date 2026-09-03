"""Growspace sub-facade for the Growspace Manager integration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from custom_components.growspace_manager.const import (
    ATTR_GROWSPACE_ID,
    ATTR_IMAGES,
    ATTR_NAME,
    ATTR_NOTES,
    ATTR_NOTIFICATION_TARGET,
    ATTR_PLANTS_PER_ROW,
    ATTR_ROWS,
    CATEGORY_NOTE,
    DOMAIN,
    EVENT_GROWSPACE_LOG_ENTRY,
    SPECIAL_GROWSPACES,
    VERSION,
    GrowspaceService,
    SteeringMode,
)
from custom_components.growspace_manager.domain.ec_state import record_drain_reading
from custom_components.growspace_manager.domain.irrigation_recipe import (
    resolve_recipe_application,
)
from custom_components.growspace_manager.domain.plant_metrics import count_live_plants
from custom_components.growspace_manager.domain.stage import StageDays
from custom_components.growspace_manager.domain.stage_calculator import (
    determine_coordinator_stage,
)
from custom_components.growspace_manager.exceptions import (
    GrowspaceError,
    GrowspaceNotFoundError,
)
from custom_components.growspace_manager.models import (
    ECTargetRange,
    Growspace,
    Subarea,
    WaterUsageData,
)
from custom_components.growspace_manager.schemas import (
    ADD_GROWSPACE_SCHEMA,
    REMOVE_GROWSPACE_SCHEMA,
    UPDATE_GROWSPACE_SCHEMA,
)
from custom_components.growspace_manager.services.strategy_stamp import (
    StrategyStamp,
    async_apply_strategy_stamp,
)
from custom_components.growspace_manager.strain_library import StrainLibrary
from custom_components.growspace_manager.substrate_tracker import SubstrateTracker
from custom_components.growspace_manager.tank_water_tracker import TankWaterTracker
from custom_components.growspace_manager.utils import (
    generate_growspace_overview_unique_id,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util, slugify

from ._definition import ServiceDefinition
from .irrigation_change import (
    IrrigationChange,
    IrrigationChangeOperation,
    IrrigationChangeResult,
    async_apply_irrigation_change,
)
from .utils import handle_service_errors

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


class GrowspaceFacade:
    """Facade for all growspace-level operations."""

    def __init__(self, coordinator: GrowspaceCoordinator) -> None:
        """Initialise the facade with the coordinator."""
        self._coordinator = coordinator
        self._tank_water_trackers: dict[str, dict[str, TankWaterTracker]] = {}
        self._substrate_trackers: dict[str, SubstrateTracker] = {}

    # -------------------------------------------------------------------------
    # CRUD
    # -------------------------------------------------------------------------

    @property
    def growspaces(self) -> dict[str, Growspace]:
        """Return all growspaces keyed by ID."""
        return self._coordinator.growspaces

    def get_growspace(self, growspace_id: str) -> Growspace | None:
        """Return a growspace by ID."""
        return self._coordinator._data_repository.get_growspace(growspace_id)

    def get_all_growspaces(self) -> dict[str, Growspace]:
        """Return all growspaces keyed by ID."""
        return {
            gs.id: gs for gs in self._coordinator._data_repository.get_all_growspaces()
        }

    def get_sorted_growspace_options(self) -> list[tuple[str, str]]:
        """Return a sorted list of (growspace_id, name) tuples."""
        return self._coordinator._growspace_manager.get_sorted_growspace_options()

    def get_canonical_special(self, gs_id: str) -> tuple[str, str]:
        """Return the canonical ID and name for a special growspace."""
        return self._coordinator._growspace_manager.get_canonical_special(gs_id)

    async def add_growspace(self, **kwargs: Any) -> Growspace:
        """Add a new growspace and register its HA device."""
        growspace = await self._coordinator._growspace_manager.add_growspace(**kwargs)
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
        await (
            self._coordinator._subsystem_manager.async_setup_growspace_sub_coordinators(
                growspace.id, growspace
            )
        )
        _LOGGER.info("Added growspace %s (%s)", growspace.name, growspace.id)
        return growspace

    async def update_growspace(self, growspace_id: str, **kwargs: Any) -> Growspace:
        """Update an existing growspace and sync its HA device name if changed."""
        growspace = await self._coordinator._growspace_manager.update_growspace(
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

    async def remove_growspace(
        self, growspace_id: str, *, delete_plants: bool = True
    ) -> None:
        """Remove a growspace, optionally detaching its plants instead."""
        await self._coordinator._growspace_manager.remove_growspace(
            growspace_id, delete_plants=delete_plants
        )
        # Mirrors add_growspace, which sets these up.
        self._coordinator._subsystem_manager.teardown_growspace_sub_coordinators(
            growspace_id
        )

    async def setup_sub_coordinators(self, growspace_id: str) -> None:
        """Set up the sub-coordinators of an existing growspace."""
        growspace = self._coordinator._data_repository.require_growspace(growspace_id)
        await (
            self._coordinator._subsystem_manager.async_setup_growspace_sub_coordinators(
                growspace_id, growspace
            )
        )

    def ensure_special_growspace(self, *args: Any, **kwargs: Any) -> Any:
        """Ensure a special growspace exists; delegates to GrowspaceManager."""
        return self._coordinator._growspace_manager.ensure_special_growspace(
            *args, **kwargs
        )

    async def carry_forward_layout_revision(
        self, growspace_id: str, previous_revision: int
    ) -> int:
        """Advance a Layout Revision past the value a repair discarded."""
        return await self._coordinator._growspace_manager.carry_forward_layout_revision(
            growspace_id, previous_revision
        )

    # -------------------------------------------------------------------------
    # Subareas
    # -------------------------------------------------------------------------

    def get_subareas(self, growspace_id: str) -> list[Subarea]:
        """Return all subareas for a growspace."""
        return self._coordinator._growspace_manager.get_subareas(growspace_id)

    async def add_subarea(self, growspace_id: str, name: str) -> Any:
        """Add a named subarea to a growspace."""
        subarea = await self._coordinator._growspace_manager.add_subarea(
            growspace_id, name
        )
        _LOGGER.info("Added subarea %s to growspace %s", name, growspace_id)
        return subarea

    async def update_subarea(
        self, growspace_id: str, subarea_id: str, environment_config: dict[str, Any]
    ) -> Any:
        """Update a subarea's environment config."""
        result = await self._coordinator._growspace_manager.update_subarea(
            growspace_id, subarea_id, environment_config
        )
        _LOGGER.info("Updated subarea %s in growspace %s", subarea_id, growspace_id)
        return result

    async def remove_subarea(self, growspace_id: str, subarea_id: str) -> None:
        """Remove a subarea from a growspace."""
        await self._coordinator._growspace_manager.remove_subarea(
            growspace_id, subarea_id
        )
        _LOGGER.info("Removed subarea %s from growspace %s", subarea_id, growspace_id)

    # -------------------------------------------------------------------------
    # Plants query
    # -------------------------------------------------------------------------

    def get_growspace_plants(self, growspace_id: str) -> list[Any]:
        """Return all plants in a growspace."""
        return self._coordinator._data_repository.get_growspace_plants(growspace_id)

    def get_growspace_grid(self, growspace_id: str) -> list[list[str | None]]:
        """Return a 2D grid of plant IDs for a growspace."""
        return self._coordinator._data_repository.get_growspace_grid(growspace_id)

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
    ) -> IrrigationChangeResult:
        """Apply an options-flow Irrigation Change."""
        return await async_apply_irrigation_change(
            self._coordinator,
            growspace_id,
            IrrigationChange(
                operation=IrrigationChangeOperation.OPTIONS,
                values=user_input,
            ),
        )

    async def set_irrigation_settings(
        self, growspace_id: str, settings: dict[str, Any]
    ) -> IrrigationChangeResult:
        """Apply a settings-action Irrigation Change."""
        return await async_apply_irrigation_change(
            self._coordinator,
            growspace_id,
            IrrigationChange(
                operation=IrrigationChangeOperation.SETTINGS,
                values=settings,
            ),
        )

    async def set_irrigation_strategy(
        self, growspace_id: str, strategy: dict[str, Any]
    ) -> IrrigationChangeResult:
        """Apply a strategy-action Irrigation Change."""
        return await async_apply_irrigation_change(
            self._coordinator,
            growspace_id,
            IrrigationChange(
                operation=IrrigationChangeOperation.STRATEGY,
                values=strategy,
            ),
        )

    async def set_steering_phase(
        self, growspace_id: str, phase: str
    ) -> IrrigationChangeResult:
        """Override the active crop-steering phase by hand (ADR-0012).

        The [[Steering Phase Machine]] decides the phase every tick and keeps
        its own state; this writes the value the frontend reads, which the
        machine leaves alone until it next transitions on its own. So the
        override holds until the machine genuinely changes phase — it is a
        correction, not a lock.
        """
        return await async_apply_irrigation_change(
            self._coordinator,
            growspace_id,
            IrrigationChange(
                operation=IrrigationChangeOperation.STEERING_PHASE,
                values={"active_steering_phase": phase},
            ),
        )

    async def clear_irrigation(self, growspace_id: str) -> IrrigationChangeResult:
        """Apply a clear Irrigation Change: reset the config, stop steering.

        The irrigation counterpart of ``remove_environment``, but routed
        through the change seam rather than around it, so the reset gets the
        same validation, atomic swap, persistence ordering and rollback as
        every other irrigation write. The whole ``IrrigationConfig`` goes back
        to its defaults — schedules and per-stage EC ranges included, since
        times pointed at a pump that is no longer configured are not a setting
        worth keeping — and the strategy is disabled without otherwise being
        rewritten.
        """
        return await async_apply_irrigation_change(
            self._coordinator,
            growspace_id,
            IrrigationChange(operation=IrrigationChangeOperation.CLEAR, values={}),
        )

    async def apply_steering_mode(
        self, growspace_id: str, mode: SteeringMode
    ) -> IrrigationChangeResult:
        """Stamp a Steering Mode's preset values into the strategy (ADR-0012).

        The grower names the mode; the change seam looks up the preset for
        (mode, stored media type, active shot sizing mode), writes those values
        into the ordinary editable strategy fields and records the mode as the
        declared intent. The coordinator never reads the mode afterwards — only
        the explicit fields. Always re-stamps, so re-selecting the current mode
        resets the fields to that mode's defaults (discarding hand tweaks).
        ``target_vwc_percent`` is never written. One logbook entry naming the
        mode and media follows a successful persist.
        """
        result = await async_apply_irrigation_change(
            self._coordinator,
            growspace_id,
            IrrigationChange(
                operation=IrrigationChangeOperation.STEERING_MODE,
                values={"steering_mode": mode},
            ),
        )
        _LOGGER.info(
            "Applied %s steering mode for growspace '%s'", mode.value, growspace_id
        )
        return result

    async def apply_irrigation_recipe(
        self, growspace_id: str, recipe_id: str
    ) -> str | None:
        """Stamp a saved [[Irrigation Recipe]] into a growspace (ADR-0045).

        The [[Recipe Stamp]]: the recipe's values are re-expressed in this
        growspace's own units — a shot size stored as a percent of substrate
        volume becomes *this* tent's pump seconds through *its* flow rate and
        pot volume — and handed to the shared [[Strategy Stamp]] seam, which
        writes them into the ordinary editable fields and records which recipe
        did it and when. Always re-stamps, so re-applying the recipe already
        applied resets the fields and discards hand tweaks.

        Returns the media-mismatch warning when the recipe was authored in a
        different medium, else None. Such an apply proceeds **unscaled**: pot
        size normalises across growspaces and media does not.

        Raises:
            GrowspaceNotFoundError: when the growspace does not exist.
            EntityNotFoundError: when the recipe does not exist.
            RecipeKindMismatchError: when the recipe holds the half this
                growspace is not running. Resolution happens before any write,
                so a refused apply changes nothing.
            RecipeApplyError: when the target cannot be given the recipe's shot
                sizes honestly.
        """
        growspace = self._coordinator.growspaces.get(growspace_id)
        if not growspace:
            raise GrowspaceNotFoundError(f"Growspace {growspace_id} not found")

        recipe = self._coordinator._recipe_library.get_recipe(recipe_id)
        strategy = growspace.irrigation_strategy
        application = resolve_recipe_application(
            recipe,
            strategy=strategy,
            config=growspace.irrigation_config,
            live_plant_count=count_live_plants(self.get_growspace_plants(growspace_id)),
        )

        authored_media = recipe.provenance.media_type.value
        target_media = strategy.substrate_profile.media_type.value
        await async_apply_strategy_stamp(
            self._coordinator,
            growspace_id,
            StrategyStamp(
                values=application.values,
                config_values=application.config_values,
                records={
                    "applied_recipe_id": recipe.id,
                    "recipe_applied_at": dt_util.utcnow().isoformat(),
                },
                logbook_message=(
                    f"Applied irrigation recipe '{recipe.name}' "
                    f"({authored_media} → {target_media})"
                ),
            ),
        )
        if application.media_warning:
            _LOGGER.warning("%s", application.media_warning)
        _LOGGER.info(
            "Applied irrigation recipe '%s' (id=%s) to growspace '%s'",
            recipe.name,
            recipe.id,
            growspace_id,
        )
        return application.media_warning

    async def assign_irrigation_program(
        self, growspace_id: str, program_id: str | None
    ) -> None:
        """Bind a growspace to an [[Irrigation Program]], or unbind it.

        Binding **applies nothing** — except when ``program_auto_advance`` is
        already on, which is that same consent expressed in advance. With it
        off this writes one field, the explicit ``irrigation_program_id``, and
        no setpoint, so picking a program from a dropdown cannot change what a
        pump does that same minute. Reading the growspace afterwards reports
        which slot it is in and which recipe that slot holds; putting those
        values into the strategy is the separate, deliberate [[Recipe Stamp]]
        gesture.

        With auto-advance on the current slot is applied immediately rather
        than at the next refresh, because a grower who opted into unattended
        progression and then binds a program has already said yes — and a
        binding that visibly did nothing for a quarter of an hour reads as a
        write that was lost. It goes through the same progression seam the
        refresh uses, so every [[Program Hold]] applies here too: a week with
        no slot, a finished program or a drifted growspace binds and changes
        nothing.

        The binding is explicit rather than matched, which is the whole point:
        ``ECRampCurve`` binds by first stage match in dictionary order, so
        which curve drives a growspace is an accident of insertion (ADR-0045).

        ``program_id`` of ``None`` unbinds.

        Raises:
            GrowspaceNotFoundError: when the growspace does not exist.
            EntityNotFoundError: when the program does not exist. Checked
                before the write, so a refused assignment changes nothing.
        """
        growspace = self._coordinator.growspaces.get(growspace_id)
        if not growspace:
            raise GrowspaceNotFoundError(f"Growspace {growspace_id} not found")

        if program_id is not None:
            # Resolved for its refusal only: binding to a program that is not
            # there would report as unbound and look like the write was lost.
            self._coordinator._program_library.get_program(program_id)

        growspace.irrigation_strategy.irrigation_program_id = program_id
        self._coordinator.cache.invalidate(growspace_id)
        await self._coordinator.async_commit()
        await self._coordinator.async_request_refresh()
        _LOGGER.info(
            "Growspace '%s' is now %s",
            growspace_id,
            f"bound to irrigation program '{program_id}'"
            if program_id is not None
            else "bound to no irrigation program",
        )

        if program_id is not None and growspace.irrigation_config.program_auto_advance:
            await self._coordinator.program_progression.async_evaluate(growspace_id)

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
            ranges.append(
                ECTargetRange(
                    stage=stage, feed_ec_min=feed_ec_min, feed_ec_max=feed_ec_max
                )
            )
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
            item_type = (
                "irrigation" if "irrigation" in schedule_key.lower() else "drain"
            )
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
        if (
            growspace_id
            not in self._coordinator._subsystem_manager.irrigation_coordinators
        ):
            growspace = self._coordinator.growspaces.get(growspace_id)
            if growspace:
                await self._coordinator._subsystem_manager.async_setup_growspace_sub_coordinators(
                    growspace_id, growspace
                )
            if (
                growspace_id
                not in self._coordinator._subsystem_manager.irrigation_coordinators
            ):
                raise ServiceValidationError(
                    f"Growspace '{growspace_id}' not found or has no irrigation setup."
                )
        return self._coordinator._subsystem_manager.irrigation_coordinators[
            growspace_id
        ]

    async def water_growspace(
        self,
        growspace_id: str,
        amount_per_plant: float | None = None,
        nutrients: dict[str, float] | None = None,
        preset_id: str | None = None,
        amount: float | None = None,
    ) -> int:
        """Record a watering event for all plants in a growspace."""
        return await self._coordinator.watering_service.async_water_growspace(
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
        drain_config = growspace.drain_config
        record = record_drain_reading(
            drain_config, feed_ec, drain_ec, drain_volume_ml, feed_volume_ml
        )
        await self._coordinator.async_commit()
        if record.alert:
            _LOGGER.warning(
                "Drain EC alert for %s: drain=%.2f, feed=%.2f, delta=%.2f exceeds threshold %.2f",
                growspace_id,
                drain_ec,
                feed_ec,
                record.ec_delta,
                drain_config.max_ec_delta,
            )
            await self._coordinator._notification_manager.async_send_notification(
                growspace_id,
                f"⚠️ High drain EC in {growspace.name}",
                f"Drain EC delta ({record.ec_delta:.2f}) exceeds threshold ({drain_config.max_ec_delta:.2f}).",
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

            gs_trackers[tank_entity] = TankWaterTracker(
                tank, stage_resolver=_stage_resolver
            )
        return gs_trackers[tank_entity]

    def get_all_trackers_for_growspace(
        self, growspace_id: str
    ) -> dict[str, TankWaterTracker]:
        """Return all cached tank water trackers for a growspace."""
        return self._tank_water_trackers.get(growspace_id, {})

    def get_substrate_tracker(self, growspace_id: str) -> SubstrateTracker | None:
        """Return the SubstrateTracker for a growspace, or None if absent.

        The tracker reads and writes ``growspace.substrate_history`` directly, so
        a single cached instance per growspace shares the persisted state with
        the steering loop and the sensor.
        """
        growspace = self.get_growspace(growspace_id)
        if growspace is None:
            return None
        tracker = self._substrate_trackers.get(growspace_id)
        if tracker is None or tracker.growspace is not growspace:
            # Re-bind if the growspace object was replaced (e.g. reload).
            tracker = SubstrateTracker(growspace)
            self._substrate_trackers[growspace_id] = tracker
        return tracker

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
            return entity_id
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

    # -------------------------------------------------------------------------
    # Subsystem coordinator access
    # -------------------------------------------------------------------------

    def get_irrigation_coordinator(self, growspace_id: str) -> Any | None:
        """Return the irrigation coordinator for a growspace, or None."""
        return self._coordinator._subsystem_manager.irrigation_coordinators.get(
            growspace_id
        )

    def get_dehumidifier_coordinator(self, growspace_id: str) -> Any | None:
        """Return the dehumidifier coordinator for a growspace, or None."""
        return self._coordinator._subsystem_manager.get_dehumidifier_controller(
            growspace_id
        )

    def calculate_biological_metrics(
        self, growspace_id: str, growspace: Growspace, days: StageDays
    ) -> dict[str, Any]:
        """Calculate biological metrics for a growspace via the environment analyzer."""
        return self._coordinator.environment_analyzer.calculate_biological_metrics(
            growspace, days
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

    # -------------------------------------------------------------------------
    # Notes
    # -------------------------------------------------------------------------

    async def add_growspace_note(
        self,
        hass: HomeAssistant,
        growspace_id: str,
        notes: str,
        images_base64: list[str] | None = None,
    ) -> None:
        """Add a note to a growspace."""
        if images_base64 is None:
            images_base64 = []

        if growspace_id not in self._coordinator.growspaces:
            raise ServiceValidationError(f"Growspace '{growspace_id}' not found")

        strain_library = self._coordinator.services.config.strain_library

        image_paths: list[str] = []
        if images_base64 and strain_library and strain_library.image_manager:
            for img_b64 in images_base64:
                try:
                    abs_path = await strain_library.image_manager.save_timeline_image(
                        plant_id=growspace_id,
                        image_base64=img_b64,
                    )
                    image_paths.append(f"timeline/{Path(abs_path).name}")
                except (
                    AttributeError,
                    KeyError,
                    ValueError,
                    ServiceValidationError,
                    GrowspaceError,
                    OSError,
                ) as e:
                    _LOGGER.error("Failed to save growspace note image: %s", e)

        event_data: dict[str, Any] = {
            ATTR_GROWSPACE_ID: growspace_id,
            ATTR_NOTES: notes,
            ATTR_IMAGES: image_paths,
            "category": CATEGORY_NOTE,
            "timestamp": dt_util.now().isoformat(),
        }

        hass.bus.async_fire(EVENT_GROWSPACE_LOG_ENTRY, event_data)
        _LOGGER.info("Added note for growspace %s", growspace_id)

    # -------------------------------------------------------------------------
    # Service call adapters
    # -------------------------------------------------------------------------

    @handle_service_errors
    async def add_growspace_from_call(
        self,
        hass: HomeAssistant,
        strain_library: StrainLibrary,
        call: ServiceCall,
    ) -> None:
        """Unpack an add_growspace ServiceCall and delegate to add_growspace."""
        device_registry = dr.async_get(hass)
        mobile_devices = [
            d.name
            for d in device_registry.devices.values()
            if any("mobile_app" in entry_id for entry_id in d.config_entries)
        ]
        notification_target = call.data.get(ATTR_NOTIFICATION_TARGET)
        if notification_target and notification_target not in mobile_devices:
            notification_target = None

        name = call.data[ATTR_NAME]
        rows = call.data[ATTR_ROWS]
        plants_per_row = call.data[ATTR_PLANTS_PER_ROW]

        growspace_id = await self.add_growspace(
            name=name,
            rows=rows,
            plants_per_row=plants_per_row,
            notification_target=notification_target,
        )

        _LOGGER.info("Growspace %s added successfully via service call", growspace_id)

    @handle_service_errors
    async def update_growspace_from_call(
        self,
        hass: HomeAssistant,
        strain_library: StrainLibrary,
        call: ServiceCall,
    ) -> None:
        """Unpack an update_growspace ServiceCall and delegate to update_growspace."""
        growspace_id = call.data[ATTR_GROWSPACE_ID]
        await self.update_growspace(
            growspace_id=growspace_id,
            name=call.data.get(ATTR_NAME),
            rows=call.data.get(ATTR_ROWS),
            plants_per_row=call.data.get(ATTR_PLANTS_PER_ROW),
            notification_target=call.data.get(ATTR_NOTIFICATION_TARGET),
        )
        _LOGGER.info("Growspace %s updated successfully", growspace_id)

    @handle_service_errors
    async def remove_growspace_from_call(
        self,
        hass: HomeAssistant,
        call: ServiceCall,
    ) -> None:
        """Unpack a remove_growspace ServiceCall and delegate to remove_growspace."""
        growspace_id = call.data[ATTR_GROWSPACE_ID]
        await self.remove_growspace(growspace_id)
        _LOGGER.info("Growspace %s removed successfully", growspace_id)


async def _handle_add_growspace(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    await coordinator.services.growspaces.add_growspace_from_call(
        hass, strain_library, call
    )


async def _handle_update_growspace(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    await coordinator.services.growspaces.update_growspace_from_call(
        hass, strain_library, call
    )


async def _handle_remove_growspace(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    await coordinator.services.growspaces.remove_growspace_from_call(hass, call)


SERVICES: list[ServiceDefinition] = [
    ServiceDefinition(
        GrowspaceService.ADD_GROWSPACE,
        _handle_add_growspace,
        ADD_GROWSPACE_SCHEMA,
        needs_strain_lib=True,
    ),
    ServiceDefinition(
        GrowspaceService.REMOVE_GROWSPACE,
        _handle_remove_growspace,
        REMOVE_GROWSPACE_SCHEMA,
        needs_strain_lib=False,
    ),
    ServiceDefinition(
        GrowspaceService.UPDATE_GROWSPACE,
        _handle_update_growspace,
        UPDATE_GROWSPACE_SCHEMA,
        needs_strain_lib=True,
    ),
]
