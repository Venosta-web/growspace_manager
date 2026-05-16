"""Global fixtures for integration tests."""

from unittest.mock import AsyncMock, Mock

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
    from unittest.mock import MagicMock

    coordinator = MagicMock()
    coordinator.hass = MagicMock()
    coordinator.growspaces = {}
    coordinator.plants = {}
    coordinator.data = MagicMock(spec=dict)
    coordinator.options = MagicMock(spec=dict)

    # Mock plant_manager with all its async methods
    coordinator.plant_manager = MagicMock()

    async def _mock_add_plant(growspace_id, strain, **kwargs):
        p = MagicMock()
        p.plant_id = f"plant_{len(coordinator.plants) + 1}"
        p.growspace_id = growspace_id
        p.strain = strain
        for k, v in kwargs.items():
            setattr(p, k, v)
        coordinator.plants[p.plant_id] = p
        return p

    coordinator.plant_manager.add_plant = AsyncMock(side_effect=_mock_add_plant)
    coordinator.plant_manager.update_plant = AsyncMock()
    coordinator.plant_manager.move_plant = AsyncMock()
    coordinator.plant_manager.switch_plants = AsyncMock()
    coordinator.plant_manager.transition_plant_stage = AsyncMock()
    coordinator.plant_manager.harvest_plant = AsyncMock()
    coordinator.plant_manager.remove_plant = AsyncMock()

    # Mock growspace_manager with all its methods
    coordinator.growspace_manager = MagicMock()

    async def _mock_add_gs(name, **kwargs):
        g = MagicMock()
        g.id = f"gs_{len(coordinator.growspaces) + 1}"
        g.name = name
        for k, v in kwargs.items():
            setattr(g, k, v)
        coordinator.growspaces[g.id] = g
        return g

    coordinator.growspace_manager.add_growspace = AsyncMock(side_effect=_mock_add_gs)
    coordinator.growspace_manager.update_growspace = AsyncMock()
    coordinator.growspace_manager.ensure_special_growspace = MagicMock(
        return_value="special_gs"
    )
    coordinator.growspace_manager.get_sorted_growspace_options = MagicMock(
        return_value=[]
    )

    # Core coordinator-level async methods (Awaited by handlers)
    coordinator.async_transition_plant_stage = AsyncMock()
    coordinator.async_save = AsyncMock()
    coordinator.async_commit = AsyncMock()
    coordinator.async_load = AsyncMock()
    coordinator.async_refresh = AsyncMock()

    async def _mock_update_env_config(
        growspace_id: str, environment_data: dict
    ) -> None:
        if growspace := coordinator.growspaces.get(growspace_id):
            for k, v in environment_data.items():
                if k == "bayesian_options" and isinstance(v, dict):
                    growspace.environment_config.bayesian_options.update(v)
                elif hasattr(growspace.environment_config, k):
                    setattr(growspace.environment_config, k, v)

    coordinator.async_update_environment_config = AsyncMock(
        side_effect=_mock_update_env_config
    )
    coordinator.async_start_flowering = AsyncMock()
    coordinator.async_start_drying = AsyncMock()
    coordinator.async_start_curing = AsyncMock()

    # Mock components
    coordinator.cache = MagicMock()
    coordinator.view_model_builder = MagicMock()
    coordinator.validator = MagicMock()
    coordinator.notification_manager = MagicMock()
    coordinator.serializer = MagicMock()

    # Public properties for services
    type(coordinator).growspace_service = property(lambda self: self.growspace_manager)
    type(coordinator).plant_service = property(lambda self: self.plant_manager)

    # Utility methods
    coordinator.calculate_days = MagicMock(side_effect=DateTimeHelper.calculate_days)
    coordinator.to_date = MagicMock(side_effect=DateTimeHelper.to_date)
    coordinator.get_growspace_plants = MagicMock(return_value=[])

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
