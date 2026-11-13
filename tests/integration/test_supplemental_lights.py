"""Exercise Supplemental Lights from the WebSocket editor to a HA output."""

from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.coordinator_builder import CoordinatorBuilder
from custom_components.growspace_manager.domain.environment_patch import (
    EnvironmentPatch,
    EnvironmentPatchError,
)
from custom_components.growspace_manager.domain.manual_override import Subsystem
from custom_components.growspace_manager.models import GrowLightConfig, Growspace
from custom_components.growspace_manager.services.environment_patch_commit import (
    async_commit_environment_patch,
)
from custom_components.growspace_manager.supplemental_light_coordinator import (
    SupplementalLightCoordinator,
)
from custom_components.growspace_manager.websocket import async_register_websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
import homeassistant.util.dt as dt_util
from tests.common import MockConfigEntry

ENTITY = "switch.supplemental"
WINDOWS = [
    {
        "start": {"anchor": "lights_on", "offset_minutes": 60},
        "end": {"anchor": "lights_on", "offset_minutes": 180},
    },
    {
        "start": {"anchor": "lights_on", "offset_minutes": 120},
        "end": {"anchor": "lights_off", "offset_minutes": -720},
    },
]


@pytest.fixture
async def tent(
    hass: HomeAssistant,
) -> AsyncIterator[tuple[MockConfigEntry, GrowspaceCoordinator, Growspace]]:
    """Provide a managed main-light cycle and a real HA switch service."""
    entry = MockConfigEntry(domain=DOMAIN, state=ConfigEntryState.LOADED)
    entry.add_to_hass(hass)
    coordinator = CoordinatorBuilder(hass, entry).build(
        data={}, options={}, strain_library=MagicMock(), seedfinder_scraper=MagicMock()
    )
    entry.runtime_data = coordinator
    growspace = Growspace(id="tent", name="Tent")
    growspace.environment_config.growlight_config = GrowLightConfig(enabled=True)
    growspace.environment_config.growlight_entities = ["light.main"]
    coordinator._data_repository.add_growspace(growspace)
    coordinator.async_commit = AsyncMock()
    coordinator.services.growspaces.get_growspace_plants = MagicMock(return_value=[])
    async_register_websocket_api(hass)

    @callback
    def set_switch(call: ServiceCall) -> None:
        hass.states.async_set(
            call.data["entity_id"], call.service.removeprefix("turn_")
        )

    hass.services.async_register("switch", "turn_on", set_switch)
    hass.services.async_register("switch", "turn_off", set_switch)
    hass.states.async_set(ENTITY, "off")
    controller = SupplementalLightCoordinator(coordinator, growspace.id)
    coordinator._subsystem_manager.environment_controllers[growspace.id] = [controller]
    await controller.async_setup()
    yield entry, coordinator, growspace
    controller.unload()
    coordinator.irrigation_safety.async_stop_overrides()


async def _command(client: Any, command: str, **data: Any) -> dict[str, Any]:
    await client.send_json_auto_id(
        {"type": f"{DOMAIN}/{command}", "growspace_id": "tent", **data}
    )
    return await client.receive_json()


async def test_save_to_actuation(
    hass: HomeAssistant, hass_ws_client: Any, tent: Any, freezer: FrozenDateTimeFactory
) -> None:
    """Save both windows, run their union, and return the stored config."""
    client = await hass_ws_client(hass)
    freezer.move_to(datetime(2026, 1, 12, 8, 30, tzinfo=dt_util.DEFAULT_TIME_ZONE))
    result = await _command(
        client,
        "save_supplemental_light",
        light={"entity_id": ENTITY, "enabled": True, "windows": WINDOWS},
    )
    assert result["success"], result
    assert hass.states.get(ENTITY).state == "on"

    result = await _command(client, "get_supplemental_lights")
    assert result["success"], result
    status = result["result"]["lights"][0]
    assert status["light"]["windows"] == WINDOWS
    assert status["window"] == {"start": "07:00", "end": "12:00"}
    assert status["state"] == "on"
    await client.close()


async def _save(client: Any, entity_id: str = ENTITY, **change: Any) -> dict[str, Any]:
    light = {"entity_id": entity_id, "enabled": True, "windows": WINDOWS}
    light.update(change.pop("light_patch", {}))
    return await _command(client, "save_supplemental_light", light=light, **change)


