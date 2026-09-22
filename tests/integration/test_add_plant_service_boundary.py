"""The public add_plant response crosses the real service registration."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.models import Growspace, Plant
from custom_components.growspace_manager.service_registration import register_services
from custom_components.growspace_manager.services.plant_facade import PlantFacade
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from tests.common import MockConfigEntry


@pytest.mark.parametrize("return_response", [True, False])
async def test_add_plant_optional_response(
    hass: HomeAssistant, return_response: bool
) -> None:
    """Existing callers still work; requesting callers receive the created ID."""
    coordinator = MagicMock()
    coordinator.growspaces = {"gs1": Growspace(id="gs1", name="Tent")}
    plant = Plant(plant_id="created-plant", growspace_id="gs1", row=1, col=1)
    coordinator._plant_manager.add_plant = AsyncMock(return_value=plant)
    coordinator.services.plants = PlantFacade(coordinator)
    entry = MockConfigEntry(domain=DOMAIN, entry_id="plant_boundary")
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    entry.runtime_data = coordinator
    await register_services(hass, MagicMock())

    response = await hass.services.async_call(
        DOMAIN,
        "add_plant",
        {
            "growspace_id": "gs1",
            "strain": "Blue Dream",
            "row": 1,
            "col": 1,
            "clone_start": "2026-09-05",
        },
        blocking=True,
        return_response=return_response,
    )

    assert response == ({"plant_id": "created-plant"} if return_response else None)
    coordinator._plant_manager.add_plant.assert_awaited_once()

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "add_plant",
            {"growspace_id": "missing", "strain": "Blue Dream", "row": 1, "col": 1},
            blocking=True,
            return_response=return_response,
        )
    coordinator._plant_manager.add_plant.assert_awaited_once()
