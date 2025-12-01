"""Plant Configuration Handler for Growspace Manager."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.helpers import selector

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class PlantConfigHandler:
    """Handler for Plant configuration steps."""

    def __init__(self, hass, config_entry):
        """Initialize the Plant config handler."""
        self.hass = hass
        self.config_entry = config_entry

    def get_plant_management_schema(self, coordinator) -> vol.Schema:
        """Build the schema for the plant management menu."""
        growspace_options = coordinator.get_sorted_growspace_options()

        schema = {
            vol.Required("action", default="add"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value="add", label="Add Plant"),
                        selector.SelectOptionDict(value="edit", label="Edit Plant"),
                        selector.SelectOptionDict(value="move", label="Move Plant"),
                        selector.SelectOptionDict(
                            value="harvest", label="Harvest Plant"
                        ),
                        selector.SelectOptionDict(
                            value="destroy", label="Destroy Plant"
                        ),
                        selector.SelectOptionDict(
                            value="back", label="Back to Main Menu"
                        ),
                    ]
                )
            ),
        }

        if growspace_options:
            schema[vol.Optional("growspace_id")] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": gs_id, "label": name}
                        for gs_id, name in growspace_options
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )

        return vol.Schema(schema)

    async def async_harvest_plant(
        self, growspace_id: str, plant_id: str, harvest_weight: float
    ) -> None:
        """Harvest a plant."""
        coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]["coordinator"]
        await coordinator.async_harvest_plant(growspace_id, plant_id, harvest_weight)

    async def async_destroy_plant(self, growspace_id: str, plant_id: str) -> None:
        """Destroy a plant."""
        coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]["coordinator"]
        await coordinator.async_remove_plant(growspace_id, plant_id)

    async def async_add_plant(
        self,
        growspace_id: str,
        strain: str,
        row: int,
        col: int,
        phenotype: str | None = None,
        veg_start: str | None = None,
        flower_start: str | None = None,
    ) -> None:
        """Add a new plant."""
        coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]["coordinator"]
        await coordinator.async_add_plant(
            growspace_id=growspace_id,
            strain=strain,
            row=row,
            col=col,
            phenotype=phenotype,
            veg_start=veg_start,
            flower_start=flower_start,
        )
        
    async def async_update_plant(self, plant_id: str, **kwargs) -> None:
        """Update an existing plant."""
        coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]["coordinator"]
        await coordinator.async_update_plant(plant_id, **kwargs)

    def get_add_plant_schema(self, growspace, coordinator) -> vol.Schema:
        """Build the schema for adding a plant."""
        # This would need to be adapted from the original config_flow logic
        # For now, I'll implement a basic schema and refine it if needed
        # We need to access the strain library for strains
        
        strains = []
        if hasattr(coordinator, "strain_library"):
             strains = coordinator.strain_library.get_all_strains()
        
        strain_options = [
            selector.SelectOptionDict(value=s.id, label=s.name)
            for s in strains
        ]
        
        schema = {
            vol.Required("strain"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=strain_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    custom_value=True,
                )
            ),
            vol.Required("row", default=1): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=growspace.rows, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Required("col", default=1): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=growspace.plants_per_row, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Optional("phenotype"): selector.TextSelector(),
            vol.Optional("veg_start"): selector.DateSelector(),
            vol.Optional("flower_start"): selector.DateSelector(),
        }
        return vol.Schema(schema)

    def get_update_plant_schema(self, plant, coordinator) -> vol.Schema:
        """Build the schema for updating a plant."""
        # Similar to add schema but with defaults from plant
        strains = []
        if hasattr(coordinator, "strain_library"):
             strains = coordinator.strain_library.get_all_strains()
        
        strain_options = [
            selector.SelectOptionDict(value=s.id, label=s.name)
            for s in strains
        ]

        schema = {
            vol.Optional("strain", default=plant.strain): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=strain_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    custom_value=True,
                )
            ),
            vol.Optional("phenotype", default=plant.phenotype or ""): selector.TextSelector(),
            vol.Optional("veg_start"): selector.DateSelector(),
            vol.Optional("flower_start"): selector.DateSelector(),
        }
        return vol.Schema(schema)
