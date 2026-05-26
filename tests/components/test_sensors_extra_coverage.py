"""Extra coverage tests for various sensor classes in sensor.py."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.helpers import async_setup_statistics_sensor
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    GrowspaceType,
    SeedBatch,
)
from custom_components.growspace_manager.sensor import (
    CalculatedVpdSensor,
    CropSteeringSensor,
    DLISensor,
    ECTargetSensor,
    EnergyUsageSensor,
    GrowspaceOverviewSensor,
    SeedInventorySensor,
    StrainLibrarySensor,
    VisionCheckupSensor,
    VpdSensor,
    WaterUsageSensor,
    _check_calculated_vpd_sensor,
    _update_growspace_entities,
)
from homeassistant.core import HomeAssistant


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator with necessary data."""
    coordinator = MagicMock()
    coordinator.hass = MagicMock()
    coordinator.last_update_success = True
    coordinator.data = {}
    coordinator.growspaces = {}
    return coordinator


@pytest.fixture
def setup_sensor_for_test():
    """Fixture to set up a sensor with necessary Home Assistant attributes for testing."""

    def _setup(sensor, _coordinator=None):
        # Reuse the coordinator's hass so preconfigured state mocks remain active
        if hasattr(sensor, "coordinator") and hasattr(sensor.coordinator, "hass"):
            sensor.hass = sensor.coordinator.hass
        else:
            sensor.hass = MagicMock()
        sensor.entity_id = "sensor.test_sensor"
        # Ensure platform is mocked to avoid AttributeError: 'NoneType' object has no attribute 'domain'
        sensor.platform = MagicMock()
        sensor.platform.domain = DOMAIN
        # Do not overwrite coordinator if it's already there
        if not hasattr(sensor, "coordinator"):
            sensor.coordinator = MagicMock()
        if not hasattr(sensor.coordinator, "hass"):
            sensor.coordinator.hass = sensor.hass

    return _setup


async def test_dlisensor_attributes(mock_coordinator, setup_sensor_for_test):
    """Test DLISensor attributes and native value."""
    # Mock growspace for attributes lookup
    growspace = MagicMock()
    growspace.growspace_type = GrowspaceType.FLOWER
    growspace.environment_config = EnvironmentConfig(
        dli_target_flower=30.0,
        dli_target_veg=20.0,
    )
    mock_coordinator.growspaces = {"test_id": growspace}

    # DLISensor needs (coordinator, growspace_id, growspace_name)
    sensor = DLISensor(mock_coordinator, "test_id", "Test Grow")
    setup_sensor_for_test(sensor, mock_coordinator)

    # Set internal state
    sensor._accumulated_mol = 25.5
    assert sensor.native_value == 25.5

    # Mock PPFD for attributes
    sensor._get_current_ppfd = MagicMock(return_value=500.0)

    attrs = sensor.extra_state_attributes
    assert attrs["target_dli"] == 30.0
    assert attrs["percentage_of_target"] == 85.0


async def test_energy_usage_sensor(mock_coordinator, setup_sensor_for_test):
    """Test EnergyUsageSensor attributes and native value."""
    # Energy sensor looks up hass.states for energy_sensors
    mock_state = MagicMock()
    mock_state.state = "100.0"
    mock_coordinator.hass.states.get.return_value = mock_state

    # Mock growspace with energy tracking
    growspace = MagicMock()
    growspace.energy_tracking.cycle_start_kwh = 90.0
    growspace.energy_tracking.cycle_start_date = "2024-03-01"
    growspace.environment_config = EnvironmentConfig(
        energy_sensors=["sensor.power"],
        electricity_cost_per_kwh=0.15,
    )
    mock_coordinator.growspaces = {"test_id": growspace}

    sensor = EnergyUsageSensor(mock_coordinator, "test_id", "Test Grow")
    setup_sensor_for_test(sensor, mock_coordinator)

    # 100.0 - 90.0 = 10.0
    assert sensor.native_value == 10.0
    attrs = sensor.extra_state_attributes
    # 10.0 * 0.15 = 1.5
    assert attrs["cost_total"] == 1.5


async def test_water_usage_sensor(mock_coordinator, setup_sensor_for_test):
    """Test WaterUsageSensor attributes and native value."""
    growspace = MagicMock()
    growspace.water_usage.total_liters = 50.0
    growspace.water_usage.cycle_start_date = "2024-03-10"
    growspace.water_usage.daily_readings = []

    mock_coordinator.growspaces = {"test_id": growspace}
    mock_coordinator.get_growspace_plants.return_value = ["plant1", "plant2"]

    sensor = WaterUsageSensor(mock_coordinator, "test_id", "Test Grow")
    setup_sensor_for_test(sensor)

    assert sensor.native_value == 50.0
    attrs = sensor.extra_state_attributes
    assert "liters_per_plant_per_day" in attrs


