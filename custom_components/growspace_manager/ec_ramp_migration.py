"""Repair-based migration for EC ramp curve growspace binding (ADR-0046).

An ``ECRampCurve`` is now owned by exactly one growspace and stores that owner in
``growspace_id``. Every curve written before this existed went through the one
broken save path (workspace#108), which discarded the grower's chosen stage and
stored an arbitrary growspace id as the curve's ``name`` — so a stored curve with
an empty ``growspace_id`` is unmigrated, exactly and without heuristics.

We do not auto-migrate. The two recoverable fields could be un-shuffled, but the
grower's stage was never written anywhere and cannot be reconstructed, and a
curve with no stage drives nothing — repairing the other fields would produce a
curve that still silently does not work. Instead we raise a repair issue per
curve directing the grower to re-save it, which is one gesture in the EC Ramp tab
and restores all three fields at once.

The check is *create-or-clear*: the same predicate inverted decides whether the
per-curve issue is raised or removed, so the repair self-heals as soon as the
curve is saved with an owner.
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
    from .models.irrigation import ECRampCurve

ISSUE_ID_PREFIX = "ec_ramp_curve_unmigrated_"


def _issue_id(curve_id: str) -> str:
    return f"{ISSUE_ID_PREFIX}{curve_id}"


def _needs_migration(curve: ECRampCurve) -> bool:
    """Return True when the curve was stored without a growspace binding."""
    return not curve.growspace_id


def _grower_label(curve: ECRampCurve) -> str:
    """Best available name for a corrupt curve.

    The broken save path put the grower's typed curve name into ``stage`` and a
    growspace id into ``name``, so ``stage`` is what the grower will recognise in
    the EC Ramp list. Fall back to ``name`` for anything else.
    """
    return curve.stage or curve.name or curve.id


@callback
def evaluate_ec_ramp_migration_issues(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator
) -> None:
    """Raise or clear the unmigrated-curve repair for every EC ramp curve."""
    for curve_id, curve in coordinator.services.config.ec_ramp_curves.items():
        issue_id = _issue_id(curve_id)
        if _needs_migration(curve):
            async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=IssueSeverity.WARNING,
                translation_key="ec_ramp_curve_unmigrated",
                translation_placeholders={"curve": _grower_label(curve)},
            )
        else:
            async_delete_issue(hass, DOMAIN, issue_id)
