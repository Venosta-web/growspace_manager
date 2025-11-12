"""Enhanced config flow for Growspace Manager integration with plant management GUI."""

from __future__ import annotations

import logging
from typing import Any, Optional

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import selector

from .const import DEFAULT_NAME, DOMAIN
from .models import Growspace, Plant

_LOGGER = logging.getLogger(__name__)

# Translation strings for the options flow
STEP_INIT = {
    "manage_growspaces": "Manage Growspaces",
    "manage_plants": "Manage Plants",
}

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Optional("name", default=DEFAULT_NAME): cv.string,
    },
)


async def ensure_default_growspaces(hass: HomeAssistant, coordinator):
    """Ensure default growspaces (dry, cure, mother, clone, veg) exist."""
    try:
        # Create special growspaces with their canonical IDs
        default_growspaces = [
            ("dry", "dry", 3, 3),
            ("cure", "cure", 3, 3),
            ("mother", "mother", 3, 3),
            ("clone", "clone", 5, 5),
            ("veg", "veg", 5, 5),
        ]

        created_count = 0
        for growspace_id, name, rows, plants_per_row in default_growspaces:
            # Use the coordinator's method to ensure special growspaces
            canonical_id = coordinator.ensure_special_growspace(
                growspace_id,
                name,
                rows,
                plants_per_row,
            )
            if canonical_id not in coordinator.growspaces:
                created_count += 1

        if created_count > 0:
            # Save the updated data
            await coordinator.async_save()
            # Notify listeners of the changes
            await coordinator.async_set_updated_data(coordinator.data)
            _LOGGER.info("Created %s default growspaces", created_count)
        else:
            _LOGGER.info("All default growspaces already exist")

    except (ValueError, TypeError, IOError) as e:
        _LOGGER.error("Error creating default growspaces: %s", e)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Growspace Manager."""

    VERSION = 1
    MINOR_VERSION = 1
    integration_name = "Growspace Manager"

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            name = user_input.get("name", DEFAULT_NAME)
            _LOGGER.debug("Creating entry for Growspace Manager with name: %s", name)
            return self.async_create_entry(
                title=name,
                data={"name": name},
            )

        _LOGGER.debug("Showing initial user form for Growspace Manager")
        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
        )

    async def async_step_add_growspace(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Add a growspace during initial setup."""
        if user_input is not None:
            _LOGGER.debug("Storing pending growspace data: %s", user_input)
            self.hass.data.setdefault(DOMAIN, {})
            self.hass.data[DOMAIN]["pending_growspace"] = {
                "name": user_input["name"],
                "rows": user_input["rows"],
                "plants_per_row": user_input["plants_per_row"],
                "notification_target": user_input.get("notification_target"),
            }
            return self.async_create_entry(
                title=getattr(self, "_integration_name", DEFAULT_NAME),
                data={"name": getattr(self, "_integration_name", DEFAULT_NAME)},
            )

        _LOGGER.debug("Showing add_growspace form")
        return self.async_show_form(
            step_id="add_growspace",
            data_schema=self._get_add_growspace_schema(),
        )

    def _get_add_growspace_schema(self):
        """Dynamic schema for adding a growspace during config flow."""
        base = {
            vol.Required("name"): selector.TextSelector(),
            vol.Required("rows", default=4): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    max=20,
                    mode=selector.NumberSelectorMode.BOX,
                ),
            ),
            vol.Required("plants_per_row", default=4): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    max=20,
                    mode=selector.NumberSelectorMode.BOX,
                ),
            ),
            vol.Optional("notification_target"): selector.TextSelector(),
        }

        # Get available notify services
        services = self.hass.services.async_services().get("notify", {})
        notification_options = [
            selector.SelectOptionDict(
                value=service,
                label=service.replace("mobile_app_", "").replace("_", " ").title(),
            )
            for service in services
            if service.startswith("mobile_app_")
        ]

        if notification_options:
            base[vol.Optional("notification_target")] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=notification_options,
                    custom_value=False,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                ),
            )
        else:
            base[vol.Optional("notification_target")] = selector.TextSelector()

        return vol.Schema(base)

    async def async_step_reauth(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle re-authentication."""
        if user_input is not None:
            # Here you would typically validate the new credentials
            # and update the config entry
            _LOGGER.debug("Re-authentication successful")
            await self.hass.config_entries.async_reload(self.context["entry_id"])
            return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth",
            data_schema=vol.Schema({}), # Add your re-auth schema here
            description_placeholders={"name": self.context["title_placeholders"]["name"]},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlowHandler:
        """Create the options flow."""
        return OptionsFlowHandler()


class OptionsFlowHandler(OptionsFlow):
    """Growspace Manager options flow."""

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Initial options menu."""
        if user_input is not None:
            action = user_input.get("action")
            if action == "manage_growspaces":
                return await self.async_step_manage_growspaces(user_input)
            if action == "manage_plants":
                return await self.async_step_manage_plants()
            if action == "configure_environment":
                return await self.async_step_select_growspace_for_env()
            if action == "reauth":
                return await self.async_step_reauth()
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self._get_main_menu_schema(),
        )

    async def async_step_manage_growspaces(
        self,
        user_input: Optional[dict[str, Any]] | None,
    ) -> ConfigFlowResult:
        """Manage growspaces."""
        try:
            coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id][
                "coordinator"
            ]
        except KeyError:
            _LOGGER.error(
                "Coordinator not found - integration may not be properly set up",
            )
            return self.async_abort(reason="setup_error")

        if user_input is not None:
            action = user_input.get("action")

            if action == "add":
                return await self.async_step_add_growspace()
            if action == "update" and user_input.get("growspace_id"):
                self._selected_growspace_id = user_input["growspace_id"]
                return await self.async_step_update_growspace()
            if action == "remove" and user_input.get("growspace_id"):
                try:
                    await coordinator.async_remove_growspace(user_input["growspace_id"])
                except (ValueError, KeyError) as err:
                    _LOGGER.error("Error removing growspace: %s", err, exc_info=True)
                    return self.async_show_form(
                        step_id="manage_growspaces",
                        data_schema=self._get_growspace_management_schema(coordinator),
                        errors={"base": "remove_failed"},
                    )
            elif action == "back":
                return self.async_show_form(
                    step_id="init",
                    data_schema=self.add_suggested_values_to_schema(
                        self._get_main_menu_schema(),
                        self.config_entry.options,
                    ),
                )

        return self.async_show_form(
            step_id="manage_growspaces",
            data_schema=self._get_growspace_management_schema(coordinator),
        )

    async def async_step_select_growspace_for_env(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Let the user select which growspace to configure."""
        coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]["coordinator"]
        growspace_options = coordinator.get_sorted_growspace_options()

        if not growspace_options:
            return self.async_abort(reason="no_growspaces")

        if user_input is not None:
            self._selected_growspace_id = user_input["growspace_id"]
            return await self.async_step_configure_environment()

        schema = vol.Schema(
            {
                vol.Required("growspace_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": gs_id, "label": name}
                            for gs_id, name in growspace_options
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    ),
                ),
            },
        )
        return self.async_show_form(
            step_id="select_growspace_for_env",
            data_schema=schema,
        )

    async def async_step_configure_environment(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle the configuration of environment sensors."""
        coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]["coordinator"]
        growspace = coordinator.growspaces.get(self._selected_growspace_id)

        if not growspace:
            return self.async_abort(reason="growspace_not_found")

        # Get existing options for this growspace
        options = self.config_entry.options.get(self._selected_growspace_id, {})

        if user_input is not None:
            # Build environment config from user input
            env_config = {
                "temperature_sensor": user_input.get("temperature_sensor"),
                "humidity_sensor": user_input.get("humidity_sensor"),
                "vpd_sensor": user_input.get("vpd_sensor"),
            }

            # Add optional sensors if configured
            if user_input.get("configure_co2") and user_input.get("co2_sensor"):
                env_config["co2_sensor"] = user_input.get("co2_sensor")

            if user_input.get("configure_fan") and user_input.get("circulation_fan"):
                env_config["circulation_fan"] = user_input.get("circulation_fan")

            # Add thresholds
            env_config["stress_threshold"] = user_input.get("stress_threshold", 0.70)
            env_config["mold_threshold"] = user_input.get("mold_threshold", 0.75)

            # Also store the checkbox states for UI persistence
            env_config["configure_co2"] = user_input.get("configure_co2", False)
            env_config["configure_fan"] = user_input.get("configure_fan", False)

            # Apply to growspace immediately
            growspace.environment_config = env_config
            await coordinator.async_save()

            # Trigger coordinator refresh to create binary sensors
            await coordinator.async_refresh()

            # Save to config entry options
            final_options = self.config_entry.options.copy()
            final_options[self._selected_growspace_id] = env_config

            _LOGGER.info(
                "Environment configuration saved for growspace %s: %s",
                growspace.name,
                env_config,
            )

            return self.async_create_entry(title="", data=final_options)

        # Build dynamic schema based on current options
        schema_dict = {}

        # Required sensors
        schema_dict[
            vol.Required(
                "temperature_sensor",
                default=options.get("temperature_sensor"),
            )
        ] = selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=["sensor", "input_number"],
                device_class=["temperature"],
            ),
        )

        schema_dict[
            vol.Required("humidity_sensor", default=options.get("humidity_sensor"))
        ] = selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=["sensor", "input_number"],
                device_class=["humidity"],
            ),
        )

        schema_dict[vol.Required("vpd_sensor", default=options.get("vpd_sensor"))] = (
            selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["sensor", "input_number"]),
            )
        )

        # CO2 sensor (optional)
        co2_enabled = options.get("configure_co2", bool(options.get("co2_sensor")))
        schema_dict[vol.Optional("configure_co2", default=co2_enabled)] = (
            selector.BooleanSelector()
        )

        if co2_enabled or (user_input and user_input.get("configure_co2")):
            schema_dict[
                vol.Optional("co2_sensor", default=options.get("co2_sensor"))
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["sensor", "input_number"],
                    device_class=["carbon_dioxide"],
                ),
            )

        # Circulation fan (optional)
        fan_enabled = options.get("configure_fan", bool(options.get("circulation_fan")))
        schema_dict[vol.Optional("configure_fan", default=fan_enabled)] = (
            selector.BooleanSelector()
        )

        if fan_enabled or (user_input and user_input.get("configure_fan")):
            schema_dict[
                vol.Optional("circulation_fan", default=options.get("circulation_fan"))
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["fan", "switch", "input_boolean"]
                ),
            )

        # Thresholds
        schema_dict[
            vol.Optional(
                "stress_threshold",
                default=options.get("stress_threshold", 0.70),
            )
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0.5,
                max=0.95,
                step=0.05,
                mode=selector.NumberSelectorMode.SLIDER,
            ),
        )

        schema_dict[
            vol.Optional("mold_threshold", default=options.get("mold_threshold", 0.75))
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0.5,
                max=0.95,
                step=0.05,
                mode=selector.NumberSelectorMode.SLIDER,
            ),
        )

        return self.async_show_form(
            step_id="configure_environment",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={"growspace_name": growspace.name},
        )

    async def async_step_add_growspace(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Add a new growspace."""
        try:
            coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id][
                "coordinator"
            ]
        except KeyError:
            _LOGGER.error(
                "Coordinator not found - integration may not be properly set up",
            )
            return self.async_abort(reason="setup_error")

        if user_input is not None:
            try:
                _LOGGER.debug("Adding growspace: %s", user_input)
                await coordinator.async_add_growspace(
                    name=user_input["name"],
                    rows=user_input["rows"],
                    plants_per_row=user_input["plants_per_row"],
                    notification_target=user_input.get("notification_target"),
                )
                return self.async_create_entry(title="", data={})
            except (ValueError, TypeError) as e:
                _LOGGER.error("Error adding growspace: %s", e)
                return self.async_show_form(
                    step_id="add_growspace",
                    data_schema=self._get_add_growspace_schema(),
                    errors={"base": "add_failed"},
                )

        _LOGGER.debug("Showing add_growspace form")
        return self.async_show_form(
            step_id="add_growspace",
            data_schema=self._get_add_growspace_schema(),
        )

    async def async_step_update_growspace(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Update an existing growspace."""
        try:
            coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id][
                "coordinator"
            ]
        except KeyError:
            _LOGGER.error(
                "Coordinator not found - integration may not be properly set up",
            )
            return self.async_abort(reason="setup_error")

        growspace = coordinator.growspaces.get(self._selected_growspace_id)

        if not growspace:
            _LOGGER.error("Growspace not found: %s", self._selected_growspace_id)
            return self.async_abort(reason="growspace_not_found")

        if user_input is not None:
            try:
                # Filter out empty values
                update_data = {k: v for k, v in user_input.items() if v}

                # Call coordinator's update method (you'll need to implement this)
                await coordinator.async_update_growspace(
                    self._selected_growspace_id,
                    **update_data,
                )

                _LOGGER.info(
                    "Successfully updated growspace: %s",
                    self._selected_growspace_id,
                )
                return self.async_create_entry(title="", data={})

            except ValueError as err:
                _LOGGER.error("Error updating growspace: %s", err, exc_info=True)
                return self.async_show_form(
                    step_id="update_growspace",
                    data_schema=self._get_update_growspace_schema(growspace),
                    errors={"base": "update_failed"},
                )

        return self.async_show_form(
            step_id="update_growspace",
            data_schema=self._get_update_growspace_schema(growspace),
        )

    async def async_step_manage_plants(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Manage plants."""
        coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]["coordinator"]

        if user_input is not None:
            action = user_input.get("action")

            if action == "add":
                return await self.async_step_select_growspace_for_plant()
            if action == "update" and user_input.get("plant_id"):
                self._selected_plant_id = user_input["plant_id"]
                return await self.async_step_update_plant()
            if action == "remove" and user_input.get("plant_id"):
                try:
                    await coordinator.async_remove_plant(user_input["plant_id"])
                except (ValueError, KeyError) as e:
                    return self.async_show_form(
                        step_id="manage_plants",
                        data_schema=self._get_plant_management_schema(coordinator),
                        errors={"base": str(e)},
                    )
            if action == "back":
                return self.async_show_form(
                    step_id="init",
                    data_schema=self.add_suggested_values_to_schema(
                        coordinator,
                        self.config_entry.options,
                    ),
                )

        return self.async_show_form(
            step_id="manage_plants",
            data_schema=self._get_plant_management_schema(coordinator),
        )
                        errors={"base": str(Exception)},
                    )
            if action == "back":
                return self.async_show_form(
                    step_id="init",
                    data_schema=self.add_suggested_values_to_schema(
                        coordinator,
                        self.config_entry.options,
                    ),
                )

        return self.async_show_form(
            step_id="manage_plants",
            data_schema=self._get_plant_management_schema(coordinator),
        )

    async def async_step_select_growspace_for_plant(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Select growspace for new plant."""
        try:
            coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id][
                "coordinator"
            ]
            # Reload coordinator data from storage to ensure we have latest growspaces
            store = self.hass.data[DOMAIN][self.config_entry.entry_id]["store"]
            fresh_data = await store.async_load() or {}
            # We must parse the raw data back into objects
            coordinator.growspaces = {
                gid: Growspace.from_dict(gdata)
                for gid, gdata in fresh_data.get("growspaces", {}).items()
            }
            coordinator.plants = {
                pid: Plant.from_dict(pdata)
                for pid, pdata in fresh_data.get("plants", {}).items()
            }
            coordinator._notifications_sent = fresh_data.get("notifications_sent", {})
            # Update the data property
            coordinator.data = {
                "growspaces": coordinator.growspaces,
                "plants": coordinator.plants,
                "notifications_sent": coordinator._notifications_sent,
            }
        except KeyError:
            _LOGGER.error(
                "Coordinator not found - integration may not be properly set up",
            )
            return self.async_abort(reason="setup_error")

        _LOGGER.info(f"Config entry ID: {self.config_entry.entry_id}")
        _LOGGER.info(
            f"Available growspaces in coordinator: {list(coordinator.growspaces.keys())}",
        )

        # Get growspaces from device registry
        device_registry = dr.async_get(self.hass)
        devices = device_registry.devices.get_devices_for_config_entry_id(
            self.config_entry.entry_id,
        )

        _LOGGER.info(f"Total devices for config entry: {len(devices)}")
        _LOGGER.info(
            f"All devices: {[(d.name, d.model, d.identifiers) for d in devices]}",
        )

        # Filter for growspace devices
        growspace_devices = [
            device
            for device in devices
            if device.model == "Growspace"
            and any(identifier[0] == DOMAIN for identifier in device.identifiers)
        ]

        _LOGGER.info(f"Found {len(growspace_devices)} growspace devices")
        for device in growspace_devices:
            _LOGGER.info(f"Growspace device: {device.name} - {device.identifiers}")

        if not growspace_devices:
            _LOGGER.warning("No growspace devices found in device registry")
            return self.async_show_form(
                step_id="select_growspace_for_plant",
                data_schema=vol.Schema({}),
                errors={
                    "base": "No growspaces available. Please create a growspace first.",
                },
            )

        if user_input is not None:
            self._selected_growspace_id = user_input["growspace_id"]
            return await self.async_step_add_plant()

        return self.async_show_form(
            step_id="select_growspace_for_plant",
            data_schema=self._get_growspace_selection_schema_from_devices(
                growspace_devices,
                coordinator,
            ),
        )

    async def async_step_add_plant(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Add a new plant."""
        coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]["coordinator"]
        growspace = coordinator.growspaces.get(self._selected_growspace_id)

        if user_input is not None:
            try:
                # Get user-requested position
                row = user_input["row"]
                col = user_input["col"]

                # Check for an occupant at that position
                occupant = None
                for plant in coordinator.get_growspace_plants(
                    self._selected_growspace_id
                ):
                    if plant.row == row and plant.col == col:
                        occupant = plant
                        break

                final_row, final_col = row, col

                if occupant:
                    _LOGGER.info(
                        "Position (%d, %d) in %s is occupied by %s. Finding next available",
                        row,
                        col,
                        self._selected_growspace_id,
                        occupant.strain,
                    )
                    # Position is occupied, find the next available slot
                    new_row, new_col = coordinator.find_first_available_position(
                        self._selected_growspace_id
                    )

                    if new_row is None:
                        # Growspace is full
                        return self.async_show_form(
                            step_id="add_plant",
                            data_schema=self._get_add_plant_schema(
                                growspace, coordinator
                            ),
                            errors={
                                "base": f"Growspace '{growspace.name}' is already full."
                            },
                        )

                    # A new, free slot was found
                    final_row, final_col = new_row, new_col
                    _LOGGER.info(
                        "Assigned plant to next available position: (%d, %d)",
                        final_row,
                        final_col,
                    )

                # Determine stage from dates
                stage = "seedling"  # default
                if user_input.get("flower_start"):
                    stage = "flower"
                elif user_input.get("veg_start"):
                    stage = "veg"

                # Create the plant at the (potentially new) final position
                plant = await coordinator.async_add_plant(
                    growspace_id=self._selected_growspace_id,
                    strain=user_input["strain"],
                    row=final_row,  # <-- Use the final (corrected) row
                    col=final_col,  # <-- Use the final (corrected) col
                    phenotype=user_input.get("phenotype", ""),
                    stage=stage,  # <-- Explicitly set the stage
                    veg_start=user_input.get("veg_start"),
                    flower_start=user_input.get("flower_start"),
                )

                _LOGGER.info(
                    "Successfully created plant %s at position (%d, %d) in growspace %s",
                    plant.plant_id,
                    plant.row,
                    plant.col,
                    plant.growspace_id,
                )

                # The coordinator's async_add_plant method handles saving and refreshing
                return self.async_create_entry(title="", data={})

            except (ValueError, TypeError) as err:
                _LOGGER.exception("Error adding plant from config flow: %s", err)
                return self.async_show_form(
                    step_id="add_plant",
                    data_schema=self._get_add_plant_schema(growspace, coordinator),
                    errors={"base": str(err)},
                )

        # Show the form on initial access
        return self.async_show_form(
            step_id="add_plant",
            data_schema=self._get_add_plant_schema(growspace, coordinator),
        )

    async def async_step_update_plant(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Update an existing plant."""
        coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]["coordinator"]
        plant = coordinator.plants.get(self._selected_plant_id)

        if not plant:
            return self.async_abort(reason="plant_not_found")

        if user_input is not None:
            try:
                # Filter out empty values
                update_data = {k: v for k, v in user_input.items() if v}
                await coordinator.async_update_plant(
                    self._selected_plant_id,
                    **update_data,
                )
                return self.async_create_entry(title="", data={})
            except ValueError as err:
                return self.async_show_form(
                    step_id="update_plant",
                    data_schema=self._get_update_plant_schema(plant, coordinator),
                    errors={"base": str(err)},
                )

        return self.async_show_form(
            step_id="update_plant",
            data_schema=self._get_update_plant_schema(plant, coordinator),
        )

    async def async_step_reauth(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle re-authentication."""
        _LOGGER.debug("Initiating re-authentication flow")
        return await self.hass.config_entries.flow.async_init(
            self.config_entry.domain,
            context={"source": config_entries.SOURCE_REAUTH, "entry_id": self.config_entry.entry_id},
            data=self.config_entry.data,
        )

    def _get_growspace_management_schema(self, coordinator) -> vol.Schema:
        """Get schema for growspace management using object attributes."""
        growspace_options = [
            selector.SelectOptionDict(
                value=growspace_id,
                label=f"{growspace.name} ({len(coordinator.get_growspace_plants(growspace_id))} plants)",
            )
            for growspace_id, growspace in coordinator.growspaces.items()
        ]

        schema: dict[Any, Any] = {
            vol.Required("action"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value="add", label="Add Growspace"),
                        selector.SelectOptionDict(
                            value="update",
                            label="Update Growspace",
                        ),
                        selector.SelectOptionDict(
                            value="remove",
                            label="Remove Growspace",
                        ),
                        selector.SelectOptionDict(
                            value="back",
                            label="← Back to Main Menu",
                        ),
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                ),
            ),
        }

        if growspace_options:
            schema[vol.Optional("growspace_id")] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=growspace_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    custom_value=True,  # ✅ allow typing a new growspace
                ),
            )
        else:
            # If no growspaces exist yet, allow text input only
            schema[vol.Optional("growspace_id")] = selector.TextSelector()

        return vol.Schema(schema)

    def _get_add_growspace_schema(self):
        """Dynamic schema for adding a growspace during options flow."""
        base = {
            vol.Required("name"): selector.TextSelector(),
            vol.Required("rows", default=4): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    max=20,
                    mode=selector.NumberSelectorMode.BOX,
                ),
            ),
            vol.Required("plants_per_row", default=4): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    max=20,
                    mode=selector.NumberSelectorMode.BOX,
                ),
            ),
        }

        # Get available notify services
        services = self.hass.services.async_services().get("notify", {})
        notification_options = [
            selector.SelectOptionDict(
                value=service,
                label=service.replace("mobile_app_", "").replace("_", " ").title(),
            )
            for service in services
            if service.startswith("mobile_app_")
        ]

        if notification_options:
            base[vol.Required("notification_target")] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=notification_options,
                    custom_value=False,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                ),
            )
        else:
            # No notify services available, allow leaving it empty
            _LOGGER.info(
                "No notify services found – notification_target will be optional.",
            )
            base[vol.Required("notification_target")] = selector.TextSelector()

        return vol.Schema(base)

    def _get_update_growspace_schema(self, growspace) -> vol.Schema:
        """Get schema for updating a growspace."""
        if not growspace:
            return vol.Schema({})

        # Get available notify services
        services = self.hass.services.async_services().get("notify", {})
        notification_options = [
            selector.SelectOptionDict(
                value=service,
                label=service.replace("mobile_app_", "").replace("_", " ").title(),
            )
            for service in services
            if service.startswith("mobile_app_")
        ]

        # Add "None" option to allow clearing notification target
        notification_options.insert(
            0,
            selector.SelectOptionDict(value="", label="None (No notifications)"),
        )

        current_notification = getattr(growspace, "notification_target", None) or ""

        base = {
            vol.Optional(
                "name",
                default=getattr(growspace, "name", ""),
            ): selector.TextSelector(),
            vol.Optional(
                "rows",
                default=getattr(growspace, "rows", 4),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    max=20,
                    mode=selector.NumberSelectorMode.BOX,
                ),
            ),
            vol.Optional(
                "plants_per_row",
                default=getattr(growspace, "plants_per_row", 4),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    max=20,
                    mode=selector.NumberSelectorMode.BOX,
                ),
            ),
        }

        if notification_options:
            base[vol.Optional("notification_target", default=current_notification)] = (
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=notification_options,
                        custom_value=False,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    ),
                )
            )
        else:
            base[vol.Optional("notification_target", default=current_notification)] = (
                selector.TextSelector()
            )

        return vol.Schema(base)

    def _get_main_menu_schema(self) -> vol.Schema:
        """Get schema for main menu."""
        return vol.Schema(
            {
                vol.Required("action"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value="manage_growspaces",
                                label="Manage Growspaces",
                            ),
                            selector.SelectOptionDict(
                                value="manage_plants",
                                label="Manage Plants",
                            ),
                            selector.SelectOptionDict(
                                value="configure_environment",
                                label="Configure Environment Sensors",
                            ),
                            selector.SelectOptionDict(
                                value="reauth",
                                label="Re-authenticate",
                            ),
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    ),
                ),
            },
        )

    def _get_plant_management_schema(self, coordinator) -> vol.Schema:
        """Get schema for plant management using object attributes."""
        plant_options = []

        for plant_id, plant in coordinator.plants.items():
            # plant is now a Plant object
            growspace = coordinator.growspaces.get(plant.growspace_id)
            growspace_name = (
                getattr(growspace, "name", "Unknown") if growspace else "Unknown"
            )
            label = f"{plant.strain} - {growspace_name} ({plant.row},{plant.col})"
            plant_options.append(selector.SelectOptionDict(value=plant_id, label=label))

        schema = {
            vol.Required("action"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value="add", label="Add New Plant"),
                        selector.SelectOptionDict(value="update", label="Update Plant"),
                        selector.SelectOptionDict(value="remove", label="Remove Plant"),
                        selector.SelectOptionDict(
                            value="back",
                            label="← Back to Main Menu",
                        ),
                    ],
                ),
            ),
        }

        if plant_options:
            schema[vol.Required("plant_id")] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=plant_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                ),
            )

        return vol.Schema(schema)

    def _get_growspace_selection_schema_from_devices(
        self,
        growspace_devices,
        coordinator,
    ) -> vol.Schema:
        """Get schema for selecting a growspace from device registry using object attributes."""
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
                    ),
                )

        return vol.Schema(
            {
                vol.Required("growspace_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=growspace_options),
                ),
            },
        )

    def _get_add_plant_schema(self, growspace, coordinator=None) -> vol.Schema:
        """Get schema for adding a plant with object-based Growspace."""
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
                ),
            )
            if strain_options
            else selector.TextSelector()
        )

        return vol.Schema(
            {
                vol.Required("strain"): strain_selector,
                vol.Optional("phenotype"): selector.TextSelector(),
                vol.Required("row", default=1): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        max=rows,
                        mode=selector.NumberSelectorMode.BOX,
                    ),
                ),
                vol.Required("col", default=1): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        max=plants_per_row,
                        mode=selector.NumberSelectorMode.BOX,
                    ),
                ),
                vol.Optional("veg_start"): selector.DateSelector(),
                vol.Optional("flower_start"): selector.DateSelector(),
            },
        )

    def _get_update_plant_schema(self, plant, coordinator) -> vol.Schema:
        """Get schema for updating a plant."""
        growspace = coordinator.growspaces.get(plant.growspace_id)

        if not growspace:
            # Fallback if growspace is somehow missing
            rows = 10
            plants_per_row = 10
        else:
            # Ensure rows and plants_per_row are integers
            rows = int(growspace.rows)
            plants_per_row = int(growspace.plants_per_row)

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
                    custom_value=True,  # Allow custom entries
                    mode=selector.SelectSelectorMode.DROPDOWN,
                ),
            )
        else:
            strain_selector = selector.TextSelector()

        return vol.Schema(
            {
                vol.Optional(
                    "strain",
                    default=plant.strain,
                ): strain_selector,
                vol.Optional(
                    "phenotype",
                    default=plant.phenotype,
                ): selector.TextSelector(),
                vol.Optional(
                    "row",
                    default=plant.row,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        max=rows,
                        mode=selector.NumberSelectorMode.BOX,
                    ),
                ),
                vol.Optional(
                    "col",
                    default=plant.col,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        max=plants_per_row,
                        mode=selector.NumberSelectorMode.BOX,
                    ),
                ),
                vol.Optional("veg_start"): selector.DateSelector(),
                vol.Optional("flower_start"): selector.DateSelector(),
            },
        )
