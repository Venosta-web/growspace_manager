"""Effect shell for the Environment Patch write seam (ADR-0026).

The one place the assign → save → refresh → targeted controller restarts →
exhaust-repair re-evaluation ordering lives. Every runtime writer of
EnvironmentConfig commits through here; the pure merge law stays in
``domain/environment_patch.py``. A caller that bypasses this shell (the
storage-manager migration, deliberately) re-assumes responsibility for
effects.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..domain.environment_patch import (
    EnvironmentPatch,
    EnvironmentPatchVerdict,
    apply_environment_patch,
)
from ..exhaust_migration import evaluate_exhaust_migration_issues

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from ..coordinator import GrowspaceCoordinator
    from ..models import Growspace

_LOGGER = logging.getLogger(__name__)

_CONTROLLER_ACCESSORS = {
    "dehumidifier": "get_dehumidifier_controller",
    "humidifier": "get_humidifier_controller",
    "circulation_fan": "get_circulation_fan_controller",
    "exhaust_fan": "get_exhaust_fan_controller",
    "growlight": "get_growlight_controller",
}


async def async_commit_environment_patch(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    growspace: Growspace,
    patch: EnvironmentPatch,
) -> EnvironmentPatchVerdict:
    """Apply an Environment Patch to the growspace and perform every effect.

    Order: assign the merged config → save → request refresh → restart each
    sub-controller named in the verdict (only controllers whose fields
    actually changed) → re-evaluate the exhaust-migration repair (ADR-0019)
    when a trigger field changed. Returns the verdict so callers can emit
    logbook text.
    """
    verdict = apply_environment_patch(growspace.environment_config, patch)
    for warning in verdict.warnings:
        _LOGGER.warning(
            "Environment patch for '%s' dropped %s: %s",
            growspace.name,
            warning.field,
            warning.message,
        )

    growspace.environment_config = verdict.config
    await coordinator.services.save()
    await coordinator.services.request_refresh()

    for controller in sorted(verdict.controllers_to_restart):
        accessor = getattr(
            coordinator._subsystem_manager,
            _CONTROLLER_ACCESSORS[controller],
        )
        if sub_coordinator := accessor(growspace.id):
            await sub_coordinator.async_restart()

    if verdict.exhaust_repair_relevant:
        evaluate_exhaust_migration_issues(hass, coordinator)

    _LOGGER.info("Environment updated for '%s': %s", growspace.name, verdict.summary)
    return verdict
