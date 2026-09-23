"""Suggest reviewing daily pump caps on growspaces created before safe defaults."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
)

from .const import DOMAIN
from .models import IrrigationConfig

if TYPE_CHECKING:
    from .coordinator import GrowspaceCoordinator


@callback
def evaluate_irrigation_cap_issues(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator
) -> None:
    """Leave legacy cap values alone and show a repair until both are set."""
    for growspace_id, growspace in coordinator.growspaces.items():
        config = growspace.irrigation_config
        if type(config) is not IrrigationConfig:
            continue
        issue_id = f"irrigation_cap_review_{growspace_id}"
        if (config.irrigation_pump_entity or config.irrigation_times) and (
            config.max_cycles_per_day is None
            or config.daily_volume_cap_liters is None
            or config.pump_flow_rate_ml_per_sec <= 0
        ):
            async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=IssueSeverity.WARNING,
                translation_key="irrigation_cap_review",
                translation_placeholders={"growspace": growspace.name},
            )
        else:
            async_delete_issue(hass, DOMAIN, issue_id)
