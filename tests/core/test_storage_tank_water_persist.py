"""Regression test: tank water_history must survive restart (options merge)."""

from dataclasses import asdict
from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    IrrigationTank,
)
from custom_components.growspace_manager.models.irrigation import (
    TankWaterEvent,
    TankWaterHistory,
)
from custom_components.growspace_manager.storage_manager import StorageManager


@pytest.fixture
def repository_mock():
    """Mock the GrowspaceRepository."""
    mock = MagicMock()
    mock.growspaces = {}
    mock.load_growspaces.side_effect = lambda gs: mock.growspaces.update(gs)
    mock.get_all_growspaces.side_effect = lambda: list(mock.growspaces.values())
    return mock


@pytest.fixture
def storage(hass, repository_mock):
    """Provide a StorageManager instance with mocked managers."""
    nutrient = MagicMock()
    nutrient.get_serialization_data.return_value = {}
    genetics = MagicMock()
    genetics.get_serialization_data.return_value = {}
    return StorageManager(hass, repository_mock, nutrient, genetics)


def _tank_with_events(events: int) -> IrrigationTank:
    history = TankWaterHistory(
        events=[
            asdict(
                TankWaterEvent(
                    timestamp=f"2026-06-1{i % 7}T10:00:00+00:00",
                    liters=10.0,
                    pct_delta=-5.0,
                    event_type="consumption",
                )
            )
            for i in range(events)
        ]
    )
    return IrrigationTank(
        sensor_entity="sensor.tank_1",
        volume_liters=200.0,
        last_recorded_level=42.0,
        peak_level=80.0,
        water_history=history,
    )


def test_runtime_water_history_survives_options_merge(
    storage: StorageManager, repository_mock: MagicMock
) -> None:
    """Storage holds fresh runtime events; options holds a stale snapshot.

    On load the options snapshot must not clobber the runtime-accumulated
    tank water_history (the restart-reset bug).
    """
    # Storage growspace: 10 runtime consumption events accumulated since the
    # last config-flow save, with a stale warning_level config value.
    storage_tank = _tank_with_events(10)
    storage_tank.warning_level = 10.0
    storage_gs = Growspace(
        id="gs1",
        name="Tent",
        environment_config=EnvironmentConfig(
            irrigation_tanks=[storage_tank], stress_threshold=0.5
        ),
    )
    data = {"growspaces": {"gs1": asdict(storage_gs)}}

    # Config-entry options: the environment_config as last written by the config
    # flow — same tank but NO accumulated runtime events and updated config
    # values (warning_level, stress_threshold).
    options_tank = IrrigationTank(
        sensor_entity="sensor.tank_1", volume_liters=200.0, warning_level=25.0
    )
    options = {
        "gs1": asdict(
            EnvironmentConfig(irrigation_tanks=[options_tank], stress_threshold=0.9)
        ),
    }

    storage._load_growspaces(data, options)

    loaded = repository_mock.growspaces["gs1"]
    tank = loaded.environment_config.irrigation_tanks[0]
    # Runtime-accumulated state survives the options merge.
    assert len(tank.water_history.events) == 10, "runtime events were wiped on load"
    assert tank.last_recorded_level == 42.0
    assert tank.peak_level == 80.0
    # Configuration from options still wins over the persisted snapshot.
    assert tank.warning_level == 25.0
    assert loaded.environment_config.stress_threshold == 0.9
