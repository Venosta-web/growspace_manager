"""Tests for CirculationFanConfig config flow."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.models import EnvironmentConfig, Growspace
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from tests.common import MockConfigEntry, mock_component


@pytest.fixture
def mock_setup_entry():
    with patch(
        "custom_components.growspace_manager.async_setup_entry", return_value=True
    ) as mock_setup:
        yield mock_setup


def _make_entry_with_growspace(
    hass: HomeAssistant,
    env_config: EnvironmentConfig | None = None,
) -> tuple[MockConfigEntry, MagicMock, MagicMock]:
    """Set up a config entry with a single growspace, return (entry, coordinator, growspace)."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        data={"name": "Test"},
        entry_id="test_entry",
    )

    mock_coordinator = MagicMock()
    mock_coordinator.services = MagicMock()

    mock_growspace = Growspace(
        id="gs1",
        name="Test GS",
        environment_config=env_config or EnvironmentConfig(),
    )
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    mock_coordinator.services.growspaces.get_sorted_growspace_options.return_value = [
        ("gs1", "Test GS")
    ]
    mock_coordinator.services.growspaces.get_growspace.return_value = mock_growspace
    mock_coordinator.services.save = AsyncMock()
    mock_coordinator.services.request_refresh = AsyncMock()
    mock_coordinator.async_refresh = AsyncMock()
    mock_coordinator._subsystem_manager.get_circulation_fan_controller.return_value = (
        None
    )
    mock_coordinator._subsystem_manager.get_exhaust_fan_controller.return_value = None
    mock_coordinator._subsystem_manager.get_growlight_controller.return_value = None

    entry.runtime_data = mock_coordinator
    entry.add_to_hass(hass)

    return entry, mock_coordinator, mock_growspace


async def _navigate_to_env_step1(hass: HomeAssistant, entry: MockConfigEntry) -> dict:
    """Navigate through options flow to the configure_environment step."""
    mock_component(hass, "recorder")

    result = await hass.config_entries.options.async_init(entry.entry_id)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"action": "configure_environment"}
    )

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"growspace_id": "gs1"}
    )
    assert result["step_id"] == "configure_environment"
    return result


async def test_enable_fan_controller_humidity_mode_saves_config(
    hass: HomeAssistant, mock_setup_entry: MagicMock, enable_custom_integrations: None
) -> None:
    """Enabling fan controller with humidity mode saves CirculationFanConfig."""
    entry, coordinator, growspace = _make_entry_with_growspace(hass)
    result = await _navigate_to_env_step1(hass, entry)

    # Submit env step 1 with configure_fan_controller=True
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "configure_fan_controller": True,
            "control_dehumidifier": False,
            "configure_dehumidifier": False,
            "configure_humidifier": False,
        },
    )

    # Should land on configure_fan_controller step
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "configure_fan_controller"

    # Submit fan controller base settings
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "enabled": True,
            "regulation_mode": "humidity",
            "min_speed": 20,
            "max_speed": 80,
            "wind_enabled": False,
        },
    )

    # Humidity mode: should show humidity target/tolerance step
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "configure_fan_humidity"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "humidity_target": 65.0,
            "humidity_tolerance": 5.0,
        },
    )

    # wind_enabled=False → skip wind step → sensor placement (no sensors to place)
    assert result["type"] == FlowResultType.CREATE_ENTRY

    # Verify CirculationFanConfig was saved
    fan_cfg = growspace.environment_config.circulation_fan_config
    assert fan_cfg.enabled is True
    assert fan_cfg.regulation_mode == "humidity"
    assert fan_cfg.min_speed == 20
    assert fan_cfg.max_speed == 80
    assert fan_cfg.humidity_target == 65.0
    assert fan_cfg.humidity_tolerance == 5.0
    assert fan_cfg.wind_enabled is False

    assert coordinator.services.save.called


