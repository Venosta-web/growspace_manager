"""Tests for the irrigation service handlers."""

from unittest.mock import AsyncMock, MagicMock, patch

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

GROWSPACE_ID = "test_growspace"
ENTRY_ID = "test_entry_id"


@pytest.fixture
def mock_irrigation_coordinator() -> MagicMock:
    """Create a mock irrigation coordinator."""
    coord = MagicMock()
    coord.async_set_settings = AsyncMock()
    coord.async_add_schedule_item = AsyncMock()
    coord.async_remove_schedule_item = AsyncMock()
    coord.get_default_duration = MagicMock(
        side_effect=lambda t: 30 if t == "irrigation" else 60
    )
    return coord


@pytest.fixture
def mock_hass_with_irrigation(
    hass: HomeAssistant, mock_irrigation_coordinator
) -> HomeAssistant:
    """Create a mock hass instance with irrigation data."""
    mock_entry = MagicMock()
    mock_entry.entry_id = ENTRY_ID
    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = MagicMock(return_value=[mock_entry])

    hass.data[DOMAIN] = {
        ENTRY_ID: {
            "irrigation_coordinators": {
                GROWSPACE_ID: mock_irrigation_coordinator,
            }
        }
    }
    return hass


@pytest.fixture
def mock_coordinator() -> MagicMock:
    """Create a mock main growspace coordinator."""
    return MagicMock()


@pytest.fixture
def mock_strain_library() -> MagicMock:
    """Create a mock strain library."""
    return MagicMock()


# =============================================================================
# Tests for _get_irrigation_coordinator
# =============================================================================


class TestGetIrrigationCoordinator:
    """Tests for _get_irrigation_coordinator helper function."""

    @pytest.mark.asyncio
    async def test_no_config_entries_raises_error(self, hass: HomeAssistant):
        """Test that missing config entries raises ServiceValidationError."""
        hass.config_entries = MagicMock()
        hass.config_entries.async_entries = MagicMock(return_value=[])

        with pytest.raises(ServiceValidationError) as exc_info:
            await _get_irrigation_coordinator(hass, GROWSPACE_ID)

        assert "not yet set up" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_missing_domain_data_raises_error(self, hass: HomeAssistant):
        """Test that missing domain data raises ServiceValidationError."""
        mock_entry = MagicMock()
        mock_entry.entry_id = ENTRY_ID
        hass.config_entries = MagicMock()
        hass.config_entries.async_entries = MagicMock(return_value=[mock_entry])

        # Domain data is missing entirely
        hass.data = {}

        with pytest.raises(ServiceValidationError) as exc_info:
            await _get_irrigation_coordinator(hass, GROWSPACE_ID)

        assert "Setup may be incomplete" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_missing_irrigation_coordinators_key_raises_error(
        self, hass: HomeAssistant
    ):
        """Test that missing irrigation_coordinators key raises ServiceValidationError."""
        mock_entry = MagicMock()
        mock_entry.entry_id = ENTRY_ID
        hass.config_entries = MagicMock()
        hass.config_entries.async_entries = MagicMock(return_value=[mock_entry])

        # Domain data exists but irrigation_coordinators key is missing
        hass.data[DOMAIN] = {ENTRY_ID: {}}

        with pytest.raises(ServiceValidationError) as exc_info:
            await _get_irrigation_coordinator(hass, GROWSPACE_ID)

        assert "Setup may be incomplete" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_growspace_not_in_coordinators_raises_error(
        self, hass: HomeAssistant
    ):
        """Test that missing growspace in coordinators raises ServiceValidationError."""
        mock_entry = MagicMock()
        mock_entry.entry_id = ENTRY_ID
        hass.config_entries = MagicMock()
        hass.config_entries.async_entries = MagicMock(return_value=[mock_entry])

        # Irrigation coordinators exist but not for this growspace
        hass.data[DOMAIN] = {ENTRY_ID: {"irrigation_coordinators": {}}}

        with pytest.raises(ServiceValidationError) as exc_info:
            await _get_irrigation_coordinator(hass, GROWSPACE_ID)

        assert "not found or has no irrigation setup" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_returns_coordinator_on_success(
        self, mock_hass_with_irrigation, mock_irrigation_coordinator
    ):
        """Test that the coordinator is returned on success."""
        result = await _get_irrigation_coordinator(
            mock_hass_with_irrigation, GROWSPACE_ID
        )
        assert result is mock_irrigation_coordinator


# =============================================================================
# Tests for handle_set_irrigation_settings
# =============================================================================


class TestHandleSetIrrigationSettings:
    """Tests for handle_set_irrigation_settings service handler."""

    @pytest.mark.asyncio
    async def test_sets_irrigation_settings_successfully(
        self,
        mock_hass_with_irrigation,
        mock_coordinator,
        mock_strain_library,
        mock_irrigation_coordinator,
    ):
        """Test that irrigation settings are set correctly."""
        call = ServiceCall(
            mock_hass_with_irrigation,
            domain=DOMAIN,
            service="set_irrigation_settings",
            data={
                "growspace_id": GROWSPACE_ID,
                "irrigation_duration": 45,
                "drain_duration": 90,
            },
        )

        await handle_set_irrigation_settings(
            mock_hass_with_irrigation, mock_coordinator, mock_strain_library, call
        )

        # Verify settings were passed without growspace_id
        mock_irrigation_coordinator.async_set_settings.assert_awaited_once_with(
            {"irrigation_duration": 45, "drain_duration": 90}
        )


# =============================================================================
# Tests for handle_add_irrigation_time
# =============================================================================


