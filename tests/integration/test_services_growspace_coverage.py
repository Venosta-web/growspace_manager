"""Coverage-focused tests for GrowspaceService."""

from unittest.mock import AsyncMock, MagicMock, patch

from freezegun import freeze_time
import pytest
from syrupy.assertion import SnapshotAssertion

from custom_components.growspace_manager.exceptions import GrowspaceNotFoundError
from custom_components.growspace_manager.managers.growspace import GrowspaceManager
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    GrowspaceType,
    Plant,
)
from homeassistant.core import HomeAssistant


def _setup_growspaces(mock, growspaces_dict: dict) -> None:
    """Configure a MagicMock repository with growspace data."""
    mock.has_growspace.side_effect = lambda gid: gid in growspaces_dict
    mock.require_growspace.side_effect = lambda gid: growspaces_dict[gid]
    mock.get_growspace.side_effect = lambda gid: growspaces_dict.get(gid)
    mock.get_all_growspaces.return_value = list(growspaces_dict.values())
    mock.get_growspace_options.return_value = {
        gs.id: getattr(gs, "name", gs.id) for gs in growspaces_dict.values()
    }
    mock.get_sorted_growspace_options.return_value = sorted(
        [(gs.id, getattr(gs, "name", gs.id)) for gs in growspaces_dict.values()],
        key=lambda x: x[1].lower(),
    )


def _setup_plants(mock, plants_dict: dict) -> None:
    """Configure a MagicMock repository with plant data."""
    mock.has_plant.side_effect = lambda pid: pid in plants_dict
    mock.require_plant.side_effect = lambda pid: plants_dict[pid]
    mock.get_plant.side_effect = lambda pid: plants_dict.get(pid)
    mock.get_all_plants.return_value = list(plants_dict.values())
    mock.get_growspace_plants.side_effect = lambda gsid: [
        p for p in plants_dict.values() if p.growspace_id == gsid
    ]
    mock.remove_plant.side_effect = lambda pid: plants_dict.pop(pid, None)


@pytest.fixture
def repository_mock():
    """Mock the GrowspaceRepository."""
    mock = MagicMock()
    mock.has_growspace.return_value = False
    mock.has_plant.return_value = False
    mock.get_growspace.return_value = None
    mock.get_plant.return_value = None
    mock.get_all_growspaces.return_value = []
    mock.get_all_plants.return_value = []
    mock.get_growspace_plants.return_value = []
    mock.get_growspace_options.return_value = {}
    mock.get_sorted_growspace_options.return_value = []
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
    hass: HomeAssistant | None,
    repository_mock,
    validator_mock,
    view_model_builder_mock,
    save_callback_mock,
    lock_mock,
    cache_mock,
):
    """GrowspaceManager fixture."""
    svc = GrowspaceManager(
        hass=hass,
        repository=repository_mock,
        notification_state=MagicMock(),
        validator=validator_mock,
        view_model_builder=view_model_builder_mock,
        save_callback=save_callback_mock,
        lock=lock_mock,
    )
    svc.cache = cache_mock
    return svc


@freeze_time("2024-01-01 12:00:00", tz_offset=0)
@pytest.mark.asyncio
async def test_add_growspace_no_notification_target(
    service, repository_mock, snapshot: SnapshotAssertion
) -> None:
    """Test add_growspace with empty notification target."""
    with patch("uuid.uuid4", return_value="test-uuid"):
        await service.add_growspace("Test", notification_target="")
    gs = repository_mock.add_growspace.call_args[0][0]
    assert gs.notification_target is None
    assert gs.to_dict() == snapshot


@pytest.mark.asyncio
async def test_update_growspace_no_changes(
    service, repository_mock, save_callback_mock
) -> None:
    """Test update_growspace with no changes."""
    gs = Growspace(id="gs1", name="Test")
    _setup_growspaces(repository_mock, {"gs1": gs})
    await service.update_growspace("gs1")
    save_callback_mock.assert_not_called()


@pytest.mark.asyncio
async def test_resize_growspace_with_invalid_plants(
    service, repository_mock, caplog: pytest.LogCaptureFixture
) -> None:
    """Test resizing growspace when plants become out of bounds."""
    gs = Growspace(id="gs1", name="Test", rows=2, plants_per_row=2)
    _setup_growspaces(repository_mock, {"gs1": gs})

    # Use actual plant objects since service uses values()
    plant = Plant(plant_id="p1", growspace_id="gs1", row=2, col=2)
    _setup_plants(repository_mock, {"p1": plant})

    # Resize to 1x1
    await service.update_growspace("gs1", rows=1, plants_per_row=1)

    assert gs.rows == 1
    assert gs.plants_per_row == 1
    assert "Found 1 plants outside new grid boundaries" in caplog.text
    assert "Plant p1" in caplog.text


def test_generate_unique_name(service, repository_mock) -> None:
    """Test unique name generation."""
    _setup_growspaces(repository_mock, {
        "gs1": Growspace(id="gs1", name="Test"),
        "gs2": Growspace(id="gs2", name="Test 1"),
    })
    assert service.generate_unique_name("Test") == "Test 2"
    assert service.generate_unique_name("New") == "New"


