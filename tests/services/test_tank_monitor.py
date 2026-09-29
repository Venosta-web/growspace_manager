"""Tests for TankLevelMonitor: low-level notifications and the Tank Offline Alert."""

from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.growspace_manager.const import NotificationTier
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    IrrigationTank,
)
from custom_components.growspace_manager.tank_monitor import (
    TankLevelMonitor,
    offline_notification_id,
    stale_after,
    unknown_tank_skip_notification_id,
)
from homeassistant.core import HomeAssistant, ServiceCall, State
from homeassistant.util import dt as dt_util

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
    event.data = {"new_state": State(TANK_ENTITY, state_value)}
    return event


async def _start_and_get_callback(monitor: TankLevelMonitor) -> dict[str, Any]:
    """Start monitor and return captured {entity_id: callback} dict."""
    captured: dict[str, Any] = {}

    def mock_track(hass, entity_id, callback):
        captured[entity_id] = callback
        return MagicMock()

    with (
        patch(
            "custom_components.growspace_manager.tank_monitor.async_track_state_change_event",
            side_effect=mock_track,
        ),
        patch(
            "custom_components.growspace_manager.tank_monitor.async_track_time_interval",
            return_value=MagicMock(),
        ),
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

    tick_unsub = MagicMock()
    with (
        patch(
            "custom_components.growspace_manager.tank_monitor.async_track_state_change_event",
            side_effect=mock_track,
        ),
        patch(
            "custom_components.growspace_manager.tank_monitor.async_track_time_interval",
            return_value=tick_unsub,
        ) as track_interval,
    ):
        await monitor.async_start()

    assert len(unsub_mocks) == 1
    assert track_interval.call_args.args[2] == timedelta(minutes=1)

    monitor.async_stop()

    unsub_mocks[0].assert_called_once()
    tick_unsub.assert_called_once()
    assert monitor._unsubs == []


# --- Tank Offline Alert (#790, ADR-0050) ---------------------------------------

GRACE = timedelta(minutes=10)


@pytest.fixture
def services(hass: HomeAssistant) -> dict[str, list[ServiceCall]]:
    """Stand in for the persistent notification services, recording calls."""
    return {
        service: async_mock_service(hass, "persistent_notification", service)
        for service in ("create", "dismiss")
    }


def _calls(
    services: dict[str, list[ServiceCall]], service: str
) -> list[dict[str, Any]]:
    return [dict(call.data) for call in services[service]]


def _pushes(notify: AsyncMock) -> list[dict[str, Any]]:
    return [
        c.kwargs
        for c in notify.call_args_list
        if c.kwargs.get("tier") == NotificationTier.TANK_OFFLINE
    ]


async def test_an_unavailable_tank_alerts_once_after_the_grace(
    hass: HomeAssistant,
    monitor: TankLevelMonitor,
    notify: AsyncMock,
    services: dict[str, list[ServiceCall]],
) -> None:
    hass.states.async_set(TANK_ENTITY, "60")
    now = dt_util.utcnow()
    await monitor._async_watch_tick(now)
    hass.states.async_set(TANK_ENTITY, "unavailable")
    dropped = hass.states.get(TANK_ENTITY).last_changed

    await monitor._async_watch_tick(dropped + GRACE - timedelta(seconds=1))
    assert _pushes(notify) == []

    await monitor._async_watch_tick(dropped + GRACE)
    await monitor._async_watch_tick(dropped + GRACE * 3)

    since = dt_util.as_local(dropped).strftime("%H:%M")
    message = (
        f"{TANK_NAME} in {GROWSPACE_NAME} has had no usable level since {since}: "
        "the sensor is unavailable. Irrigation is paused until it reports again."
    )
    assert _pushes(notify) == [
        {
            "title": f"⚠️ Tank Offline: {GROWSPACE_NAME}",
            "message": message,
            "tier": NotificationTier.TANK_OFFLINE,
        }
    ]
    assert _calls(services, "create") == [
        {
            "title": f"⚠️ Tank Offline: {GROWSPACE_NAME}",
            "message": message,
            "notification_id": offline_notification_id(GROWSPACE_ID, TANK_ENTITY),
        }
    ]


async def test_a_tank_that_stops_reporting_alerts_even_on_a_plausible_value(
    hass: HomeAssistant,
    monitor: TankLevelMonitor,
    notify: AsyncMock,
    services: dict[str, list[ServiceCall]],
) -> None:
    """The case nothing marks unavailable: a probe frozen on its last value."""
    hass.states.async_set(TANK_ENTITY, "55")
    reported = hass.states.get(TANK_ENTITY).last_reported
    await monitor._async_watch_tick(reported)

    went_stale = reported + timedelta(minutes=120)
    await monitor._async_watch_tick(went_stale + GRACE - timedelta(seconds=1))
    assert _pushes(notify) == []
    await monitor._async_watch_tick(went_stale + GRACE)

    [push] = _pushes(notify)
    assert "no report for over 120 minutes" in push["message"]


async def test_recovery_dismisses_the_alert_and_says_so(
    hass: HomeAssistant,
    monitor: TankLevelMonitor,
    notify: AsyncMock,
    services: dict[str, list[ServiceCall]],
) -> None:
    hass.states.async_set(TANK_ENTITY, "unavailable")
    start = monitor.watches.started_at
    await monitor._async_watch_tick(start + GRACE)
    callbacks = await _start_and_get_callback(monitor)

    await callbacks[TANK_ENTITY](_make_state_event("57.4"))
    hass.states.async_set(TANK_ENTITY, "57.4")
    await monitor._async_watch_tick(start + GRACE * 2)

    assert _pushes(notify)[-1] == {
        "title": f"✅ Tank Back Online: {GROWSPACE_NAME}",
        "message": f"{TANK_NAME} in {GROWSPACE_NAME} is reporting again (57%).",
        "tier": NotificationTier.TANK_OFFLINE,
    }
    assert _calls(services, "dismiss") == [
        {"notification_id": offline_notification_id(GROWSPACE_ID, TANK_ENTITY)},
        {"notification_id": unknown_tank_skip_notification_id(GROWSPACE_ID)},
    ]


async def test_the_skip_notice_stays_while_another_tank_is_still_offline(
    hass: HomeAssistant,
    monitor: TankLevelMonitor,
    growspace: Growspace,
    notify: AsyncMock,
    services: dict[str, list[ServiceCall]],
) -> None:
    growspace.environment_config.irrigation_tanks.append(
        IrrigationTank(sensor_entity="sensor.tank2", name="Tank 2")
    )
    start = monitor.watches.started_at
    await monitor._async_watch_tick(start + GRACE)
    assert len(_pushes(notify)) == 2

    hass.states.async_set(TANK_ENTITY, "70")
    await monitor._async_watch_tick(start + GRACE * 2)

    assert _calls(services, "dismiss") == [
        {"notification_id": offline_notification_id(GROWSPACE_ID, TANK_ENTITY)}
    ]


async def test_the_alert_goes_out_with_the_pause_switched_off(
    hass: HomeAssistant,
    monitor: TankLevelMonitor,
    growspace: Growspace,
    notify: AsyncMock,
    services: dict[str, list[ServiceCall]],
) -> None:
    growspace.irrigation_config.pause_on_low_tank = False
    await monitor._async_watch_tick(monitor.watches.started_at + GRACE)

    [push] = _pushes(notify)
    assert push["message"].endswith(
        "Irrigation is not paused, because Pause When Tank Is Low is off."
    )


async def test_the_growspace_grace_period_is_honoured(
    monitor: TankLevelMonitor,
    growspace: Growspace,
    notify: AsyncMock,
    services: dict[str, list[ServiceCall]],
) -> None:
    growspace.irrigation_config.tank_unknown_grace_minutes = 30
    start = monitor.watches.started_at

    await monitor._async_watch_tick(start + timedelta(minutes=29))
    assert _pushes(notify) == []
    await monitor._async_watch_tick(start + timedelta(minutes=30))
    assert len(_pushes(notify)) == 1


async def test_a_removed_tank_takes_its_alert_with_it(
    monitor: TankLevelMonitor,
    growspace: Growspace,
    notify: AsyncMock,
    services: dict[str, list[ServiceCall]],
) -> None:
    await monitor._async_watch_tick(monitor.watches.started_at + GRACE)
    growspace.environment_config.irrigation_tanks = []

    await monitor._async_watch_tick(monitor.watches.started_at + GRACE * 2)

    assert _calls(services, "dismiss") == [
        {"notification_id": offline_notification_id(GROWSPACE_ID, TANK_ENTITY)}
    ]


async def test_a_removed_tank_that_never_alerted_is_dropped_quietly(
    hass: HomeAssistant,
    monitor: TankLevelMonitor,
    growspace: Growspace,
    services: dict[str, list[ServiceCall]],
) -> None:
    hass.states.async_set(TANK_ENTITY, "60")
    await monitor._async_watch_tick(dt_util.utcnow())
    growspace.environment_config.irrigation_tanks = []

    await monitor._async_watch_tick(dt_util.utcnow())

    assert _calls(services, "dismiss") == []


async def test_the_gate_view_holds_the_last_valid_level_within_grace(
    hass: HomeAssistant, monitor: TankLevelMonitor, growspace: Growspace, tank
) -> None:
    callbacks = await _start_and_get_callback(monitor)
    await callbacks[TANK_ENTITY](_make_state_event("12"))
    hass.states.async_set(TANK_ENTITY, "unavailable")
    dropped = hass.states.get(TANK_ENTITY).last_changed

    held = monitor.watches.status(growspace, tank, dropped + GRACE / 2)
    gone = monitor.watches.status(growspace, tank, dropped + GRACE)

    assert (held.level, held.unknown) == (12.0, None)
    assert gone.level is None
    assert gone.unknown is not None
    assert gone.unknown.cause == "unavailable"


@pytest.mark.parametrize(
    ("stored", "minutes"),
    [(45, 45), ("30", 30), ("soon", 120), (None, 120), (-5, 120), (0, None)],
)
def test_stale_after_tolerates_a_malformed_stored_value(
    tank: IrrigationTank, stored: object, minutes: int | None
) -> None:
    tank.stale_after_minutes = stored  # type: ignore[assignment]
    expected = None if minutes is None else timedelta(minutes=minutes)
    assert stale_after(tank) == expected


async def test_a_tank_with_staleness_off_never_goes_stale(
    hass: HomeAssistant,
    monitor: TankLevelMonitor,
    tank: IrrigationTank,
    notify: AsyncMock,
    services: dict[str, list[ServiceCall]],
) -> None:
    """A change-only sensor on a steady level stays trusted with 0."""
    tank.stale_after_minutes = 0
    hass.states.async_set(TANK_ENTITY, "80")
    reported = hass.states.get(TANK_ENTITY).last_reported

    await monitor._async_watch_tick(reported + timedelta(days=2))

    assert _pushes(notify) == []


async def test_a_tank_with_staleness_off_still_alerts_when_unavailable(
    hass: HomeAssistant,
    monitor: TankLevelMonitor,
    tank: IrrigationTank,
    notify: AsyncMock,
    services: dict[str, list[ServiceCall]],
) -> None:
    tank.stale_after_minutes = 0
    hass.states.async_set(TANK_ENTITY, "unavailable")
    dropped = hass.states.get(TANK_ENTITY).last_changed

    await monitor._async_watch_tick(dropped + GRACE)

    [push] = _pushes(notify)
    assert "the sensor is unavailable" in push["message"]
