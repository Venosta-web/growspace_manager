"""Shared test fixtures and utilities for growspace_manager tests."""

from __future__ import annotations
import sys
from unittest.mock import MagicMock

# Inject Session into builtins to resolve Python 3.14 NameError when evaluating type annotations at runtime
import builtins
try:
    from sqlalchemy.orm import Session
    builtins.Session = Session
except ImportError:
    class DummySession:
        pass
    builtins.Session = DummySession

# Must precede any imports that pull in these dependencies
sys.modules["turbojpeg"] = MagicMock()
sys.modules["fpdf"] = MagicMock()
sys.modules["homeassistant.components.ai_task"] = MagicMock()

# Load Home Assistant core test fixtures (hass, mock_recorder, freezer, etc.)
# This must appear BEFORE other Home Assistant imports to avoid recorder initialization issues.
import importlib.util as _ilu
import pathlib as _pathlib

_ha_conftest_spec = _ilu.find_spec("tests.conftest")
_is_ha_core = (
    _ha_conftest_spec is not None
    and _ha_conftest_spec.origin is not None
    and _pathlib.Path(_ha_conftest_spec.origin).resolve()
    != _pathlib.Path(__file__).resolve()
)
if _is_ha_core:
    pytest_plugins = ["tests.conftest"]

from typing import Any
from unittest.mock import AsyncMock, patch

from syrupy.assertion import SnapshotAssertion

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

# Patch DeviceRegistry initialization bug in pytest-homeassistant-custom-component
_orig_async_load = dr.async_load


async def patched_async_load(hass: HomeAssistant, *args, **kwargs):
    """Ensure async_setup is called before async_load to initialize _loaded_event."""
    if dr.DATA_REGISTRY not in hass.data:
        dr.async_get(hass).async_setup()
    return await _orig_async_load(hass, *args, **kwargs)


dr.async_load = patched_async_load

# Prevent timezone leakage from Home Assistant core tests
_orig_set_default_time_zone = dt_util.set_default_time_zone


def patched_set_default_time_zone(time_zone):
    """Enforce UTC and ignore US/Pacific attempts from HA core fixtures."""
    if time_zone == dt_util.UTC:
        _orig_set_default_time_zone(time_zone)


dt_util.set_default_time_zone = patched_set_default_time_zone

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def enforce_utc_timezone():
    """Ensure timezone is UTC before and after each test.

    This works in tandem with our monkeypatch to prevent leaks.
    """
    dt_util.set_default_time_zone(dt_util.UTC)
    yield
    dt_util.set_default_time_zone(dt_util.UTC)


@pytest.fixture
def snapshot(snapshot: Any) -> Any:
    """Override snapshot fixture to always use HomeAssistantSnapshotExtension."""
    if isinstance(snapshot, MagicMock) or snapshot == Any:
        return snapshot
    try:
        from pytest_homeassistant_custom_component.syrupy import (  # noqa: PLC0415
            HomeAssistantSnapshotExtension,
        )
    except ImportError:
        try:
            from tests.syrupy import HomeAssistantSnapshotExtension  # noqa: PLC0415
        except ImportError:
            return snapshot
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
    from custom_components.growspace_manager.const import DOMAIN  # noqa: PLC0415
    from tests.common import MockConfigEntry  # noqa: PLC0415

    return MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={},
        title="Growspace Manager",
        unique_id="growspace_manager_test",
    )


@pytest.fixture
async def init_integration(
    hass, mock_config_entry, enable_custom_integrations, recorder_mock
):
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


def _stop_scheduler(obj: Any, attr: str) -> None:
    """Helper to safely call async_stop on an attribute."""
    import contextlib
    from unittest.mock import Mock
    if hasattr(obj, attr) and (scheduler := getattr(obj, attr)):
        if isinstance(scheduler, Mock):
            return
        if isinstance(getattr(scheduler, "async_stop", None), Mock):
            return
        with contextlib.suppress(Exception):
            scheduler.async_stop()


