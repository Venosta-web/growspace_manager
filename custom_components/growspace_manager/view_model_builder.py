"""View model builder for Growspace Manager.

Handles serialization and caching of frontend data models.
"""

from __future__ import annotations

from collections import defaultdict
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from .models import Plant
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
            plants = self.coordinator.services.growspaces.get_growspace_plants(growspace_id)

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

        # Calculate biological metrics via EnvironmentAnalyzer (View Model assembly)
        biological_metrics = (
            self.coordinator.services.growspaces.calculate_biological_metrics(
                growspace_id,
                growspace,
                max_days["max_veg_days"],
                max_days["max_flower_days"],
                max_days["max_dry_days"],
                max_days["max_cure_days"],
                max_days["max_seedling_days"],
                max_days["max_clone_days"],
                max_days["max_mother_days"],
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

        # Compute liters_today for Tank-Derived Water Mode
        liters_today: float | None = None
        env = growspace.environment_config
        if env and not env.irrigation_flow_sensors and not env.drain_volume_sensors:
            trackers = self.coordinator.services.growspaces.get_all_trackers_for_growspace(
                growspace_id
            )
            liters_today = round(
                sum(t.get_total_liters_today() for t in trackers.values()), 2
            )

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

        # Top-level timestamp for efficient frontend equality checks (change detection)
        serialized["_ts"] = int(current_time * 1000)

        # Cache the serialized data as a tuple: (timestamp, data)
        self.coordinator.cache.set(growspace_id, (current_time, serialized))
        return serialized

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
            "timed_notifications": options.get("timed_notifications", []),
            "_version": dt_util.now().isoformat(),
            "serialized_growspaces": serialized_growspaces,
            "air_exchange_recommendations": recs,
        }
