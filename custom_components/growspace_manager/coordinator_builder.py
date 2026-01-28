"""Builder for constructing GrowspaceCoordinator with all dependencies."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .strain_library import StrainLibrary

if TYPE_CHECKING:
    from .coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


class CoordinatorBuilder:
    """Builds GrowspaceCoordinator with all dependencies.

    This builder simplifies coordinator creation by encapsulating
    the initialization logic and providing a clean interface for
    async_setup_entry. This improves testability and reduces
    complexity in the integration setup code.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry[GrowspaceCoordinator],
    ) -> None:
        """Initialize the builder.

        Args:
            hass: Home Assistant instance
            entry: Config entry for this integration
        """
        self.hass = hass
        self.entry = entry

    def build(
        self,
        data: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
        strain_library: StrainLibrary | None = None,
    ) -> GrowspaceCoordinator:
        """Build a fully configured GrowspaceCoordinator.

        This method creates a coordinator with all dependencies properly
        initialized and wired together.

        Args:
            data: Initial raw data from storage to restore state. If None, starts fresh.
            options: Configuration options from the config entry.
            strain_library: Optional pre-initialized strain library. If None, creates new.

        Returns:
            Fully initialized GrowspaceCoordinator instance
        """
        # Import here to avoid circular dependency
        from .coordinator import GrowspaceCoordinator

        _LOGGER.debug(
            "Building GrowspaceCoordinator for entry %s with options: %s",
            self.entry.entry_id,
            options,
        )

        # Create coordinator using its standard __init__
        coordinator = GrowspaceCoordinator(
            hass=self.hass,
            entry=self.entry,
            data=data,
            options=options,
            strain_library=strain_library,
        )

        _LOGGER.debug("GrowspaceCoordinator built successfully")

        return coordinator
