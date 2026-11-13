"""Check exclusive lighting assignments across integration entries."""

from __future__ import annotations

from asyncio import Lock
from typing import TYPE_CHECKING

from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN

if TYPE_CHECKING:
    from collections.abc import Iterable

    from homeassistant.core import HomeAssistant

    from .coordinator import GrowspaceCoordinator
    from .models import EnvironmentConfig, Growspace

_LOCK: HassKey[Lock] = HassKey(f"{DOMAIN}.lighting_assignments")


def lighting_assignment_lock(hass: HomeAssistant) -> Lock:
    """Serialize changes that allocate or release lighting outputs."""
    return hass.data.setdefault(_LOCK, Lock())


def main_light_outputs(config: EnvironmentConfig) -> list[str]:
    """Return the primary entity for every main-light assignment."""
    return [
        *config.growlight_entities,
        *(device.mode_entity for device in config.growlight_ac_infinity_devices),
    ]


def lighting_assignments(
    coordinator: GrowspaceCoordinator, growspace: Growspace
) -> Iterable[tuple[Growspace, str, str]]:
    """Yield each assigned entity, including entries still loading at startup."""
    for entry in coordinator.hass.config_entries.async_entries(DOMAIN):
        owner = getattr(entry, "runtime_data", None)
        if owner is coordinator:
            continue
        if owner is not None:
            yield from _assignments(owner.growspaces.values())
    yield from _assignments((growspace,))
    yield from _assignments(
        space for space in coordinator.growspaces.values() if space.id != growspace.id
    )


def _assignments(
    growspaces: Iterable[Growspace],
) -> Iterable[tuple[Growspace, str, str]]:
    for space in growspaces:
        for entity in main_light_outputs(space.environment_config):
            yield space, "main light", entity
        for light in space.supplemental_lights:
            yield space, "supplemental light", light.entity_id


def validate_main_light_assignments(
    coordinator: GrowspaceCoordinator, growspace: Growspace, config: EnvironmentConfig
) -> None:
    """Reject new conflicts while allowing growers to repair old assignments."""
    previous = main_light_outputs(growspace.environment_config)
    candidate = main_light_outputs(config)
    for entity in candidate:
        count = candidate.count(entity)
        if count <= previous.count(entity):
            continue
        if count > 1:
            raise ValueError(
                f"{entity} is already assigned as a main light in {growspace.name}."
            )
        for space, role, assigned in lighting_assignments(coordinator, growspace):
            if assigned == entity:
                raise ValueError(
                    f"{entity} is already assigned as a {role} in {space.name}."
                )
