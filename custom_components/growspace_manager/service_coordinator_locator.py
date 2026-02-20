"""Service coordinator locator for finding the correct coordinator instance.

This module handles the logic for determining which GrowspaceCoordinator
instance should handle a given service call when multiple config entries exist.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

from .const import (
    ATTR_GROWSPACE_ID,
    ATTR_MOTHER_PLANT_ID,
    ATTR_PLANT_ID,
    ATTR_TARGET_GROWSPACE_ID,
    DOMAIN,
)

if TYPE_CHECKING:
    from .coordinator import GrowspaceCoordinator


class ServiceCoordinatorLocator:
    """Locates the correct coordinator for a service call.

    This class handles the logic for determining which GrowspaceCoordinator
    instance should handle a given service call when multiple config entries exist.

    It checks various ID attributes in the service call data and matches them
    against coordinator collections to find the appropriate coordinator.
    """

    # Attributes to check and their corresponding coordinator collections
    LOOKUP_MAPPINGS = [
        (ATTR_GROWSPACE_ID, "growspaces"),
        (ATTR_TARGET_GROWSPACE_ID, "growspaces"),
        (ATTR_PLANT_ID, "plants"),
        (ATTR_MOTHER_PLANT_ID, "plants"),
    ]

    @staticmethod
    def get_for_service_call(
        hass: HomeAssistant, call: ServiceCall | dict[str, Any]
    ) -> GrowspaceCoordinator:
        """Retrieve the correct coordinator based on service call data.

        Args:
            hass: The Home Assistant instance.
            call: A ServiceCall or dict containing the service call data.

        Returns:
            The appropriate GrowspaceCoordinator for the request.

        Raises:
            ServiceValidationError: If no matching coordinator can be found.
        """
        data = call.data if isinstance(call, ServiceCall) else call

        # Get all loaded coordinators
        coordinators = ServiceCoordinatorLocator._get_loaded_coordinators(hass)

        # Try to find coordinator by checking ID lookups
        coordinator = ServiceCoordinatorLocator._find_by_id_lookup(data, coordinators)
        if coordinator:
            return coordinator

        # If only one coordinator exists, use it
        if len(coordinators) == 1:
            return coordinators[0]

        # Unable to determine which coordinator to use
        raise ServiceValidationError(
            "Could not determine which Growspace Manager instance to use. "
            "Please specify a valid growspace_id or plant_id."
        )

    @staticmethod
    def _get_loaded_coordinators(hass: HomeAssistant) -> list[GrowspaceCoordinator]:
        """Get all loaded GrowspaceCoordinator instances.

        Args:
            hass: The Home Assistant instance.

        Returns:
            List of loaded GrowspaceCoordinator instances.
        """
        entries: list[Any] = hass.config_entries.async_entries(DOMAIN)
        return [
            entry.runtime_data
            for entry in entries
            if entry.state == ConfigEntryState.LOADED and hasattr(entry, "runtime_data")
        ]

    @staticmethod
    def _find_by_id_lookup(
        data: dict[str, Any], coordinators: list[GrowspaceCoordinator]
    ) -> GrowspaceCoordinator | None:
        """Find coordinator by checking if IDs exist in collections.

        Args:
            data: Service call data dictionary.
            coordinators: List of available coordinators.

        Returns:
            Matching coordinator or None if not found.
        """
        for attr_key, collection_name in ServiceCoordinatorLocator.LOOKUP_MAPPINGS:
            if val := data.get(attr_key):
                coordinator = ServiceCoordinatorLocator._check_collection(
                    val, collection_name, coordinators
                )
                if coordinator:
                    return coordinator

        return None

    @staticmethod
    def _check_collection(
        value: str | list[str], collection_name: str, coordinators: list[Any]
    ) -> Any | None:
        """Check if value exists in coordinator's collection.

        Args:
            value: Single ID or list of IDs to check.
            collection_name: Name of the collection to check (e.g., 'plants', 'growspaces').
            coordinators: List of coordinators to check.

        Returns:
            First matching coordinator or None.
        """
        for coordinator in coordinators:
            target_collection = getattr(coordinator, collection_name)

            if isinstance(value, list):
                # Check if any item in the list exists in collection
                if any(item in target_collection for item in value):
                    return coordinator
            elif value in target_collection:
                # Single value check
                return coordinator

        return None
