"""Tests for the helper functions in helpers.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.growspace_manager.helpers import (
    async_setup_statistics_sensor,
    async_setup_trend_sensor,
)


@pytest.fixture
def mock_hass():
    """Fixture for a mock HomeAssistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.config_entries = MagicMock()
    return hass

@pytest.mark.asyncio
async def test_async_setup_trend_sensor(mock_hass):
    """Test async_setup_trend_sensor function."""
    entity_registry = MagicMock(spec=er.EntityRegistry)
    entity_registry.async_get.return_value = True
    entity_registry.async_get_entity_id.return_value = None

    with patch("custom_components.growspace_manager.helpers.er.async_get", return_value=entity_registry), \
         patch("custom_components.growspace_manager.helpers.async_load_platform", new_callable=AsyncMock) as mock_load_platform:

        unique_id = await async_setup_trend_sensor(
            mock_hass, "sensor.test", "gs1", "Growspace 1", "temperature"
        )

        assert unique_id == "growspace_manager_gs1_temperature_trend"
        mock_load_platform.assert_called_once()

@pytest.mark.asyncio
async def test_async_setup_trend_sensor_source_not_found(mock_hass):
    """Test async_setup_trend_sensor when source sensor is not found."""
    entity_registry = MagicMock(spec=er.EntityRegistry)
    entity_registry.async_get.return_value = False

    with patch("custom_components.growspace_manager.helpers.er.async_get", return_value=entity_registry):
        unique_id = await async_setup_trend_sensor(
            mock_hass, "sensor.test", "gs1", "Growspace 1", "temperature"
        )
        assert unique_id is None

@pytest.mark.asyncio
async def test_async_setup_trend_sensor_already_exists(mock_hass):
    """Test async_setup_trend_sensor when the sensor already exists."""
    entity_registry = MagicMock(spec=er.EntityRegistry)
    entity_registry.async_get.return_value = True
    entity_registry.async_get_entity_id.return_value = "binary_sensor.growspace_1_temperature_trend"

    with patch("custom_components.growspace_manager.helpers.er.async_get", return_value=entity_registry), \
         patch("custom_components.growspace_manager.helpers.async_load_platform", new_callable=AsyncMock) as mock_load_platform:

        unique_id = await async_setup_trend_sensor(
            mock_hass, "sensor.test", "gs1", "Growspace 1", "temperature"
        )

        assert unique_id == "growspace_manager_gs1_temperature_trend"
        mock_load_platform.assert_not_called()

@pytest.mark.asyncio
async def test_async_setup_statistics_sensor(mock_hass):
    """Test async_setup_statistics_sensor function."""
    entity_registry = MagicMock(spec=er.EntityRegistry)
    entity_registry.async_get.return_value = True
    entity_registry.async_get_entity_id.return_value = None

    with patch("custom_components.growspace_manager.helpers.er.async_get", return_value=entity_registry), \
         patch("custom_components.growspace_manager.helpers.async_load_platform", new_callable=AsyncMock) as mock_load_platform:

        unique_id = await async_setup_statistics_sensor(
            mock_hass, "sensor.test", "gs1", "Growspace 1", "temperature"
        )

        assert unique_id == "growspace_manager_gs1_temperature_stats"
        mock_load_platform.assert_called_once()

@pytest.mark.asyncio
async def test_async_setup_statistics_sensor_source_not_found(mock_hass):
    """Test async_setup_statistics_sensor when source sensor is not found."""
    entity_registry = MagicMock(spec=er.EntityRegistry)
    entity_registry.async_get.return_value = False

    with patch("custom_components.growspace_manager.helpers.er.async_get", return_value=entity_registry):
        unique_id = await async_setup_statistics_sensor(
            mock_hass, "sensor.test", "gs1", "Growspace 1", "temperature"
        )
        assert unique_id is None

@pytest.mark.asyncio
async def test_async_setup_statistics_sensor_already_exists(mock_hass):
    """Test async_setup_statistics_sensor when the sensor already exists."""
    entity_registry = MagicMock(spec=er.EntityRegistry)
    entity_registry.async_get.return_value = True
    entity_registry.async_get_entity_id.return_value = "sensor.growspace_1_temperature_stats"

    with patch("custom_components.growspace_manager.helpers.er.async_get", return_value=entity_registry), \
         patch("custom_components.growspace_manager.helpers.async_load_platform", new_callable=AsyncMock) as mock_load_platform:

        unique_id = await async_setup_statistics_sensor(
            mock_hass, "sensor.test", "gs1", "Growspace 1", "temperature"
        )

        assert unique_id == "growspace_manager_gs1_temperature_stats"
        mock_load_platform.assert_not_called()
