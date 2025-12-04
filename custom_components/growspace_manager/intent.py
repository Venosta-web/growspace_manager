"""Intents for the Growspace Manager integration."""

from __future__ import annotations

import logging

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent

from .const import DOMAIN

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
        growspace_id = self._find_growspace(growspace_name)

        if not growspace_id:
            raise intent.IntentHandleError(f"Growspace '{growspace_name}' not found")

        # Prepare the service call data
        service_data = {"growspace_id": growspace_id}
        if user_query:
            service_data["user_query"] = user_query

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

    def _find_growspace(self, growspace_name: str) -> str | None:
        """Find the growspace ID based on the name."""
        entries = self.hass.config_entries.async_entries(DOMAIN)
        for entry in entries:
            if hasattr(entry, "runtime_data"):
                curr_coordinator = entry.runtime_data.coordinator
                for gs_id, gs in curr_coordinator.growspaces.items():
                    if gs.name.lower() == growspace_name.lower():
                        return gs_id
        return None
