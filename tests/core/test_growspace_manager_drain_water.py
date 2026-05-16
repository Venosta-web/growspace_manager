"""Tests for GrowspaceManager drain/water/tank methods."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.data_access.growspace_repository import (
    GrowspaceRepository,
)
from custom_components.growspace_manager.exceptions import GrowspaceNotFoundError
from custom_components.growspace_manager.growspace_validator import GrowspaceValidator
from custom_components.growspace_manager.managers.growspace import GrowspaceManager
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    IrrigationTank,
)
from custom_components.growspace_manager.view_model_builder import ViewModelBuilder


@pytest.fixture
def manager() -> GrowspaceManager:
    repo = GrowspaceRepository()
    gs = Growspace(id="gs1", name="Tent 1")
    repo.add_growspace(gs)
    save_cb = AsyncMock()
    return GrowspaceManager(
        hass=MagicMock(),
        repository=repo,
        notification_state=MagicMock(),
        validator=GrowspaceValidator(repo),
        view_model_builder=MagicMock(spec=ViewModelBuilder),
        save_callback=save_cb,
        lock=asyncio.Lock(),
    )


# ── async_log_drain_reading ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_async_log_drain_reading_appends_reading(
    manager: GrowspaceManager,
) -> None:
    await manager.async_log_drain_reading(
        growspace_id="gs1",
        feed_ec=1.8,
        drain_ec=2.1,
        drain_volume_ml=100.0,
        feed_volume_ml=500.0,
    )

    gs = manager.repository.require_growspace("gs1")
    assert len(gs.drain_config.readings) == 1
    reading = gs.drain_config.readings[0]
    assert reading.feed_ec == 1.8
    assert reading.drain_ec == 2.1
    assert reading.drain_volume_ml == 100.0
    assert reading.feed_volume_ml == 500.0
    manager.save_callback.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_log_drain_reading_without_volumes(
    manager: GrowspaceManager,
) -> None:
    await manager.async_log_drain_reading(
        growspace_id="gs1",
        feed_ec=2.0,
        drain_ec=2.3,
    )

    gs = manager.repository.require_growspace("gs1")
    reading = gs.drain_config.readings[0]
    assert reading.drain_volume_ml is None
    assert reading.feed_volume_ml is None


@pytest.mark.asyncio
async def test_async_log_drain_reading_enforces_rolling_window(
    manager: GrowspaceManager,
) -> None:
    gs = manager.repository.require_growspace("gs1")
    gs.drain_config.max_readings = 3

    for i in range(5):
        await manager.async_log_drain_reading("gs1", feed_ec=float(i), drain_ec=float(i) + 0.3)

    assert len(gs.drain_config.readings) == 3
    assert gs.drain_config.readings[0].feed_ec == 2.0


@pytest.mark.asyncio
async def test_async_log_drain_reading_fires_alert_when_threshold_exceeded(
    manager: GrowspaceManager,
) -> None:
    gs = manager.repository.require_growspace("gs1")
    gs.drain_config.enabled = True
    gs.drain_config.max_ec_delta = 0.5

    manager.hass.bus = MagicMock()

    await manager.async_log_drain_reading("gs1", feed_ec=1.0, drain_ec=2.0)

    manager.hass.bus.async_fire.assert_called_once()
    call_args = manager.hass.bus.async_fire.call_args
    assert call_args[0][0] == "growspace_manager_drain_ec_alert"
    assert call_args[0][1]["ec_delta"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_async_log_drain_reading_no_alert_when_below_threshold(
    manager: GrowspaceManager,
) -> None:
    gs = manager.repository.require_growspace("gs1")
    gs.drain_config.enabled = True
    gs.drain_config.max_ec_delta = 1.0

    manager.hass.bus = MagicMock()

    await manager.async_log_drain_reading("gs1", feed_ec=1.0, drain_ec=1.5)

    manager.hass.bus.async_fire.assert_not_called()


@pytest.mark.asyncio
async def test_async_log_drain_reading_unknown_growspace(
    manager: GrowspaceManager,
) -> None:
    with pytest.raises(GrowspaceNotFoundError):
        await manager.async_log_drain_reading("no_gs", feed_ec=1.0, drain_ec=1.2)


# ── async_configure_drain_monitoring ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_async_configure_drain_monitoring_all_fields(
    manager: GrowspaceManager,
) -> None:
    await manager.async_configure_drain_monitoring(
        growspace_id="gs1",
        enabled=True,
        max_ec_delta=0.4,
        target_runoff_percent=25.0,
    )

    gs = manager.repository.require_growspace("gs1")
    assert gs.drain_config.enabled is True
    assert gs.drain_config.max_ec_delta == pytest.approx(0.4)
    assert gs.drain_config.target_runoff_percent == pytest.approx(25.0)
    manager.save_callback.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_configure_drain_monitoring_partial_update(
    manager: GrowspaceManager,
) -> None:
    gs = manager.repository.require_growspace("gs1")
    gs.drain_config.max_ec_delta = 0.9

    await manager.async_configure_drain_monitoring("gs1", enabled=True)

    assert gs.drain_config.enabled is True
    assert gs.drain_config.max_ec_delta == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_async_configure_drain_monitoring_unknown_growspace(
    manager: GrowspaceManager,
) -> None:
    with pytest.raises(GrowspaceNotFoundError):
        await manager.async_configure_drain_monitoring("no_gs", enabled=True)


# ── async_reset_water_tracking ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_async_reset_water_tracking_resets_usage(
    manager: GrowspaceManager,
) -> None:
    gs = manager.repository.require_growspace("gs1")
    gs.water_usage.total_liters = 500.0

    await manager.async_reset_water_tracking("gs1")

    assert gs.water_usage.total_liters == pytest.approx(0.0)
    assert gs.water_usage.cycle_start_date != ""
    manager.save_callback.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_reset_water_tracking_unknown_growspace(
    manager: GrowspaceManager,
) -> None:
    with pytest.raises(GrowspaceNotFoundError):
        await manager.async_reset_water_tracking("no_gs")


# ── async_configure_tank ──────────────────────────────────────────────────────


@pytest.fixture
def manager_with_tank() -> GrowspaceManager:
    repo = GrowspaceRepository()
    tank = IrrigationTank(sensor_entity="sensor.tank1", volume_liters=None)
    env = EnvironmentConfig(irrigation_tanks=[tank])
    gs = Growspace(id="gs1", name="Tent 1", environment_config=env)
    repo.add_growspace(gs)
    save_cb = AsyncMock()
    return GrowspaceManager(
        hass=MagicMock(),
        repository=repo,
        notification_state=MagicMock(),
        validator=GrowspaceValidator(repo),
        view_model_builder=MagicMock(spec=ViewModelBuilder),
        save_callback=save_cb,
        lock=asyncio.Lock(),
    )


@pytest.mark.asyncio
async def test_async_configure_tank_updates_volume(
    manager_with_tank: GrowspaceManager,
) -> None:
    await manager_with_tank.async_configure_tank("gs1", "sensor.tank1", volume_liters=80.0)

    tank = manager_with_tank.repository.require_growspace("gs1").environment_config.irrigation_tanks[0]
    assert tank.volume_liters == pytest.approx(80.0)
    manager_with_tank.save_callback.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_configure_tank_volume_none_is_noop(
    manager_with_tank: GrowspaceManager,
) -> None:
    manager_with_tank.repository.require_growspace("gs1").environment_config.irrigation_tanks[0].volume_liters = 50.0

    await manager_with_tank.async_configure_tank("gs1", "sensor.tank1", volume_liters=None)

    tank = manager_with_tank.repository.require_growspace("gs1").environment_config.irrigation_tanks[0]
    assert tank.volume_liters == pytest.approx(50.0)
    manager_with_tank.save_callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_async_configure_tank_unknown_entity_is_noop(
    manager_with_tank: GrowspaceManager,
) -> None:
    await manager_with_tank.async_configure_tank("gs1", "sensor.missing", volume_liters=100.0)

    manager_with_tank.save_callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_async_configure_tank_unknown_growspace(
    manager_with_tank: GrowspaceManager,
) -> None:
    with pytest.raises(GrowspaceNotFoundError):
        await manager_with_tank.async_configure_tank("no_gs", "sensor.tank1", volume_liters=10.0)
