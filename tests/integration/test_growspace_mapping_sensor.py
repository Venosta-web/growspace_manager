"""Verify the Growspace Mapping contract through Home Assistant states."""

from datetime import timedelta

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.utils import (
    generate_growspace_overview_unique_id,
)
from homeassistant.components.recorder.db_schema import MAX_STATE_ATTRS_BYTES
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.json import json_bytes
import homeassistant.util.dt as dt_util
from tests.common import MockConfigEntry


def _mappings(hass: HomeAssistant) -> dict[str, State]:
    return {
        state.attributes["growspace_id"]: state
        for state in hass.states.async_all("sensor")
        if state.attributes.get("growspace_mapping") is True
    }


async def test_mapping_exposes_primary_entities_and_flat_live_metrics(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Discover a growspace and read configured entity IDs and numeric targets."""
    coordinator = init_integration.runtime_data
    growspace = await coordinator.services.growspaces.add_growspace(
        name="SOG 2x5",
        environment_config={
            "temperature_sensor": "sensor.shared_temperature",
            "humidity_sensors": ["sensor.shared_humidity"],
            "vpd_sensor": "sensor.custom_calculated_vpd",
            "exhaust_fan_entities": ["fan.primary_exhaust", "fan.backup_exhaust"],
            "circulation_fan_entities": ["fan.sog_under_canopy"],
            "humidifier_entities": ["humidifier.sog"],
            "dehumidifier_ac_infinity_devices": [
                {
                    "mode_entity": "select.dry_air_mode",
                    "speed_entity": "number.dry_air_intensity",
                }
            ],
            "light_sensors": ["binary_sensor.sog_lights"],
        },
    )
    await coordinator.async_refresh()
    await hass.async_block_till_done(wait_background_tasks=True)

    registry = er.async_get(hass)
    overview_id = registry.async_get_entity_id(
        "sensor", DOMAIN, generate_growspace_overview_unique_id(growspace.id)
    )
    assert overview_id is not None
    mapping = _mappings(hass)[growspace.id]
    assert mapping.attributes["overview_entity_id"] == overview_id
    assert mapping.attributes["name"] == "SOG 2x5"
    assert mapping.attributes["type"] == growspace.growspace_type.value
    assert mapping.attributes["temperature_entity_id"] == "sensor.shared_temperature"
    assert mapping.attributes["humidity_entity_id"] == "sensor.shared_humidity"
    assert mapping.attributes["vpd_entity_id"] == "sensor.custom_calculated_vpd"
    assert mapping.attributes["exhaust_entity_id"] == "fan.primary_exhaust"
    assert mapping.attributes["circulation_entity_id"] == "fan.sog_under_canopy"
    assert mapping.attributes["humidifier_entity_id"] == "humidifier.sog"
    assert mapping.attributes["dehumidifier_entity_id"] == "select.dry_air_mode"
    assert mapping.attributes["vpd_target_min"] is None

    await coordinator.services.plants.add_plant(
        growspace_id=growspace.id,
        strain="OG Kush",
        row=1,
        col=1,
        veg_start=(dt_util.now().date() - timedelta(days=14)).isoformat(),
    )
    await coordinator.async_refresh()
    await hass.async_block_till_done(wait_background_tasks=True)

    mapping = _mappings(hass)[growspace.id]
    overview = hass.states.get(overview_id)
    assert overview is not None
    metrics = overview.attributes["metrics"]
    assert isinstance(metrics["vpd_target_min"], float)
    for key in (
        "granular_stage",
        "is_day",
        "veg_week",
        "flower_week",
        "vpd_target_min",
        "vpd_target_max",
        "vpd_danger_min",
        "vpd_danger_max",
    ):
        assert mapping.attributes[key] == metrics[key]
    assert mapping.state == metrics["granular_stage"]
    assert len(json_bytes(dict(mapping.attributes))) < MAX_STATE_ATTRS_BYTES

    hass.states.async_set("binary_sensor.sog_lights", "off")
    hass.states.async_set("sensor.shared_temperature", "24")
    await hass.async_block_till_done(wait_background_tasks=True)
    overview = hass.states.get(overview_id)
    assert overview is not None
    assert overview.attributes["metrics"]["is_day"] is False
    assert _mappings(hass)[growspace.id].attributes["is_day"] is False


async def test_mapping_stays_compact_and_follows_growspace_lifecycle(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Keep independent mappings discoverable, even with large configurations."""
    coordinator = init_integration.runtime_data
    shared_temperature = "sensor." + "t" * 248
    exhaust = "fan." + "e" * 251
    first = await coordinator.services.growspaces.add_growspace(
        name="Large tent " + "🌱" * 3000,
        environment_config={
            "temperature_sensor": shared_temperature,
            "exhaust_fan_entities": [exhaust]
            + [f"fan.backup_{i:02d}_" + "f" * 220 for i in range(80)],
        },
    )
    second = await coordinator.services.growspaces.add_growspace(
        name="Second tent",
        environment_config={
            "temperature_sensor": shared_temperature,
            "humidifier_entities": ["humidifier." + "x" * MAX_STATE_ATTRS_BYTES],
            "circulation_fan_entities": ["fan." + "\x00" * 251],
        },
    )
    await coordinator.async_refresh()
    await hass.async_block_till_done(wait_background_tasks=True)

    mappings = _mappings(hass)
    for growspace_id in (first.id, second.id):
        attributes = mappings[growspace_id].attributes
        assert attributes["temperature_entity_id"] == shared_temperature
        assert attributes["vpd_entity_id"] is None
        assert len(json_bytes(dict(attributes))) < MAX_STATE_ATTRS_BYTES
        assert all(
            value is None or isinstance(value, (str, bool, int, float))
            for value in attributes.values()
        )
    assert mappings[first.id].attributes["exhaust_entity_id"] == exhaust
    assert mappings[second.id].attributes["exhaust_entity_id"] is None
    assert mappings[second.id].attributes["humidifier_entity_id"] is None
    assert mappings[second.id].attributes["circulation_entity_id"] is None

    old_overview_id = mappings[second.id].attributes["overview_entity_id"]
    renamed = "sensor.custom_second_tent_overview"
    registry = er.async_get(hass)
    registry.async_update_entity(old_overview_id, name="Second tent display")
    await hass.async_block_till_done(wait_background_tasks=True)
    registry.async_update_entity(old_overview_id, new_entity_id=renamed)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert _mappings(hass)[second.id].attributes["overview_entity_id"] == renamed

    await coordinator.services.growspaces.remove_growspace(first.id)
    await coordinator.async_refresh()
    await hass.async_block_till_done(wait_background_tasks=True)

    assert hass.states.get(mappings[first.id].entity_id) is None
    assert registry.async_get(mappings[first.id].entity_id) is None
    assert second.id in _mappings(hass)


async def test_mapping_resolves_the_registered_calculated_vpd(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Use the calculated VPD's registered ID after a Home Assistant rename."""
    coordinator = init_integration.runtime_data
    primary_vpd = "sensor.calculated_tent_calculated_vpd_1"
    growspace = await coordinator.services.growspaces.add_growspace(
        name="Calculated tent",
        environment_config={
            "vpd_sensor": primary_vpd,
            "temperature_sensors": ["sensor.shared_temperature", "sensor.inner_temp"],
            "humidity_sensors": ["sensor.shared_humidity", "sensor.inner_humidity"],
        },
    )
    await coordinator.async_refresh()
    await hass.async_block_till_done(wait_background_tasks=True)

    assert hass.states.get(primary_vpd) is not None
    assert _mappings(hass)[growspace.id].attributes["vpd_entity_id"] == primary_vpd

    renamed = "sensor.custom_calculated_vpd"
    er.async_get(hass).async_update_entity(primary_vpd, new_entity_id=renamed)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert _mappings(hass)[growspace.id].attributes["vpd_entity_id"] == renamed

    await coordinator.services.growspaces.update_growspace(
        growspace.id, name="Renamed calculated tent"
    )
    await coordinator.async_refresh()
    await hass.async_block_till_done(wait_background_tasks=True)
    mapping = _mappings(hass)[growspace.id]
    assert mapping.attributes["name"] == "Renamed calculated tent"
    assert mapping.attributes["vpd_entity_id"] == renamed

    # A configured external entity that takes the default ID wins once present.
    external = er.async_get(hass).async_get_or_create(
        "sensor",
        "template",
        "external_vpd",
        suggested_object_id=primary_vpd.removeprefix("sensor."),
    )
    assert external.entity_id == primary_vpd
    await hass.async_block_till_done(wait_background_tasks=True)
    assert _mappings(hass)[growspace.id].attributes["vpd_entity_id"] == primary_vpd