async def test_crop_steering_sensor(mock_coordinator, setup_sensor_for_test):
    """Test CropSteeringSensor attributes and native value."""
    # Patch where it is defined to handle local imports
    with patch(
        "custom_components.growspace_manager.crop_steering.get_crop_steering_state"
    ) as mock_get_state:
        mock_state = MagicMock()
        mock_state.score = 0.5
        mock_state.dryback_percent = 15.0
        mock_state.peak_vwc = 80.0
        mock_state.trough_vwc = 65.0
        mock_state.ec_trend = "flat"
        mock_get_state.return_value = mock_state

        sensor = CropSteeringSensor(mock_coordinator, "test_id", "Test Grow")
        setup_sensor_for_test(sensor, mock_coordinator)

        assert sensor.native_value == 0.5
        attrs = sensor.extra_state_attributes
        assert attrs["steering_mode"] == "generative"


async def test_ec_target_sensor(mock_coordinator, setup_sensor_for_test):
    """Test ECTargetSensor attributes and native value."""
    sensor = ECTargetSensor(mock_coordinator, "test_id", "Test Grow")
    setup_sensor_for_test(sensor)

    # Mock _get_active_curve
    mock_curve = MagicMock()
    mock_point = MagicMock()
    mock_point.week = 1
    mock_point.ec_min = 2.0
    mock_point.ec_max = 2.4
    mock_curve.points = [mock_point]
    mock_curve.stage = "flower"
    mock_curve.name = "Standard"

    sensor._get_active_curve = MagicMock(return_value=mock_curve)
    sensor._get_current_week = MagicMock(return_value=1)

    assert sensor.native_value == 2.2  # Midpoint of 2.0 and 2.4


async def test_vision_checkup_sensor(mock_coordinator, setup_sensor_for_test):
    """Test VisionCheckupSensor with and without history."""
    sensor = VisionCheckupSensor(mock_coordinator, "test_id", "Test Grow")
    setup_sensor_for_test(sensor)

    # Mock growspace in coordinator
    growspace = MagicMock()
    growspace.vision_checkup_history = []
    mock_coordinator.growspaces = {"test_id": growspace}

    # 1. Test with empty history
    assert sensor.native_value is None
    assert sensor.extra_state_attributes["total_checkups"] == 0

    # 2. Test with populated history
    mock_result = MagicMock()
    mock_result.timestamp = "2024-03-20T10:00:00"
    mock_result.severity = "healthy"
    mock_result.analysis = "All good"
    mock_result.issues_detected = []
    mock_result.recommendations = []

    growspace.vision_checkup_history = [mock_result]

    assert sensor.native_value == "healthy"
    attrs = sensor.extra_state_attributes
    assert attrs["total_checkups"] == 1
    assert attrs["last_analysis"] == "All good"


async def test_seed_inventory_sensor(mock_coordinator, setup_sensor_for_test):
    """Test SeedInventorySensor attributes and native value."""
    # Use keyword arguments
    batch = SeedBatch(
        batch_id="batch1",
        strain_name="White Widow",
        breeder="Dutch Passion",
        quantity=5,
        acquisition_date="2024-01-01",
        generation="F1",
        lineage="lineage",
        notes="notes",
    )

    mock_genetics = MagicMock()
    mock_genetics.get_total_seed_count.return_value = 5
    mock_genetics.seed_batches = {"batch1": batch}
    mock_coordinator.genetics_manager = mock_genetics

    sensor = SeedInventorySensor(mock_coordinator)
    setup_sensor_for_test(sensor, mock_coordinator)

    assert sensor.native_value == 5
    attrs = sensor.extra_state_attributes
    assert len(attrs["seed_batches"]) == 1
    assert attrs["seed_batches"][0]["strain_name"] == "White Widow"


async def test_calculated_vpd_sensor(mock_coordinator, setup_sensor_for_test):
    """Test CalculatedVpdSensor logic."""
    sensor = CalculatedVpdSensor(
        coordinator=mock_coordinator,
        growspace_id="test_grow",
        growspace_name="Test Grow",
        temp_sensor="sensor.temp",
        humidity_sensor="sensor.hum",
    )
    setup_sensor_for_test(sensor, mock_coordinator)

    # Mock states
    temp_state = MagicMock()
    temp_state.state = "25.0"  # Celsius
    hum_state = MagicMock()
    hum_state.state = "50.0"  # %

    def side_effect(entity_id):
        if entity_id == "sensor.temp":
            return temp_state
        if entity_id == "sensor.hum":
            return hum_state
        return None

    mock_coordinator.hass.states.get.side_effect = side_effect

    # VPD calculation should produce a value
    val = sensor.native_value
    assert isinstance(val, (float, int))
    assert val > 0


