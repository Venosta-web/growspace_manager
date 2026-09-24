"""Diagnostics support for Growspace Manager."""

from __future__ import annotations

import re
from typing import Any, cast

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant

from .const import VERSION
from .coordinator import GrowspaceCoordinator
from .vwc_irrigation_coordinator import VWCIrrigationCoordinator

TO_REDACT = {
    CONF_LATITUDE,
    CONF_LONGITUDE,
    "unique_id",
    "notification_target",
    "sensor_coordinates",
}

_SENSITIVE_KEY = re.compile(
    r"(?:token|secret|password|url|camera|coordinate|latitude|longitude|notification_target)",
    re.IGNORECASE,
)
_URL = re.compile(r"(?:https?|rtsp|rtsps)://", re.IGNORECASE)


def _safe(value: Any, *, unavailable: bool = False) -> Any:
    """Remove sensitive values from every diagnostics section, including nested data."""
    if isinstance(value, dict):
        return {
            key: "**REDACTED**"
            if _SENSITIVE_KEY.search(str(key))
            else _safe(item, unavailable=unavailable)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_safe(item, unavailable=unavailable) for item in value]
    if isinstance(value, str) and _URL.search(value):
        return "**REDACTED**"
    if value is None and unavailable:
        return "unavailable"
    return value


def _irrigation_diagnostics(coord: Any) -> dict[str, Any]:
    """Read the live irrigation state through implemented coordinator APIs."""
    steering = isinstance(coord, VWCIrrigationCoordinator)
    state = coord.controller_snapshot()
    result = {
        "mode": "steering" if steering else "schedule",
        "active_events": coord.active_events,
        "cycles_today": coord.cycles_today,
        "volume_dispensed_today": coord.volume_dispensed_today,
        "last_cycle_timestamp": coord.last_cycle_timestamp,
        "next_scheduled_cycle": coord.next_scheduled_cycle,
        "controller": {"state": state.state.value, **state.attributes()},
        "tanks": coord.tank_diagnostics(),
    }
    if steering:
        result.update(
            phase=coord.growspace.irrigation_strategy.active_steering_phase,
            projected_shot_window=coord.projected_shot_window,
            shot_composition=coord.shot_composition_payload(),
            ec_state=coord.ec_state_payload(),
        )
    return result


def _climate_diagnostics(
    coordinator: GrowspaceCoordinator, getter: str
) -> dict[str, Any]:
    """Collect live snapshots for one class of environment controller."""
    growspaces = coordinator.services.growspaces
    return {
        gs_id: coord.diagnostics_snapshot()
        for gs_id in coordinator.growspaces
        if (coord := getattr(growspaces, getter)(gs_id)) is not None
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: GrowspaceCoordinator = entry.runtime_data

    irrigation_states = {
        gs_id: _irrigation_diagnostics(coord)
        for gs_id in coordinator.growspaces
        if (coord := coordinator.services.growspaces.get_irrigation_coordinator(gs_id))
        is not None
    }

    dehumidifier_states = {
        gs_id: coord.diagnostics_snapshot()
        for gs_id in coordinator.growspaces
        if (
            coord := coordinator.services.growspaces.get_dehumidifier_coordinator(gs_id)
        )
        is not None
    }

    result = {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "coordinator_data": async_redact_data(coordinator.data, TO_REDACT),
        "system_stats": {
            "growspace_count": len(coordinator.growspaces),
            "plant_count": len(coordinator.plants),
            "strain_library_count": len(
                coordinator.services.config.strain_library.get_all()
            )
            if coordinator.services.config.strain_library
            else 0,
        },
        "subsystems": {
            "irrigation": irrigation_states,
            "dehumidifier": dehumidifier_states,
            "humidifier": _climate_diagnostics(
                coordinator, "get_humidifier_coordinator"
            ),
            "circulation_fan": _climate_diagnostics(
                coordinator, "get_circulation_fan_coordinator"
            ),
            "exhaust_fan": _climate_diagnostics(
                coordinator, "get_exhaust_fan_coordinator"
            ),
        },
        "irrigation_safety": {
            "faults": {
                growspace_id: record.as_dict()
                for growspace_id, record in coordinator.irrigation_safety.faults.items()
            },
            "emergency_stops": {
                growspace_id: record.as_dict()
                for growspace_id, record in coordinator.irrigation_safety.emergency_stops.items()
            },
            "fault_record_unreadable": coordinator.irrigation_safety.unreadable,
            "ledger": list(coordinator.irrigation_safety.ledger)[-100:],
        },
        "integration_version": VERSION,
    }
    result["subsystems"] = _safe(result["subsystems"], unavailable=True)
    return cast(dict[str, Any], _safe(result))
