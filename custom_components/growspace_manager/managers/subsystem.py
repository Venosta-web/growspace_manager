"""Subsystem Manager for Growspace Manager.

This module encapsulates the management of sub-coordinators (Irrigation, Dehumidifier,
Humidifier, CirculationFan) to reduce the responsibility of the main GrowspaceCoordinator.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from custom_components.growspace_manager.circulation_fan_coordinator import (
    CirculationFanCoordinator,
)
from custom_components.growspace_manager.dehumidifier_coordinator import (
    DehumidifierCoordinator,
)
from custom_components.growspace_manager.humidifier_coordinator import (
    HumidifierCoordinator,
)
from custom_components.growspace_manager.irrigation_coordinator import (
    IrrigationCoordinator,
)
from custom_components.growspace_manager.light_cycle_tracker import LightCycleTracker
from custom_components.growspace_manager.vwc_irrigation_coordinator import (
    VWCIrrigationCoordinator,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
    from custom_components.growspace_manager.models import Growspace

_LOGGER = logging.getLogger(__name__)


@runtime_checkable
class EnvironmentController(Protocol):
    """Protocol satisfied by all per-growspace environment controllers.

    Any class with async_setup() and unload() qualifies — no explicit
    inheritance required. Register new controllers (AC, CO2, etc.) by
    instantiating them in async_setup_growspace_sub_coordinators and
    appending to the environment_controllers list for the growspace.
    """

    async def async_setup(self) -> None:
        """Start the controller."""

    def unload(self) -> None:
        """Stop the controller and release listeners."""


class SubsystemManager:
    """Manages sub-coordinators for Growspace Manager."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: GrowspaceCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the SubsystemManager."""
        self.hass = hass
        self.coordinator = coordinator
        self.entry = entry

        self.irrigation_coordinators: dict[
            str, IrrigationCoordinator | VWCIrrigationCoordinator
        ] = {}
        self.light_cycle_trackers: dict[str, LightCycleTracker] = {}
        # All VPD/temperature/humidity controllers keyed by growspace_id.
        # Each list is ordered: [DehumidifierCoordinator, HumidifierCoordinator, CirculationFanCoordinator, ...]
        self.environment_controllers: dict[str, list[EnvironmentController]] = {}

    async def async_initialize_sub_coordinators(
        self, growspaces: dict[str, Growspace]
    ) -> None:
        """Initialize sub-coordinators for irrigation and dehumidifier."""
        try:
            async with asyncio.TaskGroup() as tg:
                for growspace_id, gs in growspaces.items():
                    tg.create_task(
                        self.async_setup_growspace_sub_coordinators(growspace_id, gs)
                    )
        except ExceptionGroup as eg:
            for err in eg.exceptions:
                _LOGGER.error("Failed to initialize sub-coordinator: %s", err)
            _LOGGER.warning(
                "Some sub-coordinators failed to initialize, continuing with available services"
            )

    async def async_setup_growspace_sub_coordinators(
        self, growspace_id: str, gs: Growspace
    ) -> None:
        """Setup sub-coordinators for a single growspace."""
        irrigation_coordinator: IrrigationCoordinator | VWCIrrigationCoordinator
        if gs.irrigation_strategy.enabled:
            _LOGGER.info(
                "Initializing VWC Irrigation Coordinator for growspace %s",
                growspace_id,
            )
            irrigation_coordinator = VWCIrrigationCoordinator(
                self.hass, self.entry, growspace_id, self.coordinator
            )
        else:
            _LOGGER.debug(
                "Initializing Standard Irrigation Coordinator for growspace %s",
                growspace_id,
            )
            irrigation_coordinator = IrrigationCoordinator(
                self.hass, self.entry, growspace_id, self.coordinator
            )

        await irrigation_coordinator.async_setup()
        self.irrigation_coordinators[growspace_id] = irrigation_coordinator

        light_cycle_tracker = LightCycleTracker(self.hass, growspace_id, self.coordinator)
        await light_cycle_tracker.async_setup()
        self.light_cycle_trackers[growspace_id] = light_cycle_tracker

        controllers: list[EnvironmentController] = [
            DehumidifierCoordinator(self.hass, self.entry, growspace_id, self.coordinator),
            HumidifierCoordinator(self.hass, self.entry, growspace_id, self.coordinator),
            CirculationFanCoordinator(self.hass, self.entry, growspace_id, self.coordinator),
        ]
        for controller in controllers:
            await controller.async_setup()
        self.environment_controllers[growspace_id] = controllers

    def get_dehumidifier_controller(self, growspace_id: str) -> DehumidifierCoordinator | None:
        """Return the dehumidifier coordinator for a growspace, or None."""
        for c in self.environment_controllers.get(growspace_id, []):
            if isinstance(c, DehumidifierCoordinator):
                return c
        return None

    def get_humidifier_controller(self, growspace_id: str) -> HumidifierCoordinator | None:
        """Return the humidifier coordinator for a growspace, or None."""
        for c in self.environment_controllers.get(growspace_id, []):
            if isinstance(c, HumidifierCoordinator):
                return c
        return None

    def get_circulation_fan_controller(
        self, growspace_id: str
    ) -> CirculationFanCoordinator | None:
        """Return the circulation fan coordinator for a growspace, or None."""
        for c in self.environment_controllers.get(growspace_id, []):
            if isinstance(c, CirculationFanCoordinator):
                return c
        return None

    def async_cancel_all(self) -> None:
        """Cancel all sub-coordinator listeners."""
        for irr_coordinator in self.irrigation_coordinators.values():
            try:
                irr_coordinator.async_cancel_listeners()
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("Error cancelling irrigation listeners: %s", err)

        for tracker in self.light_cycle_trackers.values():
            try:
                tracker.unload()
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("Error unloading light cycle tracker: %s", err)

        for controllers in self.environment_controllers.values():
            for controller in controllers:
                try:
                    controller.unload()
                except Exception as err:  # noqa: BLE001
                    _LOGGER.error("Error unloading environment controller: %s", err)
