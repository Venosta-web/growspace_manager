"""Tests for the Growspace SubsystemManager."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.managers.subsystem import SubsystemManager
from custom_components.growspace_manager.models import Growspace, IrrigationStrategy


@pytest.fixture
def mock_hass() -> MagicMock:
    """ReturnType mock Home Assistant instance."""
    return MagicMock()


@pytest.fixture
def mock_coordinator() -> MagicMock:
    """Return mock GrowspaceCoordinator."""
    return MagicMock()


@pytest.fixture
def mock_entry() -> MagicMock:
    """Return mock ConfigEntry."""
    return MagicMock()


@pytest.fixture
def subsystem_manager(
    mock_hass: MagicMock, mock_coordinator: MagicMock, mock_entry: MagicMock
) -> SubsystemManager:
    """Return SubsystemManager instance."""
    return SubsystemManager(mock_hass, mock_coordinator, mock_entry)


@pytest.mark.asyncio
async def test_initialization(subsystem_manager: SubsystemManager) -> None:
    """Test initialization."""
    assert subsystem_manager.irrigation_coordinators == {}
    assert subsystem_manager.dehumidifier_coordinators == {}


@pytest.mark.asyncio
async def test_async_initialize_sub_coordinators(
    subsystem_manager: SubsystemManager,
) -> None:
    """Test initializing sub-coordinators for growspaces."""
    # Define growspaces
    gs1 = Growspace(
        id="gs1",
        name="Growspace 1",
        irrigation_strategy=IrrigationStrategy(enabled=False),
    )
    gs2 = Growspace(
        id="gs2",
        name="Growspace 2",
        irrigation_strategy=IrrigationStrategy(enabled=True),
    )
    growspaces = {"gs1": gs1, "gs2": gs2}

    # Mock the coordinator classes
    with (
        patch(
            "custom_components.growspace_manager.managers.subsystem.IrrigationCoordinator",
            autospec=True,
        ) as mock_irrigation,
        patch(
            "custom_components.growspace_manager.managers.subsystem.VWCIrrigationCoordinator",
            autospec=True,
        ) as mock_vwc,
        patch(
            "custom_components.growspace_manager.managers.subsystem.DehumidifierCoordinator",
            autospec=True,
        ) as mock_dehum,
        patch(
            "custom_components.growspace_manager.managers.subsystem.HumidifierCoordinator",
            autospec=True,
        ) as mock_hum,
        patch(
            "custom_components.growspace_manager.managers.subsystem.LightCycleTracker",
            autospec=True,
        ) as mock_tracker,
    ):
        # Setup async_setup mocks
        mock_irrigation.return_value.async_setup = AsyncMock()
        mock_vwc.return_value.async_setup = AsyncMock()
        mock_dehum.return_value.async_setup = AsyncMock()
        mock_hum.return_value.async_setup = AsyncMock()
        mock_tracker.return_value.async_setup = AsyncMock()

        await subsystem_manager.async_initialize_sub_coordinators(growspaces)

        # Verify IrrigationCoordinator creation (gs1)
        mock_irrigation.assert_called_with(
            subsystem_manager.hass,
            subsystem_manager.entry,
            "gs1",
            subsystem_manager.coordinator,
        )
        assert "gs1" in subsystem_manager.irrigation_coordinators

        # Verify VWCIrrigationCoordinator creation (gs2)
        mock_vwc.assert_called_with(
            subsystem_manager.hass,
            subsystem_manager.entry,
            "gs2",
            subsystem_manager.coordinator,
        )
        assert "gs2" in subsystem_manager.irrigation_coordinators

        # Verify DehumidifierCoordinator creation
        assert mock_dehum.call_count == 2
        assert "gs1" in subsystem_manager.dehumidifier_coordinators
        assert "gs2" in subsystem_manager.dehumidifier_coordinators

        # Verify HumidifierCoordinator creation
        assert mock_hum.call_count == 2
        assert "gs1" in subsystem_manager.humidifier_coordinators
        assert "gs2" in subsystem_manager.humidifier_coordinators


@pytest.mark.asyncio
async def test_async_initialize_sub_coordinators_failure(
    subsystem_manager: SubsystemManager,
) -> None:
    """Test failure resilience during initialization."""
    gs1 = Growspace(id="gs1", name="Growspace 1")
    growspaces = {"gs1": gs1}

    with patch(
        "custom_components.growspace_manager.managers.subsystem.IrrigationCoordinator",
        autospec=True,
    ) as mock_irrigation:
        # Simulate setup failure
        mock_irrigation.return_value.async_setup = AsyncMock(
            side_effect=ValueError("Setup failed")
        )

        # Should catch exception and log warning (no crash)
        await subsystem_manager.async_initialize_sub_coordinators(growspaces)

        # Should not have added to dict if failed (logic check: logic adds to dict AFTER await async_setup)
        assert "gs1" not in subsystem_manager.irrigation_coordinators


@pytest.mark.asyncio
async def test_async_cancel_all(subsystem_manager: SubsystemManager) -> None:
    """Test cancellation of all coordinators."""
    # Setup dummy coordinators
    mock_irr = MagicMock()
    mock_irr.async_cancel_listeners = MagicMock()
    subsystem_manager.irrigation_coordinators["gs1"] = mock_irr

    mock_dehum = MagicMock()
    mock_dehum.unload = MagicMock()
    subsystem_manager.dehumidifier_coordinators["gs1"] = mock_dehum

    mock_hum = MagicMock()
    mock_hum.unload = MagicMock()
    subsystem_manager.humidifier_coordinators["gs1"] = mock_hum

    mock_tracker = MagicMock()
    mock_tracker.unload = MagicMock()
    subsystem_manager.light_cycle_trackers["gs1"] = mock_tracker

    subsystem_manager.async_cancel_all()

    mock_irr.async_cancel_listeners.assert_called_once()
    mock_dehum.unload.assert_called_once()
    mock_hum.unload.assert_called_once()
    mock_tracker.unload.assert_called_once()


@pytest.mark.asyncio
async def test_async_cancel_all_exceptions(
    subsystem_manager: SubsystemManager,
) -> None:
    """Test that exceptions during cancellation of individual coordinators are handled gracefully."""
    mock_irr = MagicMock()
    mock_irr.async_cancel_listeners = MagicMock(
        side_effect=RuntimeError("Irrigation cancel error")
    )
    subsystem_manager.irrigation_coordinators["gs1"] = mock_irr

    mock_dehum = MagicMock()
    mock_dehum.unload = MagicMock(side_effect=RuntimeError("Dehumidifier unload error"))
    subsystem_manager.dehumidifier_coordinators["gs1"] = mock_dehum

    mock_hum = MagicMock()
    mock_hum.unload = MagicMock(side_effect=RuntimeError("Humidifier unload error"))
    subsystem_manager.humidifier_coordinators["gs1"] = mock_hum

    mock_tracker = MagicMock()
    mock_tracker.unload = MagicMock(
        side_effect=RuntimeError("Light tracker unload error")
    )
    subsystem_manager.light_cycle_trackers["gs1"] = mock_tracker

    # We mock _LOGGER to verify error messages are logged
    with patch(
        "custom_components.growspace_manager.managers.subsystem._LOGGER"
    ) as mock_logger:
        subsystem_manager.async_cancel_all()

        # Verify that all unloads were called despite preceding exceptions
        mock_irr.async_cancel_listeners.assert_called_once()
        mock_dehum.unload.assert_called_once()
        mock_hum.unload.assert_called_once()
        mock_tracker.unload.assert_called_once()

        # Verify logger.error was called for each exception
        assert mock_logger.error.call_count == 4
        mock_logger.error.assert_any_call(
            "Error cancelling irrigation listeners: %s",
            mock_irr.async_cancel_listeners.side_effect,
        )
        mock_logger.error.assert_any_call(
            "Error unloading dehumidifier coordinator: %s",
            mock_dehum.unload.side_effect,
        )
        mock_logger.error.assert_any_call(
            "Error unloading humidifier coordinator: %s",
            mock_hum.unload.side_effect,
        )
        mock_logger.error.assert_any_call(
            "Error unloading light cycle tracker: %s",
            mock_tracker.unload.side_effect,
        )
