"""Integration tests for Supplemental Lights v1 (coordinator + websocket + safety)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.domain.environment_patch import (
    EnvironmentPatchError,
    patch_from_service_call,
)
from custom_components.growspace_manager.domain.manual_override import (
    ManualOverride,
    Subsystem,
)
from custom_components.growspace_manager.grow_light_coordinator import (
    GrowLightCoordinator,
    build_growspace_supplemental_statuses,
)
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    GrowLightConfig,
    SupplementalAnchor,
    SupplementalLight,
    SupplementalLightWindow,
)
from custom_components.growspace_manager.services.environment_patch_commit import (
    async_commit_environment_patch,
)
from custom_components.growspace_manager.services.safety import managed_outputs
from custom_components.growspace_manager.websocket.supplemental_lights import (
    websocket_save_supplemental_lights,
)
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

_TZ = timezone(timedelta(hours=2))


def _make_hass(states: dict[str, str] | None = None) -> MagicMock:
    hass = MagicMock(spec=HomeAssistant)
    state_map = dict(states or {})

    def _get_state(entity_id: str):
        if entity_id not in state_map:
            return None
        return SimpleNamespace(state=state_map[entity_id], attributes={})

    hass.states = MagicMock()
    hass.states.get.side_effect = _get_state
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass._state_map = state_map
    return hass


def _make_growspace(
    gs_id: str = "gs1",
    name: str = "Flower Tent",
    *,
    lights_on_time: str = "06:00:00",
    veg_day_hours: int = 18,
    flower_day_hours: int = 12,
    growlight_entities: list[str] | None = None,
    supplemental_lights: list[SupplementalLight] | None = None,
) -> MagicMock:
    gs = MagicMock()
    gs.id = gs_id
    gs.name = name
    gs.environment_config = EnvironmentConfig(
        veg_day_hours=veg_day_hours,
        flower_day_hours=flower_day_hours,
        growlight_entities=growlight_entities or [],
        growlight_config=GrowLightConfig(enabled=False),
        supplemental_lights=supplemental_lights or [],
    )
    gs.light_cycle = SimpleNamespace(lights_on_time=lights_on_time)
    gs.default_zone = MagicMock()
    return gs


def _make_coordinator(
    growspaces: dict[str, MagicMock],
    *,
    commands_allowed: bool = True,
    override: ManualOverride | None = None,
    plants_by_gs: dict[str, list] | None = None,
) -> MagicMock:
    coord = MagicMock()
    coord.growspaces = growspaces
    coord.services = MagicMock()
    coord.services.save = AsyncMock()
    coord.services.request_refresh = AsyncMock()
    coord.services.growspaces.get_growspace_plants.side_effect = lambda gs_id: (
        plants_by_gs or {}
    ).get(gs_id, [])
    coord.irrigation_safety = MagicMock()
    coord.irrigation_safety.commands_allowed.return_value = commands_allowed
    coord.irrigation_safety.override_for.return_value = override
    coord.irrigation_safety.add_override_listener.return_value = MagicMock()
    coord._subsystem_manager = MagicMock()
    coord._subsystem_manager.get_growlight_controller.return_value = None
    return coord


@pytest.mark.asyncio
async def test_save_and_reload_multiple_windows_and_reject_invalid() -> None:
    """Saves valid multi-window supplemental config and rejects invalid windows."""
    hass = _make_hass({"light.uv_bar": STATE_OFF})
    gs = _make_growspace(veg_day_hours=18, flower_day_hours=12)
    coord = _make_coordinator({"gs1": gs})

    now = datetime(2026, 7, 3, 10, 0, 0, tzinfo=_TZ)
    with (
        patch(
            "custom_components.growspace_manager.websocket.supplemental_lights.dt_util.now",
            return_value=now,
        ),
        patch(
            "custom_components.growspace_manager.grow_light_coordinator.dt_util.now",
            return_value=now,
        ),
    ):
        res = await websocket_save_supplemental_lights(
            hass,
            coord,
            {
                "growspace_id": "gs1",
                "supplemental_lights": [
                    {
                        "id": "sup1",
                        "entity_id": "light.uv_bar",
                        "enabled": True,
                        "windows": [
                            {
                                "id": "w1",
                                "start_anchor": "lights_on",
                                "start_offset_minutes": 60,
                                "end_anchor": "lights_on",
                                "end_offset_minutes": 180,
                            },
                            {
                                "id": "w2",
                                "start_anchor": "lights_off",
                                "start_offset_minutes": -120,
                                "end_anchor": "lights_off",
                                "end_offset_minutes": -30,
                            },
                        ],
                    }
                ],
            },
        )
        assert res["status"] == "saved"
        assert len(gs.environment_config.supplemental_lights) == 1
        assert len(gs.environment_config.supplemental_lights[0].windows) == 2

        # Round-trip serialization
        restored = EnvironmentConfig.from_dict(gs.environment_config.to_dict())
        assert restored.supplemental_lights[0].entity_id == "light.uv_bar"
        assert len(restored.supplemental_lights[0].windows) == 2

        # Invalid window (before lights-on) is rejected on save
        with pytest.raises(
            ServiceValidationError, match="before planned main lights-on"
        ):
            await websocket_save_supplemental_lights(
                hass,
                coord,
                {
                    "growspace_id": "gs1",
                    "supplemental_lights": [
                        {
                            "id": "sup1",
                            "entity_id": "light.uv_bar",
                            "enabled": True,
                            "windows": [
                                {
                                    "id": "bad",
                                    "start_anchor": "lights_on",
                                    "start_offset_minutes": -15,
                                    "end_anchor": "lights_on",
                                    "end_offset_minutes": 60,
                                }
                            ],
                        }
                    ],
                },
            )


@pytest.mark.asyncio
async def test_duplicate_assignment_rejected_across_roles_and_growspaces() -> None:
    """Rejects duplicate lighting assignments in both WS save and EnvironmentPatch."""
    hass = _make_hass({"light.main": STATE_OFF, "switch.uv": STATE_OFF})
    gs1 = _make_growspace("gs1", "Flower Tent", growlight_entities=["light.main"])
    gs2 = _make_growspace(
        "gs2",
        "Veg Tent",
        supplemental_lights=[SupplementalLight(id="s2", entity_id="switch.uv")],
    )
    coord = _make_coordinator({"gs1": gs1, "gs2": gs2})

    # Assigning main light as supplemental light in same growspace fails
    with pytest.raises(ServiceValidationError, match="Flower Tent"):
        await websocket_save_supplemental_lights(
            hass,
            coord,
            {
                "growspace_id": "gs1",
                "supplemental_lights": [
                    {
                        "id": "s1",
                        "entity_id": "light.main",
                        "enabled": True,
                        "windows": [],
                    }
                ],
            },
        )

    # Assigning other growspace's supplemental light as main light fails
    patch_obj = patch_from_service_call({"growlight_entities": ["switch.uv"]})
    with pytest.raises(EnvironmentPatchError, match="Veg Tent"):
        await async_commit_environment_patch(hass, coord, gs1, patch_obj)


@pytest.mark.asyncio
async def test_reconcile_startup_resume_remaining_switch_off_and_reconnect() -> None:
    """Reconciles at startup, resumes remaining active window, switches off outside, and on reconnect."""
    now_active = datetime(2026, 7, 3, 8, 0, 0, tzinfo=_TZ)  # 120m after 06:00
    now_outside = datetime(2026, 7, 3, 12, 0, 0, tzinfo=_TZ)  # 360m after 06:00
    lights = [
        SupplementalLight(
            id="s1",
            entity_id="switch.uv",
            enabled=True,
            windows=[
                SupplementalLightWindow(
                    id="w1",
                    start_anchor=SupplementalAnchor.LIGHTS_ON,
                    start_offset_minutes=60,  # 07:00
                    end_anchor=SupplementalAnchor.LIGHTS_ON,
                    end_offset_minutes=180,  # 09:00
                )
            ],
        )
    ]
    gs = _make_growspace(supplemental_lights=lights)
    coord = _make_coordinator({"gs1": gs})
    hass = _make_hass({"switch.uv": STATE_OFF})
    entry = MagicMock()
    entry.async_create_background_task.side_effect = lambda _h, coro, _name: (
        _h.loop.create_task(coro) if hasattr(_h, "loop") else coro.close()
    )
    glc = GrowLightCoordinator(hass, entry, "gs1", coord)

    # 1. Startup inside active window (08:00 in [07:00, 09:00)) -> turns ON, schedules boundary at 09:00
    with (
        patch(
            "custom_components.growspace_manager.grow_light_coordinator.dt_util.now",
            return_value=now_active,
        ),
        patch(
            "custom_components.growspace_manager.grow_light_coordinator.async_track_point_in_utc_time",
            return_value=MagicMock(),
        ) as track_time,
        patch(
            "custom_components.growspace_manager.grow_light_coordinator.async_track_state_change_event",
            return_value=MagicMock(),
        ),
    ):
        await glc.async_setup()
        hass.services.async_call.assert_awaited_once_with(
            "switch", "turn_on", {"entity_id": "switch.uv"}, blocking=True
        )
        # Boundary scheduled for 09:00 local (07:00 UTC)
        assert track_time.call_args_list[0][0][2] == datetime(
            2026, 7, 3, 7, 0, 0, tzinfo=UTC
        )

    # 2. Outside window with output found ON -> switches OFF
    hass.services.async_call.reset_mock()
    hass._state_map["switch.uv"] = STATE_ON
    with (
        patch(
            "custom_components.growspace_manager.grow_light_coordinator.dt_util.now",
            return_value=now_outside,
        ),
        patch(
            "custom_components.growspace_manager.grow_light_coordinator.async_track_point_in_utc_time",
            return_value=MagicMock(),
        ),
    ):
        await glc.async_reconcile_supplemental_lights()
        hass.services.async_call.assert_awaited_once_with(
            "switch", "turn_off", {"entity_id": "switch.uv"}, blocking=True
        )

    # 3. Reconnection from unavailable -> off inside active window triggers reconcile
    hass.services.async_call.reset_mock()
    hass._state_map["switch.uv"] = STATE_OFF
    created_coros = []
    entry.async_create_background_task.side_effect = lambda _h, coro, _name: (
        created_coros.append(coro)
    )
    event = SimpleNamespace(
        data={
            "old_state": SimpleNamespace(state=STATE_UNAVAILABLE),
            "new_state": SimpleNamespace(state=STATE_OFF),
        }
    )
    glc._on_supplemental_state_change(event)
    assert len(created_coros) == 1
    with (
        patch(
            "custom_components.growspace_manager.grow_light_coordinator.dt_util.now",
            return_value=now_active,
        ),
        patch(
            "custom_components.growspace_manager.grow_light_coordinator.async_track_point_in_utc_time",
            return_value=MagicMock(),
        ),
    ):
        await created_coros[0]
        hass.services.async_call.assert_awaited_once_with(
            "switch", "turn_on", {"entity_id": "switch.uv"}, blocking=True
        )


@pytest.mark.asyncio
async def test_manual_override_holds_commands_and_reconciles_when_cleared() -> None:
    """Lights Manual Override prevents actuation and reconciles when cleared/expired."""
    now_active = datetime(2026, 7, 3, 8, 0, 0, tzinfo=_TZ)
    lights = [
        SupplementalLight(
            id="s1",
            entity_id="switch.uv",
            enabled=True,
            windows=[
                SupplementalLightWindow(
                    id="w1",
                    start_anchor=SupplementalAnchor.LIGHTS_ON,
                    start_offset_minutes=60,
                    end_anchor=SupplementalAnchor.LIGHTS_ON,
                    end_offset_minutes=180,
                )
            ],
        )
    ]
    gs = _make_growspace(supplemental_lights=lights)
    override = ManualOverride(
        Subsystem.LIGHTS,
        now_active - timedelta(minutes=10),
        now_active + timedelta(minutes=50),
    )
    coord = _make_coordinator({"gs1": gs}, commands_allowed=False, override=override)
    hass = _make_hass({"switch.uv": STATE_OFF})
    entry = MagicMock()
    created_coros = []
    entry.async_create_background_task.side_effect = lambda _h, coro, _name: (
        created_coros.append(coro)
    )
    glc = GrowLightCoordinator(hass, entry, "gs1", coord)

    with (
        patch(
            "custom_components.growspace_manager.grow_light_coordinator.dt_util.now",
            return_value=now_active,
        ),
        patch(
            "custom_components.growspace_manager.grow_light_coordinator.async_track_point_in_utc_time",
            return_value=MagicMock(),
        ),
    ):
        await glc.async_reconcile_supplemental_lights()
        hass.services.async_call.assert_not_awaited()

        statuses = build_growspace_supplemental_statuses(hass, coord, gs)
        assert "Lights manual override active" in (statuses[0]["held_off_reason"] or "")

        # Now override clears -> listener schedules reconcile -> turns ON
        coord.irrigation_safety.commands_allowed.return_value = True
        coord.irrigation_safety.override_for.return_value = None
        glc._on_override_changed("gs1", Subsystem.LIGHTS)
        assert len(created_coros) == 1
        await created_coros[0]
        hass.services.async_call.assert_awaited_once_with(
            "switch", "turn_on", {"entity_id": "switch.uv"}, blocking=True
        )


@pytest.mark.asyncio
async def test_photoperiod_shrink_skips_newly_invalid_windows_while_valid_run() -> None:
    """After veg->flower flip, newly invalid windows are skipped/explained and valid ones run."""
    now = datetime(2026, 7, 3, 8, 0, 0, tzinfo=_TZ)
    lights = [
        SupplementalLight(
            id="s1",
            entity_id="switch.uv",
            enabled=True,
            windows=[
                SupplementalLightWindow(
                    id="early",
                    start_anchor=SupplementalAnchor.LIGHTS_ON,
                    start_offset_minutes=60,
                    end_anchor=SupplementalAnchor.LIGHTS_ON,
                    end_offset_minutes=180,
                ),
                SupplementalLightWindow(
                    id="late_veg_only",
                    start_anchor=SupplementalAnchor.LIGHTS_ON,
                    start_offset_minutes=780,  # 13h -> invalid in 12h flower
                    end_anchor=SupplementalAnchor.LIGHTS_ON,
                    end_offset_minutes=840,
                ),
            ],
        )
    ]
    flower_plant = SimpleNamespace(flower_start="2026-07-01")
    gs = _make_growspace(supplemental_lights=lights)
    coord = _make_coordinator({"gs1": gs}, plants_by_gs={"gs1": [flower_plant]})
    hass = _make_hass({"switch.uv": STATE_OFF})

    with patch(
        "custom_components.growspace_manager.grow_light_coordinator.dt_util.now",
        return_value=now,
    ):
        statuses = build_growspace_supplemental_statuses(hass, coord, gs)
        assert len(statuses[0]["skipped_windows"]) == 1
        assert statuses[0]["skipped_windows"][0]["window_id"] == "late_veg_only"
        assert statuses[0]["is_active_now"] is True


@pytest.mark.asyncio
async def test_safe_release_switches_off_and_requires_release_anyway_on_blockers() -> (
    None
):
    """Disabling/deleting/reassigning switches off first; blockers require release_anyway."""
    existing = SupplementalLight(
        id="s1",
        entity_id="switch.uv",
        enabled=True,
        windows=[],
    )
    gs = _make_growspace(supplemental_lights=[existing])
    coord = _make_coordinator({"gs1": gs})
    hass = _make_hass({"switch.uv": STATE_ON})

    # 1. Clean delete while reachable and under control -> turns off, then saves
    res = await websocket_save_supplemental_lights(
        hass,
        coord,
        {"growspace_id": "gs1", "supplemental_lights": []},
    )
    assert res["status"] == "saved"
    hass.services.async_call.assert_awaited_once_with(
        "switch", "turn_off", {"entity_id": "switch.uv"}, blocking=True
    )

    # 2. Unreachable output on disable -> needs_confirmation, not saved until release_anyway=True
    gs.environment_config.supplemental_lights = [existing]
    hass.services.async_call.reset_mock()
    hass._state_map["switch.uv"] = STATE_UNAVAILABLE
    res_unreach = await websocket_save_supplemental_lights(
        hass,
        coord,
        {
            "growspace_id": "gs1",
            "supplemental_lights": [
                {"id": "s1", "entity_id": "switch.uv", "enabled": False, "windows": []}
            ],
        },
    )
    assert res_unreach["status"] == "needs_confirmation"
    assert res_unreach["blockers"][0]["reason"] == "unreachable"
    assert gs.environment_config.supplemental_lights[0].enabled is True

    # Confirming release_anyway=True completes the release
    res_forced = await websocket_save_supplemental_lights(
        hass,
        coord,
        {
            "growspace_id": "gs1",
            "supplemental_lights": [
                {"id": "s1", "entity_id": "switch.uv", "enabled": False, "windows": []}
            ],
            "release_anyway": True,
        },
    )
    assert res_forced["status"] == "saved"
    assert gs.environment_config.supplemental_lights[0].enabled is False

    # 3. Active override on reassignment -> needs_confirmation
    gs.environment_config.supplemental_lights = [existing]
    hass._state_map["switch.uv"] = STATE_ON
    hass._state_map["switch.uv_new"] = STATE_OFF
    coord.irrigation_safety.commands_allowed.return_value = False
    coord.irrigation_safety.override_for.return_value = ManualOverride(
        Subsystem.LIGHTS,
        datetime(2026, 7, 3, 8, 0, 0, tzinfo=UTC),
        datetime(2026, 7, 3, 9, 0, 0, tzinfo=UTC),
    )
    res_ovr = await websocket_save_supplemental_lights(
        hass,
        coord,
        {
            "growspace_id": "gs1",
            "supplemental_lights": [
                {
                    "id": "s1",
                    "entity_id": "switch.uv_new",
                    "enabled": True,
                    "windows": [],
                }
            ],
        },
    )
    assert res_ovr["status"] == "needs_confirmation"
    assert res_ovr["blockers"][0]["reason"] == "manual_override"

    # 4. managed_outputs includes supplemental lights for emergency stop
    assert "switch.uv" in managed_outputs(gs)
