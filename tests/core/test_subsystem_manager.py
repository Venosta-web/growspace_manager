"""Tests for the Growspace SubsystemManager."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.circulation_fan_coordinator import (
    CirculationFanCoordinator,
)
from custom_components.growspace_manager.dehumidifier_coordinator import (
    DehumidifierCoordinator,
)
from custom_components.growspace_manager.exhaust_fan_coordinator import (
    ExhaustFanCoordinator,
)
from custom_components.growspace_manager.grow_light_coordinator import (
    GrowLightCoordinator,
)
from custom_components.growspace_manager.humidifier_coordinator import (
    HumidifierCoordinator,
)
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
    assert subsystem_manager.environment_controllers == {}


@pytest.mark.asyncio
async def test_async_initialize_sub_coordinators(
    subsystem_manager: SubsystemManager,
) -> None:
    """Test initializing sub-coordinators for growspaces."""
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
        patch(
            "custom_components.growspace_manager.managers.subsystem.GrowLightCoordinator",
            autospec=True,
        ) as mock_growlight,
    ):
        mock_irrigation.return_value.async_setup = AsyncMock()
        mock_vwc.return_value.async_setup = AsyncMock()
        mock_dehum.return_value.async_setup = AsyncMock()
        mock_hum.return_value.async_setup = AsyncMock()
        mock_tracker.return_value.async_setup = AsyncMock()
        mock_growlight.return_value.async_setup = AsyncMock()

        await subsystem_manager.async_initialize_sub_coordinators(growspaces)

        mock_irrigation.assert_called_with(
            subsystem_manager.hass,
            subsystem_manager.entry,
            "gs1",
            subsystem_manager.coordinator,
        )
        assert "gs1" in subsystem_manager.irrigation_coordinators

        mock_vwc.assert_called_with(
            subsystem_manager.hass,
            subsystem_manager.entry,
            "gs2",
            subsystem_manager.coordinator,
        )
        assert "gs2" in subsystem_manager.irrigation_coordinators

        assert mock_dehum.call_count == 2
        assert "gs1" in subsystem_manager.environment_controllers
        assert "gs2" in subsystem_manager.environment_controllers

        assert mock_hum.call_count == 2
        assert len(subsystem_manager.environment_controllers["gs1"]) >= 2
        assert len(subsystem_manager.environment_controllers["gs2"]) >= 2


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
        mock_irrigation.return_value.async_setup = AsyncMock(
            side_effect=ValueError("Setup failed")
        )

        await subsystem_manager.async_initialize_sub_coordinators(growspaces)

        assert "gs1" not in subsystem_manager.irrigation_coordinators


@pytest.mark.asyncio
async def test_async_cancel_all(subsystem_manager: SubsystemManager) -> None:
    """Test cancellation of all coordinators."""
    mock_irr = MagicMock()
    mock_irr.async_cancel_listeners = MagicMock()
    subsystem_manager.irrigation_coordinators["gs1"] = mock_irr

    mock_dehum = MagicMock()
    mock_dehum.unload = MagicMock()
    mock_hum = MagicMock()
    mock_hum.unload = MagicMock()
    subsystem_manager.environment_controllers["gs1"] = [mock_dehum, mock_hum]

    mock_tracker = MagicMock()
    mock_tracker.unload = MagicMock()
    subsystem_manager.light_cycle_trackers["gs1"] = mock_tracker

    subsystem_manager.async_cancel_all()

    mock_irr.async_cancel_listeners.assert_called_once()
    mock_dehum.unload.assert_called_once()
    mock_hum.unload.assert_called_once()
    mock_tracker.unload.assert_called_once()


@pytest.mark.asyncio
async def test_circulation_fan_coordinators_setup_and_cancel(
    subsystem_manager: SubsystemManager,
) -> None:
    """CirculationFanCoordinator is created per growspace and unloaded on cancel."""
    gs1 = Growspace(id="gs1", name="Growspace 1")
    growspaces = {"gs1": gs1}

    with (
        patch(
            "custom_components.growspace_manager.managers.subsystem.IrrigationCoordinator",
            autospec=True,
        ) as mock_irrigation,
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
        patch(
            "custom_components.growspace_manager.managers.subsystem.CirculationFanCoordinator",
            autospec=True,
        ) as mock_fan,
        patch(
            "custom_components.growspace_manager.managers.subsystem.GrowLightCoordinator",
            autospec=True,
        ) as mock_growlight,
    ):
        mock_irrigation.return_value.async_setup = AsyncMock()
        mock_dehum.return_value.async_setup = AsyncMock()
        mock_hum.return_value.async_setup = AsyncMock()
        mock_tracker.return_value.async_setup = AsyncMock()
        mock_fan.return_value.async_setup = AsyncMock()
        mock_growlight.return_value.async_setup = AsyncMock()

        await subsystem_manager.async_initialize_sub_coordinators(growspaces)

        mock_fan.assert_called_once_with(
            subsystem_manager.hass,
            subsystem_manager.entry,
            "gs1",
            subsystem_manager.coordinator,
        )
        assert "gs1" in subsystem_manager.environment_controllers

        mock_fan_instance = mock_fan.return_value
        subsystem_manager.async_cancel_all()
        mock_fan_instance.unload.assert_called_once()


@pytest.mark.parametrize(
    ("getter_name", "controller_class"),
    [
        ("get_dehumidifier_controller", DehumidifierCoordinator),
        ("get_humidifier_controller", HumidifierCoordinator),
        ("get_circulation_fan_controller", CirculationFanCoordinator),
        ("get_exhaust_fan_controller", ExhaustFanCoordinator),
    ],
)
def test_get_controller_returns_matching_instance(
    subsystem_manager: SubsystemManager,
    getter_name: str,
    controller_class: type,
) -> None:
    """Each getter returns the controller of its type from a mixed list."""
    matching = MagicMock(spec=controller_class)
    other = MagicMock(spec=object)
    subsystem_manager.environment_controllers["gs1"] = [other, matching]

    getter = getattr(subsystem_manager, getter_name)
    assert getter("gs1") is matching


@pytest.mark.parametrize(
    "getter_name",
    [
        "get_dehumidifier_controller",
        "get_humidifier_controller",
        "get_circulation_fan_controller",
        "get_exhaust_fan_controller",
    ],
)
def test_get_controller_returns_none_when_absent(
    subsystem_manager: SubsystemManager,
    getter_name: str,
) -> None:
    """Each getter returns None when no matching controller or growspace exists."""
    subsystem_manager.environment_controllers["gs1"] = [MagicMock(spec=object)]

    getter = getattr(subsystem_manager, getter_name)
    assert getter("gs1") is None
    assert getter("unknown_growspace") is None


@pytest.mark.asyncio
async def test_async_cancel_all_exceptions(
    subsystem_manager: SubsystemManager,
) -> None:
    """Test that exceptions during cancellation are handled gracefully."""
    mock_irr = MagicMock()
    mock_irr.async_cancel_listeners = MagicMock(
        side_effect=RuntimeError("Irrigation cancel error")
    )
    subsystem_manager.irrigation_coordinators["gs1"] = mock_irr

    mock_dehum = MagicMock()
    mock_dehum.unload = MagicMock(side_effect=RuntimeError("Dehumidifier unload error"))
    mock_hum = MagicMock()
    mock_hum.unload = MagicMock(side_effect=RuntimeError("Humidifier unload error"))
    subsystem_manager.environment_controllers["gs1"] = [mock_dehum, mock_hum]

    mock_tracker = MagicMock()
    mock_tracker.unload = MagicMock(
        side_effect=RuntimeError("Light tracker unload error")
    )
    subsystem_manager.light_cycle_trackers["gs1"] = mock_tracker

    with patch(
        "custom_components.growspace_manager.managers.subsystem._LOGGER"
    ) as mock_logger:
        subsystem_manager.async_cancel_all()

        mock_irr.async_cancel_listeners.assert_called_once()
        mock_dehum.unload.assert_called_once()
        mock_hum.unload.assert_called_once()
        mock_tracker.unload.assert_called_once()

        assert mock_logger.error.call_count == 4
        mock_logger.error.assert_any_call(
            "Error cancelling irrigation listeners: %s",
            mock_irr.async_cancel_listeners.side_effect,
        )
        mock_logger.error.assert_any_call(
            "Error unloading environment controller: %s",
            mock_dehum.unload.side_effect,
        )
        mock_logger.error.assert_any_call(
            "Error unloading environment controller: %s",
            mock_hum.unload.side_effect,
        )
        mock_logger.error.assert_any_call(
            "Error unloading light cycle tracker: %s",
            mock_tracker.unload.side_effect,
        )


@pytest.mark.asyncio
async def test_tearing_down_one_growspace_survives_every_failing_unload(
    subsystem_manager: SubsystemManager,
) -> None:
    """One sub-coordinator that throws must not strand the others.

    A teardown runs because the growspace is gone. A coordinator left behind
    keeps driving actuators from configuration that no longer exists, so the
    only wrong outcome here is stopping early: each failure is logged and the
    next one is torn down anyway, and every registry is emptied regardless.
    """
    mock_irr = MagicMock()
    mock_irr.async_cancel_listeners = MagicMock(
        side_effect=RuntimeError("Irrigation cancel error")
    )
    subsystem_manager.irrigation_coordinators["gs1"] = mock_irr

    mock_tracker = MagicMock()
    mock_tracker.unload = MagicMock(side_effect=RuntimeError("Tracker unload error"))
    subsystem_manager.light_cycle_trackers["gs1"] = mock_tracker

    mock_controller = MagicMock()
    mock_controller.unload = MagicMock(
        side_effect=RuntimeError("Controller unload error")
    )
    subsystem_manager.environment_controllers["gs1"] = [mock_controller]

    with patch(
        "custom_components.growspace_manager.managers.subsystem._LOGGER"
    ) as mock_logger:
        subsystem_manager.teardown_growspace_sub_coordinators("gs1")

    mock_irr.async_cancel_listeners.assert_called_once()
    mock_tracker.unload.assert_called_once()
    mock_controller.unload.assert_called_once()
    assert mock_logger.error.call_count == 3
    assert subsystem_manager.irrigation_coordinators == {}
    assert subsystem_manager.light_cycle_trackers == {}
    assert subsystem_manager.environment_controllers == {}


@pytest.mark.asyncio
async def test_tearing_down_a_growspace_with_nothing_registered(
    subsystem_manager: SubsystemManager,
) -> None:
    """A growspace that never had sub-coordinators tears down quietly.

    Reached whenever a growspace is removed before its coordinators were built
    — a failed setup, or one with every subsystem disabled.
    """
    subsystem_manager.teardown_growspace_sub_coordinators("never-existed")

    assert subsystem_manager.environment_controllers == {}


@pytest.mark.asyncio
async def test_each_environment_controller_is_found_by_its_own_accessor(
    subsystem_manager: SubsystemManager,
) -> None:
    """One list of controllers, five accessors, and each selects by type.

    The list is heterogeneous and positional order is an implementation
    detail of setup, so every accessor picks its own class out of it — and
    answers `None` for a growspace whose controllers were never built rather
    than raising at the call site.
    """
    dehumidifier = MagicMock(spec=DehumidifierCoordinator)
    humidifier = MagicMock(spec=HumidifierCoordinator)
    circulation = MagicMock(spec=CirculationFanCoordinator)
    exhaust = MagicMock(spec=ExhaustFanCoordinator)
    grow_light = MagicMock(spec=GrowLightCoordinator)
    subsystem_manager.environment_controllers["gs1"] = [
        exhaust,
        grow_light,
        dehumidifier,
        circulation,
        humidifier,
    ]

    assert subsystem_manager.get_dehumidifier_controller("gs1") is dehumidifier
    assert subsystem_manager.get_humidifier_controller("gs1") is humidifier
    assert subsystem_manager.get_circulation_fan_controller("gs1") is circulation
    assert subsystem_manager.get_exhaust_fan_controller("gs1") is exhaust
    assert subsystem_manager.get_growlight_controller("gs1") is grow_light
    assert subsystem_manager.get_growlight_controller("gs2") is None
