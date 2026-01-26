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
        return self.coordinator.notifications_sent

    @property
    def notifications_enabled(self) -> dict[str, bool]:
        """Get notifications enabled from coordinator."""
        return self.coordinator.notifications_enabled

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
        # Check cache first
        if cached := self.coordinator.cache.get(growspace_id):
            return cached

        growspace = self.growspaces[growspace_id]

        # Optimization: Use preloaded plants if available, else fetch them
        if preloaded_plants is not None:
            plants = preloaded_plants
        else:
            plants = self.coordinator.get_growspace_plants(growspace_id)

        # Calculate aggregated stats for the growspace
        stage_attr_map = {
            "veg_start": "max_veg_days",
            "flower_start": "max_flower_days",
            "dry_start": "max_dry_days",
            "cure_start": "max_cure_days",
        }

        # Calculate max days for each stage
        max_days = {
            target_var: max(
                (
                    calculate_days_since(getattr(p, attr))
                    for p in plants
                    if getattr(p, attr)
                ),
                default=0,
            )
            for attr, target_var in stage_attr_map.items()
        }

        max_veg_days = max_days["max_veg_days"]
        max_flower_days = max_days["max_flower_days"]
        max_dry_days = max_days["max_dry_days"]
        max_cure_days = max_days["max_cure_days"]

        # Calculate biological metrics via EnvironmentAnalyzer (View Model assembly)
        biological_metrics = (
            self.coordinator.environment_analyzer.calculate_biological_metrics(
                growspace, max_veg_days, max_flower_days, max_dry_days, max_cure_days
            )
        )

        # Fetch active events from irrigation sub-coordinators
        active_events = {}
        if (
            self.coordinator.subsystem_manager
            and growspace_id
            in self.coordinator.subsystem_manager.irrigation_coordinators
        ):
            irr_coord = self.coordinator.subsystem_manager.irrigation_coordinators[
                growspace_id
            ]
            active_events = irr_coord.active_events

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
        )

        # Inject timestamp for efficient frontend equality checks (change detection)
        serialized["_ts"] = int(dt_util.utcnow().timestamp() * 1000)

        # Cache the serialized data
        self.coordinator.cache.set(growspace_id, serialized)
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
        for plant in self.plants.values():
            plants_by_growspace[plant.growspace_id].append(plant)

        for growspace_id in self.growspaces:
            # Pass the pre-filtered list to the builder
            # Use empty list if no plants found for this growspace
            plants = plants_by_growspace.get(growspace_id, [])
            serialized_growspaces[growspace_id] = self.build_serialized_growspace(
                growspace_id, preloaded_plants=plants
            )

        return {
            "growspaces": self.growspaces,
            "plants": self.plants,
            "notifications_sent": self.notifications_sent,
            "notifications_enabled": self.notifications_enabled,
            "_version": dt_util.now().isoformat(),
            "serialized_growspaces": serialized_growspaces,
            "air_exchange_recommendations": recs,
        }
