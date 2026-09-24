"""Operator controls for growspace output safety."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

from ..const import DOMAIN
from ..reliability_store import ReliabilityCounter

if TYPE_CHECKING:
    from ..coordinator import GrowspaceCoordinator
    from ..models import Growspace


SAFETY_SCHEMA = vol.Schema({vol.Optional("growspace_id"): str})


def _loaded_coordinators(hass: HomeAssistant) -> list[GrowspaceCoordinator]:
    """Get every loaded instance for a global emergency stop."""
    return [
        entry.runtime_data
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED and hasattr(entry, "runtime_data")
    ]


def _targets(
    hass: HomeAssistant, growspace_id: str | None
) -> list[tuple[GrowspaceCoordinator, str]]:
    """Resolve an optional growspace ID without silently missing one."""
    targets = [
        (coordinator, key)
        for coordinator in _loaded_coordinators(hass)
        for key in coordinator.growspaces
        if growspace_id is None or key == growspace_id
    ]
    if not targets:
        raise ServiceValidationError("No matching loaded growspace")
    return targets


def managed_outputs(growspace: Growspace) -> tuple[str, ...]:
    """List every output GSM may command for this growspace."""
    env = growspace.environment_config
    plain = (
        growspace.irrigation_config.irrigation_pump_entity,
        growspace.irrigation_config.drain_pump_entity,
        *env.exhaust_fan_entities,
        *env.circulation_fan_entities,
        *env.humidifier_entities,
        *env.dehumidifier_entities,
        *env.growlight_entities,
    )
    modes = (
        *(d.mode_entity for d in env.exhaust_fan_ac_infinity_devices),
        *(d.mode_entity for d in env.circulation_fan_ac_infinity_devices),
        *(d.mode_entity for d in env.humidifier_ac_infinity_devices),
        *(d.mode_entity for d in env.dehumidifier_ac_infinity_devices),
        *(d.mode_entity for d in env.growlight_ac_infinity_devices),
    )
    return tuple(dict.fromkeys((*filter(None, plain), *modes)))


def _safe_state(hass: HomeAssistant, entity_id: str) -> bool:
    state = hass.states.get(entity_id)
    if state is None:
        return False
    domain = entity_id.split(".", 1)[0]
    if domain in ("number", "input_number"):
        try:
            return float(state.state) == 0
        except ValueError:
            return False
    if domain == "select":
        return state.state == "Off"
    return state.state == "off"


async def async_emergency_stop_growspace(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    growspace_id: str,
    user_id: str | None,
) -> None:
    """Latch first, command safe states, then demand affirmative readback."""
    outputs = managed_outputs(coordinator.growspaces[growspace_id])
    latch_error: Exception | None = None
    already_stopped = (
        coordinator.irrigation_safety.emergency_stop_for(growspace_id) is not None
    )
    try:
        await coordinator.irrigation_safety.async_latch_emergency_stop(
            growspace_id, "Operator emergency stop", outputs, user_id
        )
    except Exception as err:  # noqa: BLE001 - still command every output safe
        latch_error = err
    else:
        if not already_stopped:
            coordinator.reliability.record(
                growspace_id, ReliabilityCounter.EMERGENCY_STOP
            )
    failures: list[str] = []
    for entity_id in outputs:
        data: dict[str, object]
        domain = entity_id.split(".", 1)[0]
        if domain == "select":
            service_domain, service, data = (
                "select",
                "select_option",
                {"entity_id": entity_id, "option": "Off"},
            )
        elif domain in ("number", "input_number"):
            service_domain, service, data = (
                domain,
                "set_value",
                {"entity_id": entity_id, "value": 0},
            )
        else:
            service_domain, service, data = (
                domain
                if domain in ("switch", "fan", "light", "humidifier", "input_boolean")
                else "homeassistant",
                "turn_off",
                {"entity_id": entity_id},
            )
        try:
            await hass.services.async_call(service_domain, service, data, blocking=True)
        except Exception:  # noqa: BLE001 - attempt all outputs even if one fails
            failures.append(entity_id)
    for _ in range(10):
        unsafe = [entity for entity in outputs if not _safe_state(hass, entity)]
        if not unsafe:
            break
        await asyncio.sleep(0.1)
    if latch_error or failures or unsafe:
        raise ServiceValidationError(
            "Emergency stop incomplete: "
            + (
                f"safety record could not be saved ({latch_error}); "
                if latch_error
                else ""
            )
            + (
                "outputs not confirmed safe: " + ", ".join(sorted({*failures, *unsafe}))
                if failures or unsafe
                else ""
            )
        )
    coordinator.async_update_listeners()


async def handle_emergency_stop(hass: HomeAssistant, call: ServiceCall) -> None:
    """Stop one growspace or every loaded growspace."""
    failures: list[str] = []
    for coordinator, growspace_id in _targets(hass, call.data.get("growspace_id")):
        try:
            await async_emergency_stop_growspace(
                hass, coordinator, growspace_id, call.context.user_id
            )
        except Exception as err:  # noqa: BLE001 - a global stop must try every room
            failures.append(f"{growspace_id}: {err}")
    if failures:
        raise ServiceValidationError("; ".join(failures))


async def handle_reset_safety(hass: HomeAssistant, call: ServiceCall) -> None:
    """Admin reset only after every managed output reads safe."""
    user_id = call.context.user_id
    user = await hass.auth.async_get_user(user_id) if user_id else None
    if user is None or not user.is_admin:
        raise ServiceValidationError("Reset safety requires an admin user")
    targets = _targets(hass, call.data.get("growspace_id"))
    for coordinator, growspace_id in targets:
        store = coordinator.irrigation_safety
        record = store.emergency_stop_for(growspace_id)
        if record is None:
            continue
        outputs = tuple(
            dict.fromkeys(
                (
                    *record.outputs,
                    *managed_outputs(coordinator.growspaces[growspace_id]),
                )
            )
        )
        unsafe = [entity for entity in outputs if not _safe_state(hass, entity)]
        if unsafe:
            raise ServiceValidationError(
                "Cannot reset safety; outputs not confirmed safe: " + ", ".join(unsafe)
            )
    for coordinator, growspace_id in targets:
        store = coordinator.irrigation_safety
        if store.emergency_stop_for(growspace_id) is None:
            continue
        await store.async_reset_emergency_stop(growspace_id, user.id)
        coordinator.async_update_listeners()
