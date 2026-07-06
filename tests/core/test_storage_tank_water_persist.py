"""Regression tests: the growspace store owns environment_config (ADR-0026).

Historically ``_apply_options_to_growspaces`` replaced the store's
environment_config with the per-growspace options blob on every restart,
wiping runtime-accumulated tank state (the restart-reset bug) and silently
reverting service-made edits. Nothing writes those blobs anymore: on load a
blob is adopted only when the store has no environment config, and otherwise
ignored.
"""

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


def test_stale_options_blob_is_ignored_on_load(
    storage: StorageManager, repository_mock: MagicMock
) -> None:
    """A store with real environment config wins over a stale options blob.

    The store carries runtime events and the freshest config edits (which may
    have been made via services and never reached options); re-applying the
    blob would revert both.
    """
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

    # A stale snapshot from the era when the config flow wrote options blobs.
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
    assert len(tank.water_history.events) == 10, "runtime events were wiped on load"
    assert tank.last_recorded_level == 42.0
    assert tank.peak_level == 80.0
    assert tank.warning_level == 10.0, "stale blob reverted a store config value"
    assert loaded.environment_config.stress_threshold == 0.5


def test_legacy_blob_adopted_when_store_has_no_env_config(
    storage: StorageManager, repository_mock: MagicMock
) -> None:
    """An install predating the store-first write path adopts its blob once.

    The blob's own serialized runtime values come along — there is nothing in
    the store to carry over.
    """
    storage_gs = Growspace(id="gs1", name="Tent")
    data = {"growspaces": {"gs1": asdict(storage_gs)}}

    blob_tank = _tank_with_events(3)
    blob_tank.warning_level = 25.0
    options = {
        "gs1": asdict(
            EnvironmentConfig(irrigation_tanks=[blob_tank], stress_threshold=0.9)
        ),
    }

    storage._load_growspaces(data, options)

    loaded = repository_mock.growspaces["gs1"]
    tank = loaded.environment_config.irrigation_tanks[0]
    assert loaded.environment_config.stress_threshold == 0.9
    assert tank.warning_level == 25.0
    assert len(tank.water_history.events) == 3
    assert tank.last_recorded_level == 42.0


def test_non_dict_blob_is_ignored(
    storage: StorageManager, repository_mock: MagicMock
) -> None:
    """A malformed legacy blob must not brick startup or touch the store."""
    storage_gs = Growspace(id="gs1", name="Tent")
    data = {"growspaces": {"gs1": asdict(storage_gs)}}

    storage._load_growspaces(data, {"gs1": "not-a-dict"})

    loaded = repository_mock.growspaces["gs1"]
    assert loaded.environment_config == EnvironmentConfig()
