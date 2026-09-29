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

VWC = "sensor.vwc"
# Inside P1 for the strategy below: lights on 08:00, P0 over at 09:00.
STEERING_NOW = datetime(2023, 1, 1, 9, 30, tzinfo=dt_util.UTC)


def _growspace(**config: Any) -> Growspace:
    return Growspace(
        id="tent",
        name="Tent",
        environment_config=EnvironmentConfig(soil_moisture_sensor=VWC),
        irrigation_config=IrrigationConfig(
            irrigation_pump_entity="switch.pump", **config
        ),
        irrigation_strategy=IrrigationStrategy(
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
    return VWCIrrigationCoordinator(
        hass, MagicMock(runtime_data=runtime), growspace.id, runtime
    )


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
    assert coord._sensor_watches[VWC].alerted

    growspace.irrigation_strategy.enabled = False
    await coord._async_sensor_tick()

    assert not coord._sensor_watches[VWC].alerted
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
    growspace.environment_config.pore_ec_sensors = list(states)
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
    growspace.environment_config.pore_ec_sensors = ["sensor.ec_a"]
    coord = _coordinator(hass, growspace)
    hass.states.async_set("sensor.ec_a", "2.5")
    assert coord._average_pore_ec(growspace) == 2.5

    freezer.tick(timedelta(minutes=31))
    assert coord._average_pore_ec(growspace) is None
