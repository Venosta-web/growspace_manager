"""Tests for BriefingScheduler — AI Briefing generation with interval, entity, and manual triggers."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from custom_components.growspace_manager.briefing_scheduler import BriefingScheduler
from homeassistant.core import HomeAssistant


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_store():
    """Patch Store so construction doesn't require a real hass instance."""
    with patch(
        "custom_components.growspace_manager.briefing_scheduler.Store"
    ) as mock_store_cls:
        mock_store_cls.return_value = MagicMock()
        yield mock_store_cls


@pytest.fixture
def mock_hass() -> MagicMock:
    """Minimal Home Assistant mock."""
    hass = MagicMock(spec=HomeAssistant)
    hass.loop = asyncio.get_event_loop()
    hass.async_create_task = MagicMock(side_effect=lambda coro: asyncio.ensure_future(coro))
    return hass


@pytest.fixture
def mock_coordinator(mock_hass: MagicMock) -> MagicMock:
    """Coordinator mock with AI settings and minimal growspace data."""
    coordinator = MagicMock()
    coordinator.hass = mock_hass
    coordinator.options = {
        "ai_settings": {
            "ai_enabled": True,
            "assistant_id": "conversation.claude",
            "briefing_interval_minutes": 30,
            "briefing_trigger_entities": [],
        }
    }
    coordinator.growspaces = {}
    return coordinator


# ---------------------------------------------------------------------------
# Cycle 1 — Initialisation
# ---------------------------------------------------------------------------

