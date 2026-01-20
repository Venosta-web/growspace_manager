"""Strain configuration handler for Growspace Manager."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

import voluptuous as vol

from custom_components.growspace_manager.schemas import ADD_STRAIN_SCHEMA
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import selector

from . import BaseConfigHandler

_LOGGER = logging.getLogger(__name__)


class StrainConfigHandler(BaseConfigHandler[dict[str, Any]]):
    """Handle strain library configuration steps."""

    async def async_step_manage_strain_library(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the strain library."""
        if self.config_entry is None:
            return self.flow.async_abort(reason="setup_error")
        coordinator = self.config_entry.runtime_data
        if coordinator is None:
            return self.flow.async_abort(reason="setup_error")

        if user_input is not None:
            action = user_input.get("action")
            if action == "add_strain":
                return await self.async_step_add_strain()
            if action == "edit_strain":
                self.flow.selected_strain_id = user_input.get("strain_id")
                return await self.async_step_edit_strain()
            if action == "delete_strain":
                try:
                    await coordinator.strain_library.remove_strain(
                        user_input.get("strain_id")
                    )
                except Exception:
                    _LOGGER.exception("Error deleting strain")
                    return self.flow.async_show_form(
                        step_id="manage_strain_library",
                        data_schema=self._get_strain_library_menu_schema(coordinator),
                        errors={"base": "delete_failed"},
                    )
                return self.flow.async_show_form(
                    step_id="manage_strain_library",
                    data_schema=self._get_strain_library_menu_schema(coordinator),
                )
            if action == "import":
                return await self.async_step_import_strain_library()
            if action == "export":
                return await self.async_step_export_strain_library()
            if action == "back":
                return await self.flow.async_step_init()

        return self.flow.async_show_form(
            step_id="manage_strain_library",
            data_schema=self._get_strain_library_menu_schema(coordinator),
        )

    async def async_step_import_strain_library(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Import strain library from ZIP."""
        errors = {}
        if user_input is not None:
            if self.config_entry is None:
                errors["base"] = "setup_error"
            else:
                try:
                    coordinator = self.config_entry.runtime_data
                    file_path = user_input["file_path"]

                    await coordinator.strain_library.import_library_from_zip(
                        file_path, merge=True
                    )

                    # Reload strains to reflect changes
                    await coordinator.strain_library.async_load()

                    return await self.async_step_manage_strain_library()
                except FileNotFoundError:
                    errors["base"] = "file_not_found"
                except ValueError:
                    errors["base"] = "invalid_zip"
                except Exception:
                    _LOGGER.exception("Import failed")
                    errors["base"] = "import_failed"

        return self.flow.async_show_form(
            step_id="import_strain_library",
            data_schema=vol.Schema(
                {
                    vol.Required("file_path"): selector.TextSelector(),
                }
            ),
            errors=errors,
            description_placeholders={
                "default_path": "/config/strain_library_export.zip"
            },
        )

    async def async_step_export_strain_library(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Export strain library to ZIP."""
        if user_input is not None:
            return await self.async_step_manage_strain_library()

        if self.config_entry is None:
            return self.flow.async_abort(reason="setup_error")
        coordinator = self.config_entry.runtime_data

        # Default export location
        export_dir = self.flow.hass.config.path("exports")

        try:
            zip_path = await coordinator.strain_library.export_library_to_zip(
                export_dir
            )
            return self.flow.async_show_form(
                step_id="export_strain_library",
                description_placeholders={"path": zip_path},
                last_step=True,
            )
        except Exception:
            _LOGGER.exception("Export failed")
            return self.flow.async_abort(reason="export_failed")

    def _get_strain_library_menu_schema(
        self, coordinator: GrowspaceCoordinator
    ) -> vol.Schema:
        """Build the schema for the strain library menu."""
        if not coordinator.strain_library:
            return vol.Schema({})

        strains = list(coordinator.strain_library.get_all().keys())
        strain_options = [
            selector.SelectOptionDict(value=name, label=name) for name in strains
        ]

        schema_dict: dict[vol.Optional | vol.Required, Any] = {
            vol.Required("action"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(
                            value="add_strain", label="Add New Strain"
                        ),
                        selector.SelectOptionDict(
                            value="edit_strain", label="Edit Strain"
                        ),
                        selector.SelectOptionDict(
                            value="delete_strain", label="Delete Strain"
                        ),
                        selector.SelectOptionDict(
                            value="import", label="Import Library"
                        ),
                        selector.SelectOptionDict(
                            value="export", label="Export Library"
                        ),
                        selector.SelectOptionDict(
                            value="back", label="Back to Main Menu"
                        ),
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        }

        if strain_options:
            schema_dict[vol.Optional("strain_id")] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=strain_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )

        return vol.Schema(schema_dict)

    async def async_step_add_strain(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for adding a new strain."""
        if self.config_entry is None:
            return self.flow.async_abort(reason="setup_error")
        coordinator = self.config_entry.runtime_data

        if user_input is not None:
            await coordinator.strain_library.async_add_strain(
                name=user_input["strain"],
                breeder=user_input.get("breeder"),
                strain_type=user_input.get("type"),
                sex=user_input.get("sex"),
                description=user_input.get("description"),
                flowering_days=user_input.get("flower_days_max"),
            )
            return await self.async_step_manage_strain_library()

        return self.flow.async_show_form(
            step_id="add_strain",
            data_schema=ADD_STRAIN_SCHEMA,
        )

    async def async_step_edit_strain(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for editing a strain."""
        if user_input is not None:
            return await self.async_step_manage_strain_library()

        return self.flow.async_show_form(
            step_id="edit_strain",
            data_schema=ADD_STRAIN_SCHEMA,
        )
