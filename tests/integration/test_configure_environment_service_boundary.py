"""Service-boundary tests for environment configuration."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.models import EnvironmentConfig, Growspace
from custom_components.growspace_manager.service_registration import register_services
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from tests.common import MockConfigEntry


@pytest.fixture
async def registered_environment_service(
    hass: HomeAssistant,
) -> tuple[MagicMock, Growspace]:
    """Register production services against a loaded coordinator."""
    growspace = Growspace(
        id="gs1",
        name="Service Boundary Growspace",
        environment_config=EnvironmentConfig(),
    )
    coordinator = MagicMock()
    coordinator.growspaces = {growspace.id: growspace}
    coordinator.services.save = AsyncMock()
    coordinator.services.request_refresh = AsyncMock()
    coordinator._subsystem_manager.get_circulation_fan_controller.return_value = None

    entry = MockConfigEntry(domain=DOMAIN, entry_id="service_boundary")
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    entry.runtime_data = coordinator

    await register_services(hass, MagicMock())

    return coordinator, growspace


async def test_configure_environment_persists_moisture_band_through_service_registry(
    hass: HomeAssistant,
    registered_environment_service: tuple[MagicMock, Growspace],
) -> None:
    """A complete moisture pair crosses schema, handler, patch, and persistence."""
    coordinator, growspace = registered_environment_service

    await hass.services.async_call(
        DOMAIN,
        "configure_environment",
        {
            "growspace_id": growspace.id,
            "soil_moisture_min": 32.5,
            "soil_moisture_max": 54.0,
        },
        blocking=True,
    )

    assert growspace.environment_config.soil_moisture_min == 32.5
    assert growspace.environment_config.soil_moisture_max == 54.0
    coordinator.services.save.assert_awaited_once()


async def test_configure_environment_accepts_documented_circulation_fans(
    hass: HomeAssistant,
    registered_environment_service: tuple[MagicMock, Growspace],
) -> None:
    """The documented plural fan field crosses the public service boundary."""
    coordinator, growspace = registered_environment_service

    await hass.services.async_call(
        DOMAIN,
        "configure_environment",
        {
            "growspace_id": growspace.id,
            "circulation_fan_entities": ["fan.airflow"],
        },
        blocking=True,
    )

    assert growspace.environment_config.circulation_fan_entities == ["fan.airflow"]
    coordinator.services.save.assert_awaited_once()


@pytest.mark.parametrize(
    "partial_pair",
    [
        pytest.param({"soil_moisture_min": 32.5}, id="minimum-only"),
        pytest.param({"soil_moisture_max": 54.0}, id="maximum-only"),
    ],
)
async def test_configure_environment_rejects_partial_moisture_band_through_service_registry(
    hass: HomeAssistant,
    registered_environment_service: tuple[MagicMock, Growspace],
    partial_pair: dict[str, float],
) -> None:
    """A partial moisture pair is rejected at the public service boundary."""
    coordinator, growspace = registered_environment_service

    with pytest.raises(ServiceValidationError, match="set as a pair"):
        await hass.services.async_call(
            DOMAIN,
            "configure_environment",
            {"growspace_id": growspace.id, **partial_pair},
            blocking=True,
        )

    assert growspace.environment_config.soil_moisture_min is None
    assert growspace.environment_config.soil_moisture_max is None
    coordinator.services.save.assert_not_awaited()
