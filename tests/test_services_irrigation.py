"""Tests for irrigation service handlers."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.services.irrigation import (
    _get_irrigation_coordinator,
    handle_add_drain_time,
    handle_add_irrigation_time,
    handle_remove_drain_time,
    handle_remove_irrigation_time,
    handle_set_irrigation_settings,
)


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.config_entries = MagicMock()
    hass.data = {}
    return hass


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    return entry


@pytest.fixture
def mock_irrigation_coordinator():
    """Create a mock irrigation coordinator."""
    coordinator = MagicMock()
    coordinator.async_set_settings = AsyncMock()
    coordinator.async_add_schedule_item = AsyncMock()
    coordinator.async_remove_schedule_item = AsyncMock()
    coordinator.get_default_duration = MagicMock(return_value=300)
    return coordinator


@pytest.fixture
def mock_coordinator():
    """Create a mock growspace coordinator."""
    return MagicMock()


@pytest.fixture
def mock_strain_library():
    """Create a mock strain library."""
    return MagicMock()


class TestGetIrrigationCoordinator:
    """Tests for _get_irrigation_coordinator helper function."""

    @pytest.mark.asyncio
    async def test_no_config_entries(self, mock_hass):
        """Test error when no config entries exist."""
        mock_hass.config_entries.async_entries.return_value = []

        with pytest.raises(ServiceValidationError, match="not yet set up"):
            await _get_irrigation_coordinator(mock_hass, "gs1")

    @pytest.mark.asyncio
    async def test_missing_domain_data(self, mock_hass, mock_config_entry):
        """Test error when domain data is missing."""
        mock_hass.config_entries.async_entries.return_value = [mock_config_entry]
        # hass.data is empty

        with pytest.raises(ServiceValidationError, match="not found"):
            await _get_irrigation_coordinator(mock_hass, "gs1")

    @pytest.mark.asyncio
    async def test_missing_irrigation_coordinators(self, mock_hass, mock_config_entry):
        """Test error when irrigation_coordinators key is missing."""
        mock_hass.config_entries.async_entries.return_value = [mock_config_entry]
        mock_hass.data[DOMAIN] = {mock_config_entry.entry_id: {}}

        with pytest.raises(ServiceValidationError, match="not found"):
            await _get_irrigation_coordinator(mock_hass, "gs1")

    @pytest.mark.asyncio
    async def test_growspace_not_found(
        self, mock_hass, mock_config_entry, mock_irrigation_coordinator
    ):
        """Test error when specified growspace is not found."""
        mock_hass.config_entries.async_entries.return_value = [mock_config_entry]
        mock_hass.data[DOMAIN] = {
            mock_config_entry.entry_id: {
                "irrigation_coordinators": {"other_gs": mock_irrigation_coordinator}
            }
        }

        with pytest.raises(
            ServiceValidationError, match="'gs1' not found or has no irrigation setup"
        ):
            await _get_irrigation_coordinator(mock_hass, "gs1")

    @pytest.mark.asyncio
    async def test_success(
        self, mock_hass, mock_config_entry, mock_irrigation_coordinator
    ):
        """Test successful retrieval of irrigation coordinator."""
        mock_hass.config_entries.async_entries.return_value = [mock_config_entry]
        mock_hass.data[DOMAIN] = {
            mock_config_entry.entry_id: {
                "irrigation_coordinators": {"gs1": mock_irrigation_coordinator}
            }
        }

        result = await _get_irrigation_coordinator(mock_hass, "gs1")
        assert result == mock_irrigation_coordinator


class TestHandleSetIrrigationSettings:
    """Tests for handle_set_irrigation_settings service handler."""

    @pytest.mark.asyncio
    async def test_set_irrigation_settings(
        self,
        mock_hass,
        mock_config_entry,
        mock_irrigation_coordinator,
        mock_coordinator,
        mock_strain_library,
    ):
        """Test setting irrigation settings."""
        # Setup
        mock_hass.config_entries.async_entries.return_value = [mock_config_entry]
        mock_hass.data[DOMAIN] = {
            mock_config_entry.entry_id: {
                "irrigation_coordinators": {"gs1": mock_irrigation_coordinator}
            }
        }

        call = MagicMock(spec=ServiceCall)
        call.data = {
            "growspace_id": "gs1",
            "irrigation_pump_entity": "switch.pump",
            "drain_pump_entity": "switch.drain",
            "irrigation_duration": 600,
            "drain_duration": 300,
        }

        # Execute
        await handle_set_irrigation_settings(
            mock_hass, mock_coordinator, mock_strain_library, call
        )

        # Verify
        expected_settings = {
            "irrigation_pump_entity": "switch.pump",
            "drain_pump_entity": "switch.drain",
            "irrigation_duration": 600,
            "drain_duration": 300,
        }
        mock_irrigation_coordinator.async_set_settings.assert_awaited_once_with(
            expected_settings
        )

    @pytest.mark.asyncio
    async def test_set_irrigation_settings_growspace_not_found(
        self, mock_hass, mock_config_entry, mock_coordinator, mock_strain_library
    ):
        """Test error when growspace not found."""
        mock_hass.config_entries.async_entries.return_value = [mock_config_entry]
        mock_hass.data[DOMAIN] = {
            mock_config_entry.entry_id: {"irrigation_coordinators": {}}
        }

        call = MagicMock(spec=ServiceCall)
        call.data = {"growspace_id": "gs1", "irrigation_pump_entity": "switch.pump"}

        with pytest.raises(ServiceValidationError):
            await handle_set_irrigation_settings(
                mock_hass, mock_coordinator, mock_strain_library, call
            )


class TestHandleAddIrrigationTime:
    """Tests for handle_add_irrigation_time service handler."""

    @pytest.mark.asyncio
    async def test_add_irrigation_time_with_duration(
        self,
        mock_hass,
        mock_config_entry,
        mock_irrigation_coordinator,
        mock_coordinator,
        mock_strain_library,
    ):
        """Test adding irrigation time with explicit duration."""
        # Setup
        mock_hass.config_entries.async_entries.return_value = [mock_config_entry]
        mock_hass.data[DOMAIN] = {
            mock_config_entry.entry_id: {
                "irrigation_coordinators": {"gs1": mock_irrigation_coordinator}
            }
        }

        call = MagicMock(spec=ServiceCall)
        call.data = {"growspace_id": "gs1", "time": "08:00:00", "duration": 600}

        # Execute
        await handle_add_irrigation_time(
            mock_hass, mock_coordinator, mock_strain_library, call
        )

        # Verify
        mock_irrigation_coordinator.async_add_schedule_item.assert_awaited_once_with(
            "irrigation_times", "08:00:00", 600
        )

    @pytest.mark.asyncio
    async def test_add_irrigation_time_default_duration(
        self,
        mock_hass,
        mock_config_entry,
        mock_irrigation_coordinator,
        mock_coordinator,
        mock_strain_library,
    ):
        """Test adding irrigation time using default duration."""
        # Setup
        mock_hass.config_entries.async_entries.return_value = [mock_config_entry]
        mock_hass.data[DOMAIN] = {
            mock_config_entry.entry_id: {
                "irrigation_coordinators": {"gs1": mock_irrigation_coordinator}
            }
        }

        call = MagicMock(spec=ServiceCall)
        call.data = {"growspace_id": "gs1", "time": "08:00:00"}

        # Execute
        await handle_add_irrigation_time(
            mock_hass, mock_coordinator, mock_strain_library, call
        )

        # Verify
        mock_irrigation_coordinator.get_default_duration.assert_called_once_with(
            "irrigation"
        )
        mock_irrigation_coordinator.async_add_schedule_item.assert_awaited_once_with(
            "irrigation_times", "08:00:00", 300
        )


class TestHandleRemoveIrrigationTime:
    """Tests for handle_remove_irrigation_time service handler."""

    @pytest.mark.asyncio
    async def test_remove_irrigation_time(
        self,
        mock_hass,
        mock_config_entry,
        mock_irrigation_coordinator,
        mock_coordinator,
        mock_strain_library,
    ):
        """Test removing irrigation time."""
        # Setup
        mock_hass.config_entries.async_entries.return_value = [mock_config_entry]
        mock_hass.data[DOMAIN] = {
            mock_config_entry.entry_id: {
                "irrigation_coordinators": {"gs1": mock_irrigation_coordinator}
            }
        }

        call = MagicMock(spec=ServiceCall)
        call.data = {"growspace_id": "gs1", "time": "08:00:00"}

        # Execute
        await handle_remove_irrigation_time(
            mock_hass, mock_coordinator, mock_strain_library, call
        )

        # Verify
        mock_irrigation_coordinator.async_remove_schedule_item.assert_awaited_once_with(
            "irrigation_times", "08:00:00"
        )


class TestHandleAddDrainTime:
    """Tests for handle_add_drain_time service handler."""

    @pytest.mark.asyncio
    async def test_add_drain_time_with_duration(
        self,
        mock_hass,
        mock_config_entry,
        mock_irrigation_coordinator,
        mock_coordinator,
        mock_strain_library,
    ):
        """Test adding drain time with explicit duration."""
        # Setup
        mock_hass.config_entries.async_entries.return_value = [mock_config_entry]
        mock_hass.data[DOMAIN] = {
            mock_config_entry.entry_id: {
                "irrigation_coordinators": {"gs1": mock_irrigation_coordinator}
            }
        }

        call = MagicMock(spec=ServiceCall)
        call.data = {"growspace_id": "gs1", "time": "10:00:00", "duration": 180}

        # Execute
        await handle_add_drain_time(
            mock_hass, mock_coordinator, mock_strain_library, call
        )

        # Verify
        mock_irrigation_coordinator.async_add_schedule_item.assert_awaited_once_with(
            "drain_times", "10:00:00", 180
        )

    @pytest.mark.asyncio
    async def test_add_drain_time_default_duration(
        self,
        mock_hass,
        mock_config_entry,
        mock_irrigation_coordinator,
        mock_coordinator,
        mock_strain_library,
    ):
        """Test adding drain time using default duration."""
        # Setup
        mock_hass.config_entries.async_entries.return_value = [mock_config_entry]
        mock_hass.data[DOMAIN] = {
            mock_config_entry.entry_id: {
                "irrigation_coordinators": {"gs1": mock_irrigation_coordinator}
            }
        }

        call = MagicMock(spec=ServiceCall)
        call.data = {"growspace_id": "gs1", "time": "10:00:00"}

        # Execute
        await handle_add_drain_time(
            mock_hass, mock_coordinator, mock_strain_library, call
        )

        # Verify
        mock_irrigation_coordinator.get_default_duration.assert_called_once_with(
            "drain"
        )
        mock_irrigation_coordinator.async_add_schedule_item.assert_awaited_once_with(
            "drain_times", "10:00:00", 300
        )


class TestHandleRemoveDrainTime:
    """Tests for handle_remove_drain_time service handler."""

    @pytest.mark.asyncio
    async def test_remove_drain_time(
        self,
        mock_hass,
        mock_config_entry,
        mock_irrigation_coordinator,
        mock_coordinator,
        mock_strain_library,
    ):
        """Test removing drain time."""
        # Setup
        mock_hass.config_entries.async_entries.return_value = [mock_config_entry]
        mock_hass.data[DOMAIN] = {
            mock_config_entry.entry_id: {
                "irrigation_coordinators": {"gs1": mock_irrigation_coordinator}
            }
        }

        call = MagicMock(spec=ServiceCall)
        call.data = {"growspace_id": "gs1", "time": "10:00:00"}

        # Execute
        await handle_remove_drain_time(
            mock_hass, mock_coordinator, mock_strain_library, call
        )

        # Verify
        mock_irrigation_coordinator.async_remove_schedule_item.assert_awaited_once_with(
            "drain_times", "10:00:00"
        )
