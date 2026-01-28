"""Coverage-focused tests for GrowspaceService."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from syrupy.assertion import SnapshotAssertion

from custom_components.growspace_manager.exceptions import GrowspaceNotFoundError
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    GrowspaceType,
    Plant,
)
from custom_components.growspace_manager.services.growspace_service import (
    GrowspaceService,
)


@pytest.fixture
def repository_mock():
    """Mock the GrowspaceRepository."""
    mock = MagicMock()
    mock.growspaces = {}
    mock.plants = {}
    mock.notifications_enabled = {}
    return mock


@pytest.fixture
def validator_mock():
    """Mock the GrowspaceValidator."""
    return MagicMock()


@pytest.fixture
def view_model_builder_mock():
    """Mock the ViewModelBuilder."""
    mock = MagicMock()
    mock.build_data_property = MagicMock()
    return mock


@pytest.fixture
def lock_mock():
    """Mock the asyncio Lock."""
    mock = MagicMock()
    mock.__aenter__ = AsyncMock(return_value=None)
    mock.__aexit__ = AsyncMock(return_value=None)
    return mock


@pytest.fixture
def save_callback_mock():
    """Mock the save callback."""
    return AsyncMock()


@pytest.fixture
def cache_mock():
    """Mock the cache."""
    return MagicMock()


@pytest.fixture
def service(
    hass,
    repository_mock,
    validator_mock,
    view_model_builder_mock,
    save_callback_mock,
    lock_mock,
    cache_mock,
):
    """GrowspaceService fixture."""
    svc = GrowspaceService(
        hass=hass,
        repository=repository_mock,
        validator=validator_mock,
        view_model_builder=view_model_builder_mock,
        save_callback=save_callback_mock,
        lock=lock_mock,
    )
    svc.cache = cache_mock
    return svc


@pytest.mark.asyncio
async def test_add_growspace_no_notification_target(
    service, repository_mock, snapshot: SnapshotAssertion
) -> None:
    """Test add_growspace with empty notification target."""
    with patch("uuid.uuid4", return_value="test-uuid"):
        await service.add_growspace("Test", notification_target="")
    gs = list(repository_mock.growspaces.values())[0]
    assert gs.notification_target is None
    assert gs.to_dict() == snapshot


@pytest.mark.asyncio
async def test_update_growspace_no_changes(
    service, repository_mock, save_callback_mock
) -> None:
    """Test update_growspace with no changes."""
    gs = Growspace(id="gs1", name="Test")
    repository_mock.growspaces = {"gs1": gs}
    await service.update_growspace("gs1")
    save_callback_mock.assert_not_called()


@pytest.mark.asyncio
async def test_resize_growspace_with_invalid_plants(
    service, repository_mock, caplog: pytest.LogCaptureFixture
) -> None:
    """Test resizing growspace when plants become out of bounds."""
    gs = Growspace(id="gs1", name="Test", rows=2, plants_per_row=2)
    repository_mock.growspaces = {"gs1": gs}

    # Use actual plant objects since service uses values()
    plant = Plant(plant_id="p1", growspace_id="gs1", row=2, col=2)
    repository_mock.plants = {"p1": plant}

    # Resize to 1x1
    await service.update_growspace("gs1", rows=1, plants_per_row=1)

    assert gs.rows == 1
    assert gs.plants_per_row == 1
    assert "Found 1 plants outside new grid boundaries" in caplog.text
    assert "Plant p1" in caplog.text


def test_generate_unique_name(service, repository_mock) -> None:
    """Test unique name generation."""
    repository_mock.growspaces = {
        "gs1": Growspace(id="gs1", name="Test"),
        "gs2": Growspace(id="gs2", name="Test 1"),
    }
    assert service.generate_unique_name("Test") == "Test 2"
    assert service.generate_unique_name("New") == "New"


def test_get_sorted_growspace_options(service, repository_mock) -> None:
    """Test getting sorted growspace options."""
    repository_mock.growspaces = {
        "gs1": Growspace(id="gs1", name="B"),
        "gs2": Growspace(id="gs2", name="A"),
    }
    # Mock repository behavior
    repository_mock.get_sorted_growspace_options.return_value = [
        ("gs2", "A"),
        ("gs1", "B"),
    ]

    options = service.get_sorted_growspace_options()
    assert options == [("gs2", "A"), ("gs1", "B")]


def test_ensure_special_growspace_existing_migrate_type(
    service, repository_mock
) -> None:
    """Test ensure_special_growspace updating type for existing one."""
    gs = Growspace(id="dry", name="dry", growspace_type=GrowspaceType.FLOWER)
    repository_mock.growspaces = {"dry": gs}

    service.ensure_special_growspace("dry", "dry", growspace_type=GrowspaceType.DRY)
    assert gs.growspace_type == GrowspaceType.DRY


def test_ensure_calculated_sensors_padding(service, repository_mock) -> None:
    """Test ensure_calculated_sensors padding and updating singular."""
    env = EnvironmentConfig(
        temperature_sensors=["sensor.t1", "sensor.t2"],
        humidity_sensors=["sensor.h1", "sensor.h2"],
        vpd_sensors=["sensor.v1"],  # Only 1, needs padding
    )
    gs = Growspace(id="gs1", name="GS", environment_config=env)
    repository_mock.growspaces = {"gs1": gs}

    service.ensure_calculated_sensors()
    assert len(env.vpd_sensors) == 2
    assert env.vpd_sensors[1] == "sensor.gs_calculated_vpd_2"
    assert env.vpd_sensor == "sensor.v1"  # singular should match index 0


def test_ensure_calculated_sensors_no_sensors(service, repository_mock) -> None:
    """Test ensure_calculated_sensors with no env config."""
    gs = Growspace(id="gs1", name="GS", environment_config=None)
    repository_mock.growspaces = {"gs1": gs}
    service.ensure_calculated_sensors()
    # Should not crash


@pytest.mark.asyncio
async def test_remove_growspace(service, repository_mock, save_callback_mock) -> None:
    """Test removing a growspace."""
    gs = Growspace(id="gs1", name="Test")
    repository_mock.growspaces = {"gs1": gs}
    repository_mock.plants = {"p1": Plant(plant_id="p1", growspace_id="gs1")}
    repository_mock.notifications_enabled = {"gs1": True}
    repository_mock.remove_growspace.return_value = gs
    repository_mock.get_growspace_plants.return_value = [repository_mock.plants["p1"]]

    with patch("homeassistant.helpers.device_registry.async_get") as mock_dr:
        mock_dr.return_value.async_get_device.return_value = MagicMock(id="dev1")
        await service.remove_growspace("gs1")

        assert "gs1" not in repository_mock.growspaces
        save_callback_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_growspace_not_found(service, repository_mock) -> None:
    """Test update_growspace with non-existent ID."""
    repository_mock.growspaces = {}
    with pytest.raises(GrowspaceNotFoundError):
        await service.update_growspace("unknown")


@pytest.mark.asyncio
async def test_update_growspace_full_config(service, repository_mock) -> None:
    """Test updating all config fields of a growspace."""
    gs = Growspace(id="gs1", name="Old")
    repository_mock.growspaces = {"gs1": gs}

    await service.update_growspace(
        "gs1",
        name="New",
        notification_target="mobile",
        environment_config={"foo": "bar"},
        irrigation_config={"baz": "qux"},
        dimensions={"h": 1},
    )

    assert gs.name == "New"
    assert gs.notification_target == "mobile"
    assert gs.environment_config == {"foo": "bar"}
    assert gs.irrigation_config == {"baz": "qux"}
    assert gs.dimensions == {"h": 1}


@pytest.mark.asyncio
async def test_ensure_default_growspaces(
    service, repository_mock, view_model_builder_mock
) -> None:
    """Test ensuring default growspaces."""
    await service.ensure_default_growspaces()
    assert "dry" in repository_mock.growspaces
    assert "cure" in repository_mock.growspaces
    assert "mother" in repository_mock.growspaces
    assert "clone" in repository_mock.growspaces
    assert "veg" in repository_mock.growspaces
    view_model_builder_mock.build_data_property.assert_called_once()


@pytest.mark.asyncio
async def test_add_growspace_with_configs(service, repository_mock) -> None:
    """Test add_growspace with optional configs."""
    await service.add_growspace(
        "Test",
        dimensions={"h": 200},
        environment_config={"temp": "sensor.t1"},
        irrigation_config={"pump": "switch.p1"},
    )
    gs = list(repository_mock.growspaces.values())[0]
    assert gs.dimensions == {"h": 200}
    assert gs.environment_config == {"temp": "sensor.t1"}
    assert gs.irrigation_config == {"pump": "switch.p1"}


@pytest.mark.asyncio
async def test_remove_growspace_registry_error(service, repository_mock) -> None:
    """Test remove_growspace when registry throws."""
    gs = Growspace(id="gs1", name="Test")
    repository_mock.growspaces = {"gs1": gs}

    with patch("homeassistant.helpers.device_registry.async_get") as mock_dr:
        mock_dr.side_effect = Exception("Registry fail")
        await service.remove_growspace("gs1")
        # Should not raise
        assert "gs1" not in repository_mock.growspaces


def test_get_growspace_options(service, repository_mock) -> None:
    """Test get_growspace_options."""
    repository_mock.growspaces = {"gs1": Growspace(id="gs1", name="Test")}
    assert service.get_growspace_options() == {"gs1": "Test"}


def test_ensure_mother_growspace(service) -> None:
    """Test ensure_mother_growspace."""
    with patch.object(
        service, "ensure_special_growspace", return_value="mother"
    ) as mock_ens:
        assert service.ensure_mother_growspace() == "mother"
        mock_ens.assert_called_once()


def test_ensure_calculated_sensors_legacy_sync(service, repository_mock) -> None:
    """Test ensure_calculated_sensors syncing from legacy singular fields."""
    env = EnvironmentConfig(
        temperature_sensor="sensor.t1",
        humidity_sensor="sensor.h1",
        vpd_sensor="sensor.v1",
    )
    # Post init should have synced them to plural, but we can force it
    env.temperature_sensors = []  # Force empty plural
    env.humidity_sensors = []
    env.vpd_sensors = []  # Force empty plural

    gs = Growspace(id="gs1", name="GS", environment_config=env)
    repository_mock.growspaces = {"gs1": gs}

    service.ensure_calculated_sensors()
    # It should have used vpd_sensor to populate vpd_sensors first
    assert "sensor.v1" in env.vpd_sensors


def test_ensure_calculated_sensors_missing_singular(service, repository_mock) -> None:
    """Test ensure_calculated_sensors with missing humidity sensors."""
    env = EnvironmentConfig(
        temperature_sensors=["sensor.t1"],
        humidity_sensors=[],
    )
    gs = Growspace(id="gs1", name="GS", environment_config=env)
    repository_mock.growspaces = {"gs1": gs}
    service.ensure_calculated_sensors()
    assert not env.vpd_sensors


def test_ensure_calculated_sensors_vpd_sync(service, repository_mock) -> None:
    """Test ensure_calculated_sensors syncing vpd_sensor if plural is empty."""
    env = EnvironmentConfig(
        temperature_sensors=["sensor.t1"],
        humidity_sensors=["sensor.h1"],
        vpd_sensors=[],
        vpd_sensor="sensor.v1",
    )
    gs = Growspace(id="gs1", name="GS", environment_config=env)
    repository_mock.growspaces = {"gs1": gs}

    service.ensure_calculated_sensors()
    # It should have used vpd_sensor since vpd_sensors was empty
    assert env.vpd_sensors[0] == "sensor.v1"


def test_update_special_growspace_name_logic(service, repository_mock) -> None:
    """Test direct call to _update_special_growspace_name with different name."""
    gs = Growspace(id="dry", name="Old")
    repository_mock.growspaces = {"dry": gs}
    service._update_special_growspace_name("dry", "New")
    assert gs.name == "New"


def test_ensure_special_growspace_with_cache(
    service, repository_mock, cache_mock
) -> None:
    """Test ensure_special_growspace invalidates cache on creation and update."""
    # 1. Creation path
    service.ensure_special_growspace("dry", "dry", growspace_type=GrowspaceType.DRY)
    cache_mock.invalidate.assert_called_with("dry")
    cache_mock.invalidate.reset_mock()

    # 2. Update path (name remains same, but we force it to check)
    service.ensure_special_growspace("dry", "dry", growspace_type=GrowspaceType.DRY)
    # Even if name same, the method checks type and then invalidates if update_data is True?
    # Actually looking at code:
    # if self.cache: self.cache.invalidate(canonical_id) is in else block too.
    cache_mock.invalidate.assert_called_with("dry")


def test_ensure_calculated_sensors_with_cache(
    service, repository_mock, cache_mock
) -> None:
    """Test ensure_calculated_sensors invalidates cache on update."""
    env = EnvironmentConfig(
        temperature_sensors=["sensor.t1"],
        humidity_sensors=["sensor.h1"],
        vpd_sensors=[],
    )
    gs = Growspace(id="gs1", name="GS", environment_config=env)
    repository_mock.growspaces = {"gs1": gs}

    service.ensure_calculated_sensors()
    cache_mock.invalidate.assert_called_with("gs1")
