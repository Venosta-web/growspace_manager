"""Shared test fixtures and utilities for growspace_manager tests."""

from __future__ import annotations

import importlib.util as _ilu
import pathlib as _pathlib
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from syrupy.assertion import SnapshotAssertion

# Must precede any custom_components import that pulls in fpdf/turbojpeg.
sys.modules["turbojpeg"] = MagicMock()
sys.modules["fpdf"] = MagicMock()

# Load Home Assistant core test fixtures (hass, mock_recorder, freezer, etc.)
# This must appear AFTER the sys.modules patching above.
#
# When running inside the HA core dev environment (PYTHONPATH includes core/),
# load HA's own conftest to get the real fixture implementations.
# In the standalone CI repo pytest-homeassistant-custom-component registers
# the same fixtures automatically via its entry-point plugin – we only
# load tests.conftest when the HA core source tree is on sys.path.
#
# We detect "real HA core" by checking that find_spec("tests.conftest") does
# NOT resolve to this very file (which would happen when the standalone repo's
# own tests/ package is on the path).
_ha_conftest_spec = _ilu.find_spec("tests.conftest")
_is_ha_core = (
    _ha_conftest_spec is not None
    and _ha_conftest_spec.origin is not None
    # Ensure we didn't just find our *own* conftest (vendored repo).
    and _pathlib.Path(_ha_conftest_spec.origin).resolve()
    != _pathlib.Path(__file__).resolve()
)
if _is_ha_core:
    pytest_plugins = ["tests.conftest"]

import pytest  # noqa: E402


@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Override snapshot fixture to always use HomeAssistantSnapshotExtension.

    This ensures snapshots are stored in 'snapshots/' (not '__snapshots__/')
    consistently in both HA core and standalone CI environments.
    """
    try:
        from pytest_homeassistant_custom_component.syrupy import (  # noqa: PLC0415
            HomeAssistantSnapshotExtension,
        )
    except ImportError:
        from tests.syrupy import HomeAssistantSnapshotExtension  # noqa: PLC0415
    return snapshot.use_extension(HomeAssistantSnapshotExtension)


@pytest.fixture
def mock_recorder_before_hass(async_test_recorder) -> None:
    """Set up recorder before the hass fixture starts.

    This overrides the no-op from HA's conftest so the recorder is
    ready when hass is created. Required because growspace_manager
    declares 'recorder' as a manifest dependency.
    """


@pytest.fixture
def mock_config_entry():
    """Return a standard MockConfigEntry for the integration."""
    from tests.common import MockConfigEntry  # noqa: PLC0415

    from custom_components.growspace_manager.const import DOMAIN  # noqa: PLC0415

    return MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={},
        title="Growspace Manager",
        unique_id="growspace_manager_test",
    )


@pytest.fixture
async def init_integration(hass, mock_config_entry, enable_custom_integrations, recorder_mock):
    """Set up the real integration through the HA config entry lifecycle.

    Runs the actual async_setup_entry / async_unload_entry, so
    entry.runtime_data holds a live GrowspaceCoordinator.

    Requires enable_custom_integrations so HA's loader will scan the
    custom_components/ directory instead of treating it as empty.

    Only two things are stubbed out:
    - hass.http: the test HA instance never starts the HTTP server.
    - async_register_sidebar_panel: requires the frontend component.
    """
    mock_config_entry.add_to_hass(hass)

    mock_http = MagicMock()
    mock_http.async_register_static_paths = AsyncMock()
    hass.http = mock_http

    with patch(
        "custom_components.growspace_manager.async_register_sidebar_panel",
        new_callable=AsyncMock,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    yield mock_config_entry

    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()


def create_test_sensor(
    coordinator: Any,
    growspace_id: str,
    sensor_type: str,
    strategy_class: type,
    env_config: Any | None = None,
) -> Any:
    """Helper to create a BayesianEnvironmentSensor for testing with all dependencies."""
    from custom_components.growspace_manager.binary_sensor import (  # noqa: PLC0415
        SENSOR_TYPES,
        BayesianEnvironmentSensor,
    )

    if env_config is None:
        env_config = coordinator.growspaces[growspace_id].environment_config

    description = next(d for d in SENSOR_TYPES if d.sensor_type == sensor_type)

    return BayesianEnvironmentSensor(
        coordinator=coordinator,
        growspace_id=growspace_id,
        env_config=env_config,
        description=description,
        strategy_class=strategy_class,
        get_growspace=lambda gid: coordinator.growspaces.get(gid),
        get_plants=coordinator.get_growspace_plants,
        add_event=coordinator.add_event,
        notification_manager=coordinator.notification_manager,
        strain_library=coordinator.strain_library,
        options=coordinator.options,
    )
