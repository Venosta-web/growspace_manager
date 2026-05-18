"""Global fixtures for integration tests."""

from unittest.mock import AsyncMock, MagicMock, Mock

from freezegun.api import FrozenDateTimeFactory
import pytest

from custom_components.growspace_manager.date_time_helper import DateTimeHelper

# pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def freeze_time(freezer: FrozenDateTimeFactory) -> None:
    """Freeze time to a fixed value to avoid off-by-one date errors.

    We choose a time in the middle of the day to avoid UTC midnight issues.
    Today is 2026-01-12 according to system context.
    """
    freezer.move_to("2026-01-12 12:00:00")


@pytest.fixture
def mock_coordinator():
    """Create a comprehensive mock coordinator with all services mocked."""

    coordinator = MagicMock()
    coordinator.hass = MagicMock()
    coordinator.growspaces = {}
    coordinator.plants = {}
    coordinator.data = MagicMock(spec=dict)
    coordinator.options = MagicMock(spec=dict)

    # 1. Mock Storage Manager (Fixes 'StorageManager' object has no attribute 'async_commit')
    coordinator.storage_manager = MagicMock()
    coordinator.storage_manager.async_commit = AsyncMock()
    coordinator.storage_manager.async_save = AsyncMock()
    coordinator.storage_manager.async_force_save = AsyncMock()

    # 2. Mock plant_manager with .services nesting (Fixes 'Called 0 times' errors)
    coordinator.plant_manager = MagicMock()
    coordinator.plant_manager.services = MagicMock()  # The Facade looks here

    async def _mock_add_plant(growspace_id, strain, **kwargs):
        p = MagicMock()
        p.plant_id = f"plant_{len(coordinator.plants) + 1}"
        p.growspace_id = growspace_id
        p.genetics = MagicMock()
        p.genetics.strain_name = strain
        for k, v in kwargs.items():
            setattr(p, k, v)
        coordinator.plants[p.plant_id] = p
        return p

    # Assign methods to BOTH locations to support legacy tests and new Facade
    plant_methods = [
        "update_plant",
        "move_plant",
        "switch_plants",
        "transition_plant_stage",
        "harvest_plant",
        "remove_plant",
        "harvest",
    ]

    coordinator.plant_manager.services.plants.add_plant = AsyncMock(
        side_effect=_mock_add_plant
    )
    coordinator.plant_manager.add_plant = coordinator.plant_manager.services.plants.add_plant

    for method in plant_methods:
        mock_method = AsyncMock()
        setattr(coordinator.plant_manager.services, method, mock_method)
        setattr(coordinator.plant_manager, method, mock_method)

    # 3. Mock growspace_manager with .services nesting
    coordinator.growspace_manager = MagicMock()
    coordinator.growspace_manager.services = MagicMock()

    async def _mock_add_gs(name, **kwargs):
        g = MagicMock()
        g.id = f"gs_{len(coordinator.growspaces) + 1}"
        g.name = name
        # Add env config mock to prevent asdict() failures
        g.environment_config = MagicMock()
        for k, v in kwargs.items():
            setattr(g, k, v)
        coordinator.growspaces[g.id] = g
        return g

    coordinator.growspace_manager.services.growspaces.add_growspace = AsyncMock(
        side_effect=_mock_add_gs
    )
    coordinator.growspace_manager.add_growspace = (
        coordinator.growspace_manager.services.growspaces.add_growspace
    )

    coordinator.growspace_manager.services.growspaces.update_growspace = AsyncMock()
    coordinator.growspace_manager.update_growspace = (
        coordinator.growspace_manager.services.growspaces.update_growspace
    )

    # 4. Fix sync vs async getters (Fixes 'coroutine is not iterable')
    # These must be MagicMock, NOT AsyncMock
    coordinator.get_growspace_plants = MagicMock(return_value=[])
    coordinator.growspace_manager.get_sorted_growspace_options = MagicMock(
        return_value=[]
    )
    coordinator.get_growspace_data = MagicMock(return_value={})

    # 5. Core coordinator-level async methods
    coordinator.async_save = AsyncMock()
    coordinator.async_commit = AsyncMock()
    coordinator.async_load = AsyncMock()
    coordinator.async_refresh = AsyncMock()
    coordinator.async_request_refresh = AsyncMock()

    # 6. Mock other subsystem services
    coordinator.subsystem_manager = MagicMock()
    coordinator.subsystem_manager.async_setup_growspace_sub_coordinators = AsyncMock()

    coordinator.watering_service = MagicMock()
    coordinator.watering_service.services = MagicMock()
    coordinator.watering_service.async_water_growspace = AsyncMock()

    coordinator.training_service = MagicMock()
    coordinator.training_service.services = MagicMock()

    coordinator.ipm_service = MagicMock()
    coordinator.ipm_service.services = MagicMock()

    from custom_components.growspace_manager.services.facade import ServiceFacade
    services = ServiceFacade(coordinator)
    services.save = AsyncMock(side_effect=services.save)
    coordinator.services = services

    return coordinator


@pytest.fixture
def mock_strain_library():
    """Create a mock strain library."""
    library = Mock()
    library.strains = {}
    library.add_strain = AsyncMock()
    library.get_strain = Mock(return_value=None)
    return library


@pytest.fixture
def mock_growspace():
    """Create a mock growspace."""
    growspace = Mock()
    growspace.name = "Test Growspace"
    growspace.rows = 5
    growspace.plants_per_row = 5
    growspace.id = "gs1"
    return growspace


@pytest.fixture
def mock_plant():
    """Create a mock plant."""
    plant = Mock()
    plant.plant_id = "plant_1"
    plant.strain = "Test Strain"
    plant.phenotype = "Pheno A"
    plant.growspace_id = "gs1"
    plant.row = 2
    plant.col = 3
    plant.clone_start = None
    plant.source_mother = None
    plant.type = "veg"
    return plant
