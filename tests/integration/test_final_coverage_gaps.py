"""Tests targeting the remaining coverage gaps across multiple modules."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.irrigation_coordinator import (
    IrrigationCoordinator,
)
from custom_components.growspace_manager.managers.plant import PlantManager
from custom_components.growspace_manager.services.context import ServiceContext
from custom_components.growspace_manager.models import (
    Growspace,
    IPMPreset,
    IrrigationConfig,
    Plant,
    PlantGenetics,
    WaterUsageData,
)
from custom_components.growspace_manager.service_coordinator_locator import (
    ServiceCoordinatorLocator,
)
from custom_components.growspace_manager.services.ipm_service import IPMService
from custom_components.growspace_manager.services.watering_service import (
    WateringService,
)
from custom_components.growspace_manager.storage_manager import StorageManager
from custom_components.growspace_manager.strain_library import StrainLibrary
from custom_components.growspace_manager.websocket import (
    websocket_get_ec_ramp_curves,
    websocket_get_event_log,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

GROWSPACE_ID = "tent1"


# ---------------------------------------------------------------------------
# IrrigationCoordinator – invalid time format (lines 245-246)
# ---------------------------------------------------------------------------


@pytest.fixture
def irrigation_coordinator() -> IrrigationCoordinator:
    """Provide a minimal IrrigationCoordinator for testing."""
    main_coordinator = MagicMock()
    main_coordinator.growspaces = {
        GROWSPACE_ID: Growspace(
            id=GROWSPACE_ID,
            name="Tent 1",
            notification_target="notify.test",
            irrigation_config=IrrigationConfig(
                irrigation_pump_entity="switch.pump",
                drain_pump_entity="switch.drain",
                irrigation_duration=30,
                drain_duration=60,
                irrigation_times=[],
                drain_times=[],
            ),
        )
    }
    main_coordinator.async_save = AsyncMock()
    main_coordinator.async_refresh_growspace_data = AsyncMock()
    main_coordinator.async_set_updated_data = MagicMock()
    main_coordinator.add_event = MagicMock()

    hass = MagicMock(spec=HomeAssistant)
    hass.async_create_task = asyncio.create_task
    config_entry = MagicMock()
    config_entry.entry_id = "test_entry"

    coord = IrrigationCoordinator(
        hass=hass,
        growspace_id=GROWSPACE_ID,
        main_coordinator=main_coordinator,
        config_entry=config_entry,
    )
    return coord


@pytest.mark.asyncio
async def test_irrigation_add_schedule_item_invalid_time(
    irrigation_coordinator: IrrigationCoordinator,
) -> None:
    """Test that an invalid time string (e.g. 99:00:00) raises ValueError."""
    with pytest.raises(ValueError, match="Invalid time"):
        await irrigation_coordinator.async_add_schedule_item(
            schedule_key="irrigation_times",
            time_str="99:00:00",
            duration=30,
        )


# ---------------------------------------------------------------------------
# ServiceCoordinatorLocator.get_any – no coordinators loaded (lines 94-99)
# ---------------------------------------------------------------------------


def test_service_coordinator_locator_get_any_no_coordinators() -> None:
    """Test get_any raises ServiceValidationError when no coordinator is loaded."""
    hass = MagicMock()
    hass.config_entries.async_entries.return_value = []

    with pytest.raises(ServiceValidationError, match="No Growspace Manager"):
        ServiceCoordinatorLocator.get_any(hass)


# ---------------------------------------------------------------------------
# PlantManager.harvest_plant – PHI safety check (lines 494-507)
# ---------------------------------------------------------------------------


@pytest.fixture
def plant_manager(hass: HomeAssistant) -> PlantManager:
    """Return a minimal PlantManager for harvest tests."""
    repo = MagicMock()
    repo.plants = {}
    repo.growspaces = {}
    validator = MagicMock()
    validator.validate_plant_exists = MagicMock()

    lock = MagicMock()
    lock.__aenter__ = AsyncMock(return_value=None)
    lock.__aexit__ = AsyncMock(return_value=None)

    return PlantManager(
        ctx=ServiceContext(
            save_callback=AsyncMock(),
            lock=lock,
            add_event=MagicMock(),
            invalidate_cache=MagicMock(),
        ),
        hass=hass,
        repository=repo,
        notification_state=MagicMock(),
        validator=validator,
        growspace_manager=MagicMock(),
        strain_library=MagicMock(record_harvest=AsyncMock()),
        plant_view_builder=MagicMock(),
    )


@pytest.mark.asyncio
async def test_harvest_blocked_by_phi_clearance_date(
    plant_manager: PlantManager,
) -> None:
    """Test that harvesting is blocked when PHI clearance date is in the future."""
    future_date = (date.today() + timedelta(days=5)).isoformat()
    plant = Plant(
        plant_id="p1",
        growspace_id=GROWSPACE_ID,
        genetics=PlantGenetics(strain_name="OG Kush"),
        phi_clearance_date=future_date,
    )
    plant_manager.repository.plants["p1"] = plant

    with pytest.raises(ServiceValidationError):
        await plant_manager.harvest_plant(plant_id="p1", plant=plant)


@pytest.mark.asyncio
async def test_harvest_plant_with_all_metrics(
    plant_manager: PlantManager,
) -> None:
    """Test harvest_plant stores all optional metric fields when provided."""
    plant = Plant(
        plant_id="p2",
        growspace_id=GROWSPACE_ID,
        genetics=PlantGenetics(strain_name="Blue Dream"),
        phi_clearance_date=None,
    )
    plant_manager.repository.plants["p2"] = plant
    plant_manager.repository.get_growspace.return_value = MagicMock(
        id=GROWSPACE_ID, name="Tent", notification_target="notify.x"
    )
    plant_manager.repository.get_growspace_plants.return_value = []

    with patch(
        "custom_components.growspace_manager.managers.plant.calculate_plant_stage",
        return_value="flower",
    ):
        await plant_manager.harvest_plant(
            plant_id="p2",
            plant=plant,
            wet_weight=100.0,
            dry_weight=80.0,
            trim_weight=5.0,
            thc_percentage=22.5,
            cbd_percentage=1.2,
            terpene_profile="citrus, pine",
        )

    assert plant.harvest_metrics.wet_weight == 100.0
    assert plant.harvest_metrics.dry_weight == 80.0
    assert plant.harvest_metrics.trim_weight == 5.0
    assert plant.harvest_metrics.thc_percentage == 22.5
    assert plant.harvest_metrics.cbd_percentage == 1.2
    assert plant.harvest_metrics.terpene_profile == "citrus, pine"


# ---------------------------------------------------------------------------
# IPMService.async_apply_ipm – PHI clearance update (lines 164-172)
# ---------------------------------------------------------------------------


@pytest.fixture
def ipm_service() -> IPMService:
    """Return a minimal IPMService."""
    repo = MagicMock()
    repo.growspaces = {}
    repo.plants = {}
    repo.get_growspace_plants.return_value = []

    return IPMService(
        ctx=ServiceContext(
            save_callback=AsyncMock(),
            lock=asyncio.Lock(),
            add_event=MagicMock(),
            invalidate_cache=MagicMock(),
        ),
        hass=MagicMock(),
        repository=repo,
    )


@pytest.mark.asyncio
async def test_apply_ipm_sets_phi_clearance_date(ipm_service: IPMService) -> None:
    """Test that applying an IPM preset with phi_days sets phi_clearance_date."""
    preset = IPMPreset(
        id="preset1",
        name="Neem Oil",
        type="foliar",
        items=[{"name": "Neem", "dose_amount": 5, "dose_unit": "ml", "phi_days": 14}],
    )
    ipm_service.ipm_presets["preset1"] = preset

    plant = Plant(plant_id="p1", growspace_id=GROWSPACE_ID)
    assert plant.phi_clearance_date is None

    ipm_service.repository.get_growspace_plants.return_value = [plant]

    await ipm_service.async_apply_ipm(
        preset_id="preset1",
        growspace_id=GROWSPACE_ID,
    )

    # PHI clearance date should be set 14 days from now
    expected = (date.today() + timedelta(days=14)).isoformat()
    assert plant.phi_clearance_date == expected


@pytest.mark.asyncio
async def test_apply_ipm_phi_clearance_only_updated_when_later(
    ipm_service: IPMService,
) -> None:
    """Test PHI clearance date is only updated when new date is later."""
    preset = IPMPreset(
        id="preset1",
        name="Neem Oil",
        type="foliar",
        items=[{"name": "Neem", "dose_amount": 5, "dose_unit": "ml", "phi_days": 7}],
    )
    ipm_service.ipm_presets["preset1"] = preset

    # Plant already has a later clearance date (20 days from now)
    far_future = (date.today() + timedelta(days=20)).isoformat()
    plant = Plant(
        plant_id="p1",
        growspace_id=GROWSPACE_ID,
        phi_clearance_date=far_future,
    )

    ipm_service.repository.get_growspace_plants.return_value = [plant]

    await ipm_service.async_apply_ipm(
        preset_id="preset1",
        growspace_id=GROWSPACE_ID,
    )

    # Clearance should NOT be overwritten (existing date is later)
    assert plant.phi_clearance_date == far_future


# ---------------------------------------------------------------------------
# WateringService – rolling window enforcement (line 140)
# ---------------------------------------------------------------------------


@pytest.fixture
def watering_service() -> WateringService:
    """Return a minimal WateringService."""
    repo = MagicMock()
    repo.plants = {}
    repo.get_growspace_plants.return_value = []
    validator = MagicMock()
    nutrient_manager = MagicMock()
    nutrient_manager.resolve_nutrient_mix.return_value = ({}, None)
    nutrient_manager.deduct_from_inventory = MagicMock()

    return WateringService(
        ctx=ServiceContext(
            save_callback=AsyncMock(),
            lock=asyncio.Lock(),
            add_event=MagicMock(),
            invalidate_cache=MagicMock(),
        ),
        hass=MagicMock(),
        repository=repo,
        validator=validator,
        nutrient_manager=nutrient_manager,
    )


@pytest.mark.asyncio
async def test_watering_enforces_rolling_window(
    watering_service: WateringService,
) -> None:
    """Test that daily readings are trimmed when they exceed max_daily_readings."""
    max_readings = 3
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    two_days_ago = (date.today() - timedelta(days=2)).isoformat()

    water_usage = WaterUsageData(
        total_liters=10.0,
        max_daily_readings=max_readings,
        daily_readings=[
            {"date": two_days_ago, "liters": 1.0, "plant_count": 1},
            {"date": yesterday, "liters": 2.0, "plant_count": 1},
            {"date": today, "liters": 3.0, "plant_count": 1},
        ],
    )
    # Already at max, adding one more should push oldest out on next watering

    growspace = Growspace(
        id=GROWSPACE_ID,
        name="Tent",
        notification_target="notify.test",
        water_usage=water_usage,
    )
    plant = Plant(plant_id="p1", growspace_id=GROWSPACE_ID)

    watering_service.repository.plants["p1"] = plant
    watering_service.repository.get_growspace.return_value = growspace

    with patch(
        "custom_components.growspace_manager.services.watering_service.dt_util"
    ) as mock_dt:
        # Use a different date so a new entry is appended
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        mock_dt.now.return_value.isoformat.return_value = tomorrow
        mock_dt.now.return_value.date.return_value.isoformat.return_value = tomorrow

        await watering_service._water_plant_internal(
            plant_id="p1",
            amount=1.0,
            invalidate_cache=False,
        )

    # Should be trimmed to max_daily_readings
    assert len(water_usage.daily_readings) <= max_readings


# ---------------------------------------------------------------------------
# StorageManager – corrupt EC ramp curves (lines 308-310)
# ---------------------------------------------------------------------------


@pytest.fixture
def storage_manager(hass: HomeAssistant) -> StorageManager:
    """Return a minimal StorageManager."""
    repo = MagicMock()
    repo.growspaces = {}
    repo.plants = {}
    nutrient_manager = MagicMock()
    genetics_manager = MagicMock()
    return StorageManager(hass, repo, nutrient_manager, genetics_manager)


def test_load_ec_ramp_curves_handles_corrupt_data(
    storage_manager: StorageManager,
) -> None:
    """Test that corrupt EC ramp curve data is handled gracefully."""
    # Provide data where ECRampCurve.from_dict raises an exception
    corrupt_data = {"ec_ramp_curves": {"curve1": "not_a_dict"}}

    result = storage_manager._load_ec_ramp_curves(corrupt_data)

    assert result == {}


# ---------------------------------------------------------------------------
# StrainLibrary.get_analytics – dry/wet weights populated (lines 793-796, 798)
# ---------------------------------------------------------------------------


@pytest.fixture
def strain_library(tmp_path) -> StrainLibrary:
    """Return a StrainLibrary with in-memory data (no real DB)."""
    hass = MagicMock()
    hass.config.path.return_value = str(tmp_path / "test.sqlite")
    lib = StrainLibrary(hass)
    lib._db = None  # Prevent real DB operations
    return lib


def test_get_analytics_includes_dry_and_wet_weights(
    strain_library: StrainLibrary,
) -> None:
    """Test that get_analytics computes avg_dry_weight and avg_wet_weight."""
    strain_library.strains = {
        "OG Kush": {
            "phenotypes": {
                "Pheno A": {
                    "harvests": [
                        {
                            "veg_days": 30,
                            "flower_days": 60,
                            "dry_weight": 80.0,
                            "wet_weight": 200.0,
                        },
                        {
                            "veg_days": 28,
                            "flower_days": 62,
                            "dry_weight": 90.0,
                            "wet_weight": 220.0,
                        },
                    ]
                }
            }
        }
    }
    strain_library._analytics_cache = None

    analytics = strain_library.get_analytics()

    # Analytics returns {"strains": {...}, "strain_list": [...]}
    # Pheno stats are merged at the top level of the pheno dict
    pheno = analytics["strains"]["OG Kush"]["phenotypes"]["Pheno A"]
    assert "avg_dry_weight" in pheno
    assert pheno["avg_dry_weight"] == 85.0
    assert "total_dry_yield" in pheno
    assert pheno["total_dry_yield"] == 170.0
    assert "avg_wet_weight" in pheno
    assert pheno["avg_wet_weight"] == 210.0


def test_get_analytics_no_dry_weight_field_excluded(
    strain_library: StrainLibrary,
) -> None:
    """Test analytics when harvests have no dry or wet weight fields."""
    strain_library.strains = {
        "Strain B": {
            "phenotypes": {
                "Pheno 1": {
                    "harvests": [
                        {"veg_days": 25, "flower_days": 55},
                    ]
                }
            }
        }
    }
    strain_library._analytics_cache = None

    analytics = strain_library.get_analytics()
    pheno = analytics["strains"]["Strain B"]["phenotypes"]["Pheno 1"]

    assert "avg_dry_weight" not in pheno
    assert "avg_wet_weight" not in pheno
    assert pheno["total_harvests"] == 1


# ---------------------------------------------------------------------------
# websocket_get_event_log – plant_id filter branches (lines 229-233)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_log_skips_event_with_different_plant_id(
    hass: HomeAssistant,
) -> None:
    """Test events with a different plant_id are skipped when filtering by plant_id."""
    connection = MagicMock()
    msg = {"id": 1, "plant_id": "plant_target", "limit": 10}

    session_mock = MagicMock()
    query_mock = MagicMock()
    session_mock.query.return_value = query_mock
    query_mock.filter.return_value = query_mock
    query_mock.join.return_value = query_mock
    query_mock.order_by.return_value = query_mock
    query_mock.limit.return_value = query_mock

    # Event with a different plant_id – should be skipped (lines 230-231)
    e1 = MagicMock()
    e1.time_fired_ts = 1000.0
    d1 = MagicMock()
    d1.shared_data = json.dumps(
        {
            "plant_id": "other_plant",
            "growspace_id": "gs1",
            "category": "watering",
        }
    )
    query_mock.__iter__.return_value = iter([(e1, d1)])

    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=session_mock)
    ctx.__exit__ = MagicMock(return_value=False)

    with (
        patch(
            "custom_components.growspace_manager.websocket.logbook.session_scope",
            return_value=ctx,
        ),
        patch(
            "custom_components.growspace_manager.websocket.logbook.get_instance"
        ) as get_instance_mock,
    ):
        instance = get_instance_mock.return_value

        async def fake_executor(func, *args):
            return func(*args)

        instance.async_add_executor_job.side_effect = fake_executor

        await websocket_get_event_log(hass, connection, msg)

    connection.send_result.assert_called_once()
    # The filtered event should produce an empty list for all growspaces
    result = connection.send_result.call_args[0][1]
    all_events = [evt for evts in result.values() for evt in evts]
    assert all_events == []


@pytest.mark.asyncio
async def test_event_log_skips_shared_event_with_different_growspace(
    hass: HomeAssistant,
) -> None:
    """Test shared events (no plant_id) from a different growspace are skipped."""
    connection = MagicMock()
    msg = {
        "id": 1,
        "plant_id": "plant_target",
        "growspace_id": "gs_target",
        "limit": 10,
    }

    session_mock = MagicMock()
    query_mock = MagicMock()
    session_mock.query.return_value = query_mock
    query_mock.filter.return_value = query_mock
    query_mock.join.return_value = query_mock
    query_mock.order_by.return_value = query_mock
    query_mock.limit.return_value = query_mock

    # Event with no plant_id but a different growspace_id – lines 232-233
    e1 = MagicMock()
    e1.time_fired_ts = 1000.0
    d1 = MagicMock()
    d1.shared_data = json.dumps(
        {
            "growspace_id": "other_gs",
            "category": "watering",
        }
    )
    query_mock.__iter__.return_value = iter([(e1, d1)])

    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=session_mock)
    ctx.__exit__ = MagicMock(return_value=False)

    with (
        patch(
            "custom_components.growspace_manager.websocket.logbook.session_scope",
            return_value=ctx,
        ),
        patch(
            "custom_components.growspace_manager.websocket.logbook.get_instance"
        ) as get_instance_mock,
    ):
        instance = get_instance_mock.return_value

        async def fake_executor(func, *args):
            return func(*args)

        instance.async_add_executor_job.side_effect = fake_executor

        await websocket_get_event_log(hass, connection, msg)

    connection.send_result.assert_called_once()
    result = connection.send_result.call_args[0][1]
    all_events = [evt for evts in result.values() for evt in evts]
    assert all_events == []


# ---------------------------------------------------------------------------
# websocket_get_ec_ramp_curves – exception path (lines 573-575)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_websocket_get_ec_ramp_curves_exception(
    hass: HomeAssistant,
) -> None:
    """Test that exceptions in websocket_get_ec_ramp_curves are reported via send_error."""
    connection = MagicMock()
    msg = {"id": 42}

    with patch(
        "custom_components.growspace_manager.websocket.nutrients.GrowspaceCoordinator"
    ) as mock_coord_cls:
        mock_coord_cls.get_for_service_call.side_effect = Exception("DB error")

        websocket_get_ec_ramp_curves(hass, connection, msg)

    connection.send_error.assert_called_once_with(42, "unknown_error", "DB error")
    connection.send_result.assert_not_called()


# ---------------------------------------------------------------------------
# GrowspaceCoordinator.get_any / ServiceCoordinatorLocator.get_any success
# (coordinator.py:147, service_coordinator_locator.py:99)
# ---------------------------------------------------------------------------


def test_growspace_coordinator_get_any_success() -> None:
    """Test GrowspaceCoordinator.get_any returns first loaded coordinator."""
    fake_coordinator = MagicMock()
    mock_entry = MagicMock()
    mock_entry.state = ConfigEntryState.LOADED
    mock_entry.runtime_data = fake_coordinator

    hass = MagicMock()
    hass.config_entries.async_entries.return_value = [mock_entry]

    result = GrowspaceCoordinator.get_any(hass)
    assert result is fake_coordinator


# ---------------------------------------------------------------------------
# GrowspaceCoordinator.get_plant and get_growspace (coordinator.py:1426, 1430)
# ---------------------------------------------------------------------------


def test_coordinator_get_plant_delegates_to_repository() -> None:
    """Test get_plant returns what the data_repository returns."""
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test"
    entry.async_create_background_task = MagicMock()
    entry.data = {}
    entry.options = {}

    coordinator = GrowspaceCoordinator(hass, entry, data={}, strain_library=MagicMock())
    plant = MagicMock()
    coordinator.data_repository = MagicMock()
    coordinator.data_repository.get_plant.return_value = plant

    result = coordinator.services.plants.get_plant("p1")
    assert result is plant
    coordinator.data_repository.get_plant.assert_called_once_with("p1")


def test_coordinator_get_growspace_delegates_to_repository() -> None:
    """Test get_growspace returns what the data_repository returns."""
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test"
    entry.async_create_background_task = MagicMock()
    entry.data = {}
    entry.options = {}

    coordinator = GrowspaceCoordinator(hass, entry, data={}, strain_library=MagicMock())
    growspace = MagicMock()
    coordinator.data_repository = MagicMock()
    coordinator.data_repository.get_growspace.return_value = growspace

    result = coordinator.services.growspaces.get_growspace("gs1")
    assert result is growspace
    coordinator.data_repository.get_growspace.assert_called_once_with("gs1")