async def test_restart_mid_window_rejoins_and_exits_at_the_boundary(
    hass: HomeAssistant, hass_ws_client: Any, tent: Any, freezer: FrozenDateTimeFactory
) -> None:
    """Restore through the growspace storage model and keep only the time left."""
    _, coordinator, growspace = tent
    async with await hass_ws_client(hass) as client:
        assert (await _save(client))["success"]
    controller = coordinator.services.growspaces.get_supplemental_light_controller(
        growspace.id
    )
    controller.unload()
    restored = Growspace.from_dict(growspace.to_dict())
    coordinator._data_repository.add_growspace(restored)

    freezer.move_to(datetime(2026, 1, 13, 11, 59, tzinfo=dt_util.DEFAULT_TIME_ZONE))
    await controller.async_setup()
    assert hass.states.get(ENTITY).state == "on"
    freezer.tick(timedelta(minutes=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "off"

    hass.states.async_set(ENTITY, "unavailable")
    await hass.async_block_till_done()
    hass.states.async_set(ENTITY, "on")
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "off"


async def test_schedule_edit_skips_only_the_newly_invalid_window(
    hass: HomeAssistant, hass_ws_client: Any, tent: Any, freezer: FrozenDateTimeFactory
) -> None:
    """A shorter main cycle invalidates the lights-off-relative window."""
    _, coordinator, growspace = tent
    async with await hass_ws_client(hass) as client:
        freezer.move_to(datetime(2026, 1, 12, 8, 30, tzinfo=dt_util.DEFAULT_TIME_ZONE))
        assert (await _save(client))["success"]
        assert hass.states.get(ENTITY).state == "on"
        await async_commit_environment_patch(
            hass, coordinator, growspace, EnvironmentPatch(values={"veg_day_hours": 12})
        )
        await hass.async_block_till_done()
        status = (await _command(client, "get_supplemental_lights"))["result"][
            "lights"
        ][0]
        assert status["warnings"] == ["Window 2 must end after it starts."]
        assert status["window"] == {"start": "07:00", "end": "09:00"}
        assert status["active"]
        assert hass.states.get(ENTITY).state == "on"


@pytest.mark.parametrize("release", ["disable", "delete", "reassign"])
@pytest.mark.parametrize("failure", ["unavailable", "command", "override"])
async def test_release_requires_explicit_choice_on_failure(
    hass: HomeAssistant, hass_ws_client: Any, tent: Any, failure: str, release: str
) -> None:
    """Keep the assigned output until its release has been explicitly authorized."""
    _, coordinator, growspace = tent
    replacement = "switch.replacement"
    hass.states.async_set(replacement, "off")
    async with await hass_ws_client(hass) as client:
        assert (await _save(client))["success"]
        match failure:
            case "unavailable":
                hass.states.async_set(ENTITY, "unavailable")
                expected = "unavailable"
            case "command":

                async def fail_off(_call: ServiceCall) -> None:
                    raise HomeAssistantError("device did not respond")

                hass.services.async_register("switch", "turn_off", fail_off)
                expected = "device did not respond"
            case _:
                await coordinator.irrigation_safety.async_set_override(
                    growspace.id, Subsystem.LIGHTS, timedelta(hours=1), None
                )
                expected = "Lights Manual Override"
        change: dict[str, Any] = {"original_entity": ENTITY}
        if release == "disable":
            change["light"] = {
                "entity_id": ENTITY,
                "enabled": False,
                "windows": WINDOWS,
            }
        elif release == "reassign":
            change["light"] = {
                "entity_id": replacement,
                "enabled": True,
                "windows": WINDOWS,
            }

        result = await _command(client, "save_supplemental_light", **change)
        assert result["success"], result
        assert expected in result["result"]["release_required"]["reason"]
        assert [
            (light.entity_id, light.enabled) for light in growspace.supplemental_lights
        ] == [(ENTITY, True)]
        result = await _command(
            client, "save_supplemental_light", **change, release_anyway=True
        )
        assert result["success"], result
        assert result["result"]["release_required"] is None
        if release == "delete":
            assert not growspace.supplemental_lights
        else:
            assert [light.to_dict() for light in growspace.supplemental_lights] == [
                change["light"]
            ]


async def test_duplicate_roles_and_invalid_windows_are_refused(
    hass: HomeAssistant, hass_ws_client: Any, tent: Any
) -> None:
    """The main assignment path and supplemental write both report the existing owner."""
    _, coordinator, growspace = tent
    other = Growspace(id="nursery", name="Nursery")
    other.environment_config.growlight_entities = ["switch.nursery"]
    coordinator._data_repository.add_growspace(other)

    async with await hass_ws_client(hass) as client:
        conflict = await _save(client, "switch.nursery")
        assert "main light in Nursery" in conflict["error"]["message"]
        conflict = await _save(client, "light.main")
        assert "main light in Tent" in conflict["error"]["message"]
        invalid = await _save(
            client,
            light_patch={
                "windows": [
                    {
                        "start": {"anchor": "lights_on", "offset_minutes": -1},
                        "end": {"anchor": "lights_on", "offset_minutes": 1},
                    }
                ]
            },
        )
        assert "outside the planned main-light cycle" in invalid["error"]["message"]
        assert (await _save(client))["success"]
        conflict = await _save(client)
        assert "supplemental light in Tent" in conflict["error"]["message"]
        for target in (growspace, other):
            with pytest.raises(
                EnvironmentPatchError, match="supplemental light in Tent"
            ):
                await async_commit_environment_patch(
                    hass,
                    coordinator,
                    target,
                    EnvironmentPatch(values={"growlight_entities": [ENTITY]}),
                )


@pytest.mark.parametrize("expiry", [False, True])
async def test_override_holds_and_reconciles_when_it_ends(
    hass: HomeAssistant,
    hass_ws_client: Any,
    tent: Any,
    freezer: FrozenDateTimeFactory,
    expiry: bool,
) -> None:
    """Keep manual control until the grower clears it or its timer expires."""
    _, coordinator, growspace = tent
    safety = coordinator.irrigation_safety
    async with await hass_ws_client(hass) as client:
        freezer.move_to(datetime(2026, 1, 12, 8, 30, tzinfo=dt_util.DEFAULT_TIME_ZONE))
        await safety.async_set_override(
            growspace.id, Subsystem.LIGHTS, timedelta(minutes=2), None
        )
        assert (await _save(client))["success"]
        assert hass.states.get(ENTITY).state == "off"
        status = (await _command(client, "get_supplemental_lights"))["result"][
            "lights"
        ][0]
        assert "Lights Manual Override" in status["reason"]
        if expiry:
            freezer.tick(timedelta(minutes=2))
            async_fire_time_changed(hass)
        else:
            await safety.async_clear_override(growspace.id, Subsystem.LIGHTS, None)
        await hass.async_block_till_done()
        assert hass.states.get(ENTITY).state == "on"


async def test_reassignment_turns_the_old_light_off_before_saving(
    hass: HomeAssistant, hass_ws_client: Any, tent: Any, freezer: FrozenDateTimeFactory
) -> None:
    """The old output is off at the moment persistence sees the new assignment."""
    _, coordinator, _ = tent
    replacement = "switch.replacement"
    hass.states.async_set(replacement, "off")
    async with await hass_ws_client(hass) as client:
        freezer.move_to(datetime(2026, 1, 12, 8, 30, tzinfo=dt_util.DEFAULT_TIME_ZONE))
        assert (await _save(client))["success"]

        async def verify_release() -> None:
            assert hass.states.get(ENTITY).state == "off"
            assert hass.states.get(replacement).state == "off"

        coordinator.async_commit.side_effect = verify_release
        result = await _save(client, replacement, original_entity=ENTITY)
        assert result["success"], result
        assert hass.states.get(replacement).state == "on"


async def test_overnight_overlap_never_switches_at_interior_boundaries(
    hass: HomeAssistant, hass_ws_client: Any, tent: Any, freezer: FrozenDateTimeFactory
) -> None:
    """Two overlapping windows stay on through both interior ends and midnight."""
    _, coordinator, growspace = tent
    growspace.light_cycle.lights_on_time = "20:00"
    growspace.environment_config.veg_day_hours = 12
    windows = [
        {
            "start": {"anchor": "lights_on", "offset_minutes": 180},
            "end": {"anchor": "lights_on", "offset_minutes": 300},
        },
        {
            "start": {"anchor": "lights_on", "offset_minutes": 240},
            "end": {"anchor": "lights_off", "offset_minutes": -360},
        },
    ]
    async with await hass_ws_client(hass) as client:
        freezer.move_to(datetime(2026, 1, 12, 23, 59, tzinfo=dt_util.DEFAULT_TIME_ZONE))
        assert (await _save(client, light_patch={"windows": windows}))["success"]
        assert hass.states.get(ENTITY).state == "on"
    initial = hass.states.get(ENTITY).last_changed
    for minutes in (1, 60):
        freezer.tick(timedelta(minutes=minutes))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        assert hass.states.get(ENTITY).last_changed == initial
    freezer.tick(timedelta(minutes=60))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "off"

    freezer.tick(timedelta(hours=22))
    controller = coordinator.services.growspaces.get_supplemental_light_controller(
        growspace.id
    )
    await controller.async_reconcile()
    assert hass.states.get(ENTITY).state == "on"
    growspace.light_cycle.lights_on_time = "invalid"
    coordinator.async_update_listeners()
    await hass.async_block_till_done()
    status = controller.status()
    assert status["cycle"] is None
    assert "valid managed main-light cycle" in status["lights"][0]["reason"]
    assert hass.states.get(ENTITY).state == "off"


async def test_release_is_refused_when_an_off_command_does_not_change_state(
    hass: HomeAssistant, hass_ws_client: Any, tent: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Successful HA service dispatch can leave the old light on."""
    from custom_components.growspace_manager import supplemental_light_coordinator
    from custom_components.growspace_manager.actuator_driver import async_confirm_state

    async def read_without_waiting(hass, entity_id, expected, *, first_read):
        return await async_confirm_state(
            hass, entity_id, expected, first_read=first_read, timeout=0
        )

    monkeypatch.setattr(
        supplemental_light_coordinator, "async_confirm_state", read_without_waiting
    )
    async with await hass_ws_client(hass) as client:
        assert (await _save(client))["success"]

        @callback
        def ignore_off(_call: ServiceCall) -> None:
            pass

        hass.services.async_register("switch", "turn_off", ignore_off)
        hass.states.async_set(ENTITY, "on")
        result = await _command(
            client, "save_supplemental_light", original_entity=ENTITY
        )
        assert "did not report off" in result["result"]["release_required"]["reason"]
        assert hass.states.get(ENTITY).state == "on"


async def test_failed_save_reinstates_the_previous_assignment(
    hass: HomeAssistant, hass_ws_client: Any, tent: Any, freezer: FrozenDateTimeFactory
) -> None:
    """A failed persistence call leaves the original light assigned and scheduled."""
    _, coordinator, growspace = tent
    async with await hass_ws_client(hass) as client:
        freezer.move_to(datetime(2026, 1, 12, 8, 30, tzinfo=dt_util.DEFAULT_TIME_ZONE))
        assert (await _save(client))["success"]
        coordinator.async_commit.side_effect = OSError("Cannot save")
        result = await _command(
            client, "save_supplemental_light", original_entity=ENTITY
        )
        assert not result["success"]
        await hass.async_block_till_done()
        assert [light.entity_id for light in growspace.supplemental_lights] == [ENTITY]
        assert hass.states.get(ENTITY).state == "on"


async def test_main_light_assignments_are_exclusive_across_entries(
    hass: HomeAssistant, tent: Any
) -> None:
    """The main-light editor cannot add an entity already owned by another entry."""
    _, coordinator, growspace = tent
    other_entry = MockConfigEntry(domain=DOMAIN, state=ConfigEntryState.LOADED)
    other_entry.add_to_hass(hass)
    other = Growspace(id="nursery", name="Nursery")
    other.environment_config.growlight_entities = [ENTITY]
    other_entry.runtime_data = MagicMock(growspaces={other.id: other})
    for outputs, message in (
        ([ENTITY], "main light in Nursery"),
        (["switch.new", "switch.new"], "main light in Tent"),
    ):
        with pytest.raises(EnvironmentPatchError, match=message):
            await async_commit_environment_patch(
                hass,
                coordinator,
                growspace,
                EnvironmentPatch(values={"growlight_entities": outputs}),
            )


async def test_non_admin_can_read_but_cannot_assign_a_light(
    hass: HomeAssistant,
    hass_ws_client: Any,
    tent: Any,
    hass_read_only_access_token: str,
) -> None:
    """Only administrators can grant automation control of an output."""
    async with await hass_ws_client(hass, hass_read_only_access_token) as client:
        assert (await _command(client, "get_supplemental_lights"))["success"]
        result = await _save(client)
        assert "Only an administrator" in result["error"]["message"]


async def test_growspace_deletion_keeps_an_unreachable_assignment(
    hass: HomeAssistant, hass_ws_client: Any, tent: Any
) -> None:
    """Whole-growspace deletion cannot bypass the device release flow."""
    _, coordinator, growspace = tent
    async with await hass_ws_client(hass) as client:
        assert (await _save(client))["success"]
        hass.states.async_set(ENTITY, "unavailable")
        with pytest.raises(
            HomeAssistantError, match="Release switch.supplemental in Growlights"
        ):
            await coordinator.services.growspaces.remove_growspace(growspace.id)
        assert growspace.id in coordinator.growspaces
        result = await _command(
            client,
            "save_supplemental_light",
            original_entity=ENTITY,
            release_anyway=True,
        )
        assert result["success"]
    await coordinator.services.growspaces.remove_growspace(growspace.id)
    assert growspace.id not in coordinator.growspaces
