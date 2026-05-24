"""Tests for the PhotoperiodFlipChecker."""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import NotificationTier
from custom_components.growspace_manager.photoperiod_flip_checker import (
    PhotoperiodFlipChecker,
)
from homeassistant.core import HomeAssistant

TODAY = date(2026, 5, 24)
TODAY_DT = datetime(2026, 5, 24, 8, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def mock_hass() -> MagicMock:
    return MagicMock(spec=HomeAssistant)


@pytest.fixture
def mock_coordinator(mock_hass: MagicMock) -> MagicMock:
    coordinator = MagicMock()
    coordinator.hass = mock_hass
    coordinator.growspaces = {}
    coordinator.notification_manager.async_send_notification = AsyncMock()
    coordinator.config_entry.async_create_background_task = MagicMock()
    coordinator.services.growspaces.get_growspace_plants = MagicMock(return_value=[])
    return coordinator


def _make_growspace(
    growspace_id: str = "tent1",
    name: str = "Test Tent",
    auto_light_tracking: bool = False,
    notification_target: str = "notify.mobile",
) -> MagicMock:
    gs = MagicMock()
    gs.id = growspace_id
    gs.name = name
    gs.notification_target = notification_target
    gs.irrigation_strategy.auto_light_tracking = auto_light_tracking
    return gs


def _make_plant(flower_start: str | None) -> MagicMock:
    plant = MagicMock()
    plant.flower_start = flower_start
    return plant


async def _run_immediate_check(coordinator: MagicMock) -> None:
    """Extract and await the background task coroutine registered during schedule_growspace."""
    call_args = coordinator.config_entry.async_create_background_task.call_args
    coro = call_args.args[1]
    await coro


# ---------------------------------------------------------------------------
# Tracer bullet
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notification_sent_when_flower_start_is_today(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """Notification is sent when any plant has flower_start == today."""
    gs = _make_growspace()
    mock_coordinator.growspaces = {"tent1": gs}
    mock_coordinator.services.growspaces.get_growspace_plants.return_value = [
        _make_plant(TODAY.isoformat())
    ]

    checker = PhotoperiodFlipChecker(mock_hass, mock_coordinator)

    with (
        patch(
            "custom_components.growspace_manager.photoperiod_flip_checker.async_track_point_in_utc_time"
        ),
        patch(
            "custom_components.growspace_manager.photoperiod_flip_checker.ha_now",
            return_value=TODAY_DT,
        ),
    ):
        checker.schedule_growspace("tent1")
        await _run_immediate_check(mock_coordinator)

    mock_coordinator.notification_manager.async_send_notification.assert_called_once()
    _, kwargs = mock_coordinator.notification_manager.async_send_notification.call_args
    assert kwargs["tier"] == NotificationTier.PHOTOPERIOD_FLIP


@pytest.mark.asyncio
async def test_no_notification_when_flower_start_is_future(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """No notification sent when flower_start is in the future."""
    gs = _make_growspace()
    mock_coordinator.growspaces = {"tent1": gs}
    mock_coordinator.services.growspaces.get_growspace_plants.return_value = [
        _make_plant("2026-05-25")  # tomorrow
    ]

    checker = PhotoperiodFlipChecker(mock_hass, mock_coordinator)

    with (
        patch(
            "custom_components.growspace_manager.photoperiod_flip_checker.async_track_point_in_utc_time"
        ),
        patch(
            "custom_components.growspace_manager.photoperiod_flip_checker.ha_now",
            return_value=TODAY_DT,
        ),
    ):
        checker.schedule_growspace("tent1")
        await _run_immediate_check(mock_coordinator)

    mock_coordinator.notification_manager.async_send_notification.assert_not_called()  # future


@pytest.mark.asyncio
async def test_no_notification_when_flower_start_is_past(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """No notification sent when flower_start is in the past."""
    gs = _make_growspace()
    mock_coordinator.growspaces = {"tent1": gs}
    mock_coordinator.services.growspaces.get_growspace_plants.return_value = [
        _make_plant("2026-05-23")  # yesterday
    ]

    checker = PhotoperiodFlipChecker(mock_hass, mock_coordinator)

    with (
        patch(
            "custom_components.growspace_manager.photoperiod_flip_checker.async_track_point_in_utc_time"
        ),
        patch(
            "custom_components.growspace_manager.photoperiod_flip_checker.ha_now",
            return_value=TODAY_DT,
        ),
    ):
        checker.schedule_growspace("tent1")
        await _run_immediate_check(mock_coordinator)

    mock_coordinator.notification_manager.async_send_notification.assert_not_called()  # past


# ---------------------------------------------------------------------------
# Message variation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("auto_light_tracking", "expected_fragment"),
    [
        (True, "auto-adapt from sensor"),
        (False, "update your lights-on time to 12h"),
    ],
)
async def test_message_varies_on_auto_light_tracking(
    mock_hass: MagicMock,
    mock_coordinator: MagicMock,
    auto_light_tracking: bool,
    expected_fragment: str,
) -> None:
    """Notification message reflects auto_light_tracking setting on the growspace."""
    gs = _make_growspace(auto_light_tracking=auto_light_tracking)
    mock_coordinator.growspaces = {"tent1": gs}
    mock_coordinator.services.growspaces.get_growspace_plants.return_value = [
        _make_plant(TODAY.isoformat())
    ]

    checker = PhotoperiodFlipChecker(mock_hass, mock_coordinator)

    with (
        patch(
            "custom_components.growspace_manager.photoperiod_flip_checker.async_track_point_in_utc_time"
        ),
        patch(
            "custom_components.growspace_manager.photoperiod_flip_checker.ha_now",
            return_value=TODAY_DT,
        ),
    ):
        checker.schedule_growspace("tent1")
        await _run_immediate_check(mock_coordinator)

    call = mock_coordinator.notification_manager.async_send_notification.call_args
    # positional: (growspace_id, title, message, ...)
    _growspace_id, title, message = call.args[:3]
    assert expected_fragment in message
    assert title == "🌸 Photoperiod Flip: Test Tent"


# ---------------------------------------------------------------------------
# Cooldown tier
# ---------------------------------------------------------------------------


def test_photoperiod_flip_tier_registered_with_23h_cooldown() -> None:
    """NotificationManager._TIER_COOLDOWNS has a 23-hour entry for PHOTOPERIOD_FLIP."""
    from datetime import timedelta

    from custom_components.growspace_manager.notification_manager import NotificationManager

    cooldown = NotificationManager._TIER_COOLDOWNS[NotificationTier.PHOTOPERIOD_FLIP]
    assert cooldown == timedelta(hours=23)


# ---------------------------------------------------------------------------
# Midnight reschedule
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_midnight_callback_reschedules_for_next_day(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """After the midnight callback fires, schedule_growspace is called again."""
    gs = _make_growspace()
    mock_coordinator.growspaces = {"tent1": gs}
    mock_coordinator.services.growspaces.get_growspace_plants.return_value = []

    checker = PhotoperiodFlipChecker(mock_hass, mock_coordinator)

    captured_callback = None

    def capture_timer(_hass: MagicMock, cb: object, _dt: object) -> MagicMock:
        nonlocal captured_callback
        captured_callback = cb
        return MagicMock()

    with patch(
        "custom_components.growspace_manager.photoperiod_flip_checker.async_track_point_in_utc_time",
        side_effect=capture_timer,
    ), patch(
        "custom_components.growspace_manager.photoperiod_flip_checker.ha_now",
        return_value=TODAY_DT,
    ):
        checker.schedule_growspace("tent1")

    assert captured_callback is not None

    # Fire the midnight callback; it should re-register a new timer
    with patch(
        "custom_components.growspace_manager.photoperiod_flip_checker.async_track_point_in_utc_time",
        side_effect=capture_timer,
    ), patch(
        "custom_components.growspace_manager.photoperiod_flip_checker.ha_now",
        return_value=TODAY_DT,
    ):
        await captured_callback(TODAY_DT)

    # A second timer was registered (reschedule happened)
    assert mock_hass is not None  # sanity
    assert "tent1" in checker._unsub_timers


# ---------------------------------------------------------------------------
# schedule_all_growspaces + async_stop
# ---------------------------------------------------------------------------


def test_schedule_all_growspaces_registers_timer_per_growspace(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """schedule_all_growspaces registers a midnight timer for every growspace."""
    mock_coordinator.growspaces = {
        "tent1": _make_growspace("tent1"),
        "tent2": _make_growspace("tent2"),
    }

    checker = PhotoperiodFlipChecker(mock_hass, mock_coordinator)

    with patch(
        "custom_components.growspace_manager.photoperiod_flip_checker.async_track_point_in_utc_time",
        return_value=MagicMock(),
    ), patch(
        "custom_components.growspace_manager.photoperiod_flip_checker.ha_now",
        return_value=TODAY_DT,
    ):
        checker.schedule_all_growspaces()

    assert "tent1" in checker._unsub_timers
    assert "tent2" in checker._unsub_timers


def test_async_stop_cancels_all_timers(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """async_stop cancels every registered timer and clears the timer dict."""
    mock_coordinator.growspaces = {"tent1": _make_growspace()}

    unsub = MagicMock()
    checker = PhotoperiodFlipChecker(mock_hass, mock_coordinator)

    with patch(
        "custom_components.growspace_manager.photoperiod_flip_checker.async_track_point_in_utc_time",
        return_value=unsub,
    ), patch(
        "custom_components.growspace_manager.photoperiod_flip_checker.ha_now",
        return_value=TODAY_DT,
    ):
        checker.schedule_all_growspaces()

    checker.async_stop()

    unsub.assert_called_once()
    assert checker._unsub_timers == {}


# ---------------------------------------------------------------------------
# Malformed flower_start
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_flower_start_logs_warning_and_continues(
    mock_hass: MagicMock, mock_coordinator: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    """Malformed flower_start logs a warning and does not crash; valid plant still checked."""
    gs = _make_growspace()
    mock_coordinator.growspaces = {"tent1": gs}
    mock_coordinator.services.growspaces.get_growspace_plants.return_value = [
        _make_plant("not-a-date"),        # malformed — should warn + continue
        _make_plant(TODAY.isoformat()),   # valid — should trigger notification
    ]

    checker = PhotoperiodFlipChecker(mock_hass, mock_coordinator)

    with (
        patch(
            "custom_components.growspace_manager.photoperiod_flip_checker.async_track_point_in_utc_time"
        ),
        patch(
            "custom_components.growspace_manager.photoperiod_flip_checker.ha_now",
            return_value=TODAY_DT,
        ),
    ):
        checker.schedule_growspace("tent1")
        await _run_immediate_check(mock_coordinator)

    assert "Malformed flower_start" in caplog.text
    mock_coordinator.notification_manager.async_send_notification.assert_called_once()
