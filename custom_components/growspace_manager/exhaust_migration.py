"""Repair-based migration for exhaust-fan sole ownership (ADR-0019).

The ``ExhaustFanController`` is now the sole owner of ``exhaust_fan_entities``;
the ``DehumidifierCoordinator`` no longer cycles them. Because
``ExhaustFanConfig`` defaults to ``enabled=False``, an install that relied on the
old "exhaust rides along with the dehumidifier" behavior would silently stop
cycling its exhaust fans. We do not auto-migrate (old on/off thresholds carry no
speed-band information); instead we raise a repair issue directing the grower to
the Exhaust panel so the opt-in is explicit.

The check is *create-or-clear*: the same predicate inverted decides whether the
per-growspace issue is raised or removed, so the repair self-heals once the
grower enables the new controller, removes the exhaust entities, or turns off
``control_dehumidifier``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
)

from .const import DOMAIN

if TYPE_CHECKING:
    from .coordinator import GrowspaceCoordinator
    from .models.growspace import Growspace

ISSUE_ID_PREFIX = "exhaust_fan_migration_"


def _issue_id(growspace_id: str) -> str:
    return f"{ISSUE_ID_PREFIX}{growspace_id}"


def _needs_migration(growspace: Growspace) -> bool:
    """Return True when the dehumidifier used to cycle exhaust fans here.

    The grower had ``control_dehumidifier`` on with ``exhaust_fan_entities``
    configured, and has not yet enabled the new exhaust controller. A grower who
    already flipped ``exhaust_fan_config.enabled`` is served by the new
    controller and must not be nagged.
    """
    env = growspace.environment_config
    return bool(
        env.control_dehumidifier
        and env.exhaust_fan_entities
        and not env.exhaust_fan_config.enabled
    )


@callback
def evaluate_exhaust_migration_issues(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator
) -> None:
    """Raise or clear the exhaust-migration repair for every growspace."""
    for growspace_id, growspace in coordinator.growspaces.items():
        issue_id = _issue_id(growspace_id)
        if _needs_migration(growspace):
            async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=IssueSeverity.WARNING,
                translation_key="exhaust_fan_migration",
                translation_placeholders={"growspace": growspace.name},
            )
        else:
            async_delete_issue(hass, DOMAIN, issue_id)
