"""Subsystem Manager for Growspace Manager.

This module encapsulates the management of sub-coordinators (Irrigation, Dehumidifier)
to reduce the responsibility of the main GrowspaceCoordinator.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from ..dehumidifier_coordinator import (
    DehumidifierCoordinator,
)
from ..humidifier_coordinator import (
    HumidifierCoordinator,
)
from ..irrigation_coordinator import (
    IrrigationCoordinator,
)
from ..light_cycle_tracker import LightCycleTracker
from ..vwc_irrigation_coordinator import (
    VWCIrrigationCoordinator,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

if TYPE_CHECKING:
    from ..coordinator import GrowspaceCoordinator
    from ..models import Growspace

_LOGGER = logging.getLogger(__name__)


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
        self.dehumidifier_coordinators: dict[str, DehumidifierCoordinator] = {}
        self.humidifier_coordinators: dict[str, HumidifierCoordinator] = {}
        self.light_cycle_trackers: dict[str, LightCycleTracker] = {}

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

        # Dehumidifier coordinator setup
        dehumidifier_coordinator = DehumidifierCoordinator(
            self.hass, self.entry, growspace_id, self.coordinator
        )
        await dehumidifier_coordinator.async_setup()
        self.dehumidifier_coordinators[growspace_id] = dehumidifier_coordinator

        # Humidifier coordinator setup
        humidifier_coordinator = HumidifierCoordinator(
            self.hass, self.entry, growspace_id, self.coordinator
        )
        await humidifier_coordinator.async_setup()
        self.humidifier_coordinators[growspace_id] = humidifier_coordinator

        # Light cycle tracker setup
        light_cycle_tracker = LightCycleTracker(self.hass, growspace_id, self.coordinator)
        await light_cycle_tracker.async_setup()
        self.light_cycle_trackers[growspace_id] = light_cycle_tracker

    def async_cancel_all(self) -> None:
        """Cancel all sub-coordinator listeners."""
        for irr_coordinator in self.irrigation_coordinators.values():
            try:
                irr_coordinator.async_cancel_listeners()
            except Exception as err:
                _LOGGER.error("Error cancelling irrigation listeners: %s", err)

        for dehum_coordinator in self.dehumidifier_coordinators.values():
            try:
                dehum_coordinator.unload()
            except Exception as err:
                _LOGGER.error("Error unloading dehumidifier coordinator: %s", err)

        for hum_coordinator in self.humidifier_coordinators.values():
            try:
                hum_coordinator.unload()
            except Exception as err:
                _LOGGER.error("Error unloading humidifier coordinator: %s", err)

        for tracker in self.light_cycle_trackers.values():
            try:
                tracker.unload()
            except Exception as err:
                _LOGGER.error("Error unloading light cycle tracker: %s", err)

