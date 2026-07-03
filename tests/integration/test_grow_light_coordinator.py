"""Integration tests for GrowLightCoordinator (plain switch/light path)."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.grow_light_coordinator import (
    GrowLightCoordinator,
)
from custom_components.growspace_manager.models import (
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
    veg_day_hours: int = 18,
    flower_day_hours: int = 12,
) -> EnvironmentConfig:
    if growlight_entities is None:
        growlight_entities = ["switch.grow"]
    return EnvironmentConfig(
        growlight_entities=growlight_entities,
        growlight_config=GrowLightConfig(enabled=enabled, power=power),
        veg_day_hours=veg_day_hours,
        flower_day_hours=flower_day_hours,
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
