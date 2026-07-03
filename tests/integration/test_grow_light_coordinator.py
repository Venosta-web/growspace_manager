"""Integration tests for GrowLightCoordinator (plain switch/light path)."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.grow_light_coordinator import (
    GrowLightCoordinator,
)
from custom_components.growspace_manager.models import (
    ACInfinityGrowLight,
    EnvironmentConfig,
    GrowLightConfig,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant


@pytest.fixture
def mock_hass() -> MagicMock:
    """Return mock HomeAssistant with an async service caller."""
    hass = MagicMock(spec=HomeAssistant)
    hass.states = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    return hass


def _make_env(
    *,
    enabled: bool = True,
    power: int = 100,
    growlight_entities: list[str] | None = None,
    ac_infinity_devices: list[ACInfinityGrowLight] | None = None,
    veg_day_hours: int = 18,
    flower_day_hours: int = 12,
) -> EnvironmentConfig:
    if growlight_entities is None:
        growlight_entities = ["switch.grow"]
    return EnvironmentConfig(
        growlight_entities=growlight_entities,
        growlight_ac_infinity_devices=ac_infinity_devices or [],
        growlight_config=GrowLightConfig(enabled=enabled, power=power),
        veg_day_hours=veg_day_hours,
        flower_day_hours=flower_day_hours,
    )


def _ac_device() -> ACInfinityGrowLight:
    return ACInfinityGrowLight(
        mode_entity="select.port_mode",
        on_time_entity="time.port_on",
        off_time_entity="time.port_off",
        power_entity="number.port_power",
    )


def _make_coordinator(
    env: EnvironmentConfig,
    *,
    lights_on_time: str = "06:00:00",
    plants: list | None = None,
) -> MagicMock:
    gs = MagicMock()
    gs.environment_config = env
    gs.irrigation_strategy.lights_on_time = lights_on_time
    coord = MagicMock()
    coord.growspaces = {"gs1": gs}
    coord.services.growspaces.get_growspace_plants.return_value = plants or []
    return coord


def _at(now: datetime):
    """Patch the coordinator's clock to a fixed ``now``."""
    return patch(
        "custom_components.growspace_manager.grow_light_coordinator.dt_util.now",
        return_value=now,
    )


async def test_light_on_at_power_inside_window(mock_hass: MagicMock) -> None:
    """Inside the photoperiod, an enabled plain grow light is turned on."""
    env = _make_env(growlight_entities=["switch.grow"], power=100)
    main_coord = _make_coordinator(env, lights_on_time="06:00:00")
    coord = GrowLightCoordinator(mock_hass, MagicMock(), "gs1", main_coord)

    with _at(datetime(2026, 7, 3, 12, 0, 0)):
        await coord._async_regulate()

    mock_hass.services.async_call.assert_awaited_once_with(
        "switch", "turn_on", {ATTR_ENTITY_ID: "switch.grow"}, blocking=False
    )


async def test_light_off_outside_window(mock_hass: MagicMock) -> None:
    """Outside the photoperiod, the grow light is turned off."""
    env = _make_env(growlight_entities=["switch.grow"])
    main_coord = _make_coordinator(env, lights_on_time="06:00:00")
    coord = GrowLightCoordinator(mock_hass, MagicMock(), "gs1", main_coord)

    with _at(datetime(2026, 7, 3, 2, 0, 0)):
        await coord._async_regulate()

    mock_hass.services.async_call.assert_awaited_once_with(
        "switch", "turn_off", {ATTR_ENTITY_ID: "switch.grow"}, blocking=False
    )


async def test_dimmable_light_holds_power_inside_window(mock_hass: MagicMock) -> None:
    """A light.* grow light holds its configured brightness inside the window."""
    env = _make_env(growlight_entities=["light.bar"], power=70)
    main_coord = _make_coordinator(env, lights_on_time="06:00:00")
    coord = GrowLightCoordinator(mock_hass, MagicMock(), "gs1", main_coord)

    with _at(datetime(2026, 7, 3, 12, 0, 0)):
        await coord._async_regulate()

    mock_hass.services.async_call.assert_awaited_once_with(
        "light",
        "turn_on",
        {ATTR_ENTITY_ID: "light.bar", "brightness_pct": 70},
        blocking=False,
    )


async def test_flowering_growspace_uses_flower_photoperiod(
    mock_hass: MagicMock,
) -> None:
    """Once a plant has entered flower, the shorter 12h window governs off-time."""
    env = _make_env(
        growlight_entities=["switch.grow"], veg_day_hours=18, flower_day_hours=12
    )
    flowering = MagicMock(flower_start="2026-07-01")
    main_coord = _make_coordinator(env, lights_on_time="06:00:00", plants=[flowering])
    coord = GrowLightCoordinator(mock_hass, MagicMock(), "gs1", main_coord)

    # 19:00 is inside the 18h veg window (06:00-24:00) but outside the 12h
    # flower window (06:00-18:00) -> flower schedule turns it off.
    with _at(datetime(2026, 7, 3, 19, 0, 0)):
        await coord._async_regulate()

    mock_hass.services.async_call.assert_awaited_once_with(
        "switch", "turn_off", {ATTR_ENTITY_ID: "switch.grow"}, blocking=False
    )


