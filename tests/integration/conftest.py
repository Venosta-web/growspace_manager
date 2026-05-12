"""Global fixtures for integration tests."""

import sys
from unittest.mock import AsyncMock, MagicMock, Mock

# Mock homeassistant.components.ai_task
sys.modules["homeassistant.components.ai_task"] = MagicMock()

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
    from unittest.mock import MagicMock, AsyncMock
    from custom_components.growspace_manager.services.facade import ServiceFacade

    coordinator = MagicMock()
    coordinator.hass = MagicMock()
    coordinator.growspaces = {}
    coordinator.plants = {}
    coordinator.data = MagicMock(spec=dict)
    coordinator.options = MagicMock(spec=dict)

    # 1. Mock Storage Manager
    coordinator.storage_manager = MagicMock()
    coordinator.storage_manager.async_commit = AsyncMock()
    coordinator.storage_manager.async_save = AsyncMock()
    coordinator.storage_manager.async_force_save = AsyncMock()

    # 2. Mock plant_manager
    coordinator.plant_manager = MagicMock()

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

    coordinator.plant_manager.add_plant = AsyncMock(side_effect=_mock_add_plant)
    coordinator.plant_manager.update_plant = AsyncMock()
    coordinator.plant_manager.move_plant = AsyncMock()
    coordinator.plant_manager.switch_plants = AsyncMock()
    coordinator.plant_manager.transition_plant_stage = AsyncMock()
    coordinator.plant_manager.harvest_plant = AsyncMock()
    coordinator.plant_manager.remove_plant = AsyncMock()
    coordinator.plant_manager.harvest = AsyncMock()

    # 3. Mock growspace_manager
    coordinator.growspace_manager = MagicMock()

    async def _mock_add_gs(name, **kwargs):
        g = MagicMock()
        g.id = f"gs_{len(coordinator.growspaces) + 1}"
        g.name = name
        g.environment_config = MagicMock()
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

    # 4. Core coordinator-level async methods
    coordinator.async_save = AsyncMock()
    coordinator.async_commit = AsyncMock()
    coordinator.async_load = AsyncMock()
    coordinator.async_refresh = AsyncMock()
    coordinator.async_take_clones = AsyncMock(return_value=["clone_1"])
    coordinator.async_promote_clone = AsyncMock()
    coordinator.async_add_plant = AsyncMock()
    coordinator.async_remove_plant = AsyncMock()
    coordinator.async_harvest_plant = AsyncMock()
    coordinator.async_remove_growspace = AsyncMock()
    coordinator.async_transition_plant_stage = AsyncMock()
    coordinator.async_update_irrigation_config = AsyncMock()
    coordinator.async_update_environment_config = AsyncMock()
    coordinator.async_start_flowering = AsyncMock()
    coordinator.async_start_drying = AsyncMock()
    coordinator.async_start_curing = AsyncMock()

    # 5. Mock other subsystem services
    coordinator.subsystem_manager = MagicMock()
    coordinator.subsystem_manager.async_setup_growspace_sub_coordinators = AsyncMock()

    coordinator.watering_service = MagicMock()
    coordinator.watering_service.async_water_growspace = AsyncMock()

    coordinator.training_service = MagicMock()
    coordinator.ipm_service = MagicMock()
    coordinator.notification_manager = MagicMock()
    coordinator.notification_settings = MagicMock()
    coordinator.view_model_builder = MagicMock()
    coordinator.validator = MagicMock()
    coordinator.serializer = MagicMock()
    coordinator.data_repository = MagicMock()

    # 6. Initialize ServiceFacade
    coordinator.services = ServiceFacade(coordinator)

    # 7. Utility methods
    coordinator.calculate_days = MagicMock(side_effect=DateTimeHelper.calculate_days)
    coordinator.to_date = MagicMock(side_effect=DateTimeHelper.to_date)
    coordinator.get_growspace_plants = MagicMock(return_value=[])
    coordinator.get_growspace_data = MagicMock(return_value={})

    # Public properties for legacy compatibility
    type(coordinator).growspace_service = property(lambda self: self.growspace_manager)
    type(coordinator).plant_service = property(lambda self: self.plant_manager)

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