def test_briefing_scheduler_initializes(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """BriefingScheduler stores hass and coordinator references on construction."""
    scheduler = BriefingScheduler(mock_hass, mock_coordinator)
    assert scheduler.hass is mock_hass
    assert scheduler.coordinator is mock_coordinator


# ---------------------------------------------------------------------------
# Cycle 2 — Interval trigger
# ---------------------------------------------------------------------------

def test_start_registers_interval_listener(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """start() registers an async_track_time_interval listener at the configured cadence."""
    scheduler = BriefingScheduler(mock_hass, mock_coordinator)

    with patch(
        "custom_components.growspace_manager.briefing_scheduler.async_track_time_interval"
    ) as mock_track:
        mock_track.return_value = MagicMock()
        scheduler.start()

    mock_track.assert_called_once()
    _, _, interval = mock_track.call_args.args
    assert interval == timedelta(minutes=30)


def test_start_uses_custom_interval_minutes(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """Interval is read from briefing_interval_minutes AI setting."""
    mock_coordinator.options["ai_settings"]["briefing_interval_minutes"] = 60
    scheduler = BriefingScheduler(mock_hass, mock_coordinator)

    with patch(
        "custom_components.growspace_manager.briefing_scheduler.async_track_time_interval"
    ) as mock_track:
        mock_track.return_value = MagicMock()
        scheduler.start()

    _, _, interval = mock_track.call_args.args
    assert interval == timedelta(minutes=60)


@pytest.mark.asyncio
async def test_interval_callback_generates_briefing(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """Interval callback triggers briefing generation and caches the result."""
    scheduler = BriefingScheduler(mock_hass, mock_coordinator)
    scheduler._store = MagicMock()
    scheduler._store.async_save = AsyncMock()

    with patch.object(
        scheduler, "_generate_briefing", new_callable=AsyncMock,
        return_value={"generated_at": 1234.0, "summary_text": "All good", "ai_available": True, "kpis": [], "recommendations": []}
    ) as mock_gen:
        await scheduler._async_on_interval(None)

    mock_gen.assert_called_once()
    assert scheduler._cached_briefing is not None
    assert scheduler._cached_briefing["summary_text"] == "All good"


# ---------------------------------------------------------------------------
# Cycle 3 — Entity event trigger + debounce
# ---------------------------------------------------------------------------

def test_start_registers_entity_listener_when_entities_configured(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """start() registers async_track_state_change_event when trigger entities are set."""
    mock_coordinator.options["ai_settings"]["briefing_trigger_entities"] = [
        "binary_sensor.tent1_door", "binary_sensor.tent2_door"
    ]
    scheduler = BriefingScheduler(mock_hass, mock_coordinator)

    with (
        patch(
            "custom_components.growspace_manager.briefing_scheduler.async_track_time_interval",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.growspace_manager.briefing_scheduler.async_track_state_change_event"
        ) as mock_track_state,
    ):
        mock_track_state.return_value = MagicMock()
        scheduler.start()

    mock_track_state.assert_called_once()
    _, entity_ids, _ = mock_track_state.call_args.args
    assert "binary_sensor.tent1_door" in entity_ids


def test_start_skips_entity_listener_when_no_entities(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """start() does NOT register entity listener when trigger_entities is empty."""
    mock_coordinator.options["ai_settings"]["briefing_trigger_entities"] = []
    scheduler = BriefingScheduler(mock_hass, mock_coordinator)

    with (
        patch(
            "custom_components.growspace_manager.briefing_scheduler.async_track_time_interval",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.growspace_manager.briefing_scheduler.async_track_state_change_event"
        ) as mock_track_state,
    ):
        scheduler.start()

    mock_track_state.assert_not_called()


@pytest.mark.asyncio
async def test_entity_change_to_on_schedules_debounced_generation(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """State change to 'on' schedules a 5-second debounced generation."""
    scheduler = BriefingScheduler(mock_hass, mock_coordinator)
    scheduler._store = MagicMock()
    scheduler._store.async_save = AsyncMock()

    fake_state = MagicMock()
    fake_state.state = "on"
    event = MagicMock()
    event.data = {"new_state": fake_state}

    debounce_handle = MagicMock()
    mock_hass.loop.call_later = MagicMock(return_value=debounce_handle)

    scheduler._async_on_entity_change(event)

    mock_hass.loop.call_later.assert_called_once()
    delay, _ = mock_hass.loop.call_later.call_args.args
    assert delay == 5.0


@pytest.mark.asyncio
async def test_entity_change_to_off_ignored(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """State changes to states other than 'on' are ignored."""
    scheduler = BriefingScheduler(mock_hass, mock_coordinator)

    fake_state = MagicMock()
    fake_state.state = "off"
    event = MagicMock()
    event.data = {"new_state": fake_state}

    mock_hass.loop.call_later = MagicMock()
    scheduler._async_on_entity_change(event)

    mock_hass.loop.call_later.assert_not_called()


@pytest.mark.asyncio
async def test_rapid_entity_changes_are_debounced(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """Rapid successive state-change events cancel the previous debounce timer."""
    scheduler = BriefingScheduler(mock_hass, mock_coordinator)

    handles = [MagicMock(), MagicMock(), MagicMock()]
    mock_hass.loop.call_later = MagicMock(side_effect=handles)

    def make_on_event():
        fake_state = MagicMock()
        fake_state.state = "on"
        event = MagicMock()
        event.data = {"new_state": fake_state}
        return event

    scheduler._async_on_entity_change(make_on_event())
    scheduler._async_on_entity_change(make_on_event())
    scheduler._async_on_entity_change(make_on_event())

    # First two handles should have been cancelled
    handles[0].cancel.assert_called_once()
    handles[1].cancel.assert_called_once()
    # Third handle is still pending
    handles[2].cancel.assert_not_called()


# ---------------------------------------------------------------------------
# Cycle 4 — Manual refresh (force_refresh=True)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_briefing_force_refresh_bypasses_cache(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """get_briefing(force_refresh=True) ignores cached result and generates fresh."""
    scheduler = BriefingScheduler(mock_hass, mock_coordinator)
    scheduler._store = MagicMock()
    scheduler._store.async_save = AsyncMock()

    stale = {"generated_at": 1.0, "summary_text": "Stale", "ai_available": False, "kpis": [], "recommendations": []}
    fresh = {"generated_at": 2.0, "summary_text": "Fresh", "ai_available": True, "kpis": [], "recommendations": []}

    scheduler._cached_briefing = stale

    with patch.object(scheduler, "_generate_briefing", new_callable=AsyncMock, return_value=fresh):
        result = await scheduler.async_get_briefing(force_refresh=True)

    assert result["summary_text"] == "Fresh"


@pytest.mark.asyncio
async def test_get_briefing_returns_cache_when_available(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """get_briefing() returns cached result without regenerating when cache is warm."""
    scheduler = BriefingScheduler(mock_hass, mock_coordinator)
    scheduler._store = MagicMock()

    cached = {"generated_at": 999.0, "summary_text": "Cached", "ai_available": True, "kpis": [], "recommendations": []}
    scheduler._cached_briefing = cached

    with patch.object(scheduler, "_generate_briefing", new_callable=AsyncMock) as mock_gen:
        result = await scheduler.async_get_briefing(force_refresh=False)

    mock_gen.assert_not_called()
    assert result["summary_text"] == "Cached"


@pytest.mark.asyncio
async def test_get_briefing_loads_from_store_when_no_cache(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """get_briefing() loads persisted briefing from Store when in-memory cache is cold."""
    scheduler = BriefingScheduler(mock_hass, mock_coordinator)
    stored = {"generated_at": 50.0, "summary_text": "Stored", "ai_available": True, "kpis": [], "recommendations": []}
    scheduler._store = MagicMock()
    scheduler._store.async_load = AsyncMock(return_value=stored)

    with patch.object(scheduler, "_generate_briefing", new_callable=AsyncMock) as mock_gen:
        result = await scheduler.async_get_briefing(force_refresh=False)

    mock_gen.assert_not_called()
    assert result["summary_text"] == "Stored"


@pytest.mark.asyncio
async def test_get_briefing_discards_stored_briefing_with_old_kpis_format(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """Stored briefing with kpis as dict (old format) is discarded and regenerated."""
    scheduler = BriefingScheduler(mock_hass, mock_coordinator)
    old_format = {
        "generated_at": 50.0,
        "summary_text": "Old",
        "ai_available": False,
        "kpis": {"open_issues": 0},  # old dict format
        "recommendations": [],
    }
    fresh = {
        "generated_at": 99.0,
        "summary_text": "Fresh",
        "ai_available": False,
        "kpis": [{"label": "Open Issues", "value": 0}],
        "recommendations": [],
    }
    scheduler._store = MagicMock()
    scheduler._store.async_load = AsyncMock(return_value=old_format)
    scheduler._store.async_save = AsyncMock()

    with patch.object(scheduler, "_generate_briefing", new_callable=AsyncMock, return_value=fresh) as mock_gen:
        result = await scheduler.async_get_briefing(force_refresh=False)

    mock_gen.assert_called_once()
    assert isinstance(result["kpis"], list)


# ---------------------------------------------------------------------------
# Cycle 5 — AI unavailable → Bayesian fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_briefing_ai_unavailable_returns_bayesian(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """When AI is disabled, briefing summary uses Bayesian data and ai_available=False."""
    mock_coordinator.options["ai_settings"]["ai_enabled"] = False
    scheduler = BriefingScheduler(mock_hass, mock_coordinator)

    briefing = await scheduler._generate_briefing()

    assert briefing["ai_available"] is False
    assert isinstance(briefing["summary_text"], str)
    assert len(briefing["summary_text"]) > 0


@pytest.mark.asyncio
async def test_generate_briefing_no_assistant_id_returns_bayesian(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """When AI enabled but no assistant_id set, briefing falls back to Bayesian."""
    mock_coordinator.options["ai_settings"]["assistant_id"] = None
    scheduler = BriefingScheduler(mock_hass, mock_coordinator)

    briefing = await scheduler._generate_briefing()

    assert briefing["ai_available"] is False


@pytest.mark.asyncio
async def test_generate_briefing_ai_error_returns_bayesian(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """When AI call raises an exception, briefing falls back to Bayesian."""
    scheduler = BriefingScheduler(mock_hass, mock_coordinator)

    with patch.object(
        scheduler,
        "_generate_ai_content",
        new_callable=AsyncMock,
        side_effect=Exception("AI is down"),
    ):
        briefing = await scheduler._generate_briefing()

    assert briefing["ai_available"] is False
    assert isinstance(briefing["summary_text"], str)


@pytest.mark.asyncio
async def test_generate_briefing_includes_required_fields(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """Generated briefing always contains all required fields."""
    mock_coordinator.options["ai_settings"]["ai_enabled"] = False
    scheduler = BriefingScheduler(mock_hass, mock_coordinator)

    briefing = await scheduler._generate_briefing()

    assert "generated_at" in briefing
    assert "summary_text" in briefing
    assert isinstance(briefing["kpis"], list)
    assert "recommendations" in briefing
    assert "ai_available" in briefing


# ---------------------------------------------------------------------------
# Cycle 6 — Listener cleanup on unload
# ---------------------------------------------------------------------------

def test_async_stop_cancels_all_listeners(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """async_stop() unsubscribes all registered listeners."""
    scheduler = BriefingScheduler(mock_hass, mock_coordinator)

    unsub1 = MagicMock()
    unsub2 = MagicMock()
    scheduler._unsubs = [unsub1, unsub2]

    scheduler.async_stop()

    unsub1.assert_called_once()
    unsub2.assert_called_once()
    assert scheduler._unsubs == []


def test_async_stop_cancels_pending_debounce(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """async_stop() cancels any pending debounce timer."""
    scheduler = BriefingScheduler(mock_hass, mock_coordinator)

    debounce_handle = MagicMock()
    scheduler._debounce_handle = debounce_handle

    scheduler.async_stop()

    debounce_handle.cancel.assert_called_once()
    assert scheduler._debounce_handle is None


def test_async_stop_is_idempotent(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """Calling async_stop() twice does not raise."""
    scheduler = BriefingScheduler(mock_hass, mock_coordinator)
    scheduler.async_stop()
    scheduler.async_stop()  # Should not raise
