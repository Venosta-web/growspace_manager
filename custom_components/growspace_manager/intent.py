"""Intents for the Growspace Manager integration."""
from __future__ import annotations

import logging

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent

from .const import DOMAIN
from .coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)

INTENT_ASK_GROW_ADVICE = "GrowspaceManagerAskAdvice"


async def async_setup_intents(hass: HomeAssistant) -> None:
    """Set up the Growspace Manager intents."""
    intent.async_register(hass, AskGrowAdviceIntent(hass))


class AskGrowAdviceIntent(intent.IntentHandler):
    """Handle Ask Grow Advice intent."""

    intent_type = INTENT_ASK_GROW_ADVICE
    slot_schema = {
        vol.Required("growspace"): cv.string,
        vol.Optional("query"): cv.string,
    }

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the intent handler."""
        self.hass = hass

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the intent."""
        slots = self.async_validate_slots(intent_obj.slots)
        growspace_name = slots["growspace"]["value"]
        user_query = slots.get("query", {}).get("value")

        # Find the growspace ID based on the name
        coordinator: GrowspaceCoordinator | None = None
        growspace_id: str | None = None

        # Look through all config entries for this domain to find the growspace
        if DOMAIN in self.hass.data:
            for entry_data in self.hass.data[DOMAIN].values():
                if isinstance(entry_data, dict) and "coordinator" in entry_data:
                    curr_coordinator = entry_data["coordinator"]
                    for gs_id, gs in curr_coordinator.growspaces.items():
                        if gs.name.lower() == growspace_name.lower():
                            coordinator = curr_coordinator
                            growspace_id = gs_id
                            break
                if growspace_id:
                    break

        if not growspace_id or not coordinator:
            raise intent.IntentHandleError(f"Growspace '{growspace_name}' not found")

        # Prepare the service call data
        service_data = {"growspace_id": growspace_id}
        if user_query:
            service_data["user_query"] = user_query

        # We need to manually call the service handler logic or the service itself.
        # Calling the service via hass.services.async_call is usually better to ensure proper context,
        # but we want the return value (the speech).
        # However, intents usually return a speech response directly.

        # Let's call the service and get the response
        try:
            response_data = await self.hass.services.async_call(
                DOMAIN,
                "ask_grow_advice",
                service_data,
                blocking=True,
                return_response=True,
            )

            speech_text = "I couldn't get a response from the grow assistant."
            if response_data and "response" in response_data:
                speech_text = response_data["response"]

        except Exception as err:
            _LOGGER.error("Error handling ask grow advice intent: %s", err)
            raise intent.IntentHandleError(f"Error getting advice: {err}") from err

        response = intent_obj.create_response()
        response.async_set_speech(speech_text)
        return response
