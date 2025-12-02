"""Plant Configuration Handler for Growspace Manager."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.helpers import selector

from ..const import DOMAIN

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
        await coordinator.async_remove_plant(plant_id)

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

    def get_growspace_selection_schema(
        self, growspace_devices, coordinator
    ) -> vol.Schema:
        """Build the schema for selecting a growspace from the device registry."""
        growspace_options = []

        for device in growspace_devices:
            # Extract growspace_id from device identifiers
            growspace_id = None
            for identifier_set in device.identifiers:
                if identifier_set[0] == DOMAIN:
                    growspace_id = identifier_set[1]
                    break

            if growspace_id:
                growspace_obj = coordinator.growspaces.get(growspace_id)
                rows = getattr(growspace_obj, "rows", "?")
                plants_per_row = getattr(growspace_obj, "plants_per_row", "?")

                growspace_options.append(
                    selector.SelectOptionDict(
                        value=growspace_id,
                        label=f"{device.name} ({rows}x{plants_per_row})",
                    )
                )

        return vol.Schema(
            {
                vol.Required("growspace_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=growspace_options)
                ),
            }
        )

    def get_add_plant_schema(self, growspace, coordinator=None) -> vol.Schema:
        """Build the schema for the add plant form."""
        if not growspace:
            return vol.Schema({})

        rows = getattr(growspace, "rows", 10)
        plants_per_row = getattr(growspace, "plants_per_row", 10)

        # Get strain options for autocomplete
        strain_options = []
        if coordinator:
            strain_list = coordinator.get_strain_options()
            strain_options = [
                selector.SelectOptionDict(value=strain, label=strain)
                for strain in strain_list
            ]

        strain_selector = (
            selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=strain_options,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
            if strain_options
            else selector.TextSelector()
        )

        # Relax limits for special growspaces
        is_special = growspace.id in ["mother", "clone", "dry", "cure"]
        max_row = 100 if is_special else rows
        max_col = 100 if is_special else plants_per_row

        return vol.Schema(
            {
                vol.Required("strain"): strain_selector,
                vol.Optional("phenotype"): selector.TextSelector(),
                vol.Required("row", default=1): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=max_row, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required("col", default=1): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=max_col, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional("veg_start"): selector.DateSelector(),
                vol.Optional("flower_start"): selector.DateSelector(),
            }
        )

    def get_update_plant_schema(self, plant, coordinator) -> vol.Schema:
        """Build the schema for the update plant form."""
        growspace = coordinator.growspaces.get(plant.growspace_id) if plant else None

        # Ensure rows and plants_per_row are integers
        rows = int(growspace.rows) if growspace else 10
        plants_per_row = int(growspace.plants_per_row) if growspace else 10

        # Get strain options for autocomplete
        strain_options = []
        strain_list = coordinator.get_strain_options()
        strain_options = [
            selector.SelectOptionDict(value=strain, label=strain)
            for strain in strain_list
        ]

        # Use autocomplete selector if we have strains, otherwise text input
        if strain_options:
            strain_selector = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=strain_options,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        else:
            strain_selector = selector.TextSelector()

        # Relax limits for special growspaces
        is_special = growspace and growspace.id in ["mother", "clone", "dry", "cure"]
        max_row = 100 if is_special else rows
        max_col = 100 if is_special else plants_per_row

        return vol.Schema(
            {
                vol.Optional(
                    "strain", default=plant.strain if plant else ""
                ): strain_selector,
                vol.Optional(
                    "phenotype", default=plant.phenotype if plant else ""
                ): selector.TextSelector(),
                vol.Optional(
                    "row", default=plant.row if plant else 1
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=max_row, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    "col", default=plant.col if plant else 1
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=max_col, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional("veg_start"): selector.DateSelector(),
                vol.Optional("flower_start"): selector.DateSelector(),
            }
        )
