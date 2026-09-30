"""Crop steering decides only on a moisture reading it can trust (#789).

Real Home Assistant state, so ``last_reported`` and ``last_changed`` move the
way the product sees them: a report that repeats the value advances the first
and leaves the second alone.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from freezegun.api import FrozenDateTimeFactory
import pytest

from custom_components.growspace_manager.const import NotificationTier
from custom_components.growspace_manager.domain.sensor_validity import SensorAlert
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    IrrigationConfig,
    IrrigationStrategy,
)
from custom_components.growspace_manager.reliability_store import ReliabilityStore
from custom_components.growspace_manager.vwc_irrigation_coordinator import (
    VWCIrrigationCoordinator,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.util import dt as dt_util
from tests.common import async_mock_service
from tests.zones import zoned

VWC = "sensor.vwc"
# Inside P1 for the strategy below: lights on 08:00, P0 over at 09:00.
STEERING_NOW = datetime(2023, 1, 1, 9, 30, tzinfo=dt_util.UTC)


def _growspace(**config: Any) -> Growspace:
    return zoned(
        Growspace(
            id="tent",
            name="Tent",
            environment_config=EnvironmentConfig(),
            irrigation_config=IrrigationConfig(
                irrigation_pump_entity="switch.pump", **config
            ),
        ),
        soil_moisture_sensor=VWC,
        strategy=IrrigationStrategy(
            enabled=True,
            lights_on_time="08:00:00",
            p0_duration_minutes=60,
            target_vwc_percent=50.0,
            p1_shot_duration_seconds=10,
            p1_shot_interval_minutes=15,
        ),
    )


@pytest.fixture
def notify() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def services(hass: HomeAssistant) -> dict[str, list[ServiceCall]]:
    return {
        service: async_mock_service(hass, "persistent_notification", service)
        for service in ("create", "dismiss")
    }


def _coordinator(
    hass: HomeAssistant, growspace: Growspace, notify: AsyncMock | None = None
) -> VWCIrrigationCoordinator:
    runtime = MagicMock()
    runtime.reliability = ReliabilityStore(hass, "control-sensor-validity")
    runtime.irrigation_safety = None
    runtime.growspaces = {growspace.id: growspace}
    runtime.services.notifications.manager.async_send_notification = (
        notify or AsyncMock()
    )
    entry = MagicMock(runtime_data=runtime)
    entry.async_create_background_task.side_effect = lambda hass_, target, name: (
        hass.async_create_task(target)
    )
    return VWCIrrigationCoordinator(hass, entry, growspace.id, runtime)


async def _tick(coord: VWCIrrigationCoordinator) -> MagicMock:
    """Run one steering tick; return the shot trigger, which never fires water."""
    with (
        patch(
            "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
            return_value=STEERING_NOW,
        ),
        patch.object(coord, "_fire_shot") as fire,
    ):
        await coord._update_loop(STEERING_NOW)
        if coord._supply_task is not None:
            await coord._supply_task
    return fire


def _reasons(coord: VWCIrrigationCoordinator) -> list[str]:
    return [reason.code for reason in coord.controller_snapshot().reasons]


async def test_a_fresh_dry_reading_fires_a_shot(hass: HomeAssistant) -> None:
    """The control case every refusal below is measured against."""
    coord = _coordinator(hass, _growspace())
    hass.states.async_set(VWC, "30")

    (await _tick(coord)).assert_called_once()
    assert _reasons(coord) == []


async def test_a_pinned_sensor_withholds_shots_and_says_why(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A probe frozen at a dry value stops being believed past its window."""
    coord = _coordinator(hass, _growspace())
    hass.states.async_set(VWC, "30")
    assert coord._read_moisture(VWC).valid

    freezer.tick(timedelta(minutes=31))

    (await _tick(coord)).assert_not_called()
    snapshot = coord.controller_snapshot()
    assert snapshot.state.value == "inhibited"
    assert [r.code for r in snapshot.reasons] == ["sensor_stale"]
    assert VWC in snapshot.reasons[0].detail
    assert coord.shot_composition_payload()["infiltration"] == "unknown"


