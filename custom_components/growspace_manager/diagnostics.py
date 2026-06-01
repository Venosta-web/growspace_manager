"""Diagnostics support for Growspace Manager."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant

from .const import VERSION
from .coordinator import GrowspaceCoordinator

TO_REDACT = {
    CONF_LATITUDE,
    CONF_LONGITUDE,
    "unique_id",
    # Add any other sensitive keys here
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: GrowspaceCoordinator = entry.runtime_data

    # Collect sub-coordinator states
    irrigation_states = {
        gs_id: {
            "is_running": getattr(coord, "is_running", None),
            "mode": getattr(coord, "mode", None),
        }
        for gs_id in coordinator.growspaces
        if (coord := coordinator.services.growspaces.get_irrigation_coordinator(gs_id)) is not None
    }

    dehumidifier_states = {
        gs_id: {
            "control_enabled": getattr(coord, "control_dehumidifier", None),
            "target_vpd": getattr(coord, "_target_vpd", None),
        }
        for gs_id in coordinator.growspaces
        if (coord := coordinator.services.growspaces.get_dehumidifier_coordinator(gs_id)) is not None
    }

    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "coordinator_data": async_redact_data(coordinator.data, TO_REDACT),
        "system_stats": {
            "growspace_count": len(coordinator.growspaces),
            "plant_count": len(coordinator.plants),
            "strain_library_count": len(coordinator.strain_library.get_all())
            if coordinator.strain_library
            else 0,
        },
        "subsystems": {
            "irrigation": irrigation_states,
            "dehumidifier": dehumidifier_states,
        },
        "integration_version": VERSION,
    }
