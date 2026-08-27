"""Tests for BriefingScheduler — AI Briefing generation with interval, entity, and manual triggers."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.briefing_scheduler import BriefingScheduler
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    WaterUsageData,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

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
    hass.async_create_task = MagicMock(
        side_effect=lambda coro: asyncio.ensure_future(coro)
    )
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
        scheduler,
        "_generate_briefing",
        new_callable=AsyncMock,
        return_value={
            "generated_at": 1234.0,
            "summary_text": "All good",
            "ai_available": True,
            "kpis": [],
            "recommendations": [],
        },
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
        "binary_sensor.tent1_door",
        "binary_sensor.tent2_door",
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

    stale = {
        "generated_at": 1.0,
        "summary_text": "Stale",
        "ai_available": False,
        "kpis": [],
        "recommendations": [],
    }
    fresh = {
        "generated_at": 2.0,
        "summary_text": "Fresh",
        "ai_available": True,
        "kpis": [],
        "recommendations": [],
    }

    scheduler._cached_briefing = stale

    with patch.object(
        scheduler, "_generate_briefing", new_callable=AsyncMock, return_value=fresh
    ):
        result = await scheduler.async_get_briefing(force_refresh=True)

    assert result["summary_text"] == "Fresh"


@pytest.mark.asyncio
async def test_get_briefing_returns_cache_when_available(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """get_briefing() returns cached result without regenerating when cache is warm."""
    scheduler = BriefingScheduler(mock_hass, mock_coordinator)
    scheduler._store = MagicMock()

    cached = {
        "generated_at": 999.0,
        "summary_text": "Cached",
        "ai_available": True,
        "kpis": [],
        "recommendations": [],
    }
    scheduler._cached_briefing = cached

    with patch.object(
        scheduler, "_generate_briefing", new_callable=AsyncMock
    ) as mock_gen:
        result = await scheduler.async_get_briefing(force_refresh=False)

    mock_gen.assert_not_called()
    assert result["summary_text"] == "Cached"


@pytest.mark.asyncio
async def test_get_briefing_loads_from_store_when_no_cache(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """get_briefing() loads persisted briefing from Store when in-memory cache is cold."""
    scheduler = BriefingScheduler(mock_hass, mock_coordinator)
    stored = {
        "generated_at": 50.0,
        "summary_text": "Stored",
        "ai_available": True,
        "kpis": [],
        "recommendations": [],
    }
    scheduler._store = MagicMock()
    scheduler._store.async_load = AsyncMock(return_value=stored)

    with patch.object(
        scheduler, "_generate_briefing", new_callable=AsyncMock
    ) as mock_gen:
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

    with patch.object(
        scheduler, "_generate_briefing", new_callable=AsyncMock, return_value=fresh
    ) as mock_gen:
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


# ---------------------------------------------------------------------------
# Cycle 7 — Bayesian summary content
# ---------------------------------------------------------------------------


def _make_sensor_state(active: bool, reasons: list[str]) -> MagicMock:
    state = MagicMock()
    state.state = "on" if active else "off"
    state.attributes = {"reasons": reasons}
    return state


def _setup_bayesian_states(
    mock_hass: MagicMock,
    growspace_id: str,
    *,
    stress: tuple[bool, list[str]] = (False, []),
    mold_risk: tuple[bool, list[str]] = (False, []),
    optimal: tuple[bool, list[str]] = (True, []),
) -> None:
    from custom_components.growspace_manager.const import DOMAIN

    states = {
        f"binary_sensor.{DOMAIN}_{growspace_id}_stress": _make_sensor_state(*stress),
        f"binary_sensor.{DOMAIN}_{growspace_id}_mold_risk": _make_sensor_state(
            *mold_risk
        ),
        f"binary_sensor.{DOMAIN}_{growspace_id}_optimal": _make_sensor_state(*optimal),
    }
    mock_hass.states = MagicMock()
    mock_hass.states.get.side_effect = lambda eid: states.get(eid)


def test_bayesian_summary_not_optimal_includes_reasons(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """When optimal sensor is off with reasons, summary text includes those reasons."""
    growspace = MagicMock()
    growspace.id = "tent1"
    growspace.name = "Tent 1"
    mock_coordinator.growspaces = {"tent1": growspace}

    _setup_bayesian_states(
        mock_hass,
        "tent1",
        optimal=(False, ["VPD out of range (1.2)"]),
    )

    scheduler = BriefingScheduler(mock_hass, mock_coordinator)
    summary = scheduler._generate_bayesian_summary()

    assert "VPD out of range (1.2)" in summary
    assert "conditions normal" not in summary


def test_bayesian_summary_optimal_active_says_optimal(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """When optimal sensor is on, summary text says 'conditions optimal'."""
    growspace = MagicMock()
    growspace.id = "tent1"
    growspace.name = "Tent 1"
    mock_coordinator.growspaces = {"tent1": growspace}

    _setup_bayesian_states(mock_hass, "tent1", optimal=(True, []))

    scheduler = BriefingScheduler(mock_hass, mock_coordinator)
    summary = scheduler._generate_bayesian_summary()

    assert "conditions optimal" in summary


def test_bayesian_summary_stress_active_detected(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """When stress sensor is on, summary mentions 'plant stress'."""
    growspace = MagicMock()
    growspace.id = "tent1"
    growspace.name = "Tent 1"
    mock_coordinator.growspaces = {"tent1": growspace}

    _setup_bayesian_states(
        mock_hass,
        "tent1",
        stress=(True, ["leaf curl", "tip burn"]),
        optimal=(False, []),
    )

    scheduler = BriefingScheduler(mock_hass, mock_coordinator)
    summary = scheduler._generate_bayesian_summary()

    assert "plant stress" in summary
    assert "leaf curl" in summary
    assert "tip burn" in summary


def test_bayesian_summary_mold_risk_active_detected(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """When mold_risk sensor is on, summary mentions 'mold risk'."""
    growspace = MagicMock()
    growspace.id = "tent1"
    growspace.name = "Tent 1"
    mock_coordinator.growspaces = {"tent1": growspace}

    _setup_bayesian_states(
        mock_hass,
        "tent1",
        mold_risk=(True, []),
        optimal=(False, []),
    )

    scheduler = BriefingScheduler(mock_hass, mock_coordinator)
    summary = scheduler._generate_bayesian_summary()

    assert "mold risk" in summary


# ---------------------------------------------------------------------------
# Cycle 8 — _read_bayesian_states with real sensor state
# ---------------------------------------------------------------------------


def test_read_bayesian_states_returns_active_true_when_sensor_on(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """_read_bayesian_states returns active=True and reasons when sensor state is 'on'."""
    from custom_components.growspace_manager.const import DOMAIN

    state = MagicMock()
    state.state = "on"
    state.attributes = {"reasons": ["high humidity"]}

    mock_hass.states = MagicMock()
    mock_hass.states.get.side_effect = lambda eid: (
        state if eid == f"binary_sensor.{DOMAIN}_tent1_mold_risk" else None
    )

    scheduler = BriefingScheduler(mock_hass, mock_coordinator)
    result = scheduler._read_bayesian_states("tent1")

    assert result["mold_risk"]["active"] is True
    assert result["mold_risk"]["reasons"] == ["high humidity"]


# ---------------------------------------------------------------------------
# Cycle 9 — _collect_kpis with growspace VPD + water data
# ---------------------------------------------------------------------------


def test_collect_kpis_includes_avg_vpd_from_growspace_env_state(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """_collect_kpis reads VPD via read_environment_vpd and adds Avg VPD KPI."""
    growspace = Growspace(id="tent1", name="Tent 1")
    mock_coordinator.growspaces = {"tent1": growspace}
    mock_coordinator.alert_monitor.get_alerts.return_value = []
    mock_coordinator.services.growspaces.get_all_trackers_for_growspace.return_value = {}

    scheduler = BriefingScheduler(mock_hass, mock_coordinator)

    with patch(
        "custom_components.growspace_manager.briefing_scheduler.read_environment_vpd",
        return_value=1.3,
    ):
        kpis = scheduler._collect_kpis()

    labels = {k["label"] for k in kpis}
    assert "Avg VPD" in labels
    vpd_kpi = next(k for k in kpis if k["label"] == "Avg VPD")
    assert vpd_kpi["value"] == 1.3


def test_collect_kpis_includes_water_use_when_nonzero(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """_collect_kpis aggregates today's water across sources (ADR-0017).

    Non-tank growspace: WaterUsageData.daily_readings holds today's manual +
    pump-estimate liters, summed into the Water Use KPI.
    """
    today = dt_util.now().date().isoformat()
    growspace = Growspace(
        id="tent1",
        name="Tent 1",
        environment_config=EnvironmentConfig(),
        water_usage=WaterUsageData(
            total_liters=100.0,
            cycle_start_date="2026-06-01",
            daily_readings=[
                {"date": today, "liters": 40.0, "source": "manual"},
                {"date": today, "liters": 2.5, "source": "pump_estimate"},
            ],
        ),
    )
    mock_coordinator.growspaces = {"tent1": growspace}
    mock_coordinator.alert_monitor.get_alerts.return_value = []
    mock_coordinator.services.growspaces.get_all_trackers_for_growspace.return_value = {}

    scheduler = BriefingScheduler(mock_hass, mock_coordinator)

    with patch(
        "custom_components.growspace_manager.briefing_scheduler.read_environment_vpd",
        return_value=None,
    ):
        kpis = scheduler._collect_kpis()

    labels = {k["label"] for k in kpis}
    assert "Water Use" in labels
    water_kpi = next(k for k in kpis if k["label"] == "Water Use")
    assert water_kpi["value"] == 42.5


# ---------------------------------------------------------------------------
# Cycle 10 — _generate_briefing AI success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_briefing_ai_success_returns_ai_available_true(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """When AI call succeeds, briefing has ai_available=True and returned content."""
    scheduler = BriefingScheduler(mock_hass, mock_coordinator)
    mock_coordinator.alert_monitor.get_alerts.return_value = []

    with patch.object(
        scheduler,
        "_generate_ai_content",
        new_callable=AsyncMock,
        return_value=(
            "Plants are thriving.",
            [
                {
                    "title": "Water now",
                    "description": "Plants need water.",
                    "impact": "high",
                    "suggested_action": {},
                }
            ],
        ),
    ):
        briefing = await scheduler._generate_briefing()

    assert briefing["ai_available"] is True
    assert briefing["summary_text"] == "Plants are thriving."
    assert len(briefing["recommendations"]) == 1


# ---------------------------------------------------------------------------
# Cycle 11 — _generate_ai_content response parsing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_ai_content_parses_summary_and_recommendations(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """_generate_ai_content parses SUMMARY: and RECOMMENDATIONS: from AI speech."""
    import json

    recs = [
        {
            "title": "Lower VPD",
            "description": "VPD is above target range.",
            "impact": "high",
            "suggested_action": {},
        }
    ]
    speech_text = f"SUMMARY: All healthy. RECOMMENDATIONS: {json.dumps(recs)}"

    mock_result = MagicMock()
    mock_result.response.speech = {"plain": {"speech": speech_text}}

    mock_coordinator.growspaces = {}

    scheduler = BriefingScheduler(mock_hass, mock_coordinator)

    with patch(
        "homeassistant.components.conversation.async_converse",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        summary, recommendations = await scheduler._generate_ai_content(
            "conversation.claude", []
        )

    assert "All healthy" in summary
    assert len(recommendations) == 1
    assert recommendations[0]["title"] == "Lower VPD"


@pytest.mark.asyncio
async def test_generate_ai_content_invalid_recommendations_json_returns_empty(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """_generate_ai_content returns empty recommendations list when JSON is malformed."""
    speech_text = "SUMMARY: OK. RECOMMENDATIONS: not-valid-json"

    mock_result = MagicMock()
    mock_result.response.speech = {"plain": {"speech": speech_text}}

    mock_coordinator.growspaces = {}

    scheduler = BriefingScheduler(mock_hass, mock_coordinator)

    with patch(
        "homeassistant.components.conversation.async_converse",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        summary, recommendations = await scheduler._generate_ai_content(
            "conversation.claude", []
        )

    assert recommendations == []
    assert "OK" in summary


@pytest.mark.asyncio
async def test_generate_ai_content_empty_speech_returns_bayesian_fallback(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """_generate_ai_content falls back to Bayesian summary when speech is empty."""
    mock_result = MagicMock()
    mock_result.response.speech = {"plain": {"speech": ""}}

    mock_coordinator.growspaces = {}

    scheduler = BriefingScheduler(mock_hass, mock_coordinator)

    with patch(
        "homeassistant.components.conversation.async_converse",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        summary, recommendations = await scheduler._generate_ai_content(
            "conversation.claude", []
        )

    assert recommendations == []
    assert isinstance(summary, str)
    assert len(summary) > 0


@pytest.mark.asyncio
async def test_generate_ai_content_summary_only_strips_prefix(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """_generate_ai_content strips SUMMARY: prefix when no RECOMMENDATIONS: section."""
    speech_text = "SUMMARY: Plants look great today."

    mock_result = MagicMock()
    mock_result.response.speech = {"plain": {"speech": speech_text}}

    mock_coordinator.growspaces = {}

    scheduler = BriefingScheduler(mock_hass, mock_coordinator)

    with patch(
        "homeassistant.components.conversation.async_converse",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        summary, recommendations = await scheduler._generate_ai_content(
            "conversation.claude", []
        )

    assert summary == "Plants look great today."
    assert recommendations == []
