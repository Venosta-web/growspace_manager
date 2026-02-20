"""Snapshot tests for Growspace Manager presentation view models."""

from unittest.mock import MagicMock, patch

import pytest
from syrupy.assertion import SnapshotAssertion

from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    GrowspaceType,
    IrrigationConfig,
    Plant,
    PlantGenetics,
)
from custom_components.growspace_manager.presentation.growspace_view_model import (
    GrowspaceViewModelBuilder,
)
from homeassistant.core import HomeAssistant


@pytest.fixture
def builder(hass: HomeAssistant) -> GrowspaceViewModelBuilder:
    """Fixture for GrowspaceViewModelBuilder."""
    return GrowspaceViewModelBuilder(hass)


def test_growspace_view_model_snapshot(
    hass: HomeAssistant, builder: GrowspaceViewModelBuilder, snapshot: SnapshotAssertion
) -> None:
    """Test GrowspaceViewModelBuilder.build output matches snapshot."""
    env_config = EnvironmentConfig(
        temperature_sensor="sensor.temp",
        humidity_sensor="sensor.hum",
        vpd_sensor="sensor.vpd",
        control_dehumidifier=True,
    )
    irr_config = IrrigationConfig(
        irrigation_pump_entity="switch.pump",
        drain_pump_entity="switch.drain",
        irrigation_duration=120,
    )
    growspace = Growspace(
        id="gs_test",
        name="Test Room",
        rows=2,
        plants_per_row=2,
        growspace_type=GrowspaceType.VEG,
        environment_config=env_config,
        irrigation_config=irr_config,
    )

    plant1 = Plant(
        plant_id="p1",
        growspace_id="gs_test",
        row=1,
        col=1,
        stage="veg",
        genetics=PlantGenetics(strain_name="Northern Lights"),
    )
    plants = [plant1]

    # Mock helpers
    with (
        patch.object(
            builder.entity_queries,
            "lookup_overview_entity_id",
            return_value="sensor.gs_test_overview",
        ),
        patch.object(
            builder.entity_queries,
            "lookup_plant_entity_id",
            return_value="sensor.p1_entity",
        ),
    ):
        result = builder.build(
            growspace=growspace,
            plants=plants,
            biological_metrics={"daily_avg_temp": 24.5, "daily_avg_hum": 55.0},
            max_veg_days=15,
            max_flower_days=-1,
        )

        # Sort keys or exclude timestamp if it were here (it's not yet)
        assert result == snapshot


def test_plant_view_model_snapshot(
    hass: HomeAssistant, builder: GrowspaceViewModelBuilder, snapshot: SnapshotAssertion
) -> None:
    """Test PlantViewModelBuilder.build output matches snapshot."""
    plant = Plant(
        plant_id="p1",
        growspace_id="gs_test",
        row=1,
        col=2,
        stage="flower",
        genetics=PlantGenetics(strain_name="Blueberry", phenotype_name="Sweet Berry"),
    )

    # Building a plant view model typically happens via the growspace builder or directly
    result = builder.plant_builder.build(plant, entity_id="sensor.p1_entity")

    assert result == snapshot
