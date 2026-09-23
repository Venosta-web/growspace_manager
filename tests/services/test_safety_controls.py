"""Growspace safety controls gate outputs and survive restart."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.circulation_fan_coordinator import (
    CirculationFanCoordinator,
)
from custom_components.growspace_manager.const import EVENT_GROWSPACE_LOG_ENTRY
from custom_components.growspace_manager.domain.irrigation_safety import ControllerState
from custom_components.growspace_manager.exhaust_fan_coordinator import (
    ExhaustFanCoordinator,
)
from custom_components.growspace_manager.grow_light_coordinator import (
    GrowLightCoordinator,
)
from custom_components.growspace_manager.irrigation_coordinator import (
    IrrigationCoordinator,
)
from custom_components.growspace_manager.irrigation_safety_store import (
    IrrigationSafetyStore,
)
from custom_components.growspace_manager.models import (
    ACInfinityDevice,
    ACInfinityGrowLight,
    EnvironmentConfig,
    Growspace,
    IrrigationConfig,
)
from custom_components.growspace_manager.services.safety import (
    _safe_state,
    _targets,
    async_emergency_stop_growspace,
    handle_emergency_stop,
    handle_reset_safety,
    managed_outputs,
)
from custom_components.growspace_manager.vpd_on_off_controller import VpdOnOffController
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError


def _growspace() -> Growspace:
    return Growspace(
        id="tent",
        name="Tent",
        irrigation_config=IrrigationConfig(irrigation_pump_entity="switch.pump"),
        environment_config=EnvironmentConfig(
            humidifier_entities=["humidifier.mist"],
            dehumidifier_entities=["switch.dry"],
            growlight_entities=["light.grow"],
            exhaust_fan_entities=["fan.exhaust"],
            circulation_fan_entities=["number.circulation"],
            exhaust_fan_ac_infinity_devices=[
                ACInfinityDevice(
                    mode_entity="select.exhaust_mode",
                    speed_entity="number.exhaust_speed",
                )
            ],
            growlight_ac_infinity_devices=[
                ACInfinityGrowLight(
                    mode_entity="select.grow_mode",
                    on_time_entity="time.grow_on",
                    off_time_entity="time.grow_off",
                    power_entity="number.grow_power",
                )
            ],
        ),
    )


async def test_legacy_irrigation_migrates_armed_once(hass: HomeAssistant) -> None:
    logbook: list[dict] = []
    hass.bus.async_listen(
        EVENT_GROWSPACE_LOG_ENTRY, lambda event: logbook.append(event.data)
    )
    store = IrrigationSafetyStore(hass, "migration")
    await store.async_load()
    assert await store.async_initialize_controls({"tent": _growspace()}) == ["tent"]
    assert store.irrigation_armed("tent")
    assert store.ledger[-1]["action"] == "irrigation_armed_migration"
    assert store.irrigation_review_pending("tent")
    restarted = IrrigationSafetyStore(hass, "migration")
    await restarted.async_load()
    assert await restarted.async_initialize_controls({"tent": _growspace()}) == []
    assert restarted.irrigation_armed("tent")
    assert restarted.irrigation_review_pending("tent")
    await restarted.async_set_control("tent", "irrigation_armed", False, "grower")
    assert not restarted.irrigation_review_pending("tent")
    assert restarted.ledger[-1]["user_id"] == "grower"
    assert any("grower" in event["message"] for event in logbook)
    again = IrrigationSafetyStore(hass, "migration")
    await again.async_load()
    assert not again.irrigation_armed("tent")


async def test_reaffirming_migrated_arm_clears_review(hass: HomeAssistant) -> None:
    store = IrrigationSafetyStore(hass, "review-ack")
    await store.async_load()
    await store.async_initialize_controls({"tent": _growspace()})
    await store.async_set_control("tent", "irrigation_armed", True, "reviewer")
    assert not store.irrigation_review_pending("tent")
    assert store.ledger[-1]["user_id"] == "reviewer"


async def test_new_irrigation_is_disarmed(hass: HomeAssistant) -> None:
    store = IrrigationSafetyStore(hass, "new-irrigation")
    await store.async_load()
    await store.async_initialize_controls({"tent": Growspace(id="tent", name="Tent")})
    assert not store.irrigation_armed("tent")
    restarted = IrrigationSafetyStore(hass, "new-irrigation")
    await restarted.async_load()
    assert not restarted.irrigation_armed("tent")


async def test_emergency_stop_commands_all_outputs_and_reset_checks_readback(
    hass: HomeAssistant,
) -> None:
    growspace = _growspace()
    coordinator = MagicMock()
    coordinator.growspaces = {"tent": growspace}
    coordinator.irrigation_safety = IrrigationSafetyStore(hass, "stop-controls")
    await coordinator.irrigation_safety.async_load()
    await coordinator.irrigation_safety.async_initialize_controls(
        coordinator.growspaces
    )
    outputs = managed_outputs(growspace)
    assert set(outputs) == {
        "switch.pump",
        "humidifier.mist",
        "switch.dry",
        "light.grow",
        "fan.exhaust",
        "number.circulation",
        "select.exhaust_mode",
        "select.grow_mode",
    }
    for entity in outputs:
        hass.states.async_set(entity, "on")

    service_hass = MagicMock()
    service_hass.states.get.side_effect = hass.states.get

    async def turn_off(
        _domain: str, _service: str, data: dict, **_kwargs: object
    ) -> None:
        hass.states.async_set(
            data["entity_id"],
            "Off"
            if _service == "select_option"
            else "0"
            if _service == "set_value"
            else "off",
        )

    service_hass.services.async_call = AsyncMock(side_effect=turn_off)
    calls = service_hass.services.async_call
    await async_emergency_stop_growspace(service_hass, coordinator, "tent", "operator")
    assert calls.await_count == len(outputs)
    assert coordinator.irrigation_safety.emergency_stop_for("tent") is not None
    restarted = IrrigationSafetyStore(hass, "stop-controls")
    await restarted.async_load()
    assert not restarted.automation_enabled("tent")

    call = MagicMock()
    call.context.user_id = "admin"
    call.data = {"growspace_id": "tent"}
    service_hass.auth.async_get_user = AsyncMock(
        return_value=MagicMock(id="admin", is_admin=True)
    )
    coordinator.irrigation_safety = restarted
    with patch(
        "custom_components.growspace_manager.services.safety._targets",
        return_value=[(coordinator, "tent")],
    ):
        hass.states.async_set("switch.pump", "on")
        with pytest.raises(ServiceValidationError, match="switch.pump"):
            await handle_reset_safety(service_hass, call)
        assert restarted.emergency_stop_for("tent") is not None
        hass.states.async_set("switch.pump", "off")
        await handle_reset_safety(service_hass, call)
    assert restarted.emergency_stop_for("tent") is None
    assert restarted.ledger[-1]["action"] == "reset_safety"
    assert restarted.ledger[-1]["user_id"] == "admin"


async def test_automation_off_blocks_pump_service_calls(hass: HomeAssistant) -> None:
    store = IrrigationSafetyStore(hass, "automation-off")
    await store.async_load()
    await store.async_initialize_controls({"tent": _growspace()})
    await store.async_set_control("tent", "automation", False, "operator")
    runtime = MagicMock()
    runtime.irrigation_safety = store
    runtime.growspaces = {"tent": _growspace()}
    service_hass = MagicMock()
    service_hass.services.async_call = AsyncMock()
    coordinator = IrrigationCoordinator(
        service_hass, MagicMock(runtime_data=runtime), "tent", runtime
    )
    runtime.growspaces["tent"].irrigation_config.irrigation_times = [
        {"time": "10:00:00", "duration": 5}
    ]
    snapshot = coordinator.controller_snapshot()
    assert snapshot.state is ControllerState.INHIBITED
    assert snapshot.reasons[0].code == "automation_off"
    await coordinator._run_pump_cycle("irrigation", "switch.pump", 5, {})
    service_hass.services.async_call.assert_not_awaited()


@pytest.mark.parametrize(
    "controller_type,method",
    [
        (ExhaustFanCoordinator, "_async_regulate"),
        (CirculationFanCoordinator, "_async_regulate"),
        (GrowLightCoordinator, "_async_regulate"),
        (VpdOnOffController, "async_check_and_control"),
    ],
)
async def test_automation_off_blocks_climate_and_light_commands(
    controller_type: type, method: str
) -> None:
    controller = controller_type.__new__(controller_type)
    controller.main_coordinator = MagicMock()
    controller.main_coordinator.irrigation_safety.automation_enabled.return_value = (
        False
    )
    controller.growspace_id = "tent"
    controller.hass = MagicMock()
    controller.hass.services.async_call = AsyncMock()
    await getattr(controller, method)()
    controller.hass.services.async_call.assert_not_awaited()


async def test_stop_remains_latched_after_output_refuses_off(
    hass: HomeAssistant,
) -> None:
    coordinator = MagicMock()
    coordinator.growspaces = {"tent": _growspace()}
    coordinator.irrigation_safety = IrrigationSafetyStore(hass, "refused-stop")
    await coordinator.irrigation_safety.async_load()
    service_hass = MagicMock()
    service_hass.states.get.return_value.state = "on"
    service_hass.services.async_call = AsyncMock(
        side_effect=RuntimeError("relay offline")
    )
    with patch(
        "custom_components.growspace_manager.services.safety.asyncio.sleep",
        new=AsyncMock(),
    ):
        with pytest.raises(ServiceValidationError, match="not confirmed safe"):
            await async_emergency_stop_growspace(
                service_hass, coordinator, "tent", "operator"
            )
    assert coordinator.irrigation_safety.emergency_stop_for("tent") is not None
    assert not coordinator.irrigation_safety.automation_enabled("tent")


async def test_global_stop_attempts_every_growspace_after_a_failure() -> None:
    hass = MagicMock()
    call = MagicMock()
    call.data = {}
    call.context.user_id = "operator"
    first = MagicMock()
    second = MagicMock()
    with (
        patch(
            "custom_components.growspace_manager.services.safety._targets",
            return_value=[(first, "first"), (second, "second")],
        ),
        patch(
            "custom_components.growspace_manager.services.safety.async_emergency_stop_growspace",
            new=AsyncMock(side_effect=[RuntimeError("relay offline"), None]),
        ) as stop,
    ):
        with pytest.raises(ServiceValidationError, match="first"):
            await handle_emergency_stop(hass, call)
    assert stop.await_count == 2
    stop.assert_any_await(hass, second, "second", "operator")


def test_targets_include_only_loaded_entries_and_require_a_match() -> None:
    hass = MagicMock()
    loaded = MagicMock(state=ConfigEntryState.LOADED)
    loaded.runtime_data.growspaces = {"tent": _growspace()}
    unloaded = MagicMock(state=ConfigEntryState.NOT_LOADED)
    unloaded.runtime_data.growspaces = {"other": _growspace()}
    hass.config_entries.async_entries.return_value = [loaded, unloaded]
    assert _targets(hass, None) == [(loaded.runtime_data, "tent")]
    assert _targets(hass, "tent") == [(loaded.runtime_data, "tent")]
    with pytest.raises(ServiceValidationError, match="No matching loaded growspace"):
        _targets(hass, "other")


def test_safe_state_requires_affirmative_readback(hass: HomeAssistant) -> None:
    assert not _safe_state(hass, "switch.missing")
    hass.states.async_set("number.speed", "unavailable")
    assert not _safe_state(hass, "number.speed")
    hass.states.async_set("number.speed", "0")
    assert _safe_state(hass, "number.speed")


async def test_unreadable_store_still_commands_outputs_safe() -> None:
    coordinator = MagicMock()
    coordinator.growspaces = {"tent": _growspace()}
    coordinator.irrigation_safety.async_latch_emergency_stop = AsyncMock(
        side_effect=RuntimeError("record unreadable")
    )
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.states.get.return_value.state = "off"
    with patch(
        "custom_components.growspace_manager.services.safety.asyncio.sleep",
        new=AsyncMock(),
    ):
        with pytest.raises(ServiceValidationError, match="record unreadable"):
            await async_emergency_stop_growspace(hass, coordinator, "tent", "operator")
    assert hass.services.async_call.await_count == len(managed_outputs(_growspace()))


async def test_reset_requires_admin_and_skips_unlatched_growspace() -> None:
    hass = MagicMock()
    call = MagicMock()
    call.context.user_id = "grower"
    call.data = {"growspace_id": "tent"}
    hass.auth.async_get_user = AsyncMock(
        return_value=MagicMock(id="grower", is_admin=False)
    )
    with pytest.raises(ServiceValidationError, match="admin"):
        await handle_reset_safety(hass, call)

    coordinator = MagicMock()
    coordinator.irrigation_safety.emergency_stop_for.return_value = None
    hass.auth.async_get_user = AsyncMock(
        return_value=MagicMock(id="admin", is_admin=True)
    )
    with patch(
        "custom_components.growspace_manager.services.safety._targets",
        return_value=[(coordinator, "tent")],
    ):
        await handle_reset_safety(hass, call)
    coordinator.irrigation_safety.async_reset_emergency_stop.assert_not_called()
