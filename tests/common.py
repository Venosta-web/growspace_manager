"""Shim exposing Home Assistant test helpers via the installed package.

Tests written against HA core's ``tests.common`` use symbols like
``MockConfigEntry`` and ``async_capture_events``.  When running in the
standalone growspace_manager repo the HA core ``tests/`` tree is not
available, but ``pytest-homeassistant-custom-component`` ships the same
helpers under ``pytest_homeassistant_custom_component.common``.

Re-exporting everything here allows all existing ``from tests.common import
...`` statements to work without modification in both environments.
"""

from pytest_homeassistant_custom_component.common import (  # noqa: F401
    MockConfigEntry,
    async_capture_events,
    mock_component,
)
