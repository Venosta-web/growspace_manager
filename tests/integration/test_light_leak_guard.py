"""Integration tests for the Light Leak Guard in GrowLightCoordinator (#794)."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import (
    CATEGORY_ALERT,
    EVENT_GROWSPACE_LOG_ENTRY,
    NotificationTier,
)
from custom_components.growspace_manager.grow_light_coordinator import (
    GrowLightCoordinator,
)
from custom_components.growspace_manager.models import (
    ACInfinityGrowLight,
    EnvironmentConfig,
    GrowLightConfig,
    LightLeakConfig,
)
from custom_components.growspace_manager.notification_manager import NotificationManager
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

_MODULE = "custom_components.growspace_manager.grow_light_coordinator"
_SENSOR = "sensor.tent_lux"
_FLOWERING = MagicMock(flower_start="2026-07-01")
# 18:00–06:00 is the 12h flower dark period for a 06:00 lights-on.
_NIGHT = datetime(2026, 7, 3, 20, 0)


@pytest.fixture
def mock_hass() -> MagicMock:
    """Return mock HomeAssistant with an async service caller and a bus."""
    hass = MagicMock(spec=HomeAssistant)
    hass.states = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.bus = MagicMock()
    _wire_states(hass, {})
    return hass


@pytest.fixture(autouse=True)
def mock_track_interval():
    """Patch the interval tracker; each registration gets its own remover."""
    with patch(f"{_MODULE}.async_track_time_interval") as mock:
        mock.side_effect = lambda *_args: MagicMock()
        yield mock


@pytest.fixture(autouse=True)
def mock_track_point():
    """Patch the midnight reconcile scheduler."""
    with patch(f"{_MODULE}.async_track_point_in_utc_time") as mock:
        mock.return_value = MagicMock()
        yield mock


@pytest.fixture
def mock_push():
    """Patch the AC Infinity schedule configurator."""
    with (
        patch(f"{_MODULE}.push_ac_infinity_schedule", new=AsyncMock()) as push,
        patch(f"{_MODULE}.ac_infinity_schedule_matches", return_value=False),
    ):
        yield push


def _wire_states(hass: MagicMock, states: dict[str, str]) -> None:
    """Make hass.states.get answer from ``states`` (live: mutate it later)."""

    def _get(entity_id: str) -> MagicMock | None:
        if entity_id not in states:
            return None
        st = MagicMock()
        st.state = states[entity_id]
        return st

    hass.states.get.side_effect = _get


def _ac_device() -> ACInfinityGrowLight:
    return ACInfinityGrowLight(
        mode_entity="select.port_mode",
        on_time_entity="time.port_on",
        off_time_entity="time.port_off",
        power_entity="number.port_power",
    )


def _make_env(
    *,
    controller: bool = False,
    growlight_entities: list[str] | None = None,
    ac_infinity_devices: list[ACInfinityGrowLight] | None = None,
    sensor: str | None = _SENSOR,
    **leak: object,
) -> EnvironmentConfig:
    return EnvironmentConfig(
        growlight_entities=growlight_entities or [],
        growlight_ac_infinity_devices=ac_infinity_devices or [],
        growlight_config=GrowLightConfig(enabled=controller),
        light_leak_config=LightLeakConfig(illuminance_sensor=sensor, **leak),
    )


def _make_guard(
    hass: MagicMock, env: EnvironmentConfig, *, plants: list | None = None
) -> tuple[GrowLightCoordinator, MagicMock]:
    gs = MagicMock()
    gs.name = "Test Tent"
    gs.environment_config = env
    gs.irrigation_strategy.lights_on_time = "06:00:00"
    main = MagicMock()
    main.growspaces = {"gs1": gs}
    main.services.growspaces.get_growspace_plants.return_value = (
        [_FLOWERING] if plants is None else plants
    )
    main.services.notifications.manager.async_send_notification = AsyncMock()
    return GrowLightCoordinator(hass, MagicMock(), "gs1", main), main


def _notify(main: MagicMock) -> AsyncMock:
    return main.services.notifications.manager.async_send_notification


def _at(now: datetime):
    return patch(f"{_MODULE}.dt_util.now", return_value=now)


async def _check(coord: GrowLightCoordinator, start: datetime, minutes: int) -> None:
    """Run the minute check ``minutes`` times, one minute apart from ``start``."""
    for i in range(minutes):
        with _at(start + timedelta(minutes=i)):
            await coord._async_check_light_leak()


def _logbook(hass: MagicMock) -> list[dict]:
    return [
        c.args[1]
        for c in hass.bus.async_fire.call_args_list
        if c.args[0] == EVENT_GROWSPACE_LOG_ENTRY
    ]


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------


async def test_setup_checks_now_and_every_minute(
    mock_hass: MagicMock, mock_track_interval: MagicMock
) -> None:
    """A lux sensor alone arms the guard: a start-up check, then every minute."""
    _wire_states(mock_hass, {_SENSOR: "5"})
    coord, _main = _make_guard(mock_hass, _make_env())

    with _at(_NIGHT):
        await coord.async_setup()

    intervals = [c.args[2] for c in mock_track_interval.call_args_list]
    assert intervals == [timedelta(minutes=1)]  # no regulation tick: no controller
    assert coord._leak_episode.started_at == _NIGHT


@pytest.mark.parametrize(
    "env",
    [
        _make_env(enabled=False),
        _make_env(sensor=None),  # nothing to watch: no sensor, no controller
    ],
)
async def test_guard_stays_off_without_evidence_to_watch(
    mock_hass: MagicMock, mock_track_interval: MagicMock, env: EnvironmentConfig
) -> None:
    """A disabled guard, or one with neither lights nor a sensor, never runs."""
    coord, _main = _make_guard(mock_hass, env)

    with _at(_NIGHT):
        await coord.async_setup()

    mock_track_interval.assert_not_called()


async def test_setup_without_environment_is_noop(
    mock_hass: MagicMock, mock_track_interval: MagicMock
) -> None:
    """A growspace that has vanished starts nothing."""
    coord, main = _make_guard(mock_hass, _make_env())
    main.growspaces = {}

    await coord.async_setup()
    await coord._async_check_light_leak()

    mock_track_interval.assert_not_called()
    _notify(main).assert_not_awaited()


async def test_minute_tick_schedules_a_check(mock_hass: MagicMock) -> None:
    """The interval callback hands the check to a background task."""
    coord, _main = _make_guard(mock_hass, _make_env())

    coord._on_leak_check(_NIGHT)

    create = coord.config_entry.async_create_background_task
    create.assert_called_once()
    create.call_args.args[1].close()  # the un-awaited check coroutine


async def test_unload_cancels_the_minute_check(
    mock_hass: MagicMock, mock_track_interval: MagicMock
) -> None:
    """Unloading removes the leak-check listener."""
    coord, _main = _make_guard(mock_hass, _make_env())
    with _at(_NIGHT):
        await coord.async_setup()
    remove = coord._remove_leak_check
    assert remove is not None

    coord.unload()

    remove.assert_called_once()
    assert coord._remove_leak_check is None


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


async def test_illuminance_leak_alerts_once_per_episode(mock_hass: MagicMock) -> None:
    """Lux above threshold past the debounce raises one critical alert."""
    _wire_states(mock_hass, {_SENSOR: "5"})
    coord, main = _make_guard(mock_hass, _make_env())

    await _check(coord, _NIGHT, 2)
    _notify(main).assert_not_awaited()  # still inside the 120s debounce

    await _check(coord, _NIGHT + timedelta(minutes=2), 5)

    _notify(main).assert_awaited_once()
    growspace_id, title, message = _notify(main).call_args.args
    assert growspace_id == "gs1"
    assert title == "🚨 Light Leak: Test Tent"
    assert "(18:00–06:00)" in message
    assert f"{_SENSOR} reads 5 lx (threshold 1 lx)" in message
    assert "Check the room" in message
    assert _notify(main).call_args.kwargs["tier"] == NotificationTier.LIGHT_LEAK

    [entry] = _logbook(mock_hass)
    assert entry["category"] == CATEGORY_ALERT
    assert entry["sensor_type"] == "light_leak"
    assert entry["growspace_id"] == "gs1"
    assert entry["reasons"] == [message]


async def test_cleared_episode_is_logged_and_the_next_alerts_again(
    mock_hass: MagicMock,
) -> None:
    """The end of an episode is logged with its duration; a new one re-alerts."""
    states = {_SENSOR: "5"}
    _wire_states(mock_hass, states)
    coord, main = _make_guard(mock_hass, _make_env())

    await _check(coord, _NIGHT, 3)  # confirmed at +2 min
    states[_SENSOR] = "0"
    await _check(coord, _NIGHT + timedelta(minutes=3), 1)

    ended = _logbook(mock_hass)[-1]
    assert ended["reasons"] == ["Light leak ended"]
    assert ended["duration_sec"] == 180

    states[_SENSOR] = "5"
    await _check(coord, _NIGHT + timedelta(minutes=4), 3)
    assert _notify(main).await_count == 2


@pytest.mark.parametrize(
    ("when", "plants", "all_stages", "alerts"),
    [
        # The lit period is never watched.
        (datetime(2026, 7, 3, 12, 0), None, False, False),
        # A veg night is watched only when configured for every stage.
        (datetime(2026, 7, 3, 2, 0), [], False, False),
        (datetime(2026, 7, 3, 2, 0), [], True, True),
    ],
)
async def test_watch_is_limited_to_the_flowering_dark_period(
    mock_hass: MagicMock,
    when: datetime,
    plants: list | None,
    all_stages: bool,
    alerts: bool,
) -> None:
    """No alert in the light or in veg, unless ``all_stages`` is set."""
    _wire_states(mock_hass, {_SENSOR: "500"})
    coord, main = _make_guard(
        mock_hass, _make_env(all_stages=all_stages), plants=plants
    )

    await _check(coord, when, 5)

    assert _notify(main).await_count == (1 if alerts else 0)


@pytest.mark.parametrize("reading", ["unavailable", "unknown", "0.4"])
async def test_unreadable_or_dark_sensor_is_no_leak(
    mock_hass: MagicMock, reading: str
) -> None:
    """An unavailable sensor is no evidence, and one under threshold is dark."""
    _wire_states(mock_hass, {_SENSOR: reading})
    coord, main = _make_guard(mock_hass, _make_env())

    await _check(coord, _NIGHT, 5)

    _notify(main).assert_not_awaited()
    assert _logbook(mock_hass) == []


async def test_managed_light_on_in_the_dark_alerts(mock_hass: MagicMock) -> None:
    """A grow light GSM drives that stays on in the dark is a leak by itself."""
    _wire_states(mock_hass, {"switch.grow": "on"})
    env = _make_env(controller=True, growlight_entities=["switch.grow"], sensor=None)
    coord, main = _make_guard(mock_hass, env)

    await _check(coord, _NIGHT, 3)

    _notify(main).assert_awaited_once()
    assert "grow light still on: switch.grow" in _notify(main).call_args.args[2]


async def test_unmanaged_light_is_not_evidence(mock_hass: MagicMock) -> None:
    """With the controller off, a configured light's state is not the guard's."""
    _wire_states(mock_hass, {"switch.grow": "on", _SENSOR: "0"})
    env = _make_env(controller=False, growlight_entities=["switch.grow"])
    coord, main = _make_guard(mock_hass, env)

    await _check(coord, _NIGHT, 5)

    _notify(main).assert_not_awaited()


async def test_restart_mid_episode_does_not_alert_again(
    mock_hass: MagicMock,
) -> None:
    """A config edit restarts the coordinator, not the episode."""
    _wire_states(mock_hass, {_SENSOR: "5"})
    coord, main = _make_guard(mock_hass, _make_env())

    await _check(coord, _NIGHT, 3)
    with _at(_NIGHT + timedelta(minutes=3)):
        await coord.async_restart()
    await _check(coord, _NIGHT + timedelta(minutes=4), 3)

    _notify(main).assert_awaited_once()


# ---------------------------------------------------------------------------
# Opt-in switch-off and read-back
# ---------------------------------------------------------------------------


def _switch_off_env() -> EnvironmentConfig:
    return _make_env(
        controller=True,
        growlight_entities=["switch.grow"],
        ac_infinity_devices=[_ac_device()],
        switch_off_lights=True,
    )


def _lit_states() -> dict[str, str]:
    return {_SENSOR: "5", "switch.grow": "on", "select.port_mode": "On"}


async def test_opt_in_switches_managed_lights_off(mock_hass: MagicMock) -> None:
    """With the opt-in, the alert switches every managed grow light off."""
    _wire_states(mock_hass, _lit_states())
    coord, main = _make_guard(mock_hass, _switch_off_env())

    await _check(coord, _NIGHT, 3)

    mock_hass.services.async_call.assert_any_await(
        "switch", "turn_off", {ATTR_ENTITY_ID: "switch.grow"}, blocking=False
    )
    mock_hass.services.async_call.assert_any_await(
        "select",
        "select_option",
        {ATTR_ENTITY_ID: "select.port_mode", "option": "Off"},
        blocking=False,
    )
    message = _notify(main).call_args.args[2]
    assert "grow light still on: switch.grow, select.port_mode" in message
    assert "Switching the managed grow lights off until lights-on." in message


async def test_switched_off_lights_read_back_off(mock_hass: MagicMock) -> None:
    """Lights that read back off are logged as such, with no second alert."""
    states = _lit_states()
    _wire_states(mock_hass, states)
    coord, main = _make_guard(mock_hass, _switch_off_env())
    await _check(coord, _NIGHT, 3)

    states.update({"switch.grow": "off", "select.port_mode": "Off"})
    await _check(coord, _NIGHT + timedelta(minutes=3), 1)

    assert _logbook(mock_hass)[-1]["reasons"] == ["Managed grow lights read back off"]
    assert coord._leak_switched_off_at is None
    _notify(main).assert_awaited_once()


async def test_lights_that_stay_on_are_reported_after_the_grace(
    mock_hass: MagicMock,
) -> None:
    """A light still on two minutes after switch-off raises a second alert."""
    _wire_states(mock_hass, _lit_states())
    coord, main = _make_guard(mock_hass, _switch_off_env())
    await _check(coord, _NIGHT, 3)  # switched off at +2 min

    await _check(coord, _NIGHT + timedelta(minutes=3), 1)
    _notify(main).assert_awaited_once()  # still inside the read-back grace

    await _check(coord, _NIGHT + timedelta(minutes=4), 3)

    assert _notify(main).await_count == 2
    message = _notify(main).call_args.args[2]
    assert "did not switch off" in message
    assert "switch.grow, select.port_mode" in message
    assert _notify(main).call_args.kwargs["tier"] == NotificationTier.LIGHT_LEAK


async def test_read_back_is_dropped_when_the_dark_period_ends(
    mock_hass: MagicMock, mock_push: AsyncMock
) -> None:
    """Lights on after lights-on are meant to be on: no read-back alert."""
    _wire_states(mock_hass, _lit_states())
    coord, main = _make_guard(mock_hass, _make_env_zero_debounce())
    with _at(datetime(2026, 7, 4, 5, 59)):
        await coord._async_check_light_leak()  # confirms and switches off
    assert coord._leak_switched_off_at is not None

    with _at(datetime(2026, 7, 4, 6, 5)):
        await coord._async_check_light_leak()

    assert coord._leak_switched_off_at is None
    _notify(main).assert_awaited_once()


def _make_env_zero_debounce() -> EnvironmentConfig:
    env = _switch_off_env()
    env.light_leak_config.debounce_seconds = 0
    return env


async def test_switched_off_ac_infinity_schedule_is_restored_at_lights_on(
    mock_hass: MagicMock, mock_push: AsyncMock
) -> None:
    """Ports the guard switched off get their schedule back at lights-on."""
    _wire_states(mock_hass, _lit_states())
    coord, _main = _make_guard(mock_hass, _make_env_zero_debounce())
    with _at(_NIGHT):
        await coord._async_check_light_leak()
    assert coord._leak_restore_schedules is True

    with _at(datetime(2026, 7, 4, 5, 59)):
        await coord._async_check_light_leak()
    mock_push.assert_not_awaited()  # still dark

    with _at(datetime(2026, 7, 4, 6, 0)):
        await coord._async_check_light_leak()

    mock_push.assert_awaited_once()
    assert mock_push.call_args.kwargs["on_time"] == "06:00:00"
    assert mock_push.call_args.kwargs["off_time"] == "18:00:00"
    assert coord._leak_restore_schedules is False


async def test_opt_in_without_managed_lights_only_alerts(
    mock_hass: MagicMock,
) -> None:
    """With no lights GSM drives, the opt-in has nothing to switch."""
    _wire_states(mock_hass, {_SENSOR: "5"})
    coord, main = _make_guard(mock_hass, _make_env(switch_off_lights=True))

    await _check(coord, _NIGHT, 3)

    mock_hass.services.async_call.assert_not_awaited()
    assert "Check the room" in _notify(main).call_args.args[2]


# ---------------------------------------------------------------------------
# Notification tier
# ---------------------------------------------------------------------------


def test_light_leak_tier_is_never_on_cooldown() -> None:
    """A Bayesian critical alert's cooldown cannot mute a light-leak alert."""
    manager = NotificationManager(MagicMock(), MagicMock(options={}), MagicMock())
    manager._set_cooldown("gs1", NotificationTier.CRITICAL)
    manager._set_cooldown("gs1", NotificationTier.LIGHT_LEAK)

    now = dt_util.utcnow()
    assert manager._is_on_cooldown("gs1", NotificationTier.CRITICAL, now)
    assert not manager._is_on_cooldown("gs1", NotificationTier.LIGHT_LEAK, now)
