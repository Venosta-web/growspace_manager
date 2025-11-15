"""Tests for the Growspace Manager sensor platform."""
from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.growspace_manager.const import DOMAIN


async def test_sensor_creation(hass: HomeAssistant) -> None:
    """Test that all sensors are created."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "My Growspace"},
        options={
            "global_settings": {
                "weather_entity": "weather.home",
                "lung_room_temp_sensor": "sensor.lung_temp",
                "lung_room_humidity_sensor": "sensor.lung_humidity",
            }
        },
    )
    config_entry.add_to_hass(hass)

    with patch(
        "custom_components.growspace_manager.GrowspaceCoordinator.async_load",
        return_value=True,
    ), patch(
        "custom_components.growspace_manager.sensor.async_setup_trend_sensor",
        return_value="trend_unique_id",
    ), patch(
        "custom_components.growspace_manager.sensor.async_setup_statistics_sensor",
        return_value="stats_unique_id",
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    growspace = await coordinator.async_add_growspace(
        name="Test Growspace",
        rows=2,
        plants_per_row=2,
    )
    await coordinator.async_add_plant(
        growspace_id=growspace.id,
        strain="Test Plant",
        row=1,
        col=1,
    )
    await hass.async_block_till_done()

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.test_growspace") is not None
    assert hass.states.get("sensor.test_plant_1_1") is not None
    assert hass.states.get("sensor.growspace_strain_library") is not None
    assert hass.states.get("sensor.growspaces_list") is not None
    assert hass.states.get("sensor.outside_vpd") is not None
    assert hass.states.get("sensor.lung_room_vpd") is not None
    assert (
        hass.states.get("sensor.test_growspace_air_exchange") is not None
    )


async def test_growspace_overview_sensor_state_and_attributes(
    hass: HomeAssistant,
) -> None:
    """Test the state and attributes of the GrowspaceOverviewSensor."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "My Growspace"},
    )
    config_entry.add_to_hass(hass)

    with patch(
        "custom_components.growspace_manager.GrowspaceCoordinator.async_load",
        return_value=True,
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    growspace = await coordinator.async_add_growspace(
        name="Test Growspace",
        rows=2,
        plants_per_row=2,
    )
    await coordinator.async_add_plant(
        growspace_id=growspace.id,
        strain="Test Plant",
        row=1,
        col=1,
    )
    await hass.async_block_till_done()

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_growspace")
    assert state is not None
    assert state.state == "1"
    assert state.attributes["total_plants"] == 1
    assert "grid" in state.attributes


async def test_plant_entity_state_and_attributes(hass: HomeAssistant) -> None:
    """Test the state and attributes of the PlantEntity."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "My Growspace"},
    )
    config_entry.add_to_hass(hass)

    with patch(
        "custom_components.growspace_manager.GrowspaceCoordinator.async_load",
        return_value=True,
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    growspace = await coordinator.async_add_growspace(
        name="Test Growspace",
        rows=2,
        plants_per_row=2,
    )
    await coordinator.async_add_plant(
        growspace_id=growspace.id,
        strain="Test Plant",
        row=1,
        col=1,
        veg_start="2023-01-01",
    )
    await hass.async_block_till_done()

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_plant_1_1")
    assert state is not None
    assert state.state == "veg"
    assert "veg_days" in state.attributes


async def test_vpd_sensor_logic(hass: HomeAssistant) -> None:
    """Test the logic of the VpdSensor."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "My Growspace"},
        options={
            "global_settings": {
                "weather_entity": "weather.home",
            }
        },
    )
    config_entry.add_to_hass(hass)

    hass.states.async_set(
        "weather.home", "sunny", {"temperature": 25, "humidity": 60}
    )

    with patch(
        "custom_components.growspace_manager.GrowspaceCoordinator.async_load",
        return_value=True,
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    state = hass.states.get("sensor.outside_vpd")
    assert state is not None
    assert state.state == "1.28"
