"""View model builder for Growspace Manager.

Handles serialization and caching of frontend data models.
"""

from __future__ import annotations

from collections import defaultdict
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from .crop_steering import get_crop_steering_state
from .domain.ec_state import resolve_feed_stage_week
from .domain.irrigation_program import resolve_program_slot
from .domain.irrigation_recipe import recipe_has_drifted
from .domain.plant_metrics import count_live_plants
from .domain.stage import StageDays
from .domain.water_aggregation import compute_growspace_water
from .models import Plant
from .notifications.timed import normalize_timed_notifications
from .presentation import GrowspaceViewModelBuilder
from .utils import calculate_days_since

if TYPE_CHECKING:
    from .coordinator import GrowspaceCoordinator
    from .models import Growspace

_LOGGER = logging.getLogger(__name__)


class ViewModelBuilder:
    """Builds view models for frontend consumption.

    Handles:
    - Growspace serialization with caching
    - Plant statistics aggregation
    - Data property assembly for frontend

    This class orchestrates coordinator-specific concerns (caching, biological metrics,
    irrigation events) and delegates the actual view model building to presentation layer.
    """

    def __init__(self, coordinator: GrowspaceCoordinator) -> None:
        """Initialize the ViewModelBuilder.

        Args:
            coordinator: The GrowspaceCoordinator instance
        """
        self.coordinator = coordinator
        self._growspace_builder = GrowspaceViewModelBuilder(coordinator.hass)

    @property
    def growspaces(self) -> dict[str, Growspace]:
        """Get growspaces from coordinator."""
        return self.coordinator.growspaces

    @property
    def plants(self) -> dict[str, Plant]:
        """Get plants from coordinator."""
        return self.coordinator.plants

    @property
    def notifications_sent(self) -> dict[str, dict[str, dict[str, bool]]]:
        """Get notifications sent from coordinator."""
        return self.coordinator.notification_state.sent

    @property
    def notifications_enabled(self) -> dict[str, bool]:
        """Get notifications enabled from coordinator."""
        return self.coordinator.notification_state.enabled

    def build_serialized_growspace(
        self, growspace_id: str, preloaded_plants: list[Plant] | None = None
    ) -> dict[str, Any]:
        """Build serialized growspace data with caching.

        Args:
            growspace_id: The ID of the growspace to serialize.
            preloaded_plants: Optional list of plants in this growspace.
                              If provided, avoids a full scan of plants dict.

        Returns:
            Serialized growspace data with timestamp and cached result.
        """
        current_time = dt_util.utcnow().timestamp()

        # Check cache first with a 30-second TTL
        cached_entry = self.coordinator.cache.get(growspace_id)
        if isinstance(cached_entry, tuple) and len(cached_entry) == 2:
            cached_time, cached_data = cached_entry
            if current_time - cached_time < 30.0:  # 30-second TTL
                return cached_data

        growspace = self.growspaces[growspace_id]

        # Optimization: Use preloaded plants if available, else fetch them
        if preloaded_plants is not None:
            plants = preloaded_plants
        else:
            plants = self.coordinator.services.growspaces.get_growspace_plants(
                growspace_id
            )

        # Calculate aggregated stats for the growspace
        stage_attr_map = {
            "seedling_start": "max_seedling_days",
            "clone_start": "max_clone_days",
            "veg_start": "max_veg_days",
            "flower_start": "max_flower_days",
            "dry_start": "max_dry_days",
            "cure_start": "max_cure_days",
            "mother_start": "max_mother_days",
        }

        # Calculate max days for each stage
        max_days = {
            target_var: max(
                (
                    calculate_days_since(getattr(p, attr))
                    for p in plants
                    if getattr(p, attr)
                ),
                default=-1,
            )
            for attr, target_var in stage_attr_map.items()
        }

        max_veg_days = max_days["max_veg_days"]
        max_flower_days = max_days["max_flower_days"]
        max_dry_days = max_days["max_dry_days"]
        max_cure_days = max_days["max_cure_days"]

        stage_days = StageDays(
            veg=max_days["max_veg_days"],
            flower=max_days["max_flower_days"],
            dry=max_days["max_dry_days"],
            cure=max_days["max_cure_days"],
            seedling=max_days["max_seedling_days"],
            clone=max_days["max_clone_days"],
            mother=max_days["max_mother_days"],
        )
        biological_metrics = (
            self.coordinator.services.growspaces.calculate_biological_metrics(
                growspace_id,
                growspace,
                stage_days,
            )
        )

        # Fetch active events and cycle telemetry from irrigation sub-coordinators
        active_events = {}
        last_cycle_timestamp: str | None = None
        next_scheduled_cycle: str | None = None
        projected_shot_window: dict[str, str] | None = None
        cycles_today: int = 0
        volume_dispensed_today: float = 0.0
        irr_coord = self.coordinator.services.growspaces.get_irrigation_coordinator(
            growspace_id
        )
        if irr_coord is not None:
            active_events = irr_coord.active_events
            last_cycle_timestamp = irr_coord.last_cycle_timestamp
            next_scheduled_cycle = irr_coord.next_scheduled_cycle
            projected_shot_window = irr_coord.projected_shot_window
            cycles_today = irr_coord.cycles_today
            volume_dispensed_today = irr_coord.volume_dispensed_today

        # Canonical [[Aggregate Water Use]] for today (ADR-0017): manual +
        # (tank-derived in tank mode, else pump-estimate). The shared helper owns
        # all source selection, so this path no longer branches on sensor config.
        trackers = self.coordinator.services.growspaces.get_all_trackers_for_growspace(
            growspace_id
        )
        liters_today = compute_growspace_water(growspace, trackers.values()).today

        # Use presentation layer to build rich growspace payload
        serialized = self._growspace_builder.build(
            growspace,
            plants,
            biological_metrics,
            max_veg_days=max_veg_days,
            max_flower_days=max_flower_days,
            max_dry_days=max_dry_days,
            max_cure_days=max_cure_days,
            active_events=active_events,
            liters_today=liters_today,
        )

        # Inject irrigation cycle telemetry into the irrigation sub-object
        serialized["irrigation"]["last_cycle_timestamp"] = last_cycle_timestamp
        serialized["irrigation"]["next_scheduled_cycle"] = next_scheduled_cycle
        serialized["irrigation"]["projected_shot_window"] = projected_shot_window
        serialized["irrigation"]["cycles_today"] = cycles_today
        serialized["irrigation"]["volume_dispensed_today"] = volume_dispensed_today

        # Surface the measured steering readout alongside the tracker-derived
        # substrate metrics. The score, its Measured Classification, and the
        # Intent Deviation live on the CropSteeringState (computed with the
        # coordinator's live VWC) — not reachable from the presentation builder,
        # which only has hass — so they are injected here next to the telemetry.
        # None throughout when the strategy is disabled / no reading yet, so the
        # card can lock the score panel rather than show a synthetic value.
        steering_state = get_crop_steering_state(self.coordinator, growspace_id)
        substrate = serialized["irrigation"]["substrate"]
        substrate["score"] = (
            round(steering_state.score, 2) if steering_state is not None else None
        )
        substrate["measured_classification"] = (
            steering_state.measured_classification
            if steering_state is not None
            else None
        )
        substrate["intent_deviation"] = (
            steering_state.intent_deviation if steering_state is not None else None
        )
        substrate["runoff_score"] = (
            steering_state.runoff_score if steering_state is not None else None
        )

        # Shot Size Composition is runtime state on the VWC coordinator (base ×
        # VWC factor × EC modulation), absent on time-based irrigation.
        substrate["shot_composition"] = (
            irr_coord.shot_composition_payload()
            if irr_coord is not None and hasattr(irr_coord, "shot_composition_payload")
            else None
        )

        # EC State: the reconciled feed/pore EC view (ADR-0015), only on the VWC
        # coordinator. None on time-based irrigation so the card can lock the panel.
        serialized["irrigation"]["ec_state"] = (
            irr_coord.ec_state_payload()
            if irr_coord is not None and hasattr(irr_coord, "ec_state_payload")
            else None
        )

        # The global [[Irrigation Recipe]] library rides every growspace payload
        # for the same reason the notification settings below do: the card's
        # irrigation dialog seeds from the device payload, and the recipe picker
        # lives in that dialog. It is global, not per-growspace — the same
        # library appears on every payload — and this is what puts it inside the
        # golden contract fixture, where a dropped field fails CI (ADR-0030).
        serialized["irrigation"]["recipes"] = (
            self.coordinator.services.config.get_irrigation_recipes()
        )

        # [[Recipe Stamp]] drift, computed on read rather than stored: because
        # recipes are held by reference, a hash written at stamp time would go
        # stale the moment the recipe itself was edited (ADR-0045). None means
        # the question does not apply — the growspace has never had a recipe
        # applied, or the one it names has since been removed from the library.
        serialized["irrigation"]["applied_recipe_drifted"] = self._applied_recipe_drift(
            growspace, plants
        )

        # The global [[Irrigation Program]] library rides every payload for the
        # same reason the recipe library above does: the card's program editor
        # lives in the dialog that seeds from the device payload.
        serialized["irrigation"]["programs"] = (
            self.coordinator.services.config.get_irrigation_programs()
        )

        # Where this growspace currently sits in the program it is bound to —
        # the slot and that slot's recipe, resolved on read. None whenever the
        # question does not apply: nothing bound, or a binding naming a program
        # the library no longer holds.
        serialized["irrigation"]["program"] = self._program_state(growspace, plants)

        # Global notification settings ride every growspace payload so the card's
        # Config Dialog (which seeds from the device payload) can round-trip saved
        # values. They are global, not per-growspace, but mirror notifications_enabled
        # in being duplicated across payloads.
        options = self.coordinator.config_entry.options
        serialized["notification_settings"] = options.get("notification_settings", {})
        serialized["ai_auto_alerts"] = options.get("ai_settings", {}).get(
            "ai_auto_alerts", True
        )
        serialized["timed_notifications"] = normalize_timed_notifications(
            options.get("timed_notifications", [])
        )

        # Top-level timestamp for efficient frontend equality checks (change detection)
        serialized["_ts"] = int(current_time * 1000)

        # Cache the serialized data as a tuple: (timestamp, data)
        self.coordinator.cache.set(growspace_id, (current_time, serialized))
        return serialized

    def _applied_recipe_drift(
        self, growspace: Growspace, plants: list[Plant]
    ) -> bool | None:
        """Return whether the growspace still holds what its recipe stamped.

        None when there is nothing to compare against: no recipe was ever
        applied, or the applied recipe has since been deleted from the global
        library (deleting leaves references dangling rather than cascading).
        """
        recipe_id = growspace.irrigation_strategy.applied_recipe_id
        if recipe_id is None:
            return None
        recipe = self.coordinator.services.config.find_irrigation_recipe(recipe_id)
        if recipe is None:
            return None
        return recipe_has_drifted(
            recipe,
            strategy=growspace.irrigation_strategy,
            config=growspace.irrigation_config,
            live_plant_count=count_live_plants(plants),
        )

    def _program_state(
        self, growspace: Growspace, plants: list[Plant]
    ) -> dict[str, Any] | None:
        """Return the bound [[Irrigation Program]]'s current slot and recipe.

        The position comes from ``resolve_feed_stage_week`` — the same seam the
        [[Active Feed EC Target]] uses, reused unchanged so one card never
        shows two different weeks for one tent ([[Recipe Week Resolution]]).
        No second week calculator exists.

        ``slot`` and ``recipe`` are ``None`` independently of one another and
        of each other's causes: a growspace with no live plants has no
        position to match, a defined position may simply have no slot
        ([[Program Hold]]), and a slot may name a recipe the library no longer
        holds — all three report cleanly rather than raising, because holding
        is the safe answer and an error here would blank a whole payload.

        ``stage``/``week`` are reported even when nothing matched, so the card
        can say *which* week found no slot rather than only that none was
        found.
        """
        program_id = growspace.irrigation_strategy.irrigation_program_id
        if program_id is None:
            return None
        program = self.coordinator.services.config.find_irrigation_program(program_id)
        if program is None:
            return None

        stage, week = resolve_feed_stage_week(plants)
        slot = resolve_program_slot(program, stage=stage, week=week)
        recipe = (
            self.coordinator.services.config.find_irrigation_recipe(slot.recipe_id)
            if slot is not None
            else None
        )
        return {
            "program_id": program.id,
            "name": program.name,
            "stage": stage,
            "week": week,
            "slot": slot.to_dict() if slot is not None else None,
            "recipe": recipe.to_dict() if recipe is not None else None,
        }

    def build_data_property(
        self, preserve_air_exchange_recs: bool = True
    ) -> dict[str, Any]:
        """Build the coordinator data property for frontend consumption.

        Args:
            preserve_air_exchange_recs: Whether to preserve existing air exchange
                                        recommendations from current data.

        Returns:
            Dictionary containing all coordinator state for frontend.
        """
        # Preserve existing recommendations if valid
        recs = {}
        if (
            preserve_air_exchange_recs
            and self.coordinator.data
            and isinstance(self.coordinator.data, dict)
        ):
            recs = self.coordinator.data.get("air_exchange_recommendations", {})

        # Optimized: Serialize growspaces using cache
        serialized_growspaces = {}

        # Pre-calculate plant distribution to avoid O(N*M) lookups
        # Build plants_by_growspace index - O(N) where N = number of plants
        plants_by_growspace: dict[str, list[Plant]] = defaultdict(list)
        for plant_id, plant in self.plants.items():
            if plant.growspace_id not in self.growspaces:
                _LOGGER.warning(
                    "Orphaned plant detected: Plant '%s' refers to non-existent growspace '%s'. It will be excluded from the view",
                    plant_id,
                    plant.growspace_id,
                )
            plants_by_growspace[plant.growspace_id].append(plant)

        for growspace_id in self.growspaces:
            # Pass the pre-filtered list to the builder
            # Use empty list if no plants found for this growspace
            plants = plants_by_growspace.get(growspace_id, [])
            serialized_growspaces[growspace_id] = self.build_serialized_growspace(
                growspace_id, preloaded_plants=plants
            )

        options = self.coordinator.config_entry.options
        return {
            "growspaces": self.growspaces,
            "plants": self.plants,
            "notifications_sent": self.notifications_sent,
            "notifications_enabled": self.notifications_enabled,
            "notification_settings": options.get("notification_settings", {}),
            "timed_notifications": normalize_timed_notifications(
                options.get("timed_notifications", [])
            ),
            "_version": dt_util.now().isoformat(),
            "serialized_growspaces": serialized_growspaces,
            "air_exchange_recommendations": recs,
        }