def test_get_sorted_growspace_options(service, repository_mock) -> None:
    """Test getting sorted growspace options."""
    _setup_growspaces(repository_mock, {
        "gs1": Growspace(id="gs1", name="B"),
        "gs2": Growspace(id="gs2", name="A"),
    })
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
    _setup_growspaces(repository_mock, {"dry": gs})

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
    _setup_growspaces(repository_mock, {"gs1": gs})

    service.ensure_calculated_sensors()
    assert len(env.vpd_sensors) == 2
    assert env.vpd_sensors[1] == "sensor.gs_calculated_vpd_2"
    assert env.vpd_sensor == "sensor.v1"  # singular should match index 0


def test_ensure_calculated_sensors_no_sensors(service, repository_mock) -> None:
    """Test ensure_calculated_sensors with no env config."""
    gs = Growspace(id="gs1", name="GS", environment_config=None)
    _setup_growspaces(repository_mock, {"gs1": gs})
    service.ensure_calculated_sensors()
    # Should not crash


@pytest.mark.asyncio
async def test_remove_growspace(service, repository_mock, save_callback_mock) -> None:
    """Test removing a growspace."""
    gs = Growspace(id="gs1", name="Test")
    _setup_growspaces(repository_mock, {"gs1": gs})
    _setup_plants(repository_mock, {"p1": Plant(plant_id="p1", growspace_id="gs1")})
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
    _setup_growspaces(repository_mock, {})
    with pytest.raises(GrowspaceNotFoundError):
        await service.update_growspace("unknown")


@pytest.mark.asyncio
async def test_update_growspace_full_config(service, repository_mock) -> None:
    """Test updating all config fields of a growspace."""
    gs = Growspace(id="gs1", name="Old")
    _setup_growspaces(repository_mock, {"gs1": gs})

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
    added_ids = set()
    repository_mock.add_growspace.side_effect = lambda gs: added_ids.add(gs.id)
    await service.ensure_default_growspaces()
    assert "dry" in added_ids
    assert "cure" in added_ids
    assert "mother" in added_ids
    assert "clone" in added_ids
    assert "veg" in added_ids
    view_model_builder_mock.build_data_property.assert_called_once()


@pytest.mark.asyncio
async def test_add_growspace_with_configs(service, repository_mock) -> None:
    """Test add_growspace with optional configs."""
    from custom_components.growspace_manager.models import EnvironmentConfig

    await service.add_growspace(
        "Test",
        dimensions={"h": 200},
        environment_config={"temp": "sensor.t1"},
        irrigation_config={"pump": "switch.p1"},
    )
    gs = repository_mock.add_growspace.call_args[0][0]
    assert gs.dimensions == {"h": 200}
    # environment_config and irrigation_config get converted to typed objects by from_dict
    assert gs.environment_config is not None
    assert isinstance(gs.environment_config, EnvironmentConfig)
    assert gs.irrigation_config is not None


@pytest.mark.asyncio
async def test_remove_growspace_registry_error(service, repository_mock) -> None:
    """Test remove_growspace when registry throws."""
    gs = Growspace(id="gs1", name="Test")
    _setup_growspaces(repository_mock, {"gs1": gs})

    with patch("homeassistant.helpers.device_registry.async_get") as mock_dr:
        mock_dr.side_effect = Exception("Registry fail")
        await service.remove_growspace("gs1")
        # Should not raise
        assert "gs1" not in repository_mock.growspaces


def test_get_growspace_options(service, repository_mock) -> None:
    """Test get_growspace_options."""
    _setup_growspaces(repository_mock, {"gs1": Growspace(id="gs1", name="Test")})
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
    _setup_growspaces(repository_mock, {"gs1": gs})

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
    _setup_growspaces(repository_mock, {"gs1": gs})
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
    _setup_growspaces(repository_mock, {"gs1": gs})

    service.ensure_calculated_sensors()
    # It should have used vpd_sensor since vpd_sensors was empty
    assert env.vpd_sensors[0] == "sensor.v1"


def test_update_special_growspace_name_logic(service, repository_mock) -> None:
    """Test direct call to _update_special_growspace_name with different name."""
    gs = Growspace(id="dry", name="Old")
    _setup_growspaces(repository_mock, {"dry": gs})
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
    _setup_growspaces(repository_mock, {"gs1": gs})

    service.ensure_calculated_sensors()
    cache_mock.invalidate.assert_called_with("gs1")


def test_update_special_growspace_name_not_found(
    service, repository_mock, caplog: pytest.LogCaptureFixture
) -> None:
    """Test _update_special_growspace_name when growspace is not found."""
    _setup_growspaces(repository_mock, {})
    service._update_special_growspace_name("unknown", "New Name")
    assert "Special growspace unknown not found, skipping name update" in caplog.text


def test_get_canonical_special(service, repository_mock) -> None:
    """Test get_canonical_special for various scenarios."""
    # Special cases
    assert service.get_canonical_special("dry") == ("dry", "Dry Room")
    assert service.get_canonical_special("dry_room") == ("dry", "Dry Room")
    assert service.get_canonical_special("cure") == ("cure", "Cure Room")
    assert service.get_canonical_special("clone") == ("clone", "Clone Room")
    assert service.get_canonical_special("mother") == ("mother", "Mother Room")

    # Existing growspace
    gs = Growspace(id="gs1", name="My Room")
    _setup_growspaces(repository_mock, {"gs1": gs})
    assert service.get_canonical_special("gs1") == ("gs1", "My Room")

    # Not found
    assert service.get_canonical_special("unknown") == ("unknown", "unknown")
