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


async def test_flow_meter_config_through_registered_service(
    hass, registered_environment_service
):
    """Supply and zone meters coexist; omission keeps and [] clears them."""
    coordinator, growspace = registered_environment_service
    hass.states.async_set(
        "sensor.supply",
        "1",
        {
            "device_class": "water",
            "state_class": "total_increasing",
            "unit_of_measurement": "L",
        },
    )
    hass.states.async_set(
        "sensor.zone",
        "1",
        {"device_class": "volume_flow_rate", "unit_of_measurement": "gal/min"},
    )
    meters = [
        {"entity_id": "sensor.supply", "placement": "supply"},
        {"entity_id": "sensor.zone", "placement": "default"},
    ]
    await hass.services.async_call(
        DOMAIN,
        "configure_environment",
        {"growspace_id": growspace.id, "flow_meters": meters},
        blocking=True,
    )
    assert [
        meter.to_dict() for meter in growspace.environment_config.flow_meters
    ] == meters
    await hass.services.async_call(
        DOMAIN,
        "configure_environment",
        {"growspace_id": growspace.id, "lst_offset": -1},
        blocking=True,
    )
    assert [
        meter.to_dict() for meter in growspace.environment_config.flow_meters
    ] == meters
    await hass.services.async_call(
        DOMAIN,
        "configure_environment",
        {"growspace_id": growspace.id, "flow_meters": []},
        blocking=True,
    )
    assert growspace.environment_config.flow_meters == []
    assert coordinator.services.save.await_count == 3


@pytest.mark.parametrize(
    "meters",
    [
        [{"entity_id": "sensor.missing", "placement": "supply"}],
        [{"entity_id": "sensor.supply", "placement": "missing-zone"}],
        [
            {"entity_id": "sensor.supply", "placement": "supply"},
            {"entity_id": "sensor.supply", "placement": "supply"},
        ],
    ],
)
async def test_invalid_meter_service_is_atomic(
    hass, registered_environment_service, meters
):
    coordinator, growspace = registered_environment_service
    hass.states.async_set(
        "sensor.supply",
        "1",
        {"device_class": "water", "state_class": "total", "unit_of_measurement": "L"},
    )
    original = growspace.to_dict()
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "configure_environment",
            {"growspace_id": growspace.id, "flow_meters": meters, "lst_offset": -1},
            blocking=True,
        )
    assert growspace.to_dict() == original
    coordinator.services.save.assert_not_awaited()
