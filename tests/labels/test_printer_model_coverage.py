"""Tests for which printers a profile's evidence covers (hub issue #231).

The suites answer the device-registry lookup with the tested model, so this
one asks the real registry: a B1 is covered, a B21 is not, and a device ID the
registry does not know has no model anyone can check.
"""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.growspace_manager.labels.canonical import NIIMBOT_B1_50X30
from custom_components.growspace_manager.labels.canonical.preview import (
    _printer_covered,
    device_model,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr


@pytest.fixture(autouse=True)
def printers_are_the_tested_model() -> None:
    """Replace the suites' stand-in: this module asks the real registry."""


def _printer(hass: HomeAssistant, model: str) -> str:
    entry = MockConfigEntry(domain="niimbot")
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("niimbot", f"{model}-address")},
        manufacturer="Niimbot",
        model=model,
    )
    return device.id


async def test_a_registered_printer_reports_the_model_it_was_registered_under(
    hass: HomeAssistant,
) -> None:
    assert device_model(hass, _printer(hass, "B1")) == "B1"


async def test_a_printer_nobody_registered_has_no_model(hass: HomeAssistant) -> None:
    assert device_model(hass, "no-such-device") is None


async def test_the_tested_model_is_covered_and_its_neighbours_are_not(
    hass: HomeAssistant,
) -> None:
    assert _printer_covered(hass, NIIMBOT_B1_50X30, _printer(hass, "B1"))
    assert not _printer_covered(hass, NIIMBOT_B1_50X30, _printer(hass, "B21"))
    assert not _printer_covered(hass, NIIMBOT_B1_50X30, "no-such-device")


async def test_a_render_that_names_no_printer_is_not_refused_for_it(
    hass: HomeAssistant,
) -> None:
    """A preview drawn before anyone chose a printer authorizes nothing, and
    every route that puts a record on paper requires one."""
    assert _printer_covered(hass, NIIMBOT_B1_50X30, None)
