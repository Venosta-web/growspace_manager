"""Config handlers for Growspace Manager."""

from __future__ import annotations

from abc import ABC
import logging
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

if TYPE_CHECKING:
    from custom_components.growspace_manager.config_flow import OptionsFlowHandler
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

# NOTE: Handler imports moved to bottom of file to avoid circular import
# (handlers import BaseConfigHandler which must be defined first)

T = TypeVar("T")

_LOGGER = logging.getLogger(__name__)


class AbortFlow(Exception):
    """Exception to signal config flow should abort."""

    def __init__(self, reason: str) -> None:
        """Initialize abort flow exception."""
        super().__init__(reason)
        self.reason = reason


class BaseConfigHandler(ABC, Generic[T]):
    """Base class for configuration handlers."""

    config_entry: ConfigEntry | None = None
    _flow: OptionsFlowHandler | None = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the handler."""
        if len(args) == 1 and hasattr(args[0], "hass"):
            # Orchestrator style
            self._flow = args[0]
            self.hass = args[0].hass
            self.config_entry = getattr(args[0], "config_entry", None)
        elif len(args) >= 2 and isinstance(args[0], HomeAssistant):
            # Traditional/Test style
            self._flow = None
            self.hass = args[0]
            self.config_entry = args[1]
        else:
            # Fallback
            self._flow = kwargs.get("flow")
            if self._flow:
                self.hass = self._flow.hass
                self.config_entry = getattr(self._flow, "config_entry", None)
            else:
                self.hass = kwargs.get("hass")
                self.config_entry = kwargs.get("config_entry")

    @property
    def flow(self) -> OptionsFlowHandler:
        """Return the owning options flow.

        Only unset in the traditional/test construction style, which never
        drives steps that touch it.
        """
        assert self._flow is not None
        return self._flow

    @flow.setter
    def flow(self, value: OptionsFlowHandler | None) -> None:
        self._flow = value

    def get_coordinator(self) -> GrowspaceCoordinator:
        """Get coordinator with validation.

        Returns:
            GrowspaceCoordinator instance

        Raises:
            AbortFlow: If coordinator not available
        """
        if self.config_entry is None:
            raise AbortFlow("setup_error")
        coordinator = self.config_entry.runtime_data
        if coordinator is None:
            raise AbortFlow("setup_error")
        return coordinator

    async def websocket_get_event_log(
        self, hass: HomeAssistant, connection: Any, msg: dict[str, Any]
    ) -> None:
        """Handle websocket request for event log."""
        # This method body is missing from the provided diff,
        # so it's left as a placeholder.

    async def transition_plant_stage(
        self, hass: HomeAssistant, connection: Any, msg: dict[str, Any]
    ) -> None:
        """Handle websocket request to transition plant stage."""
        # This method body is missing from the provided diff,
        # so it's left as a placeholder.

    def clean_input(self, user_input: dict[str, Any]) -> dict[str, Any]:
        """Remove empty or None values from input."""
        return {k: v for k, v in user_input.items() if v is not None and v != ""}

    def merge_options(
        self, current_options: dict[str, Any], new_options: dict[str, Any]
    ) -> dict[str, Any]:
        """Merge new options into current options."""
        updated = current_options.copy()
        updated.update(new_options)
        return updated


# Import handlers AFTER BaseConfigHandler is defined to avoid circular import
from .ai_config_handler import AIConfigHandler  # noqa: E402
from .bayesian_advanced_handler import BayesianAdvancedHandler  # noqa: E402
from .dehumidifier_handler import DehumidifierHandler  # noqa: E402
from .environment_config_handler import EnvironmentConfigHandler  # noqa: E402
from .environment_sensors_handler import EnvironmentSensorsHandler  # noqa: E402
from .fan_controller_handler import FanControllerHandler  # noqa: E402
from .growspace_config_handler import GrowspaceConfigHandler  # noqa: E402
from .humidifier_handler import HumidifierHandler  # noqa: E402
from .irrigation_config_handler import IrrigationConfigHandler  # noqa: E402
from .notification_config_handler import NotificationConfigHandler  # noqa: E402
from .plant_config_handler import PlantConfigHandler  # noqa: E402
from .strain_config_handler import StrainConfigHandler  # noqa: E402

__all__ = [
    "AIConfigHandler",
    "BaseConfigHandler",
    "BayesianAdvancedHandler",
    "DehumidifierHandler",
    "EnvironmentConfigHandler",
    "EnvironmentSensorsHandler",
    "FanControllerHandler",
    "GrowspaceConfigHandler",
    "HumidifierHandler",
    "IrrigationConfigHandler",
    "NotificationConfigHandler",
    "PlantConfigHandler",
    "StrainConfigHandler",
]
