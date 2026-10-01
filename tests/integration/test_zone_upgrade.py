"""A v1.2.3 store upgrades into Irrigation Zones and nothing it did changes.

The documents in ``tests/fixtures/upgrade/`` were written by v1.2.3's own
models (see ``write_v1_2_3_storage.py`` there): one growspace steered on a
moisture probe with a schedule, a drain, a tank and pore/bulk EC, and one on a
plain schedule. ``v1_2_3_unique_ids.json`` is every entity unique_id the last
build before zones registered from them. ADR-0063 item 7 asks four things of
them, and this module is where each is asserted.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import (
    DOMAIN,
    STORAGE_KEY_CONFIG,
    STORAGE_KEY_PLANTS,
)
from custom_components.growspace_manager.domain.infiltration import InfiltrationState
from custom_components.growspace_manager.domain.irrigation_zone import (
    LIGHT_CYCLE_FIELDS,
    ZONE_CONFIG_FIELDS,
    ZONE_ENVIRONMENT_FIELDS,
    ZONE_MIGRATION_INVALID,
    effective_config,
    effective_strategy,
    migrate_growspace_document,
    zone_integrity_problems,
)
from custom_components.growspace_manager.domain.pump_cycle import (
    cycle_volume_liters,
    decide_cycle,
)
from custom_components.growspace_manager.domain.steering_phase import (
    SteeringPhaseMachine,
    SteeringTickInputs,
    resolve_day_hours,
)
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    IrrigationConfig,
    IrrigationStrategy,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.helpers.storage import Store, UnsupportedStorageVersionError
from tests.common import MockConfigEntry

FIXTURES = Path(__file__).parent.parent / "fixtures" / "upgrade"
COPY_KEY = f"{STORAGE_KEY_CONFIG}.v1"


def _golden(key: str) -> dict[str, Any]:
    return json.loads((FIXTURES / key).read_text())


def _v1_growspaces() -> dict[str, dict[str, Any]]:
    return _golden(STORAGE_KEY_CONFIG)["data"]["growspaces"]


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    with patch(
        "custom_components.growspace_manager.async_register_sidebar_panel",
        new_callable=AsyncMock,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def _unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_golden_store_upgrades_and_keeps_every_entity(
    hass: HomeAssistant,
    hass_storage: dict,
    mock_config_entry: MockConfigEntry,
    enable_custom_integrations: None,
    recorder_mock: None,
) -> None:
    """Valid v2 document, moved fields intact, same unique_ids, an exact copy."""
    golden_config = _golden(STORAGE_KEY_CONFIG)
    hass_storage[STORAGE_KEY_CONFIG] = copy.deepcopy(golden_config)
    hass_storage[STORAGE_KEY_PLANTS] = _golden(STORAGE_KEY_PLANTS)

    await _setup(hass, mock_config_entry)

    stored = hass_storage[STORAGE_KEY_CONFIG]
    assert stored["version"] == 2
    for growspace_id, before in golden_config["data"]["growspaces"].items():
        after = stored["data"]["growspaces"][growspace_id]
        assert zone_integrity_problems(after) == []
        (zone,) = after["irrigation_zones"]
        assert zone["id"] == "default"
        for name in ZONE_CONFIG_FIELDS:
            if name in before["irrigation_config"]:
                assert zone[name] == before["irrigation_config"][name], name
        for name in ZONE_ENVIRONMENT_FIELDS:
            if name in before["environment_config"]:
                assert zone[name] == before["environment_config"][name], name
        for name, value in before["irrigation_strategy"].items():
            if name == "applied_recipe_id":
                assert name not in zone["strategy"]
                applied = zone["strategy"].get("applied_recipe")
                recipe = stored["data"]["irrigation_recipes"].get(value)
                if recipe is None:
                    assert applied is None
                else:
                    assert applied["id"] == value
                    assert applied["revision"] == recipe["revision"] == 1
                    assert applied["values"] == recipe[recipe["kind"]]
            elif name in LIGHT_CYCLE_FIELDS:
                assert after["light_cycle"][name] == value, name
            else:
                assert zone["strategy"][name] == value, name
        for name, value in before["substrate_history"].items():
            assert zone["substrate_history"][name] == value, name

    kept = hass_storage[COPY_KEY]
    assert kept["version"] == golden_config["version"]
    assert kept["minor_version"] == golden_config["minor_version"]
    assert kept["data"] == golden_config["data"]

    unique_ids = sorted(
        entry.unique_id
        for entry in er.async_get(hass).entities.values()
        if entry.platform == DOMAIN
    )
    assert unique_ids == json.loads((FIXTURES / "v1_2_3_unique_ids.json").read_text())
    assert not [
        issue_id
        for (domain, issue_id) in ir.async_get(hass).issues
        if domain == DOMAIN and issue_id.startswith(ZONE_MIGRATION_INVALID)
    ]

    await _unload(hass, mock_config_entry)
    with pytest.raises(UnsupportedStorageVersionError):
        await Store(hass, 1, STORAGE_KEY_CONFIG).async_load()


def _before(
    document: dict[str, Any],
) -> tuple[IrrigationConfig, IrrigationStrategy, int]:
    """What v1.2.3 handed the steering code: its own documents, as stored."""
    return (
        IrrigationConfig.from_dict(document["irrigation_config"]),
        IrrigationStrategy.from_dict(document["irrigation_strategy"]),
        resolve_day_hours(EnvironmentConfig.from_dict(document["environment_config"])),
    )


def _after(
    document: dict[str, Any],
) -> tuple[IrrigationConfig, IrrigationStrategy, int]:
    """What a zoned build hands it: the implicit zone's effective views."""
    growspace = Growspace.from_dict(migrate_growspace_document(document))
    return (
        effective_config(growspace),
        effective_strategy(growspace),
        resolve_day_hours(growspace.environment_config),
    )