@pytest.mark.parametrize(
    ("raw", "zero_is_implausible", "reason"),
    [
        ("0", True, "sensor_implausible"),
        ("-5", False, "sensor_implausible"),
        ("150", False, "sensor_implausible"),
        ("nan", False, "sensor_implausible"),
        ("unavailable", False, "sensor_unavailable"),
    ],
)
async def test_an_untrustworthy_reading_is_never_read_as_dry(
    hass: HomeAssistant, raw: str, zero_is_implausible: bool, reason: str
) -> None:
    coord = _coordinator(
        hass, _growspace(moisture_zero_is_implausible=zero_is_implausible)
    )
    hass.states.async_set(VWC, raw)

    (await _tick(coord)).assert_not_called()
    assert _reasons(coord) == [reason]
    assert coord._moisture_value() is None


async def test_zero_is_a_reading_unless_configured_otherwise(
    hass: HomeAssistant,
) -> None:
    coord = _coordinator(hass, _growspace())
    hass.states.async_set(VWC, "0")

    (await _tick(coord)).assert_called_once()


async def test_a_steady_sensor_that_keeps_reporting_is_not_stale(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """``last_reported`` advances on a repeated value; ``last_updated`` does not."""
    coord = _coordinator(hass, _growspace())
    hass.states.async_set(VWC, "30")
    first_update = hass.states.get(VWC).last_updated

    for _ in range(30):
        freezer.tick(timedelta(minutes=2))
        hass.states.async_set(VWC, "30")
        assert coord._read_moisture(VWC).valid

    state = hass.states.get(VWC)
    assert state.last_updated == first_update
    assert state.last_reported > first_update + timedelta(minutes=30)
    (await _tick(coord)).assert_called_once()

    # Silent now: three of its learned two-minute intervals later, it is stale,
    # long before the 30-minute cap.
    freezer.tick(timedelta(minutes=7))
    (await _tick(coord)).assert_not_called()
    assert _reasons(coord) == ["sensor_stale"]


async def test_staleness_can_be_switched_off(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    coord = _coordinator(hass, _growspace(sensor_stale_after_minutes=0))
    hass.states.async_set(VWC, "30")
    freezer.tick(timedelta(days=2))

    (await _tick(coord)).assert_called_once()


async def test_a_recovered_sensor_releases_the_hold(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    coord = _coordinator(hass, _growspace())
    hass.states.async_set(VWC, "150")
    (await _tick(coord)).assert_not_called()

    freezer.tick(timedelta(minutes=1))
    hass.states.async_set(VWC, "30")

    (await _tick(coord)).assert_called_once()
    assert _reasons(coord) == []


def _pushes(notify: AsyncMock) -> list[str]:
    assert all(
        call.kwargs["tier"] == NotificationTier.SENSOR_INVALID
        for call in notify.call_args_list
    )
    return [call.args[1] for call in notify.call_args_list]


async def test_one_alert_per_invalid_episode(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    notify: AsyncMock,
    services: dict[str, list[ServiceCall]],
) -> None:
    """Shots stop at once; the alert waits out the delay, once; recovery clears it."""
    coord = _coordinator(hass, _growspace(), notify)
    hass.states.async_set(VWC, "40")
    with patch.object(
        coord, "_async_record_controller_state", new=AsyncMock()
    ) as recorded:
        await coord._async_sensor_tick()
        assert recorded.await_count == 0

        hass.states.async_set(VWC, "unavailable")
        for _ in range(40):
            freezer.tick(timedelta(minutes=1))
            await coord._async_sensor_tick()
        # One ledger write for the edge, not one a minute.
        assert recorded.await_count == 1

        assert _pushes(notify) == ["⚠️ Moisture Sensor Invalid: Tent"]
        [created] = [dict(call.data) for call in services["create"]]
        assert created["notification_id"] == "growspace_sensor_invalid_tent_sensor.vwc"
        assert "it is unavailable" in created["message"]

        hass.states.async_set(VWC, "42")
        await coord._async_sensor_tick()
        await coord._async_sensor_tick()
        assert recorded.await_count == 2

    assert _pushes(notify)[1:] == ["✅ Moisture Sensor Back: Tent"]
    assert "(42)" in notify.call_args_list[1].args[2]
    assert [dict(call.data) for call in services["dismiss"]] == [
        {"notification_id": "growspace_sensor_invalid_tent_sensor.vwc"}
    ]


async def test_a_short_dropout_raises_no_alert(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    notify: AsyncMock,
    services: dict[str, list[ServiceCall]],
) -> None:
    coord = _coordinator(hass, _growspace(sensor_alert_delay_minutes=15), notify)
    hass.states.async_set(VWC, "150")
    for _ in range(14):
        freezer.tick(timedelta(minutes=1))
        await coord._async_sensor_tick()
    hass.states.async_set(VWC, "40")
    await coord._async_sensor_tick()

    notify.assert_not_called()
    assert services["create"] == services["dismiss"] == []


async def test_turning_steering_off_clears_an_alert(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    notify: AsyncMock,
    services: dict[str, list[ServiceCall]],
) -> None:
    """A sensor that no longer decides anything withholds nothing."""
    growspace = _growspace(sensor_alert_delay_minutes=0)
    coord = _coordinator(hass, growspace, notify)
    hass.states.async_set(VWC, "unavailable")
    await coord._async_sensor_tick()
    assert coord._control_watch.alerted

    growspace.default_zone.strategy.enabled = False
    await coord._async_sensor_tick()

    assert not coord._control_watch.alerted
    assert len(services["dismiss"]) == 1
    assert coord._moisture_invalidity is None


async def test_the_watch_alert_is_the_domain_one(hass: HomeAssistant) -> None:
    """The shell advances the same episode the domain tests pin."""
    coord = _coordinator(hass, _growspace(sensor_alert_delay_minutes=0))
    hass.states.async_set(VWC, "unavailable")
    coord._read_moisture(VWC)
    assert coord._sensor_watches[VWC].alert(dt_util.utcnow(), timedelta(0)) is (
        SensorAlert.INVALID
    )


@pytest.mark.parametrize(
    ("states", "average"),
    [
        # A µS/cm probe is converted, not read as 2500 mS/cm.
        ({"sensor.ec_a": ("2500", "µS/cm"), "sensor.ec_b": ("3.5", "mS/cm")}, 3.0),
        # An implausible or unavailable probe is left out, not averaged in.
        ({"sensor.ec_a": ("45", "mS/cm"), "sensor.ec_b": ("3.5", "mS/cm")}, 3.5),
        ({"sensor.ec_a": ("unavailable", None), "sensor.ec_b": ("2", None)}, 2.0),
        ({"sensor.ec_a": ("-1", None), "sensor.ec_b": ("nan", None)}, None),
    ],
)
async def test_pore_ec_is_validated_per_sensor(
    hass: HomeAssistant,
    states: dict[str, tuple[str, str | None]],
    average: float | None,
) -> None:
    growspace = _growspace()
    growspace.default_zone.pore_ec_sensors = list(states)
    coord = _coordinator(hass, growspace)
    for entity_id, (value, unit) in states.items():
        hass.states.async_set(
            entity_id, value, {"unit_of_measurement": unit} if unit else {}
        )

    assert coord._average_pore_ec(growspace) == average


async def test_a_stale_pore_ec_sensor_is_left_out(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    growspace = _growspace()
    growspace.default_zone.pore_ec_sensors = ["sensor.ec_a"]
    coord = _coordinator(hass, growspace)
    hass.states.async_set("sensor.ec_a", "2.5")
    assert coord._average_pore_ec(growspace) == 2.5

    freezer.tick(timedelta(minutes=31))
    assert coord._average_pore_ec(growspace) is None


async def _flat_confirmed_shot(coord, hass, freezer, *, manual=False, before=30):
    """Exercise the pump-completion hook and two distinct post-shot reports."""
    _ = coord.control_measurement
    coord._irrigation_cycle_started(manual=manual)
    coord._irrigation_cycle_ended(
        end_dt=dt_util.utcnow(), moisture_before=before, manual=manual
    )
    for _ in range(2):
        freezer.tick(timedelta(minutes=1))
        hass.states.async_set(VWC, str(before))
        await _tick(coord)


async def test_flat_control_probe_degrades_alerts_and_recovers(
    hass, freezer, notify, services
):
    """Repeated reports are fresh but cannot justify a fourth steering shot."""
    growspace = _growspace(sensor_alert_delay_minutes=3)
    growspace.default_zone.moisture_witness_sensors = ["sensor.witness"]
    hass.states.async_set("sensor.witness", "unavailable")  # No healthy substitute.
    hass.states.async_set(VWC, "30")
    coord = _coordinator(hass, growspace, notify)
    tracker = (
        coord._main_coordinator.services.growspaces.get_substrate_tracker.return_value
    )
    for count in range(1, 4):
        await _flat_confirmed_shot(coord, hass, freezer)
        assert coord._response_watch.failures == count
    assert coord.current_vwc is None
    assert _reasons(coord) == ["probe_unresponsive"]
    (await _tick(coord)).assert_not_called()
    assert coord._pending_observation is None
    tracker.record_gap.assert_called()
    tracker.record_reading.reset_mock()
    await _tick(coord)
    tracker.record_reading.assert_not_called()
    # A Manual Run still reaches the shared safety gates.
    assert coord._operator_hold(manual=True) is None
    await coord._async_sensor_tick()
    assert not services["create"]
    freezer.tick(timedelta(minutes=3))
    hass.states.async_set(VWC, "30")
    await coord._async_sensor_tick()
    assert len(services["create"]) == 1
    assert VWC in services["create"][0].data["message"]
    assert "switch.pump" in services["create"][0].data["message"]
    await coord._async_sensor_tick()
    assert len(services["create"]) == 1
    # A late rise attributable to the last confirmed shot releases the hold.
    hass.states.async_set(VWC, "40")
    await _tick(coord)
    assert coord.current_vwc == 40
    assert _reasons(coord) == []
    await coord._async_sensor_tick()
    assert len(services["dismiss"]) == 1
    assert len(_pushes(notify)) == 2


async def test_manual_and_saturated_shots_never_count(hass, freezer):
    coord = _coordinator(hass, _growspace())
    hass.states.async_set(VWC, "30")
    for _ in range(4):
        await _flat_confirmed_shot(coord, hass, freezer, manual=True)
        await _flat_confirmed_shot(coord, hass, freezer, before=50)
    assert coord._response_watch.failures == 0
    assert coord._control_sensor_inhibit() is None


async def test_probe_change_replaces_response_evidence(hass, freezer):
    coord = _coordinator(hass, _growspace())
    hass.states.async_set(VWC, "30")
    await _flat_confirmed_shot(coord, hass, freezer)
    coord.growspace.default_zone.soil_moisture_sensor = "sensor.replacement"
    hass.states.async_set("sensor.replacement", "45")
    assert coord.control_measurement.value == 45
    assert coord._response_watch.failures == 0


@pytest.mark.parametrize("removed", [False, True])
async def test_missing_post_shot_evidence_cannot_train_or_count(hass, removed):
    coord = _coordinator(hass, _growspace())
    hass.states.async_set(VWC, "30")
    coord._irrigation_cycle_ended(
        end_dt=dt_util.utcnow(), moisture_before=30, manual=False
    )
    if removed:
        coord.growspace.default_zone.soil_moisture_sensor = None
    else:
        hass.states.async_set(VWC, "unavailable")
    coord._sample_control_response()
    coord._resolve_pending_observation()
    assert coord._pending_observation is None
    assert coord._response_watch.failures == 0
    assert coord.current_vwc is None


async def test_witness_steers_with_provenance_but_never_trains_or_records_dryback(
    hass, freezer, notify, services
):
    growspace = _growspace()
    growspace.default_zone.moisture_witness_sensors = ["sensor.witness"]
    coord = _coordinator(hass, growspace, notify)
    tracker = (
        coord._main_coordinator.services.growspaces.get_substrate_tracker.return_value
    )
    hass.states.async_set(VWC, "30")
    hass.states.async_set("sensor.witness", "24")
    assert coord.current_vwc == 30  # Learns +6 without averaging.
    coord._irrigation_cycle_ended(
        end_dt=dt_util.utcnow(), moisture_before=30, manual=False
    )
    hass.states.async_set(VWC, "unavailable")
    with patch.object(coord._composer, "observe") as observe:
        (await _tick(coord)).assert_called_once()
        coord._resolve_pending_observation()
        observe.assert_not_called()
    assert coord.current_vwc == 30
    assert _reasons(coord) == []
    measurement = coord.control_measurement
    assert measurement.substitute_for == VWC
    assert measurement.probe["entity_id"] == "sensor.witness"
    assert measurement.observed_at == hass.states.get("sensor.witness").last_reported
    assert coord.witness_substitution == {
        "entity_id": "sensor.witness",
        "offset": 6.0,
        "since": dt_util.utcnow().isoformat(),
    }
    tracker.record_gap.assert_called()
    tracker.record_reading.assert_not_called()
    tracker.record_shot.assert_not_called()
    coord._record_substrate_shot("P2")
    tracker.record_shot.assert_not_called()
    coord._irrigation_cycle_started(manual=False)
    coord._irrigation_cycle_ended(
        end_dt=dt_util.utcnow(), moisture_before=30, manual=False
    )
    assert coord._pending_observation is None
    await coord._async_sensor_tick()
    await coord._async_sensor_tick()
    assert len(notify.call_args_list) == 1
    assert "steering on witness sensor.witness" in notify.call_args_list[0].args[2]
    assert not services["create"]
    hass.states.async_set(VWC, "33")
    assert coord.control_measurement.substitute_for is None
    assert coord.current_vwc == 33
    assert coord.witness_substitution is None
    await coord._async_sensor_tick()
    assert len(notify.call_args_list) == 2
    tracker.record_reading.reset_mock()
    await _tick(coord)
    tracker.record_reading.assert_called_with(33.0, STEERING_NOW.isoformat(), lit=True)


async def test_witness_loss_pages_only_once_for_the_last_healthy_peer(
    hass, notify, services
):
    growspace = _growspace()
    growspace.default_zone.moisture_witness_sensors = ["sensor.first", "sensor.second"]
    coord = _coordinator(hass, growspace, notify)
    hass.states.async_set(VWC, "30")
    for entity in growspace.default_zone.moisture_witness_sensors:
        hass.states.async_set(entity, "24")
    await coord._async_sensor_tick()
    hass.states.async_set("sensor.first", "unavailable")
    await coord._async_sensor_tick()
    assert not notify.call_args_list
    assert coord.current_vwc == 30
    hass.states.async_set("sensor.second", "unavailable")
    await coord._async_sensor_tick()
    await coord._async_sensor_tick()
    assert len(notify.call_args_list) == 1
    assert notify.call_args_list[0].kwargs["tier"] == NotificationTier.INFO
    assert "last healthy witness" in notify.call_args_list[0].args[2]
    assert not services["create"]
    assert _reasons(coord) == []
    # Regaining a safety net permits one notice for its next loss.
    hass.states.async_set("sensor.second", "24")
    await coord._async_sensor_tick()
    hass.states.async_set("sensor.second", "unavailable")
    await coord._async_sensor_tick()
    assert len(notify.call_args_list) == 2


async def test_witness_without_valid_pair_history_cannot_hide_control_failure(hass):
    growspace = _growspace()
    growspace.default_zone.moisture_witness_sensors = ["sensor.witness"]
    coord = _coordinator(hass, growspace)
    hass.states.async_set(VWC, "unavailable")
    hass.states.async_set("sensor.witness", "30")
    assert coord.current_vwc is None
    assert coord.witness_substitution is None
    (await _tick(coord)).assert_not_called()
    assert _reasons(coord) == ["sensor_unavailable"]
    hass.states.async_set(VWC, "40")
    assert coord.current_vwc == 40
    # Changing the elected probe discards the old baseline's offset.
    growspace.default_zone.soil_moisture_sensor = "sensor.new_control"
    assert coord.current_vwc is None
    assert coord.witness_substitution is None


async def test_substituted_shot_can_recover_unresponsive_control_without_training(
    hass, freezer
):
    growspace = _growspace()
    growspace.default_zone.moisture_witness_sensors = ["sensor.witness"]
    coord = _coordinator(hass, growspace)
    hass.states.async_set(VWC, "30")
    hass.states.async_set("sensor.witness", "24")
    _ = coord.control_measurement
    coord._response_watch.unresponsive_since = dt_util.utcnow()
    assert coord.control_measurement.substitute_for == VWC
    coord._irrigation_cycle_started(manual=False)
    coord._irrigation_cycle_ended(
        end_dt=dt_util.utcnow(), moisture_before=30, manual=False
    )
    assert coord._pending_observation is None
    freezer.tick(timedelta(minutes=1))
    hass.states.async_set(VWC, "34")
    coord._sample_control_response()
    assert coord._response_watch.unresponsive_since is None
    assert coord.current_vwc == 34
    assert coord.control_measurement.substitute_for is None


async def test_last_witness_loss_while_control_failed_uses_degraded_alert_only(
    hass, notify, services
):
    growspace = _growspace(sensor_alert_delay_minutes=0)
    growspace.default_zone.moisture_witness_sensors = ["sensor.witness"]
    coord = _coordinator(hass, growspace, notify)
    hass.states.async_set(VWC, "30")
    hass.states.async_set("sensor.witness", "24")
    await coord._async_sensor_tick()
    hass.states.async_set(VWC, "unavailable")
    hass.states.async_set("sensor.witness", "unavailable")
    await coord._async_sensor_tick()
    assert len(notify.call_args_list) == 1
    assert notify.call_args_list[0].kwargs["tier"] == NotificationTier.SENSOR_INVALID
    assert len(services["create"]) == 1
