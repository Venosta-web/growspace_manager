"""ServiceDefinition dataclass — shared by all service modules."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

import voluptuous as vol
from homeassistant.core import SupportsResponse

from custom_components.growspace_manager.const import GrowspaceService


@dataclass
class ServiceDefinition:
    """Bundles everything needed to register one HA service."""

    name: GrowspaceService
    handler: Callable[..., Coroutine[Any, Any, Any]]
    schema: vol.Schema | None = None
    needs_strain_lib: bool = False
    supports_response: SupportsResponse | None = None
