"""Contract tests for the Acceptable Moisture Band in the growspace payload.

The card never reads sensor entity attributes, so the band has to reach it
through the growspace view model. These pin what the card needs to tell an
inherited band from a custom one, and to show an incompatibility state.
"""

from __future__ import annotations

import pytest

from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    GrowspaceType,
)
from custom_components.growspace_manager.presentation.growspace_view_model import (
    GrowspaceViewModelBuilder,
)
from homeassistant.core import HomeAssistant

MOISTURE_SENSOR = "sensor.test_soil_moisture"


def _growspace(env: EnvironmentConfig) -> Growspace:
    """Build a growspace carrying the given environment config."""
    return Growspace(
        id="gs1",
        name="Test",
        growspace_type=GrowspaceType.FLOWER,
        environment_config=env,
    )


def _environment(hass: HomeAssistant, env: EnvironmentConfig) -> dict:
    """Return the environment attribute block the card receives."""
    return GrowspaceViewModelBuilder(hass)._get_environment_attributes(_growspace(env))


async def test_inherited_band_is_reported_as_effective_but_not_custom(
    hass: HomeAssistant,
) -> None:
    """The card can show 20–60% without presenting it as a saved override."""
    attributes = _environment(hass, EnvironmentConfig())

    assert attributes["soil_moisture_min"] is None
    assert attributes["soil_moisture_max"] is None
    assert attributes["soil_moisture_band"] == {
        "min": 20.0,
        "max": 60.0,
        "is_custom": False,
    }


async def test_custom_band_is_reported_as_a_saved_override(
    hass: HomeAssistant,
) -> None:
    """A stored pair reaches the card as both raw values and an effective band."""
    attributes = _environment(
        hass, EnvironmentConfig(soil_moisture_min=32.5, soil_moisture_max=54.0)
    )

    assert attributes["soil_moisture_min"] == 32.5
    assert attributes["soil_moisture_max"] == 54.0
    assert attributes["soil_moisture_band"] == {
        "min": 32.5,
        "max": 54.0,
        "is_custom": True,
    }


async def test_stored_band_is_visible_without_any_sensor(
    hass: HomeAssistant,
) -> None:
    """Removing the sensor must not make a stored override look discarded."""
    attributes = _environment(
        hass,
        EnvironmentConfig(soil_moisture_min=32.5, soil_moisture_max=54.0),
    )

    assert "soil_moisture_sensor" not in attributes
    assert attributes["soil_moisture_min"] == 32.5
    assert attributes["soil_moisture_max"] == 54.0


@pytest.mark.parametrize(
    ("unit", "compatible"),
    [
        pytest.param("%", True, id="percentage"),
        pytest.param(None, True, id="legacy-no-unit-metadata"),
        pytest.param("°C", False, id="temperature"),
        pytest.param("m³/m³", False, id="volumetric-ratio"),
    ],
)
async def test_sensor_unit_compatibility_reaches_the_card(
    hass: HomeAssistant, unit: str | None, compatible: bool
) -> None:
    """The card needs the unit to render an incompatibility state."""
    hass.states.async_set(
        MOISTURE_SENSOR,
        "42.0",
        {} if unit is None else {"unit_of_measurement": unit},
    )

    attributes = _environment(
        hass, EnvironmentConfig(soil_moisture_sensor=MOISTURE_SENSOR)
    )

    assert attributes["soil_moisture_sensor"] == MOISTURE_SENSOR
    assert attributes["soil_moisture_value"] == "42.0"
    assert attributes["soil_moisture_unit"] == unit
    assert attributes["soil_moisture_band_compatible"] is compatible


async def test_band_does_not_depend_on_pump_or_tank_hardware(
    hass: HomeAssistant,
) -> None:
    """Visibility rests on the moisture sensor alone, never on irrigation gear."""
    hass.states.async_set(MOISTURE_SENSOR, "42.0", {"unit_of_measurement": "%"})

    attributes = _environment(
        hass,
        EnvironmentConfig(
            soil_moisture_sensor=MOISTURE_SENSOR,
            soil_moisture_min=32.5,
            soil_moisture_max=54.0,
            irrigation_tanks=[],
        ),
    )

    assert attributes["soil_moisture_band_compatible"] is True
    assert attributes["soil_moisture_band"]["is_custom"] is True
