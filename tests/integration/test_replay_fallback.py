# ruff: noqa: F811
"""Exercise replay through the real supply queue and pump cycle effects."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.growspace_manager.domain.delivery_attempt import AttemptTrigger
from custom_components.growspace_manager.domain.sensor_validity import Invalidity
from tests.domain.test_replay_fallback import REF, attempt
from tests.integration.test_vwc_irrigation_coordinator import (  # noqa: F401
    await_pump_task,
    mock_growspace,
    mock_hass,
    mock_main_coordinator,
    mock_sleep,
    mock_wait_for_switch_state,
    vwc_coordinator,
)

pytestmark = pytest.mark.usefixtures(
    "pump_reads_back_off", "mock_sleep", "mock_wait_for_switch_state"
)
AT = datetime(2026, 9, 30, 10, tzinfo=UTC)


def seed(coord):
    coord._zone.degraded_fallback = "replay"
    coord._zone.substrate_history.reference_days = [REF]
    coord._deliveries.attempts.append(attempt(11))
    coord.hass.states.get.return_value.state = "unavailable"
    coord._control_watch.watching_since = AT - timedelta(hours=1)
    _ = coord.control_measurement
    coord._control_watch.invalid_since = AT - timedelta(minutes=20)
    coord._control_watch.alerted = True


async def test_hold_alert_then_opt_in_replay_uses_queue_and_records_link(
    vwc_coordinator,
):
    c = vwc_coordinator
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=AT,
    ):
        seed(c)
        c._zone.degraded_fallback = "hold"
        assert "degraded_fallback" in c._fallback_alert_message()
        assert REF["day"] in c._fallback_alert_message()
        c._zone.degraded_fallback = "replay"
        assert "80%" in c._fallback_alert_message()
        assert c.fallback_payload()["shots_left"][0]["planned_s"] == 8
        await c._update_fallback(c.control_measurement)
        assert c._supply_task is None  # future water is not queued early
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=AT + timedelta(hours=1),
    ):
        c._live_plant_count = lambda: 1
        c._run_pump_cycle = AsyncMock()
        await c._update_fallback(c.control_measurement)
        await c._supply_task
        args = c._run_pump_cycle.call_args.args
        assert args[2] == 8
        assert args[3]["fallback"] is True
        assert args[3]["reference_attempt_id"] == "shot-11"
        assert c.fallback_payload()["shots_left"] == []
        c._run_pump_cycle.assert_awaited_once()


async def test_recovery_and_expiry_notice_only_once(vwc_coordinator):
    c = vwc_coordinator
    c._async_notify = AsyncMock()
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=AT,
    ):
        seed(c)
        c._fallback_alert_message()
        c._deliveries.attempts.clear()
        await c._update_fallback(c.control_measurement)
        await c._update_fallback(c.control_measurement)
        c._async_notify.assert_awaited_once()
        assert c.fallback_payload() is None
        c.hass.states.get.return_value.state = "40"
        await c._update_fallback(c.control_measurement)
        assert not c._fallback_expired


@pytest.mark.parametrize(
    "mode", ["grace", "hold", "disabled", "plants", "p3", "cooldown", "ec"]
)
async def test_replay_bounds_at_front(vwc_coordinator, mode):
    c = vwc_coordinator
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=AT,
    ):
        seed(c)
        c._fallback_alert_message()
        if mode == "grace":
            c._control_watch.alerted = False
            await c._update_fallback(c.control_measurement)
            assert c._supply_task is None
            return
        if mode == "hold":
            c._zone.degraded_fallback = "hold"
        if mode == "disabled":
            c._zone.strategy.enabled = False
        if mode == "plants":
            c._live_plant_count = lambda: 0
        else:
            c._live_plant_count = lambda: 1
        if mode == "cooldown":
            c._last_cycle_timestamp = AT.isoformat()
        if mode == "ec":
            c._is_halted_by_runoff_ec = lambda gs: True
        c._run_pump_cycle = AsyncMock()
        c._fallback_started = AT - timedelta(hours=1)
        c._deliveries.attempts[0] = attempt(10)
        data = {"reference_attempt_id": "shot-10"}
        if mode == "p3":
            with patch(
                "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
                return_value=AT.replace(hour=19),
            ):
                await c._async_decide_fallback_claim(data)
        else:
            await c._async_decide_fallback_claim(data)
        c._run_pump_cycle.assert_not_called()


async def test_reference_day_requires_own_probe_whole_lit_window_and_confirmed_water(
    vwc_coordinator,
):
    c = vwc_coordinator
    c._deliveries.attempts.append(attempt(11))
    start = datetime(2026, 9, 29, 8, tzinfo=UTC)
    for minute in range(0, 721, 10):
        with patch(
            "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
            return_value=start + timedelta(minutes=minute),
        ):
            c._watch_reference_day(c.control_measurement)
    assert c._zone.substrate_history.reference_days == [
        {**REF, "attempt_ids": ["shot-11"]}
    ]
    # Closing again is idempotent, and the next day cannot inherit coverage.
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=AT,
    ):
        c._watch_reference_day(c.control_measurement)
    assert not c._zone.substrate_history.reference_window["clean"]
    assert c._zone.substrate_history.reference_days == [
        {**REF, "attempt_ids": ["shot-11"]}
    ]


async def test_confirmed_replay_charges_caps_but_never_trains_or_records_substrate(
    vwc_coordinator,
):
    from freezegun import freeze_time

    c = vwc_coordinator
    with (
        freeze_time(AT),
        patch(
            "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
            return_value=AT,
        ),
    ):
        seed(c)
        c._zone.pump_flow_rate_ml_per_sec = 2
        c._response_watch.confirmed_shot(
            30, AT - timedelta(minutes=30), near_saturation=False
        )
        c._response_watch.failures = 3
        c._response_watch.unresponsive_since = AT - timedelta(minutes=20)
        c._irrigation_cycle_started = AsyncMock()  # should never be called
        c._irrigation_cycle_ended = AsyncMock()
        c._async_spawn_settling_report = AsyncMock()
        c._record_substrate_shot = AsyncMock()
        c._startup_cleared = True
        await c._run_pump_cycle(
            "irrigation",
            "switch.pump",
            8,
            {
                "fallback": True,
                "reference_day": REF["day"],
                "reference_attempt_id": "shot-11",
            },
        )
        row = c._deliveries.attempts[-1]
        assert row.trigger is AttemptTrigger.FALLBACK
        assert row.on_confirmed_at is not None
        assert row.charged_l == 0.016
        assert row.trigger_evidence.reference_attempt_id == "shot-11"
        assert c._response_watch.before is None
        assert c._response_watch.failures == 3
        assert c._response_watch.unresponsive_since is not None
        assert c.cycles_today == 1
        assert c.volume_dispensed_today == 0.016
        assert c.last_cycle_timestamp == AT.isoformat()
        for effect in [
            c._irrigation_cycle_started,
            c._irrigation_cycle_ended,
            c._async_spawn_settling_report,
            c._record_substrate_shot,
        ]:
            effect.assert_not_called()


@pytest.mark.parametrize("gate", ["cap", "dark", "startup"])
async def test_replay_obeys_pump_cycle_gates(vwc_coordinator, gate):
    from freezegun import freeze_time

    c = vwc_coordinator
    with (
        freeze_time(AT),
        patch(
            "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
            return_value=AT,
        ),
    ):
        seed(c)
        c._startup_cleared = gate != "startup"
        if gate == "startup":
            c._startup_began_at = AT
        if gate == "cap":
            c.growspace.irrigation_config.max_cycles_per_day = 1
            from tests.delivery_helpers import charge_today

            charge_today(c, cycles=1)
        if gate == "dark":
            c.growspace.irrigation_config.skip_during_dark = True
            c._is_lights_dark = lambda: True
        await c._run_pump_cycle("irrigation", "switch.pump", 8, {"fallback": True})
        row = c._deliveries.attempts[-1]
        assert row.trigger is AttemptTrigger.FALLBACK
        assert row.on_confirmed_at is None
        assert row.charged_l == 0


@pytest.mark.parametrize(
    "dirty", ["degraded", "witness", "replay", "no_shots", "disabled", "gap"]
)
async def test_dirty_day_cannot_become_a_reference(vwc_coordinator, dirty):
    from dataclasses import replace

    c = vwc_coordinator
    shot = attempt(11)
    if dirty != "no_shots":
        c._deliveries.attempts.append(
            replace(shot, trigger=AttemptTrigger.FALLBACK)
            if dirty == "replay"
            else shot
        )
    start = datetime(2026, 9, 29, 8, tzinfo=UTC)
    for minute in range(0, 721, 10):
        if dirty == "gap" and 120 <= minute <= 160:
            continue
        with patch(
            "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
            return_value=start + timedelta(minutes=minute),
        ):
            measurement = c.control_measurement
            if minute == 120:
                if dirty == "degraded":
                    measurement = replace(
                        measurement, value=None, cause=Invalidity.STALE
                    )
                if dirty == "witness":
                    measurement = replace(measurement, substitute_for="sensor.moisture")
                if dirty == "disabled":
                    c._zone.strategy.enabled = False
            c._watch_reference_day(measurement)
    assert c._zone.substrate_history.reference_days == []


async def test_no_reference_and_new_day_offsets(vwc_coordinator):
    c = vwc_coordinator
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=AT,
    ):
        assert "No compatible" in c._fallback_alert_message()
        seed(c)
        c._fallback_alert_message()
        c._fallback_used.add("shot-11")
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=AT + timedelta(days=1),
    ):
        await c._update_fallback(c.control_measurement)
        assert c.fallback_payload()["shots_left"][0]["at"].startswith("2026-10-01")
        assert c._fallback_used == set()


@pytest.mark.parametrize("value", ["replay", "hold", "bad"])
def test_zone_edit_validates_fallback_setting(value):
    from custom_components.growspace_manager.domain.zone_edit import edited_zones
    from custom_components.growspace_manager.exceptions import ValidationChangeError
    from custom_components.growspace_manager.models import Growspace
    from tests.zones import zoned

    growspace = zoned(Growspace(id="g", name="g"))
    values = {"zone_id": "default", "degraded_fallback": value}
    if value == "bad":
        with pytest.raises(ValidationChangeError, match="hold or replay"):
            edited_zones(growspace, "update", values)
    else:
        changed = edited_zones(growspace, "update", values)
        assert changed.default_zone.degraded_fallback == value
        assert growspace.default_zone.degraded_fallback == "hold"


async def test_new_episode_waits_out_grace_even_when_recovery_notice_has_not_run(
    vwc_coordinator,
):
    c = vwc_coordinator
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=AT,
    ):
        seed(c)
        c._fallback_alert_message()
        assert c.fallback_payload() is not None
        c.hass.states.get.return_value.state = "40"
        assert c.control_measurement.value == 40  # A valid sensor edge, between ticks.
        c.hass.states.get.return_value.state = "unavailable"
        _ = c.control_measurement
        c._control_watch.invalid_since = AT - timedelta(minutes=1)
        assert c.fallback_payload() is None
        await c._update_fallback(c.control_measurement)
        assert c._fallback_reference is None
        assert c._supply_task is None


async def test_alerted_opt_in_and_setting_change_invalidate_window(vwc_coordinator):
    c = vwc_coordinator
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=AT,
    ):
        seed(c)
        await c._update_fallback(c.control_measurement)
        assert c.fallback_payload() is not None
        c._watch_reference_day(c.control_measurement)
        c._zone.soil_moisture_sensor = "sensor.new_control"
        c._watch_reference_day(c.control_measurement)
        assert not c._zone.substrate_history.reference_window["clean"]
        c._zone.strategy.enabled = False
        await c._update_loop(AT)
        assert c._fallback_reference is None


async def test_late_claim_with_no_matching_reference_shot_is_dropped(vwc_coordinator):
    c = vwc_coordinator
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=AT,
    ):
        seed(c)
        c._fallback_alert_message()
        await c._async_decide_fallback_claim({"reference_attempt_id": "gone"})
        assert c._running_tasks == {}


@pytest.mark.parametrize(
    "gap_seconds,delay_minutes,clean",
    [(30, 0, False), (30, 15, True), (1200, 15, False)],
)
async def test_restart_marks_only_the_unwatched_lit_gap(
    vwc_coordinator, gap_seconds, delay_minutes, clean
):
    c = vwc_coordinator
    c._config().sensor_alert_delay_minutes = delay_minutes
    c.growspace.irrigation_config.sensor_alert_delay_minutes = delay_minutes
    window = {
        "lights_on": AT.replace(hour=8).isoformat(),
        "last_seen": (AT - timedelta(seconds=gap_seconds)).isoformat(),
        "clean": True,
    }
    c._zone.substrate_history.reference_window = window
    with (
        patch(
            "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
            return_value=AT,
        ),
        patch(
            "custom_components.growspace_manager.irrigation_coordinator.IrrigationCoordinator.async_setup",
            new_callable=AsyncMock,
        ),
    ):
        await c.async_setup()
    assert window["clean"] is clean


def test_scheduled_controller_does_not_offer_a_steering_replay(vwc_coordinator):
    from custom_components.growspace_manager.irrigation_coordinator import (
        BaseIrrigationCoordinator,
    )

    assert BaseIrrigationCoordinator._fallback_alert_message(vwc_coordinator) == ""


@pytest.mark.parametrize(
    "state,reported",
    [
        ("inhibited", "fallback"),
        ("fault", "fault"),
        ("emergency_stop", "emergency_stop"),
    ],
)
async def test_zone_wire_reports_fallback_without_hiding_latched_safety_state(
    hass, vwc_coordinator, state, reported
):
    from unittest.mock import MagicMock

    from custom_components.growspace_manager.domain.irrigation_safety import (
        ControllerSnapshot,
        ControllerState,
    )
    from custom_components.growspace_manager.view_model_builder import ViewModelBuilder
    from tests.integration.test_growspace_view_model_coverage import (
        _make_mock_coordinator,
    )

    c = vwc_coordinator
    coordinator = _make_mock_coordinator(hass, c.growspace, {})
    coordinator.services.growspaces.get_irrigation_coordinator.return_value = c
    c.zone_snapshot = MagicMock(return_value=ControllerSnapshot(ControllerState(state)))
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=AT,
    ):
        seed(c)
        c._fallback_alert_message()
        wire = ViewModelBuilder(coordinator).build_serialized_growspace("gs1")
        zone = wire["irrigation"]["zones"][0]
        assert zone["state"] == reported
        assert zone["degraded_fallback"] == "replay"
        assert zone["reference_day"] == REF["day"]
        assert zone["fallback"]["cause"] == "sensor_unavailable"
        assert zone["replay_shots_left"][0]["reference_attempt_id"] == "shot-11"
