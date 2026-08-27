"""Tests for TankLevelMonitor."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import NotificationTier
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    IrrigationTank,
)
from custom_components.growspace_manager.tank_monitor import TankLevelMonitor
from homeassistant.core import HomeAssistant

GROWSPACE_ID = "gs1"
GROWSPACE_NAME = "Test Tent"
TANK_ENTITY = "sensor.tank1"
TANK_NAME = "Water Tank"
WARNING_LEVEL = 30.0


@pytest.fixture
def tank() -> IrrigationTank:
    return IrrigationTank(
        sensor_entity=TANK_ENTITY, name=TANK_NAME, warning_level=WARNING_LEVEL
    )


@pytest.fixture
def growspace(tank: IrrigationTank) -> Growspace:
    return Growspace(
        id=GROWSPACE_ID,
        name=GROWSPACE_NAME,
        environment_config=EnvironmentConfig(irrigation_tanks=[tank]),
    )


@pytest.fixture
def mock_coordinator(growspace: Growspace) -> MagicMock:
    coordinator = MagicMock()
    coordinator.growspaces = {GROWSPACE_ID: growspace}
    return coordinator


@pytest.fixture
def notify() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def monitor(
    hass: HomeAssistant, mock_coordinator: MagicMock, notify: AsyncMock
) -> TankLevelMonitor:
    return TankLevelMonitor(hass, mock_coordinator, notify)


def _make_state_event(state_value: str) -> MagicMock:
    event = MagicMock()
    event.data = {"new_state": MagicMock(state=state_value)}
    return event


async def _start_and_get_callback(monitor: TankLevelMonitor) -> dict[str, Any]:
    """Start monitor and return captured {entity_id: callback} dict."""
    captured: dict[str, Any] = {}

    def mock_track(hass, entity_id, callback):
        captured[entity_id] = callback
        return MagicMock()

    with patch(
        "custom_components.growspace_manager.tank_monitor.async_track_state_change_event",
        side_effect=mock_track,
    ):
        await monitor.async_start()

    return captured


async def test_no_notification_when_level_above_warning(
    monitor: TankLevelMonitor, notify: AsyncMock
) -> None:
    """Level above warning threshold produces no notification."""
    callbacks = await _start_and_get_callback(monitor)
    assert TANK_ENTITY in callbacks

    await callbacks[TANK_ENTITY](_make_state_event("50.0"))

    notify.assert_not_awaited()


async def test_notification_when_level_at_warning(
    monitor: TankLevelMonitor, notify: AsyncMock
) -> None:
    """Level exactly at warning threshold fires notification with correct arguments."""
    callbacks = await _start_and_get_callback(monitor)

    await callbacks[TANK_ENTITY](_make_state_event(str(WARNING_LEVEL)))

    notify.assert_awaited_once_with(
        GROWSPACE_ID,
        title="⚠️ Low Irrigation Tank Level",
        message=f"{TANK_NAME} in {GROWSPACE_NAME} is at {WARNING_LEVEL:.0f}% (warning at {WARNING_LEVEL:.0f}%)",
        tier=NotificationTier.CRITICAL,
    )


async def test_no_notification_for_unparseable_state(
    monitor: TankLevelMonitor, notify: AsyncMock
) -> None:
    """Sensor state that cannot be parsed as a percentage fires no notification."""
    callbacks = await _start_and_get_callback(monitor)

    await callbacks[TANK_ENTITY](_make_state_event("unavailable"))

    notify.assert_not_awaited()


async def test_no_notification_when_new_state_is_none(
    monitor: TankLevelMonitor, notify: AsyncMock
) -> None:
    """Event with new_state=None (entity removed) fires no notification."""
    callbacks = await _start_and_get_callback(monitor)

    event = MagicMock()
    event.data = {"new_state": None}
    await callbacks[TANK_ENTITY](event)

    notify.assert_not_awaited()


async def test_no_subscription_for_growspace_without_tanks(
    hass: HomeAssistant, notify: AsyncMock
) -> None:
    """Growspace with no irrigation tanks registers no state listeners."""
    coordinator = MagicMock()
    coordinator.growspaces = {
        "gs_notanks": Growspace(
            id="gs_notanks",
            name="No Tanks",
            environment_config=EnvironmentConfig(irrigation_tanks=[]),
        )
    }
    monitor = TankLevelMonitor(hass, coordinator, notify)
    callbacks = await _start_and_get_callback(monitor)

    assert callbacks == {}
    notify.assert_not_awaited()


async def test_no_subscription_for_growspace_without_environment_config(
    hass: HomeAssistant, notify: AsyncMock
) -> None:
    """Growspace with no EnvironmentConfig registers no state listeners."""
    coordinator = MagicMock()
    coordinator.growspaces = {"gs_noenv": Growspace(id="gs_noenv", name="No Env")}
    monitor = TankLevelMonitor(hass, coordinator, notify)
    callbacks = await _start_and_get_callback(monitor)

    assert callbacks == {}
    notify.assert_not_awaited()


async def test_async_stop_cancels_all_subscriptions(
    monitor: TankLevelMonitor, notify: AsyncMock
) -> None:
    """async_stop() calls each unsubscribe handle so further state changes are ignored."""
    unsub_mocks: list[MagicMock] = []

    def mock_track(hass, entity_id, callback):
        m = MagicMock()
        unsub_mocks.append(m)
        return m

    with patch(
        "custom_components.growspace_manager.tank_monitor.async_track_state_change_event",
        side_effect=mock_track,
    ):
        await monitor.async_start()

    assert len(unsub_mocks) == 1

    monitor.async_stop()

    unsub_mocks[0].assert_called_once()
    assert monitor._unsubs == []
