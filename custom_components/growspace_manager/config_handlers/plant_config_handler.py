"""Plant Configuration Handler for Growspace Manager."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import Growspace, Plant
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import selector

from . import BaseConfigHandler

_LOGGER = logging.getLogger(__name__)


class PlantConfigHandler(BaseConfigHandler[dict[str, Any]]):
    """Handler for Plant configuration steps."""

    async def async_step_manage_plants(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle plant management step."""
        if self.config_entry is None:
            return self.flow.async_abort(reason="setup_error")
        coordinator = self.config_entry.runtime_data
        if coordinator is None:
            return self.flow.async_abort(reason="setup_error")

        if user_input is not None:
            action = user_input.get("action")

            if action == "add":
                return await self.async_step_select_growspace_for_plant()
            if action == "update" and user_input.get("plant_id"):
                self.flow.selected_plant_id = user_input["plant_id"]
                return await self.async_step_update_plant()
            if action == "remove" and user_input.get("plant_id"):
                try:
                    plant = coordinator.plants.get(user_input["plant_id"])
                    if plant:
                        await self.async_destroy_plant(plant.growspace_id, plant.id)
                except Exception:
                    _LOGGER.exception("Error removing plant")
                    return self.flow.async_show_form(
                        step_id="manage_plants",
                        data_schema=self.get_plant_management_schema(coordinator),
                        errors={"base": "remove_failed"},
                    )
            if action == "back":
                return await self.flow.async_step_init()

        return self.flow.async_show_form(
            step_id="manage_plants",
            data_schema=self.get_plant_management_schema(coordinator),
        )

    async def async_step_select_growspace_for_plant(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle growspace selection for plant step."""
        if self.config_entry is None:
            return self.flow.async_abort(reason="setup_error")
        coordinator = self.config_entry.runtime_data
        if coordinator is None:
            return self.flow.async_abort(reason="setup_error")

        if user_input is not None:
            self.flow.selected_growspace_id = user_input["growspace_id"]
            return await self.async_step_add_plant()

        growspace_options = coordinator.growspace_service.get_sorted_growspace_options()
        if not growspace_options:
            return self.flow.async_abort(reason="no_growspaces")

        schema: dict[Any, Any] = {
            vol.Required("growspace_id"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value=gid, label=name)
                        for gid, name in growspace_options
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        }

        return self.flow.async_show_form(
            step_id="select_growspace_for_plant",
            data_schema=vol.Schema(schema),
        )

    async def async_step_add_plant(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle adding a plant step."""
        if self.config_entry is None:
            return self.flow.async_abort(reason="setup_error")
        coordinator = self.config_entry.runtime_data
        if coordinator is None:
            return self.flow.async_abort(reason="setup_error")
        growspace_id = self.flow.selected_growspace_id
        growspace = coordinator.growspaces.get(growspace_id)

        if user_input is not None:
            try:
                await self.async_add_plant(
                    growspace_id=growspace_id,
                    strain=user_input["strain"],
                    row=user_input["row"],
                    col=user_input["col"],
                    phenotype=user_input.get("phenotype"),
                    veg_start=user_input.get("veg_start"),
                    flower_start=user_input.get("flower_start"),
                )
                return self.flow.async_create_entry(title="", data={})
            except Exception as err:
                _LOGGER.exception("Error adding plant")
                return self.flow.async_show_form(
                    step_id="add_plant",
                    data_schema=self.get_add_plant_schema(growspace, coordinator),
                    errors={"base": str(err)},
                )

        return self.flow.async_show_form(
            step_id="add_plant",
            data_schema=self.get_add_plant_schema(growspace, coordinator),
        )

    async def async_step_update_plant(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle updating a plant step."""
        if self.config_entry is None:
            return self.flow.async_abort(reason="setup_error")
        coordinator = self.config_entry.runtime_data
        if coordinator is None:
            return self.flow.async_abort(reason="setup_error")
        plant_id = self.flow.selected_plant_id
        plant = coordinator.plants.get(plant_id)

        if not plant:
            return self.flow.async_abort(reason="plant_not_found")

        if user_input is not None:
            try:
                # Filter out empty values
                update_data = {k: v for k, v in user_input.items() if v}
                await self.async_update_plant(plant_id, **update_data)
                return self.flow.async_create_entry(title="", data={})
            except Exception as err:
                _LOGGER.exception("Error updating plant")
                return self.flow.async_show_form(
                    step_id="update_plant",
                    data_schema=self.get_update_plant_schema(plant, coordinator),
                    errors={"base": str(err)},
                )

        return self.flow.async_show_form(
            step_id="update_plant",
            data_schema=self.get_update_plant_schema(plant, coordinator),
        )

    def get_plant_management_schema(
        self, coordinator: GrowspaceCoordinator
    ) -> vol.Schema:
        """Build the schema for the plant management menu."""
        plant_options = [
            selector.SelectOptionDict(
                value=p_id, label=f"{p.strain} ({p.growspace_id} R{p.row}C{p.col})"
            )
            for p_id, p in coordinator.plants.items()
        ]

        schema_dict: dict[vol.Optional | vol.Required, Any] = {
            vol.Required("action"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value="add", label="Add New Plant"),
                        selector.SelectOptionDict(value="update", label="Update Plant"),
                        selector.SelectOptionDict(value="remove", label="Remove Plant"),
                        selector.SelectOptionDict(
                            value="back", label="Back to Main Menu"
                        ),
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        }

        if plant_options:
            schema_dict[vol.Optional("plant_id")] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=plant_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )

        return vol.Schema(schema_dict)

    def get_growspace_selection_schema(
        self, growspace_devices: list[Any], coordinator: GrowspaceCoordinator
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

    def get_add_plant_schema(
        self,
        growspace: Growspace | None,
        coordinator: GrowspaceCoordinator | None = None,
    ) -> vol.Schema:
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

    def get_update_plant_schema(
        self, plant: Plant | None, coordinator: GrowspaceCoordinator
    ) -> vol.Schema:
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

    async def async_harvest_plant(
        self, growspace_id: str, plant_id: str, harvest_weight: float
    ) -> None:
        """Harvest a plant."""
        if self.config_entry is None:
            raise ValueError("Coordinator not found")
        coordinator = self.config_entry.runtime_data
        await coordinator.async_harvest_plant(growspace_id, plant_id, harvest_weight)

    async def async_destroy_plant(self, growspace_id: str, plant_id: str) -> None:
        """Destroy a plant."""
        if self.config_entry is None:
            raise ValueError("Coordinator not found")
        coordinator = self.config_entry.runtime_data
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
        if self.config_entry is None:
            raise ValueError("Coordinator not found")
        coordinator = self.config_entry.runtime_data
        if coordinator is None:
            raise ValueError("Coordinator not found")
        await coordinator.async_add_plant(
            growspace_id=growspace_id,
            strain=strain,
            row=row,
            col=col,
            phenotype=phenotype,
            veg_start=veg_start,
            flower_start=flower_start,
        )

    async def async_update_plant(self, plant_id: str, **kwargs: Any) -> None:
        """Update an existing plant."""
        if self.config_entry is None:
            raise ValueError("Coordinator not found")
        coordinator = self.config_entry.runtime_data
        if coordinator is None:
            raise ValueError("Coordinator not found")
        await coordinator.async_update_plant(plant_id, **kwargs)