async def test_configure_fan_controller_false_skips_fan_steps(
    hass: HomeAssistant, mock_setup_entry: MagicMock, enable_custom_integrations: None
) -> None:
    """When configure_fan_controller is False, fan controller steps are skipped."""
    entry, coordinator, growspace = _make_entry_with_growspace(hass)
    result = await _navigate_to_env_step1(hass, entry)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "configure_fan_controller": False,
            "control_dehumidifier": False,
            "configure_dehumidifier": False,
            "configure_humidifier": False,
        },
    )

    # No sensors to place and fan controller skipped → complete immediately
    assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_vpd_mode_shows_critical_temp_step(
    hass: HomeAssistant, mock_setup_entry: MagicMock, enable_custom_integrations: None
) -> None:
    """VPD regulation mode routes through configure_fan_vpd step for critical temps."""
    entry, coordinator, growspace = _make_entry_with_growspace(hass)
    result = await _navigate_to_env_step1(hass, entry)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "configure_fan_controller": True,
            "control_dehumidifier": False,
            "configure_dehumidifier": False,
            "configure_humidifier": False,
        },
    )
    assert result["step_id"] == "configure_fan_controller"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "enabled": True,
            "regulation_mode": "vpd",
            "min_speed": 10,
            "max_speed": 90,
            "wind_enabled": False,
        },
    )

    # VPD mode → vpd step (target, tolerance, critical temps)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "configure_fan_vpd"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "vpd_target": 1.2,
            "vpd_tolerance": 0.15,
            "critical_temp_low": 18.0,
            "critical_temp_high": 32.0,
            "critical_temp_hysteresis": 1.5,
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY

    fan_cfg = growspace.environment_config.circulation_fan_config
    assert fan_cfg.regulation_mode == "vpd"
    assert fan_cfg.vpd_target == 1.2
    assert fan_cfg.vpd_tolerance == 0.15
    assert fan_cfg.critical_temp_low == 18.0
    assert fan_cfg.critical_temp_high == 32.0
    assert fan_cfg.critical_temp_hysteresis == 1.5


async def test_humidity_mode_does_not_show_vpd_step(
    hass: HomeAssistant, mock_setup_entry: MagicMock, enable_custom_integrations: None
) -> None:
    """Humidity mode does NOT route through the VPD critical-temp step."""
    entry, coordinator, growspace = _make_entry_with_growspace(hass)
    result = await _navigate_to_env_step1(hass, entry)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "configure_fan_controller": True,
            "control_dehumidifier": False,
            "configure_dehumidifier": False,
            "configure_humidifier": False,
        },
    )

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "enabled": True,
            "regulation_mode": "humidity",
            "min_speed": 20,
            "max_speed": 80,
            "wind_enabled": False,
        },
    )

    # Humidity → humidity step, NOT vpd step
    assert result["step_id"] == "configure_fan_humidity"


async def test_wind_enabled_shows_wind_step(
    hass: HomeAssistant, mock_setup_entry: MagicMock, enable_custom_integrations: None
) -> None:
    """When wind_enabled=True the wind configuration step is shown."""
    entry, coordinator, growspace = _make_entry_with_growspace(hass)
    result = await _navigate_to_env_step1(hass, entry)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "configure_fan_controller": True,
            "control_dehumidifier": False,
            "configure_dehumidifier": False,
            "configure_humidifier": False,
        },
    )

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "enabled": True,
            "regulation_mode": "humidity",
            "min_speed": 20,
            "max_speed": 80,
            "wind_enabled": True,
        },
    )
    assert result["step_id"] == "configure_fan_humidity"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"humidity_target": 60.0, "humidity_tolerance": 5.0},
    )

    # wind_enabled=True → wind step shown
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "configure_fan_wind"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"wind_period_seconds": 120, "wind_amplitude_pct": 25},
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY

    fan_cfg = growspace.environment_config.circulation_fan_config
    assert fan_cfg.wind_enabled is True
    assert fan_cfg.wind_period_seconds == 120
    assert fan_cfg.wind_amplitude_pct == 25


async def test_min_speed_greater_than_max_speed_raises_error(
    hass: HomeAssistant, mock_setup_entry: MagicMock, enable_custom_integrations: None
) -> None:
    """min_speed >= max_speed is invalid and returns a form error."""
    entry, coordinator, growspace = _make_entry_with_growspace(hass)
    result = await _navigate_to_env_step1(hass, entry)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "configure_fan_controller": True,
            "control_dehumidifier": False,
            "configure_dehumidifier": False,
            "configure_humidifier": False,
        },
    )

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "enabled": True,
            "regulation_mode": "humidity",
            "min_speed": 80,
            "max_speed": 20,
            "wind_enabled": False,
        },
    )

    # Should re-display the form with an error
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "configure_fan_controller"
    assert "base" in result.get("errors", {})
