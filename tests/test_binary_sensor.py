"""Tests for the Growspace Manager binary_sensor platform."""
from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.growspace_manager.const import DOMAIN


async def test_bayesian_sensors_creation(hass: HomeAssistant) -> None:
    """Test that Bayesian sensors are created."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "My Growspace"},
        options={
            "global_settings": {"weather_entity": "weather.home"},
            "gs1": {
                "temperature_sensor": "sensor.temp",
                "humidity_sensor": "sensor.humidity",
                "vpd_sensor": "sensor.vpd",
            },
        },
    )
    config_entry.add_to_hass(hass)

    with patch(
        "custom_components.growspace_manager.GrowspaceCoordinator.async_load",
        return_value=True,
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    await coordinator.async_add_growspace(
        name="Test Growspace",
        rows=2,
        plants_per_row=2,
    )
    await hass.async_block_till_done()

    # At this point, the growspace is added, but the entities are not yet created.
    # We need to trigger the entity creation.
    # In a real scenario, this would happen on the next update or on setup.
    # For now, let's assume the setup process handles this.
    # The current code doesn't dynamically add entities after initial setup,
    # so we need to restart the setup process.
    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.test_growspace_plants_under_stress") is not None
    assert hass.states.get("binary_sensor.test_growspace_high_mold_risk") is not None
    assert hass.states.get("binary_sensor.test_growspace_optimal_conditions") is not None


async def test_stress_sensor_logic(hass: HomeAssistant) -> None:
    """Test the logic of the stress sensor."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "My Growspace"},
        options={
            "global_settings": {"weather_entity": "weather.home"},
            "gs1": {
                "temperature_sensor": "sensor.temp",
                "humidity_sensor": "sensor.humidity",
                "vpd_sensor": "sensor.vpd",
            },
        },
    )
    config_entry.add_to_hass(hass)

    hass.states.async_set("sensor.temp", "35")
    hass.states.async_set("sensor.humidity", "50")
    hass.states.async_set("sensor.vpd", "1.5")

    with patch(
        "custom_components.growspace_manager.binary_sensor.BayesianEnvironmentSensor._async_analyze_sensor_trend",
        return_value={"trend": "stable", "crossed_threshold": False},
    ), patch(
        "custom_components.growspace_manager.GrowspaceCoordinator.async_load",
        return_value=True,
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    await coordinator.async_add_growspace(
        name="Test Growspace",
        rows=2,
        plants_per_row=2,
    )
    await hass.async_block_till_done()

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    await coordinator.async_refresh()
    await hass.async_block_till_done()

    stress_sensor = hass.states.get(
        "binary_sensor.test_growspace_plants_under_stress"
    )
    assert stress_sensor is not None
    assert stress_sensor.state == "on"


async def test_mold_risk_sensor_logic(hass: HomeAssistant) -> None:
    """Test the logic of the mold risk sensor."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "My Growspace"},
        options={
            "global_settings": {"weather_entity": "weather.home"},
            "gs1": {
                "temperature_sensor": "sensor.temp",
                "humidity_sensor": "sensor.humidity",
                "vpd_sensor": "sensor.vpd",
            },
        },
    )
    config_entry.add_to_hass(hass)

    hass.states.async_set("sensor.temp", "22")
    hass.states.async_set("sensor.humidity", "65")
    hass.states.async_set("sensor.vpd", "1.0")

    with patch(
        "custom_components.growspace_manager.binary_sensor.BayesianEnvironmentSensor._async_analyze_sensor_trend",
        return_value={"trend": "stable", "crossed_threshold": False},
    ), patch(
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
        flower_start="2023-01-01",
    )
    await hass.async_block_till_done()

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    await coordinator.async_refresh()
    await hass.async_block_till_done()

    mold_sensor = hass.states.get("binary_sensor.test_growspace_high_mold_risk")
    assert mold_sensor is not None
    assert mold_sensor.state == "on"


async def test_optimal_conditions_sensor_logic(hass: HomeAssistant) -> None:
    """Test the logic of the optimal conditions sensor."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "My Growspace"},
        options={
            "global_settings": {"weather_entity": "weather.home"},
            "gs1": {
                "temperature_sensor": "sensor.temp",
                "humidity_sensor": "sensor.humidity",
                "vpd_sensor": "sensor.vpd",
            },
        },
    )
    config_entry.add_to_hass(hass)

    hass.states.async_set("sensor.temp", "25")
    hass.states.async_set("sensor.humidity", "60")
    hass.states.async_set("sensor.vpd", "1.2")

    with patch(
        "custom_components.growspace_manager.binary_sensor.BayesianEnvironmentSensor._async_analyze_sensor_trend",
        return_value={"trend": "stable", "crossed_threshold": False},
    ), patch(
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

    await coordinator.async_refresh()
    await hass.async_block_till_done()

    optimal_sensor = hass.states.get(
        "binary_sensor.test_growspace_optimal_conditions"
    )
    assert optimal_sensor is not None
    assert optimal_sensor.state == "on"