class TestHandleAddIrrigationTime:
    """Tests for handle_add_irrigation_time service handler."""

    @pytest.mark.asyncio
    async def test_adds_irrigation_time_with_explicit_duration(
        self,
        mock_hass_with_irrigation,
        mock_coordinator,
        mock_strain_library,
        mock_irrigation_coordinator,
    ):
        """Test adding irrigation time with explicit duration."""
        call = ServiceCall(
            mock_hass_with_irrigation,
            domain=DOMAIN,
            service="add_irrigation_time",
            data={
                "growspace_id": GROWSPACE_ID,
                "time": "10:00:00",
                "duration": 45,
            },
        )

        await handle_add_irrigation_time(
            mock_hass_with_irrigation, mock_coordinator, mock_strain_library, call
        )

        mock_irrigation_coordinator.async_add_schedule_item.assert_awaited_once_with(
            "irrigation_times", "10:00:00", 45
        )

    @pytest.mark.asyncio
    async def test_adds_irrigation_time_with_default_duration(
        self,
        mock_hass_with_irrigation,
        mock_coordinator,
        mock_strain_library,
        mock_irrigation_coordinator,
    ):
        """Test adding irrigation time without duration uses default."""
        call = ServiceCall(
            mock_hass_with_irrigation,
            domain=DOMAIN,
            service="add_irrigation_time",
            data={
                "growspace_id": GROWSPACE_ID,
                "time": "14:00:00",
            },
        )

        await handle_add_irrigation_time(
            mock_hass_with_irrigation, mock_coordinator, mock_strain_library, call
        )

        # Should use default duration from get_default_duration("irrigation") = 30
        mock_irrigation_coordinator.get_default_duration.assert_called_once_with(
            "irrigation"
        )
        mock_irrigation_coordinator.async_add_schedule_item.assert_awaited_once_with(
            "irrigation_times", "14:00:00", 30
        )


# =============================================================================
# Tests for handle_remove_irrigation_time
# =============================================================================


class TestHandleRemoveIrrigationTime:
    """Tests for handle_remove_irrigation_time service handler."""

    @pytest.mark.asyncio
    async def test_removes_irrigation_time_successfully(
        self,
        mock_hass_with_irrigation,
        mock_coordinator,
        mock_strain_library,
        mock_irrigation_coordinator,
    ):
        """Test removing irrigation time."""
        call = ServiceCall(
            mock_hass_with_irrigation,
            domain=DOMAIN,
            service="remove_irrigation_time",
            data={
                "growspace_id": GROWSPACE_ID,
                "time": "10:00:00",
            },
        )

        await handle_remove_irrigation_time(
            mock_hass_with_irrigation, mock_coordinator, mock_strain_library, call
        )

        mock_irrigation_coordinator.async_remove_schedule_item.assert_awaited_once_with(
            "irrigation_times", "10:00:00"
        )


# =============================================================================
# Tests for handle_add_drain_time
# =============================================================================


class TestHandleAddDrainTime:
    """Tests for handle_add_drain_time service handler."""

    @pytest.mark.asyncio
    async def test_adds_drain_time_with_explicit_duration(
        self,
        mock_hass_with_irrigation,
        mock_coordinator,
        mock_strain_library,
        mock_irrigation_coordinator,
    ):
        """Test adding drain time with explicit duration."""
        call = ServiceCall(
            mock_hass_with_irrigation,
            domain=DOMAIN,
            service="add_drain_time",
            data={
                "growspace_id": GROWSPACE_ID,
                "time": "12:00:00",
                "duration": 120,
            },
        )

        await handle_add_drain_time(
            mock_hass_with_irrigation, mock_coordinator, mock_strain_library, call
        )

        mock_irrigation_coordinator.async_add_schedule_item.assert_awaited_once_with(
            "drain_times", "12:00:00", 120
        )

    @pytest.mark.asyncio
    async def test_adds_drain_time_with_default_duration(
        self,
        mock_hass_with_irrigation,
        mock_coordinator,
        mock_strain_library,
        mock_irrigation_coordinator,
    ):
        """Test adding drain time without duration uses default."""
        call = ServiceCall(
            mock_hass_with_irrigation,
            domain=DOMAIN,
            service="add_drain_time",
            data={
                "growspace_id": GROWSPACE_ID,
                "time": "18:00:00",
            },
        )

        await handle_add_drain_time(
            mock_hass_with_irrigation, mock_coordinator, mock_strain_library, call
        )

        # Should use default duration from get_default_duration("drain") = 60
        mock_irrigation_coordinator.get_default_duration.assert_called_once_with(
            "drain"
        )
        mock_irrigation_coordinator.async_add_schedule_item.assert_awaited_once_with(
            "drain_times", "18:00:00", 60
        )


# =============================================================================
# Tests for handle_remove_drain_time
# =============================================================================


class TestHandleRemoveDrainTime:
    """Tests for handle_remove_drain_time service handler."""

    @pytest.mark.asyncio
    async def test_removes_drain_time_successfully(
        self,
        mock_hass_with_irrigation,
        mock_coordinator,
        mock_strain_library,
        mock_irrigation_coordinator,
    ):
        """Test removing drain time."""
        call = ServiceCall(
            mock_hass_with_irrigation,
            domain=DOMAIN,
            service="remove_drain_time",
            data={
                "growspace_id": GROWSPACE_ID,
                "time": "12:00:00",
            },
        )

        await handle_remove_drain_time(
            mock_hass_with_irrigation, mock_coordinator, mock_strain_library, call
        )

        mock_irrigation_coordinator.async_remove_schedule_item.assert_awaited_once_with(
            "drain_times", "12:00:00"
        )