def _cancel_debouncer(obj: Any) -> None:
    """Helper to safely cancel a debouncer."""
    import contextlib
    from unittest.mock import Mock
    if hasattr(obj, "_debounced_refresh") and (debouncer := getattr(obj, "_debounced_refresh")):
        if isinstance(debouncer, Mock):
            return
        if isinstance(getattr(debouncer, "async_cancel", None), Mock):
            return
        with contextlib.suppress(Exception):
            debouncer.async_cancel()


def _close_unawaited_coro(mock_func: Any) -> None:
    """Helper to safely close unawaited mocked coroutines."""
    import contextlib
    from unittest.mock import Mock
    if isinstance(mock_func, Mock):
        for call in mock_func.call_args_list:
            for arg in call[0]:
                if hasattr(arg, "close"):
                    with contextlib.suppress(Exception):
                        arg.close()
            for arg in call[1].values():
                if hasattr(arg, "close"):
                    with contextlib.suppress(Exception):
                        arg.close()


@pytest.fixture(autouse=True)
def cleanup_coordinators(request):
    """Track and automatically clean up all GrowspaceCoordinator instances and their unawaited mock coroutines."""
    import asyncio
    import contextlib
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

    coordinators = []
    original_init = GrowspaceCoordinator.__init__

    def patched_init(self, *args, **kwargs):
        coordinators.append(self)
        original_init(self, *args, **kwargs)

    GrowspaceCoordinator.__init__ = patched_init

    yield

    GrowspaceCoordinator.__init__ = original_init

    # Teardown: Stop all schedulers, close unawaited coroutines, and run async_shutdown
    async def shutdown_all():
        for coord in coordinators:
            # 1. Stop all internal schedulers/monitors to release timers immediately
            for attr in ("briefing_scheduler", "vision_scheduler", "photoperiod_checker", "alert_monitor"):
                _stop_scheduler(coord, attr)

            # Cancel debouncer on the main coordinator
            _cancel_debouncer(coord)

            # Cancel debouncers and shut down irrigation coordinators
            if hasattr(coord, "irrigation_coordinators") and coord.irrigation_coordinators:
                for irr_coord in coord.irrigation_coordinators.values():
                    _cancel_debouncer(irr_coord)
                    with contextlib.suppress(Exception):
                        await irr_coord.async_shutdown()

            # Cancel debouncers and shut down dehumidifier coordinators
            if hasattr(coord, "subsystem_manager") and coord.subsystem_manager:
                sub_mgr = coord.subsystem_manager
                if hasattr(sub_mgr, "dehumidifier_coordinators") and sub_mgr.dehumidifier_coordinators:
                    for deh_coord in sub_mgr.dehumidifier_coordinators.values():
                        _cancel_debouncer(deh_coord)
                        with contextlib.suppress(Exception):
                            await deh_coord.async_shutdown()

            # 2. Close any unawaited coroutines passed to mocked async_create_background_task on the coordinator's entry
            if hasattr(coord, "config_entry") and coord.config_entry:
                if hasattr(coord.config_entry, "async_create_background_task"):
                    _close_unawaited_coro(coord.config_entry.async_create_background_task)

            # 3. Call full async_shutdown
            with contextlib.suppress(Exception):
                await coord.async_shutdown()

        # 4. Clean up any mocked task/job creators on the hass fixture
        if "hass" in request.fixturenames:
            with contextlib.suppress(Exception):
                hass_obj = request.getfixturevalue("hass")
                for attr_name in ("async_create_background_task", "async_create_task", "async_add_job", "async_add_executor_job"):
                    if hasattr(hass_obj, attr_name):
                        _close_unawaited_coro(getattr(hass_obj, attr_name))

        # 5. Clean up any unawaited coroutines created by AsyncMock or any other Mock in gc
        import gc
        for obj in list(gc.get_objects()):
            if type(obj).__name__ == "coroutine":
                if "AsyncMockMixin._execute_mock_call" in str(obj) or "mock" in str(obj).lower():
                    with contextlib.suppress(Exception):
                        obj.close()

    loop = asyncio.get_event_loop()
    if loop.is_running():
        loop.create_task(shutdown_all())
    else:
        with contextlib.suppress(Exception):
            loop.run_until_complete(shutdown_all())