async def test_reconcile_is_level_based_not_edge(mock_hass: MagicMock) -> None:
    """Each tick re-asserts state (level-based), so control self-heals."""
    env = _make_env(growlight_entities=["switch.grow"])
    main_coord = _make_coordinator(env, lights_on_time="06:00:00")
    coord = GrowLightCoordinator(mock_hass, MagicMock(), "gs1", main_coord)

    with _at(datetime(2026, 7, 3, 12, 0, 0)):
        await coord._async_regulate()
        await coord._async_regulate()

    assert mock_hass.services.async_call.await_count == 2


async def test_disabled_controller_issues_no_writes(mock_hass: MagicMock) -> None:
    """A disabled grow light controller never commands the device."""
    env = _make_env(enabled=False, growlight_entities=["switch.grow"])
    main_coord = _make_coordinator(env)
    coord = GrowLightCoordinator(mock_hass, MagicMock(), "gs1", main_coord)

    with _at(datetime(2026, 7, 3, 12, 0, 0)):
        await coord._async_regulate()

    mock_hass.services.async_call.assert_not_awaited()


@pytest.fixture
def mock_track_interval():
    """Patch async_track_time_interval in the coordinator module."""
    with patch(
        "custom_components.growspace_manager.grow_light_coordinator.async_track_time_interval"
    ) as mock:
        mock.return_value = MagicMock()
        yield mock


async def test_setup_starts_tick_when_enabled(
    mock_hass: MagicMock, mock_track_interval: MagicMock
) -> None:
    """Setup registers a 10-second tick when enabled with grow lights."""
    env = _make_env(enabled=True, growlight_entities=["switch.grow"])
    coord = GrowLightCoordinator(mock_hass, MagicMock(), "gs1", _make_coordinator(env))

    await coord.async_setup()

    mock_track_interval.assert_called_once()
    assert mock_track_interval.call_args[0][2] == timedelta(seconds=10)


@pytest.mark.parametrize(
    ("enabled", "entities"),
    [(False, ["switch.grow"]), (True, [])],
)
async def test_setup_skips_when_disabled_or_unconfigured(
    mock_hass: MagicMock,
    mock_track_interval: MagicMock,
    enabled: bool,
    entities: list[str],
) -> None:
    """No tick is registered when disabled or when no grow light is configured."""
    env = _make_env(enabled=enabled, growlight_entities=entities)
    coord = GrowLightCoordinator(mock_hass, MagicMock(), "gs1", _make_coordinator(env))

    await coord.async_setup()

    mock_track_interval.assert_not_called()


def _patch_push():
    """Patch the AC Infinity configurator used by the coordinator."""
    return patch(
        "custom_components.growspace_manager.grow_light_coordinator.push_ac_infinity_schedule",
        new=AsyncMock(),
    )


async def test_setup_pushes_ac_infinity_schedule(
    mock_hass: MagicMock, mock_track_interval: MagicMock
) -> None:
    """Setup configures the onboard schedule on an AC Infinity grow light."""
    device = _ac_device()
    env = _make_env(
        growlight_entities=[], ac_infinity_devices=[device], power=80
    )  # veg 18h, lights on 06:00 -> off at 00:00
    coord = GrowLightCoordinator(
        mock_hass, MagicMock(), "gs1", _make_coordinator(env, lights_on_time="06:00:00")
    )

    with _patch_push() as mock_push:
        await coord.async_setup()

    mock_push.assert_awaited_once_with(
        mock_hass, device, on_time="06:00:00", off_time="00:00:00", power=80
    )


async def test_ac_infinity_only_starts_no_tick(
    mock_hass: MagicMock, mock_track_interval: MagicMock
) -> None:
    """An AC Infinity-only grow light is configured, not live-ticked."""
    env = _make_env(growlight_entities=[], ac_infinity_devices=[_ac_device()])
    coord = GrowLightCoordinator(mock_hass, MagicMock(), "gs1", _make_coordinator(env))

    with _patch_push():
        await coord.async_setup()

    mock_track_interval.assert_not_called()


async def test_mixed_plain_and_ac_infinity_both_activate(
    mock_hass: MagicMock, mock_track_interval: MagicMock
) -> None:
    """A growspace with both kinds ticks the plain light and configures AC Infinity."""
    env = _make_env(
        growlight_entities=["switch.grow"], ac_infinity_devices=[_ac_device()]
    )
    coord = GrowLightCoordinator(mock_hass, MagicMock(), "gs1", _make_coordinator(env))

    with _patch_push() as mock_push:
        await coord.async_setup()

    mock_track_interval.assert_called_once()
    mock_push.assert_awaited_once()


async def test_disabled_does_not_push_ac_infinity(
    mock_hass: MagicMock, mock_track_interval: MagicMock
) -> None:
    """A disabled controller configures nothing on the AC Infinity device."""
    env = _make_env(
        enabled=False, growlight_entities=[], ac_infinity_devices=[_ac_device()]
    )
    coord = GrowLightCoordinator(mock_hass, MagicMock(), "gs1", _make_coordinator(env))

    with _patch_push() as mock_push:
        await coord.async_setup()

    mock_push.assert_not_awaited()


async def test_regulate_ignores_ac_infinity_devices(mock_hass: MagicMock) -> None:
    """The live tick never commands AC Infinity devices (they run autonomously)."""
    env = _make_env(growlight_entities=[], ac_infinity_devices=[_ac_device()])
    coord = GrowLightCoordinator(mock_hass, MagicMock(), "gs1", _make_coordinator(env))

    with _at(datetime(2026, 7, 3, 12, 0, 0)):
        await coord._async_regulate()

    mock_hass.services.async_call.assert_not_awaited()
