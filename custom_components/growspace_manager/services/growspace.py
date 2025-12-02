"""Services related to Growspaces."""

import logging

import homeassistant.helpers.device_registry as dr
from homeassistant.components import conversation
from homeassistant.components.persistent_notification import (
    async_create as create_notification,
)
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

from ..const import CONF_AI_ENABLED, CONF_ASSISTANT_ID, DOMAIN
from ..coordinator import GrowspaceCoordinator
from ..strain_library import StrainLibrary

_LOGGER = logging.getLogger(__name__)


async def handle_add_growspace(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,  # Keep for consistency, though not used here
    call: ServiceCall,
) -> None:
    """Handle add growspace service call."""
    try:
        device_registry = dr.async_get(hass)
        mobile_devices = [
            d.name
            for d in device_registry.devices.values()
            if any("mobile_app" in entry_id for entry_id in d.config_entries)
        ]
        notification_target = call.data.get("notification_target")
        if notification_target and notification_target not in mobile_devices:
            notification_target = None

        growspace_id = await coordinator.async_add_growspace(
            name=call.data["name"],
            rows=call.data["rows"],
            plants_per_row=call.data["plants_per_row"],
            notification_target=notification_target,
        )

        _LOGGER.info("Growspace %s added successfully via service call", growspace_id)
        hass.bus.async_fire(
            f"{DOMAIN}_growspace_added",
            {"growspace_id": growspace_id, "name": call.data["name"]},
        )

    except Exception as err:
        _LOGGER.error("Failed to add growspace: %s", err)
        create_notification(
            hass,
            f"Failed to add growspace: {str(err)}",
            title="Growspace Manager Error",
        )
        raise


async def handle_ask_grow_advice(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> dict:
    """Handle ask grow advice service call."""
    try:
        growspace_id = call.data["growspace_id"]
        user_query = call.data.get("user_query", "Give me a general status update.")

        # Check if AI is enabled
        ai_settings = coordinator.options.get("ai_settings", {})
        if not ai_settings.get(CONF_AI_ENABLED):
            raise ServiceValidationError(
                "AI assistant is not enabled. Please go to the Growspace Manager integration settings to enable it."
            )

        agent_id = ai_settings.get(CONF_ASSISTANT_ID)
        growspace = coordinator.growspaces.get(growspace_id)
        if not growspace:
            raise ServiceValidationError(f"Growspace {growspace_id} not found.")

        # Gather Environment State
        env_config = getattr(growspace, "environment_config", {})
        sensor_data = {}
        for key in ["temperature_sensor", "humidity_sensor", "vpd_sensor", "co2_sensor"]:
             entity_id = env_config.get(key)
             if entity_id:
                  state = hass.states.get(entity_id)
                  if state and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                       sensor_data[key] = f"{state.state} {state.attributes.get('unit_of_measurement', '')}"

        # Gather Active Reasons from Bayesian Sensors
        active_reasons = []
        for sensor_type in ["stress", "mold_risk", "optimal", "drying", "curing"]:
             entity_id = f"binary_sensor.{DOMAIN}_{growspace_id}_{sensor_type}"
             state = hass.states.get(entity_id)
             if state:
                  # Get reasons attribute
                  reasons = state.attributes.get("reasons", [])
                  if reasons:
                       active_reasons.extend([f"{sensor_type.replace('_', ' ').title()}: {r}" for r in reasons])

        # Construct Prompt
        environment_text = ", ".join([f"{k}: {v}" for k, v in sensor_data.items()])
        reasons_text = "; ".join(active_reasons) if active_reasons else "None"

        prompt = (
            f"You are an expert cannabis cultivation master. "
            f"Analyze this environment for growspace '{growspace.name}':\n"
            f"Sensors: {environment_text}\n"
            f"Active Issues/Reasons: {reasons_text}\n"
            f"User Query: {user_query}\n"
            f"Provide actionable advice."
        )

        _LOGGER.debug("Sending advice prompt to LLM: %s", prompt)

        result = await conversation.async_process(
            hass,
            text=prompt,
            conversation_id=None,
            agent_id=agent_id,
            context=call.context,
        )

        response_text = "Sorry, I couldn't generate advice at this time."
        if (
            result
            and result.response
            and result.response.speech
            and result.response.speech.get("plain")
        ):
             response_text = result.response.speech["plain"]["speech"]

        return {"response": response_text}

    except Exception as err:
        _LOGGER.error("Error in ask_grow_advice: %s", err)
        raise


async def handle_remove_growspace(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,  # Keep for consistency
    call: ServiceCall,
) -> None:
    """Handle remove growspace service call."""
    try:
        await coordinator.async_remove_growspace(call.data["growspace_id"])
        _LOGGER.info("Growspace %s removed successfully", call.data["growspace_id"])
        hass.bus.async_fire(
            f"{DOMAIN}_growspace_removed",
            {"growspace_id": call.data["growspace_id"]},
        )
    except Exception as err:
        _LOGGER.error("Failed to remove growspace: %s", err)
        create_notification(
            hass,
            f"Failed to remove growspace: {str(err)}",
            title="Growspace Manager Error",
        )
        raise
