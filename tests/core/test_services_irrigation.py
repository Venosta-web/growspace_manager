"""Tests for irrigation service handlers."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.services.irrigation import (
    _get_irrigation_coordinator,
    handle_add_drain_time,
    handle_add_irrigation_time,
    handle_remove_drain_time,
    handle_remove_irrigation_time,
    handle_run_irrigation_cycle,
    handle_set_irrigation_settings,
    handle_set_irrigation_strategy,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError


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
    # Kept for the get_default_duration lookup which still happens directly
    coordinator.get_default_duration = MagicMock(return_value=300)
    return coordinator


@pytest.fixture
def mock_coordinator():
    """Create a mock growspace coordinator."""
    coordinator = MagicMock()
    coordinator.growspaces = {}
    coordinator._subsystem_manager = MagicMock()
    coordinator._subsystem_manager.irrigation_coordinators = {}
    coordinator._subsystem_manager.async_setup_growspace_sub_coordinators = AsyncMock()

    # FIX: Add the services namespace and make the target methods awaitable
    coordinator.services = MagicMock()
    coordinator.services.growspaces.set_irrigation_settings = AsyncMock()
    coordinator.services.growspaces.set_irrigation_strategy = AsyncMock()
    coordinator.services.growspaces.add_irrigation_schedule_item = AsyncMock()
    coordinator.services.growspaces.remove_irrigation_schedule_item = AsyncMock()

    return coordinator


@pytest.fixture
def mock_strain_library():
    """Create a mock strain library."""
    return MagicMock()


class TestGetIrrigationCoordinator:
    """Tests for _get_irrigation_coordinator helper function."""

    @pytest.mark.asyncio
    async def test_missing_irrigation_coordinators(self, mock_coordinator):
        """Test error when irrigation_coordinators key is missing."""
        # Using a plain object to simulate missing attribute
        mock_coordinator = object()

        with pytest.raises(ServiceValidationError, match="not found"):
            await _get_irrigation_coordinator(mock_coordinator, "gs1")

    @pytest.mark.asyncio
    async def test_growspace_not_found(
        self, mock_coordinator, mock_irrigation_coordinator
    ):
        """Test error when specified growspace is not found."""
        mock_coordinator.services.growspaces.get_irrigation_coordinator.return_value = (
            None
        )
        mock_coordinator.growspaces = {}

        with pytest.raises(
            ServiceValidationError, match="'gs1' not found or has no irrigation setup"
        ):
            await _get_irrigation_coordinator(mock_coordinator, "gs1")

    @pytest.mark.asyncio
    async def test_success(self, mock_coordinator, mock_irrigation_coordinator):
        """Test successful retrieval of irrigation coordinator."""
        mock_coordinator.services.growspaces.get_irrigation_coordinator.return_value = (
            mock_irrigation_coordinator
        )

        result = await _get_irrigation_coordinator(mock_coordinator, "gs1")
        assert result == mock_irrigation_coordinator

    @pytest.mark.asyncio
    async def test_lazy_init_success(
        self, mock_coordinator, mock_irrigation_coordinator
    ):
        """Test successful lazy initialization of irrigation coordinator."""
        growspace_id = "lazy_gs"
        mock_growspace = MagicMock()
        mock_coordinator.growspaces = {growspace_id: mock_growspace}
        mock_coordinator.services.growspaces.get_irrigation_coordinator.side_effect = [
            None,
            mock_irrigation_coordinator,
        ]

        result = await _get_irrigation_coordinator(mock_coordinator, growspace_id)

        assert result == mock_irrigation_coordinator
        mock_coordinator._subsystem_manager.async_setup_growspace_sub_coordinators.assert_awaited_once_with(
            growspace_id, mock_growspace
        )


class TestHandleSetIrrigationSettings:
    """Tests for handle_set_irrigation_settings service handler."""

    @pytest.mark.asyncio
    async def test_set_irrigation_settings(
        self,
        mock_hass,
        mock_irrigation_coordinator,
        mock_coordinator,
    ):
        """Test setting irrigation settings."""
        # Setup
        mock_coordinator._subsystem_manager.irrigation_coordinators = {
            "gs1": mock_irrigation_coordinator
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
        await handle_set_irrigation_settings(mock_hass, mock_coordinator, call)

        # Verify against the main coordinator services facade
        expected_settings = {
            "irrigation_pump_entity": "switch.pump",
            "drain_pump_entity": "switch.drain",
            "irrigation_duration": 600,
            "drain_duration": 300,
        }
        mock_coordinator.services.growspaces.set_irrigation_settings.assert_awaited_once_with(
            "gs1", expected_settings
        )

    @pytest.mark.asyncio
    async def test_set_irrigation_settings_accepts_input_boolean_entities(
        self,
        mock_hass: MagicMock,
        mock_irrigation_coordinator: MagicMock,
        mock_coordinator: MagicMock,
    ) -> None:
        """input_boolean entities are accepted for pump fields (no domain restriction in schema)."""
        mock_coordinator._subsystem_manager.irrigation_coordinators = {
            "gs1": mock_irrigation_coordinator
        }

        call = MagicMock(spec=ServiceCall)
        call.data = {
            "growspace_id": "gs1",
            "irrigation_pump_entity": "input_boolean.sim_e2e_veg_irrigation_pump",
            "drain_pump_entity": "input_boolean.sim_e2e_veg_drain_pump",
        }

        await handle_set_irrigation_settings(mock_hass, mock_coordinator, call)

        mock_coordinator.services.growspaces.set_irrigation_settings.assert_awaited_once_with(
            "gs1",
            {
                "irrigation_pump_entity": "input_boolean.sim_e2e_veg_irrigation_pump",
                "drain_pump_entity": "input_boolean.sim_e2e_veg_drain_pump",
            },
        )

    @pytest.mark.asyncio
    async def test_set_irrigation_settings_growspace_not_found(
        self, mock_hass, mock_coordinator
    ):
        """Test error when growspace not found."""
        mock_coordinator.services.growspaces.get_irrigation_coordinator.return_value = (
            None
        )
        mock_coordinator.growspaces = {}

        call = MagicMock(spec=ServiceCall)
        call.data = {"growspace_id": "gs1", "irrigation_pump_entity": "switch.pump"}

        # Should raise ServiceValidationError because GS not found even in fallback
        with pytest.raises(ServiceValidationError, match="not found"):
            await handle_set_irrigation_settings(mock_hass, mock_coordinator, call)


class TestHandleAddIrrigationTime:
    """Tests for handle_add_irrigation_time service handler."""

    @pytest.mark.asyncio
    async def test_add_irrigation_time_with_duration(
        self,
        mock_hass,
        mock_irrigation_coordinator,
        mock_coordinator,
    ):
        """Test adding irrigation time with explicit duration."""
        # Setup
        mock_coordinator._subsystem_manager.irrigation_coordinators = {
            "gs1": mock_irrigation_coordinator
        }

        call = MagicMock(spec=ServiceCall)
        call.data = {"growspace_id": "gs1", "time": "08:00:00", "duration": 600}

        # Execute
        await handle_add_irrigation_time(mock_hass, mock_coordinator, call)

        # Verify against the main coordinator services facade
        mock_coordinator.services.growspaces.add_irrigation_schedule_item.assert_awaited_once_with(
            "gs1", "irrigation_times", "08:00:00", 600
        )

    @pytest.mark.asyncio
    async def test_add_irrigation_time_default_duration(
        self,
        mock_hass,
        mock_irrigation_coordinator,
        mock_coordinator,
    ):
        """Test adding irrigation time using default duration."""
        # Setup
        mock_coordinator.services.growspaces.get_irrigation_coordinator.return_value = (
            mock_irrigation_coordinator
        )

        call = MagicMock(spec=ServiceCall)
        call.data = {"growspace_id": "gs1", "time": "08:00:00"}

        # Execute
        await handle_add_irrigation_time(mock_hass, mock_coordinator, call)

        # Verify
        mock_irrigation_coordinator.get_default_duration.assert_called_once_with(
            "irrigation"
        )
        mock_coordinator.services.growspaces.add_irrigation_schedule_item.assert_awaited_once_with(
            "gs1", "irrigation_times", "08:00:00", 300
        )


class TestHandleRemoveIrrigationTime:
    """Tests for handle_remove_irrigation_time service handler."""

    @pytest.mark.asyncio
    async def test_remove_irrigation_time(
        self,
        mock_hass,
        mock_irrigation_coordinator,
        mock_coordinator,
    ):
        """Test removing irrigation time."""
        # Setup
        mock_coordinator._subsystem_manager.irrigation_coordinators = {
            "gs1": mock_irrigation_coordinator
        }

        call = MagicMock(spec=ServiceCall)
        call.data = {"growspace_id": "gs1", "time": "08:00:00"}

        # Execute
        await handle_remove_irrigation_time(mock_hass, mock_coordinator, call)

        # Verify against the main coordinator services facade
        mock_coordinator.services.growspaces.remove_irrigation_schedule_item.assert_awaited_once_with(
            "gs1", "irrigation_times", "08:00:00"
        )


class TestHandleAddDrainTime:
    """Tests for handle_add_drain_time service handler."""

    @pytest.mark.asyncio
    async def test_add_drain_time_with_duration(
        self,
        mock_hass,
        mock_irrigation_coordinator,
        mock_coordinator,
    ):
        """Test adding drain time with explicit duration."""
        # Setup
        mock_coordinator._subsystem_manager.irrigation_coordinators = {
            "gs1": mock_irrigation_coordinator
        }

        call = MagicMock(spec=ServiceCall)
        call.data = {"growspace_id": "gs1", "time": "10:00:00", "duration": 180}

        # Execute
        await handle_add_drain_time(mock_hass, mock_coordinator, call)

        # Verify against the main coordinator services facade
        mock_coordinator.services.growspaces.add_irrigation_schedule_item.assert_awaited_once_with(
            "gs1", "drain_times", "10:00:00", 180
        )

    @pytest.mark.asyncio
    async def test_add_drain_time_default_duration(
        self,
        mock_hass,
        mock_irrigation_coordinator,
        mock_coordinator,
    ):
        """Test adding drain time using default duration."""
        # Setup
        mock_coordinator.services.growspaces.get_irrigation_coordinator.return_value = (
            mock_irrigation_coordinator
        )

        call = MagicMock(spec=ServiceCall)
        call.data = {"growspace_id": "gs1", "time": "10:00:00"}

        # Execute
        await handle_add_drain_time(mock_hass, mock_coordinator, call)

        # Verify
        mock_irrigation_coordinator.get_default_duration.assert_called_once_with(
            "drain"
        )
        mock_coordinator.services.growspaces.add_irrigation_schedule_item.assert_awaited_once_with(
            "gs1", "drain_times", "10:00:00", 300
        )


class TestHandleRemoveDrainTime:
    """Tests for handle_remove_drain_time service handler."""

    @pytest.mark.asyncio
    async def test_remove_drain_time(
        self,
        mock_hass,
        mock_irrigation_coordinator,
        mock_coordinator,
    ):
        """Test removing drain time."""
        # Setup
        mock_coordinator._subsystem_manager.irrigation_coordinators = {
            "gs1": mock_irrigation_coordinator
        }

        call = MagicMock(spec=ServiceCall)
        call.data = {"growspace_id": "gs1", "time": "10:00:00"}

        # Execute
        await handle_remove_drain_time(mock_hass, mock_coordinator, call)

        # Verify against the main coordinator services facade
        mock_coordinator.services.growspaces.remove_irrigation_schedule_item.assert_awaited_once_with(
            "gs1", "drain_times", "10:00:00"
        )


class TestHandleSetIrrigationStrategy:
    """Tests for handle_set_irrigation_strategy service handler."""

    @pytest.mark.asyncio
    async def test_set_irrigation_strategy(
        self,
        mock_hass: MagicMock,
        mock_irrigation_coordinator: MagicMock,
        mock_coordinator: MagicMock,
    ) -> None:
        """Test setting irrigation strategy."""
        # Setup
        mock_coordinator._subsystem_manager.irrigation_coordinators = {
            "gs1": mock_irrigation_coordinator
        }

        call = MagicMock(spec=ServiceCall)
        call.data = {
            "growspace_id": "gs1",
            "enabled": True,
            "lights_on_time": "06:00:00",
            "p0_duration_minutes": 60,
            "p2_stop_before_lights_off_minutes": 120,
            "target_vwc_percent": 55.0,
            "maintenance_dryback_percent": 2.0,
            "shot_duration_seconds": 10,
            "shot_interval_minutes": 15,
        }

        # Execute
        await handle_set_irrigation_strategy(mock_hass, mock_coordinator, call)

        # Verify against the main coordinator services facade
        expected_strategy = {
            "enabled": True,
            "lights_on_time": "06:00:00",
            "p0_duration_minutes": 60,
            "p2_stop_before_lights_off_minutes": 120,
            "target_vwc_percent": 55.0,
            "maintenance_dryback_percent": 2.0,
            "shot_duration_seconds": 10,
            "shot_interval_minutes": 15,
        }
        mock_coordinator.services.growspaces.set_irrigation_strategy.assert_awaited_once_with(
            "gs1", expected_strategy
        )

    @pytest.mark.asyncio
    async def test_set_irrigation_strategy_growspace_not_found(
        self, mock_hass: MagicMock, mock_coordinator: MagicMock
    ) -> None:
        """Test error when growspace not found."""
        mock_coordinator.services.growspaces.get_irrigation_coordinator.return_value = (
            None
        )
        mock_coordinator.growspaces = {}

        call = MagicMock(spec=ServiceCall)
        call.data = {"growspace_id": "gs1", "enabled": True}

        # Should raise ServiceValidationError because GS not found even in fallback
        with pytest.raises(ServiceValidationError, match="not found"):
            await handle_set_irrigation_strategy(mock_hass, mock_coordinator, call)


class TestHandleRunIrrigationCycle:
    """Tests for handle_run_irrigation_cycle service handler (US-4)."""

    @pytest.mark.asyncio
    async def test_run_irrigation_cycle_with_explicit_duration(
        self,
        mock_hass: MagicMock,
        mock_irrigation_coordinator: MagicMock,
        mock_coordinator: MagicMock,
    ) -> None:
        """Calling the service triggers async_manual_run with the supplied duration."""
        mock_irrigation_coordinator.async_manual_run = AsyncMock()
        mock_coordinator.services.growspaces.get_irrigation_coordinator.return_value = (
            mock_irrigation_coordinator
        )

        call = MagicMock(spec=ServiceCall)
        call.data = {"growspace_id": "gs1", "duration": 45}

        await handle_run_irrigation_cycle(mock_hass, mock_coordinator, call)

        mock_irrigation_coordinator.async_manual_run.assert_awaited_once_with(
            duration=45
        )

    @pytest.mark.asyncio
    async def test_run_irrigation_cycle_without_duration_passes_none(
        self,
        mock_hass: MagicMock,
        mock_irrigation_coordinator: MagicMock,
        mock_coordinator: MagicMock,
    ) -> None:
        """When duration is omitted the coordinator receives None and uses its default."""
        mock_irrigation_coordinator.async_manual_run = AsyncMock()
        mock_coordinator.services.growspaces.get_irrigation_coordinator.return_value = (
            mock_irrigation_coordinator
        )

        call = MagicMock(spec=ServiceCall)
        call.data = {"growspace_id": "gs1"}

        await handle_run_irrigation_cycle(mock_hass, mock_coordinator, call)

        mock_irrigation_coordinator.async_manual_run.assert_awaited_once_with(
            duration=None
        )

    @pytest.mark.asyncio
    async def test_run_irrigation_cycle_unknown_growspace_raises(
        self,
        mock_hass: MagicMock,
        mock_coordinator: MagicMock,
    ) -> None:
        """Service raises ServiceValidationError when the growspace has no coordinator."""
        mock_coordinator.services.growspaces.get_irrigation_coordinator.return_value = (
            None
        )
        mock_coordinator.growspaces = {}

        call = MagicMock(spec=ServiceCall)
        call.data = {"growspace_id": "nonexistent"}

        with pytest.raises(ServiceValidationError, match="not found"):
            await handle_run_irrigation_cycle(mock_hass, mock_coordinator, call)


class TestVolumeModeStrategyValidation:
    """Volume Mode gating + substrate-profile folding (ADR-0011)."""

    def _make_growspace(self, liters_per_pot: float, flow_rate: float):
        from custom_components.growspace_manager.models import (
            Growspace,
            IrrigationConfig,
            IrrigationStrategy,
            SubstrateProfile,
        )

        gs = Growspace(
            id="gs1",
            name="GS",
            irrigation_config=IrrigationConfig(pump_flow_rate_ml_per_sec=flow_rate),
        )
        gs.irrigation_strategy = IrrigationStrategy(
            substrate_profile=SubstrateProfile(liters_per_pot=liters_per_pot)
        )
        return gs

    @pytest.mark.asyncio
    async def test_volume_mode_rejected_without_profile(
        self, mock_hass: MagicMock, mock_coordinator: MagicMock
    ) -> None:
        """Selecting Volume Mode without a substrate profile is rejected."""
        mock_coordinator.growspaces = {"gs1": self._make_growspace(0.0, 20.0)}

        call = MagicMock(spec=ServiceCall)
        call.data = {"growspace_id": "gs1", "shot_sizing_mode": "volume"}

        with pytest.raises(ServiceValidationError, match="Volume Mode requires"):
            await handle_set_irrigation_strategy(mock_hass, mock_coordinator, call)
        mock_coordinator.services.growspaces.set_irrigation_strategy.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_volume_mode_rejected_without_flow_rate(
        self, mock_hass: MagicMock, mock_coordinator: MagicMock
    ) -> None:
        """Selecting Volume Mode without a pump flow rate is rejected."""
        mock_coordinator.growspaces = {"gs1": self._make_growspace(6.0, 0.0)}

        call = MagicMock(spec=ServiceCall)
        call.data = {"growspace_id": "gs1", "shot_sizing_mode": "volume"}

        with pytest.raises(ServiceValidationError, match="Volume Mode requires"):
            await handle_set_irrigation_strategy(mock_hass, mock_coordinator, call)

    @pytest.mark.asyncio
    async def test_volume_mode_accepted_when_profile_set_in_same_call(
        self, mock_hass: MagicMock, mock_coordinator: MagicMock
    ) -> None:
        """A single call may set the profile and switch to Volume Mode together."""
        mock_coordinator.growspaces = {"gs1": self._make_growspace(0.0, 20.0)}

        call = MagicMock(spec=ServiceCall)
        call.data = {
            "growspace_id": "gs1",
            "shot_sizing_mode": "volume",
            "substrate_media_type": "rockwool",
            "substrate_liters_per_pot": 6.0,
        }

        await handle_set_irrigation_strategy(mock_hass, mock_coordinator, call)

        _gid, strategy = (
            mock_coordinator.services.growspaces.set_irrigation_strategy.await_args[0]
        )
        # Flat substrate keys are folded into a nested profile dict.
        assert "substrate_media_type" not in strategy
        assert strategy["substrate_profile"] == {
            "media_type": "rockwool",
            "liters_per_pot": 6.0,
        }
        assert strategy["shot_sizing_mode"] == "volume"

    @pytest.mark.asyncio
    async def test_seconds_mode_skips_volume_validation(
        self, mock_hass: MagicMock, mock_coordinator: MagicMock
    ) -> None:
        """Seconds Mode is accepted with no profile or flow rate."""
        mock_coordinator.growspaces = {"gs1": self._make_growspace(0.0, 0.0)}

        call = MagicMock(spec=ServiceCall)
        call.data = {"growspace_id": "gs1", "shot_sizing_mode": "seconds"}

        await handle_set_irrigation_strategy(mock_hass, mock_coordinator, call)

        mock_coordinator.services.growspaces.set_irrigation_strategy.assert_awaited_once()
