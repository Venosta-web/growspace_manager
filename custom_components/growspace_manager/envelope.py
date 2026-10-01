"""The tested scale envelope and its pump-time inference (ADR-0060)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .actuator_driver import STATE_CONFIRM_TIMEOUT_SECONDS
from .const import DOMAIN, ShotSizingMode
from .domain.irrigation_schedule import schedulable_events
from .domain.plant_metrics import count_live_plants
from .domain.shot_sizing import percent_to_seconds
from .irrigation_coordinator import ON_CONFIRM_TIMEOUT_SECONDS

if TYPE_CHECKING:
    from .models import Growspace, Plant

MAX_IRRIGATED_GROWSPACES = 10
MAX_ENVELOPE_SHOT_SECONDS = 118
DEFAULT_INTERVAL_SECONDS = 900
CONFIRMATION_OVERHEAD_SECONDS = (
    2 * ON_CONFIRM_TIMEOUT_SECONDS + 2 * STATE_CONFIRM_TIMEOUT_SECONDS
)


def pump_shortfall(growspace: Growspace, plants: Iterable[Plant]) -> float:
    """Compare the configured longest shot against the shortest zone interval.

    Schedule intervals include the overnight wrap. Volume-mode shots use the
    live plants in each zone, just as composition does. An unsized volume shot
    cannot run and contributes no pump time. Adaptive runtime gains are not a
    configured shot, and are deliberately outside this configuration warning.
    """
    durations: list[float] = []
    intervals: list[float] = []
    live = [p for p in plants if p.growspace_id == growspace.id]
    for zone in growspace.irrigation_zones:
        strategy = zone.strategy
        if strategy.enabled:
            intervals.extend(
                [
                    strategy.p1_shot_interval_minutes * 60,
                    strategy.p2_shot_interval_minutes * 60,
                ]
            )
            if strategy.shot_sizing_mode is ShotSizingMode.VOLUME:
                count = count_live_plants(
                    p for p in live if (p.row, p.col) in zone.cells
                )
                durations.extend(
                    percent_to_seconds(
                        percent,
                        liters_per_pot=strategy.substrate_profile.liters_per_pot,
                        live_plant_count=count,
                        flow_rate_ml_per_sec=zone.pump_flow_rate_ml_per_sec,
                    )
                    or 0
                    for percent in (
                        strategy.p1_shot_volume_percent,
                        strategy.p2_shot_volume_percent,
                    )
                )
            else:
                durations.extend(
                    [
                        strategy.p1_shot_duration_seconds,
                        strategy.p2_shot_duration_seconds,
                    ]
                )
        else:
            events = schedulable_events(
                [dict(item) for item in zone.irrigation_times]
            ).valid
            durations.extend(
                item.get("duration") or zone.irrigation_duration or 0
                for _, item in events
            )
            slots = sorted(
                {at.hour * 3600 + at.minute * 60 + at.second for at, _ in events}
            )
            if slots:
                intervals.extend(
                    b - a
                    for a, b in zip(slots, [*slots[1:], slots[0] + 86400], strict=True)
                )
            if zone.soil_trigger_percent is not None:
                durations.append(zone.irrigation_duration or 0)
                intervals.append(zone.min_interval_minutes * 60)
    if not durations or not intervals:
        return 0
    required = len(growspace.irrigation_zones) * (
        max(durations) + CONFIRMATION_OVERHEAD_SECONDS
    )
    return max(0, required - min(intervals))


@callback
def async_refresh_envelope_issues(
    hass: HomeAssistant, growspaces: Iterable[Growspace], plants: Iterable[Plant]
) -> None:
    """Reconcile informational Repairs after setup or a committed configuration."""
    irrigated = [gs for gs in growspaces if gs.irrigation_config.irrigation_pump_entity]
    plants = list(plants)
    if len(irrigated) > MAX_IRRIGATED_GROWSPACES:
        ir.async_create_issue(
            hass,
            DOMAIN,
            "irrigated_growspaces_envelope",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="irrigated_growspaces_envelope",
            translation_placeholders={
                "count": str(len(irrigated)),
                "limit": str(MAX_IRRIGATED_GROWSPACES),
            },
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, "irrigated_growspaces_envelope")
    current = set()
    for gs in irrigated:
        issue_id = f"pump_time_envelope_{gs.id}"
        if shortfall := pump_shortfall(gs, plants):
            current.add(issue_id)
            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="pump_time_envelope",
                translation_placeholders={
                    "growspace": gs.name,
                    "zones": ", ".join(
                        zone.name or zone.id for zone in gs.irrigation_zones
                    ),
                    "shortfall": f"{shortfall:g}",
                },
            )
    for domain, issue_id in list(ir.async_get(hass).issues):
        if (
            domain == DOMAIN
            and issue_id.startswith("pump_time_envelope_")
            and issue_id not in current
        ):
            ir.async_delete_issue(hass, DOMAIN, issue_id)