def _steering_day(
    config: IrrigationConfig, strategy: IrrigationStrategy, day_hours: int
) -> list[Any]:
    """Tick one machine through a day of readings and return every verdict."""
    machine = SteeringPhaseMachine("golden")
    start = datetime(2026, 9, 21, tzinfo=UTC)
    verdicts = []
    last_shot = None
    for minute in range(0, 24 * 60, 5):
        now = start + timedelta(minutes=minute)
        vwc = 44.0 + (minute % 180) / 15
        verdict = machine.tick(
            SteeringTickInputs(
                now=now,
                vwc=vwc,
                strategy=strategy,
                auto_advance_p2_to_p3=config.auto_advance_p2_to_p3,
                soil_trigger_percent=config.soil_trigger_percent,
                pump_flow_rate_ml_per_sec=config.pump_flow_rate_ml_per_sec,
                pump_configured=bool(config.irrigation_pump_entity),
                day_hours=day_hours,
                live_plant_count=2,
                last_shot=last_shot,
                interval_factor=1.0,
                infiltration=InfiltrationState.SETTLED,
            )
        )
        if verdict.fire is not None:
            last_shot = now
        verdicts.append(verdict)
    return verdicts


@pytest.mark.parametrize("growspace_id", ["tent_steered", "tent_scheduled"])
def test_steering_tick_verdicts_are_identical_after_migrating(
    growspace_id: str,
) -> None:
    """A day of steering ticks decides exactly as it did on v1.2.3's documents."""
    document = _v1_growspaces()[growspace_id]

    before = _steering_day(*_before(document))
    after = _steering_day(*_after(document))

    assert after == before
    if growspace_id == "tent_steered":
        assert any(verdict.fire for verdict in before), "the day must fire shots"


@pytest.mark.parametrize("growspace_id", ["tent_steered", "tent_scheduled"])
def test_schedule_tick_verdicts_are_identical_after_migrating(
    growspace_id: str,
) -> None:
    """The Pump Cycle Gate decides every scheduled cycle as it did before."""
    document = _v1_growspaces()[growspace_id]

    def verdicts(config: IrrigationConfig) -> list[Any]:
        volume = cycle_volume_liters(config, config.irrigation_duration or 0)
        return [
            decide_cycle(
                event_type="irrigation",
                is_manual=False,
                config=config,
                tank_readings=[],
                lights_dark=dark,
                cycles_today=cycles,
                volume_today=today,
                cycle_volume_l=volume,
            )
            for dark in (False, True)
            for cycles in (0, 39, 40)
            for today in (0.0, 17.5, 18.0)
        ]

    before = verdicts(_before(document)[0])
    after = verdicts(_after(document)[0])

    assert after == before
    assert {verdict.fire for verdict in before} == (
        {True, False} if growspace_id == "tent_steered" else {True}
    )