async def test_vpd_fallback_logic(mock_coordinator, setup_sensor_for_test):
    """Test _check_calculated_vpd_sensor fallback conditions."""
    # 1. Test when vpd_sensor is already set in env_config
    env_config = EnvironmentConfig(vpd_sensor="sensor.existing_vpd")
    growspace = Growspace(
        id="test_grow",
        name="Test Grow",
        environment_config=env_config,
    )

    result = _check_calculated_vpd_sensor(mock_coordinator, growspace)
    assert isinstance(result, list)

    # 2. Test when temperature or humidity sensors are missing
    env_config_missing = EnvironmentConfig(
        temperature_sensor=None, humidity_sensor=None
    )
    growspace_missing = Growspace(
        id="test_grow",
        name="Test Grow",
        environment_config=env_config_missing,
    )
    result = _check_calculated_vpd_sensor(mock_coordinator, growspace_missing)
    assert len(result) == 0

    # 3. Test when both are present - should return a new CalculatedVpdSensor
    env_config_present = EnvironmentConfig(
        temperature_sensor="sensor.temp", humidity_sensor="sensor.hum"
    )
    growspace_present = Growspace(
        id="test_grow",
        name="Test Grow",
        environment_config=env_config_present,
    )

    result = _check_calculated_vpd_sensor(mock_coordinator, growspace_present)
    assert len(result) > 0
    # CalculatedVpdSensor stores coordinator as _coordinator
    # CalculatedVpdSensor stores coordinator as _coordinator
    assert result[0]._coordinator == mock_coordinator


@pytest.mark.asyncio
async def test_seed_inventory_sensor_attributes_full(setup_sensor_for_test):
    """Test SeedInventorySensor attributes with actual seed batch."""
    coordinator = MagicMock()
    batch = SeedBatch(
        batch_id="batch1",
        strain_name="Strain A",
        breeder="Source A",
        quantity=10,
        acquisition_date=date.today().isoformat(),
        generation="F1",
        lineage="None",
        notes="Some notes",
    )
    coordinator.genetics_manager.seed_batches = {"batch1": batch}
    coordinator.get_growspace_plants.return_value = []

    sensor = SeedInventorySensor(coordinator)
    setup_sensor_for_test(sensor)

    attrs = sensor.extra_state_attributes
    # In sensor.py, it's seed_batches
    assert len(attrs["seed_batches"]) == 1
    assert attrs["seed_batches"][0]["strain_name"] == "Strain A"
    assert attrs["seed_batches"][0]["notes"] == "Some notes"


async def test_dli_sensor_attributes_full(setup_sensor_for_test):
    """Test DLISensor attributes."""
    coordinator = MagicMock()
    growspace = MagicMock()

    growspace.growspace_type = GrowspaceType.VEG
    growspace.environment_config.dli_target_veg = 30.0
    growspace.environment_config.veg_day_hours = 18.0
    coordinator.growspaces = {"gs1": growspace}

    sensor = DLISensor(coordinator, "gs1", "Growspace 1")
    setup_sensor_for_test(sensor)

    sensor._accumulated_mol = 15.5
    sensor._photoperiod = 12.0
    sensor._last_reset_date = str(date.today())

    attrs = sensor.extra_state_attributes
    assert attrs["target_dli"] == 30.0
    assert attrs["accumulated_dli"] == 15.5
    assert attrs["photoperiod"] == 12.0
    assert attrs["last_reset"] is not None


@pytest.mark.asyncio
async def test_vpd_sensor_added_to_hass_weather(setup_sensor_for_test):
    """Test VpdSensor.async_added_to_hass with weather entity."""
    coordinator = MagicMock()
    sensor = VpdSensor(
        coordinator, "outside", "Outside VPD", "weather.home", None, None
    )
    setup_sensor_for_test(sensor)

    with patch(
        "custom_components.growspace_manager.sensor.vpd.async_track_state_change_event"
    ) as mock_track:
        await sensor.async_added_to_hass()
        mock_track.assert_called_once()
        assert mock_track.call_args[0][1] == ["weather.home"]


