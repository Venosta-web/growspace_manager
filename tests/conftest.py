"""Shared test fixtures and utilities for growspace_manager tests."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.growspace_manager.binary_sensor import (
    SENSOR_TYPES,
    BayesianEnvironmentSensor,
)
from custom_components.growspace_manager.models import EnvironmentConfig


def create_test_sensor(
    coordinator: MagicMock,
    growspace_id: str,
    sensor_type: str,
    strategy_class: type,
    env_config: EnvironmentConfig | None = None,
) -> BayesianEnvironmentSensor:
    """Helper to create a BayesianEnvironmentSensor for testing with all dependencies."""
    if env_config is None:
        env_config = coordinator.growspaces[growspace_id].environment_config

    description = next(d for d in SENSOR_TYPES if d.sensor_type == sensor_type)

    return BayesianEnvironmentSensor(
        coordinator=coordinator,
        growspace_id=growspace_id,
        env_config=env_config,
        description=description,
        strategy_class=strategy_class,
        # Inject dependencies
        get_growspace=lambda gid: coordinator.growspaces.get(gid),
        get_plants=coordinator.get_growspace_plants,
        add_event=coordinator.add_event,
        notification_manager=coordinator.notification_manager,
        strain_library=coordinator.strain_library,
        options=coordinator.options,
    )
