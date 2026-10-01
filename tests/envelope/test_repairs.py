"""Envelope warnings are configuration feedback, never a configuration gate."""

from unittest.mock import AsyncMock

import pytest

from custom_components.growspace_manager.const import DOMAIN, ShotSizingMode
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.envelope import (
    async_refresh_envelope_issues,
    pump_shortfall,
)
from custom_components.growspace_manager.models import (
    Growspace,
    IrrigationConfig,
    IrrigationZone,
    Plant,
)
from custom_components.growspace_manager.services.irrigation_change import (
    IrrigationChange,
    IrrigationChangeOperation,
    async_apply_irrigation_change,
)
from homeassistant.helpers import issue_registry as ir
from tests.common import MockConfigEntry


def tent(id="tent", count=6, duration=118):
    gs = Growspace(
        id=id,
        name=id,
        rows=1,
        plants_per_row=count,
        irrigation_config=IrrigationConfig(irrigation_pump_entity=f"switch.{id}"),
    )
    gs.irrigation_zones = [
        IrrigationZone(
            id="default" if i == 0 else str(i), name=f"Zone {i}", cells=[(1, i + 1)]
        )
        for i in range(count)
    ]
    for zone in gs.irrigation_zones:
        zone.strategy.enabled = True
        zone.strategy.p1_shot_duration_seconds = duration
        zone.strategy.p2_shot_duration_seconds = duration
    return gs


@pytest.mark.parametrize("count,expected", [(0, False), (10, False), (11, True)])
async def test_instance_count_warns_only_above_ten(hass, count, expected):
    growspaces = [tent(str(i)) for i in range(count)]
    unwatered = tent("unwatered")
    unwatered.irrigation_config.irrigation_pump_entity = None
    async_refresh_envelope_issues(hass, [*growspaces, unwatered], [])
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "irrigated_growspaces_envelope")
    assert (issue is not None) == expected
    if issue:
        assert issue.severity is ir.IssueSeverity.WARNING
        assert not issue.is_fixable
        assert issue.translation_placeholders == {"count": "11", "limit": "10"}
    assert all(gs.irrigation_config.irrigation_pump_entity for gs in growspaces)
    async_refresh_envelope_issues(hass, [], [])
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, "irrigated_growspaces_envelope")
        is None
    )


async def test_shortfall_names_all_zones_and_clears_on_removal(hass):
    gs = tent(duration=119)
    async_refresh_envelope_issues(hass, [gs], [])
    registry = ir.async_get(hass)
    issue = registry.async_get_issue(DOMAIN, "pump_time_envelope_tent")
    assert issue.translation_placeholders == {
        "growspace": "tent",
        "zones": "Zone 0, Zone 1, Zone 2, Zone 3, Zone 4, Zone 5",
        "shortfall": "6",
    }
    assert not issue.is_fixable
    # Preserve unrelated repairs during reconciliation.
    ir.async_create_issue(
        hass,
        DOMAIN,
        "unrelated",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="unrelated",
    )
    async_refresh_envelope_issues(hass, [], [])
    assert registry.async_get_issue(DOMAIN, "pump_time_envelope_tent") is None
    assert registry.async_get_issue(DOMAIN, "unrelated") is not None


def test_shortest_interval_and_longest_phase_across_zones():
    gs = tent()
    assert pump_shortfall(gs, []) == 0
    gs.irrigation_zones[-1].strategy.p2_shot_duration_seconds = 120
    gs.irrigation_zones[0].strategy.p1_shot_interval_minutes = 10
    assert pump_shortfall(gs, []) == 312


def test_schedule_wrap_fallback_duration_and_soil_interval():
    gs = tent(count=2, duration=0)
    for zone in gs.irrigation_zones:
        zone.strategy.enabled = False
        zone.irrigation_duration = 10
        zone.irrigation_times = [
            {"time": "23:59"},
            {"time": "00:00:00"},
            {"time": "invalid", "duration": 999},
        ]
    assert pump_shortfall(gs, []) == 24
    for zone in gs.irrigation_zones:
        zone.irrigation_times = []
        zone.soil_trigger_percent = 40
        zone.min_interval_minutes = 1
    assert pump_shortfall(gs, []) == 24
    gs.irrigation_zones[0].irrigation_duration = None
    gs.irrigation_zones[1].soil_trigger_percent = None
    assert pump_shortfall(gs, []) == 4
    gs.irrigation_zones[0].soil_trigger_percent = None
    assert pump_shortfall(gs, []) == 0


def test_volume_uses_live_zone_membership():
    gs = tent(count=2)
    for zone in gs.irrigation_zones:
        zone.strategy.shot_sizing_mode = ShotSizingMode.VOLUME
        zone.strategy.substrate_profile.liters_per_pot = 10
        zone.strategy.p1_shot_volume_percent = 10
        zone.strategy.p2_shot_volume_percent = 5
        zone.pump_flow_rate_ml_per_sec = 1
    plants = [
        Plant(
            plant_id="live", growspace_id=gs.id, row=1, col=1, veg_start="2026-01-01"
        ),
        Plant(plant_id="elsewhere", growspace_id="elsewhere", row=1, col=1),
    ]
    assert pump_shortfall(gs, plants) == 1164
    assert pump_shortfall(gs, []) == 0
    gs.irrigation_zones[0].pump_flow_rate_ml_per_sec = 0
    assert pump_shortfall(gs, plants) == 0


async def test_committed_change_warns_immediately_and_correction_clears(hass):
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    coordinator = GrowspaceCoordinator.build(hass, entry, data={})
    entry.runtime_data = coordinator
    gs = tent()
    coordinator._data_repository.add_growspace(gs)
    coordinator.storage_manager.async_force_save = AsyncMock()
    for method in (
        "async_project_activity",
        "async_project_harvest_outcomes",
        "async_project_water",
        "async_project_safety",
    ):
        setattr(coordinator, method, AsyncMock())
    await async_apply_irrigation_change(
        coordinator,
        gs.id,
        IrrigationChange(
            IrrigationChangeOperation.STRATEGY, {"p1_shot_duration_seconds": 120}
        ),
        zone_id="default",
    )
    assert gs.default_zone.strategy.p1_shot_duration_seconds == 120
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, "pump_time_envelope_tent")
        is not None
    )
    await async_apply_irrigation_change(
        coordinator,
        gs.id,
        IrrigationChange(
            IrrigationChangeOperation.STRATEGY, {"p1_shot_duration_seconds": 118}
        ),
        zone_id="default",
    )
    assert ir.async_get(hass).async_get_issue(DOMAIN, "pump_time_envelope_tent") is None


async def test_count_is_instance_wide_across_entries(hass):
    coordinators = []
    for index in range(2):
        entry = MockConfigEntry(domain=DOMAIN, unique_id=str(index))
        entry.add_to_hass(hass)
        coordinator = GrowspaceCoordinator.build(hass, entry, data={})
        entry.runtime_data = coordinator
        coordinators.append(coordinator)
        for number in range(6):
            coordinator._data_repository.add_growspace(tent(f"{index}_{number}"))
    coordinators[0]._refresh_envelope_issues()
    assert (
        ir.async_get(hass)
        .async_get_issue(DOMAIN, "irrigated_growspaces_envelope")
        .translation_placeholders["count"]
        == "12"
    )