async def test_invalid_zones_hold_only_that_growspace_until_they_are_valid(
    hass: HomeAssistant,
    hass_storage: dict,
    mock_config_entry: MockConfigEntry,
    enable_custom_integrations: None,
    recorder_mock: None,
) -> None:
    """``zone_migration_invalid`` latches on its growspace and clears on a load."""
    data = copy.deepcopy(_golden(STORAGE_KEY_CONFIG)["data"])
    data["growspaces"] = {
        growspace_id: migrate_growspace_document(document)
        for growspace_id, document in data["growspaces"].items()
    }
    broken = data["growspaces"]["tent_scheduled"]
    broken["irrigation_zones"][0]["cells"].pop()
    hass_storage[STORAGE_KEY_CONFIG] = {
        "version": 2,
        "minor_version": 1,
        "key": STORAGE_KEY_CONFIG,
        "data": data,
    }

    await _setup(hass, mock_config_entry)

    issue_id = f"{ZONE_MIGRATION_INVALID}_tent_scheduled"
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_key == ZONE_MIGRATION_INVALID
    assert issue.translation_placeholders == {
        "growspace": "Tent Scheduled",
        "problems": "1 cell(s) belong to no zone, first (3, 2)",
        "copy": f".storage/{COPY_KEY}",
    }
    assert (
        ir.async_get(hass).async_get_issue(
            DOMAIN, f"{ZONE_MIGRATION_INVALID}_tent_steered"
        )
        is None
    )

    growspaces = mock_config_entry.runtime_data.services.growspaces
    held = growspaces.get_irrigation_coordinator("tent_scheduled").controller_snapshot()
    assert held.state.value == "fault"
    assert held.fault_id == ZONE_MIGRATION_INVALID
    steered = growspaces.get_irrigation_coordinator(
        "tent_steered"
    ).controller_snapshot()
    assert steered.fault_id is None

    await _unload(hass, mock_config_entry)
    stored = hass_storage[STORAGE_KEY_CONFIG]["data"]["growspaces"]["tent_scheduled"]
    stored["irrigation_zones"][0]["cells"].append([3, 2])

    await _setup(hass, mock_config_entry)

    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
    growspaces = mock_config_entry.runtime_data.services.growspaces
    released = growspaces.get_irrigation_coordinator(
        "tent_scheduled"
    ).controller_snapshot()
    assert released.fault_id is None
    await _unload(hass, mock_config_entry)


async def test_unreadable_zone_keeps_growspace_and_original_storage(
    hass: HomeAssistant,
    hass_storage: dict,
    mock_config_entry: MockConfigEntry,
    enable_custom_integrations: None,
    recorder_mock: None,
) -> None:
    """A malformed zone must not take plants or climate down or be saved away."""
    data = copy.deepcopy(_golden(STORAGE_KEY_CONFIG)["data"])
    data["growspaces"] = {
        gid: migrate_growspace_document(document)
        for gid, document in data["growspaces"].items()
    }
    broken = data["growspaces"]["tent_scheduled"]
    broken["irrigation_zones"][0]["cells"] = 3
    hass_storage[STORAGE_KEY_CONFIG] = {
        "version": 2,
        "minor_version": 1,
        "key": STORAGE_KEY_CONFIG,
        "data": data,
    }

    await _setup(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data
    assert "tent_scheduled" in coordinator.growspaces
    coordinator.growspaces[
        "tent_scheduled"
    ].environment_config.temperature_sensor = "sensor.repaired_climate"
    assert (
        coordinator.services.growspaces.get_irrigation_coordinator("tent_scheduled")
        .controller_snapshot()
        .fault_id
        == ZONE_MIGRATION_INVALID
    )
    await coordinator.storage_manager.async_force_save()
    assert (
        hass_storage[STORAGE_KEY_CONFIG]["data"]["growspaces"]["tent_scheduled"][
            "environment_config"
        ]["temperature_sensor"]
        == "sensor.repaired_climate"
    )
    assert (
        hass_storage[STORAGE_KEY_CONFIG]["data"]["growspaces"]["tent_scheduled"][
            "irrigation_zones"
        ][0]["cells"]
        == 3
    )
    await _unload(hass, mock_config_entry)