async def test_strain_library_sensor_attributes_avg(setup_sensor_for_test):
    """Test StrainLibrarySensor attributes averaging logic."""
    coordinator = MagicMock()
    analytics = {"strains": {"Strain A": {}}, "strain_list": ["Strain A"]}
    coordinator.strain_library.get_analytics.return_value = analytics
    coordinator.strain_library.get_all.return_value = {"Strain A": {}}
    coordinator.services.config.strain_library.get_analytics.return_value = analytics
    coordinator.services.config.strain_library.get_all.return_value = {"Strain A": {}}

    sensor = StrainLibrarySensor(coordinator)
    setup_sensor_for_test(sensor)

    attrs = sensor.extra_state_attributes
    assert attrs["strain_count"] == 1
    assert "Strain A" in attrs["strain_list"]


@pytest.mark.asyncio
async def test_update_growspace_entities_new_vpd(hass: HomeAssistant):
    """Test _update_growspace_entities triggers new calculated VPD sensor task."""

    coordinator = MagicMock()
    config_entry = MagicMock()
    growspace_entities = {}
    calculated_vpd_unique_ids = set()
    async_add_entities = MagicMock()

    gs = MagicMock(id="gs1")
    gs.name = "GS1"
    gs.environment_config = EnvironmentConfig(
        temperature_sensor="sensor.temp", humidity_sensor="sensor.hum"
    )
    coordinator.growspaces = {"gs1": gs}

    with (
        patch(
            "custom_components.growspace_manager.sensor._setup._async_create_derivative_sensors",
            new_callable=AsyncMock,
        ),
        patch("custom_components.growspace_manager.sensor._setup.GrowspaceOverviewSensor"),
    ):
        await _update_growspace_entities(
            hass,
            coordinator,
            config_entry,
            growspace_entities,
            async_add_entities,
            calculated_vpd_unique_ids,
            set(),
        )

    assert async_add_entities.called
    expected_id = f"{DOMAIN}_gs1_calculated_vpd"
    assert expected_id in calculated_vpd_unique_ids


@pytest.mark.asyncio
async def test_setup_statistics_sensor_error(hass: HomeAssistant):
    """Test async_setup_statistics_sensor exception handling."""

    with (
        patch(
            "custom_components.growspace_manager.helpers.async_load_platform",
            side_effect=Exception("Failed"),
        ),
        patch("custom_components.growspace_manager.helpers._LOGGER") as mock_logger,
    ):
        # It should catch it and log it
        await async_setup_statistics_sensor(hass, "sensor.source", "gs1", "GS1", "type")
        mock_logger.error.assert_called()


@pytest.mark.asyncio
async def test_growspace_overview_sensor_added_to_hass_tracking(setup_sensor_for_test):
    """Test GrowspaceOverviewSensor.async_added_to_hass sets up tracking."""
    coordinator = MagicMock()
    # Provide values for ALL trackable sensors to ensure they are found by getattr
    env_config = EnvironmentConfig(
        temperature_sensor="sensor.temp",
        humidity_sensor="sensor.hum",
        vpd_sensor="sensor.vpd",
        soil_moisture_sensor="sensor.soil",
    )
    gs = Growspace(id="gs1", name="GS1", environment_config=env_config)
    coordinator.growspaces = {"gs1": gs}

    sensor = GrowspaceOverviewSensor(coordinator, "gs1", gs)
    setup_sensor_for_test(sensor)

    with patch(
        "custom_components.growspace_manager.sensor.overview.async_track_state_change_event"
    ) as mock_track:
        await sensor.async_added_to_hass()
        mock_track.assert_called_once()


@pytest.mark.asyncio
async def test_check_calculated_vpd_sensor_fallback(
    mock_coordinator, setup_sensor_for_test
):
    """Test _check_calculated_vpd_sensor fallback to singular vpd_sensor."""

    env_config = EnvironmentConfig(vpd_sensor="sensor.my_vpd")
    # Manually set plural to ensure fallback is tested
    env_config.vpd_sensors = []

    gs = Growspace(id="gs1", name="GS1", environment_config=env_config)

    # To hit line 478, vpd_sensors must be empty but vpd_sensor must exist
    result = _check_calculated_vpd_sensor(mock_coordinator, gs)
    assert len(result) == 0  # Should not create because physical VPD exists

    # Now clear vpd_sensor and vpd_sensors to allow creation
    env_config.vpd_sensor = None
    env_config.vpd_sensors = []
    env_config.temperature_sensor = "sensor.temp"
    env_config.humidity_sensor = "sensor.hum"

    result = _check_calculated_vpd_sensor(mock_coordinator, gs)
    assert len(result) > 0
