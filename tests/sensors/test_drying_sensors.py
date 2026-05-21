"""Tests for DryingWeightSensor, DryingMoistureSensor, DryingReadyForCureSensor."""

from unittest.mock import MagicMock, PropertyMock

import pytest

from custom_components.growspace_manager.models import (
    DryingData,
    HarvestMetrics,
    MoistureEntry,
    Plant,
    WeightEntry,
)
from custom_components.growspace_manager.sensor import (
    DryingMoistureSensor,
    DryingWeightSensor,
)
from custom_components.growspace_manager.binary_sensor import DryingReadyForCureSensor


def _make_plant(
    plant_id: str = "p1",
    wet_weight: float | None = None,
    weight_log: list[WeightEntry] | None = None,
    moisture_log: list[MoistureEntry] | None = None,
) -> Plant:
    """Build a Plant with optional drying data."""
    plant = Plant(plant_id=plant_id, growspace_id="g1")
    plant.harvest_metrics = HarvestMetrics(wet_weight=wet_weight)
    plant.drying_data = DryingData(
        weight_log=weight_log or [],
        moisture_log=moisture_log or [],
    )
    return plant


def _make_coordinator(plant: Plant) -> MagicMock:
    """Mock coordinator that returns a single plant."""
    coord = MagicMock()
    coord.plants = {plant.plant_id: plant}
    coord.growspaces = {}
    coord.services.plants.get_plant.side_effect = coord.plants.get
    coord.services.growspaces.get_growspace.return_value = None
    return coord


# --- DryingWeightSensor ---

class TestDryingWeightSensor:
    def test_native_value_returns_latest_weight(self) -> None:
        """State is the most recent weight_log entry."""
        plant = _make_plant(
            weight_log=[
                WeightEntry(date="2026-05-14", weight_grams=350.0),
                WeightEntry(date="2026-05-15", weight_grams=320.0),
            ]
        )
        sensor = DryingWeightSensor(_make_coordinator(plant), plant)
        assert sensor.native_value == pytest.approx(320.0)

    def test_native_value_none_when_no_log(self) -> None:
        """State is None when no weight entries exist."""
        plant = _make_plant()
        sensor = DryingWeightSensor(_make_coordinator(plant), plant)
        assert sensor.native_value is None

    def test_attributes_include_weight_lost_pct(self) -> None:
        """extra_state_attributes includes weight_lost_pct when wet_weight is known."""
        plant = _make_plant(
            wet_weight=400.0,
            weight_log=[
                WeightEntry(date="2026-05-14", weight_grams=400.0),
                WeightEntry(date="2026-05-15", weight_grams=300.0),
            ],
        )
        sensor = DryingWeightSensor(_make_coordinator(plant), plant)
        attrs = sensor.extra_state_attributes
        assert attrs["weight_lost_pct"] == pytest.approx(25.0)

    def test_attributes_weight_lost_pct_none_without_wet_weight(self) -> None:
        """weight_lost_pct is None when harvest wet_weight is unknown."""
        plant = _make_plant(
            wet_weight=None,
            weight_log=[WeightEntry(date="2026-05-15", weight_grams=300.0)],
        )
        sensor = DryingWeightSensor(_make_coordinator(plant), plant)
        assert sensor.extra_state_attributes["weight_lost_pct"] is None

    def test_attributes_include_days_to_target(self) -> None:
        """days_to_target is computed from rolling average when enough entries exist."""
        plant = _make_plant(
            wet_weight=400.0,
            weight_log=[
                WeightEntry(date="2026-05-12", weight_grams=400.0),
                WeightEntry(date="2026-05-13", weight_grams=380.0),
                WeightEntry(date="2026-05-14", weight_grams=360.0),
                WeightEntry(date="2026-05-15", weight_grams=340.0),
            ],
        )
        sensor = DryingWeightSensor(_make_coordinator(plant), plant)
        # target=100g, current=340g, avg_loss=20g/day → 12 days
        assert sensor.extra_state_attributes["days_to_target"] == pytest.approx(12.0)

    def test_attributes_days_to_target_none_with_single_entry(self) -> None:
        """days_to_target is None when fewer than 2 log entries."""
        plant = _make_plant(
            wet_weight=400.0,
            weight_log=[WeightEntry(date="2026-05-15", weight_grams=380.0)],
        )
        sensor = DryingWeightSensor(_make_coordinator(plant), plant)
        assert sensor.extra_state_attributes["days_to_target"] is None


# --- DryingMoistureSensor ---

class TestDryingMoistureSensor:
    def test_native_value_returns_latest_moisture(self) -> None:
        """State is the most recent moisture_log entry."""
        plant = _make_plant(
            moisture_log=[
                MoistureEntry(date="2026-05-14", moisture_percent=16.0),
                MoistureEntry(date="2026-05-15", moisture_percent=13.5),
            ]
        )
        sensor = DryingMoistureSensor(_make_coordinator(plant), plant)
        assert sensor.native_value == pytest.approx(13.5)

    def test_native_value_none_when_no_log(self) -> None:
        """State is None when no moisture entries exist."""
        plant = _make_plant()
        sensor = DryingMoistureSensor(_make_coordinator(plant), plant)
        assert sensor.native_value is None


# --- DryingReadyForCureSensor ---

class TestDryingReadyForCureSensor:
    def test_is_on_when_moisture_at_threshold(self) -> None:
        """Binary sensor is on when moisture is exactly at threshold."""
        plant = _make_plant(
            moisture_log=[MoistureEntry(date="2026-05-15", moisture_percent=12.0)]
        )
        sensor = DryingReadyForCureSensor(_make_coordinator(plant), plant)
        assert sensor.is_on is True

    def test_is_on_when_moisture_below_threshold(self) -> None:
        """Binary sensor is on when moisture is below threshold."""
        plant = _make_plant(
            moisture_log=[MoistureEntry(date="2026-05-15", moisture_percent=10.5)]
        )
        sensor = DryingReadyForCureSensor(_make_coordinator(plant), plant)
        assert sensor.is_on is True

    def test_is_off_when_moisture_above_threshold(self) -> None:
        """Binary sensor is off when moisture is above threshold."""
        plant = _make_plant(
            moisture_log=[MoistureEntry(date="2026-05-15", moisture_percent=14.0)]
        )
        sensor = DryingReadyForCureSensor(_make_coordinator(plant), plant)
        assert sensor.is_on is False

    def test_is_off_when_no_moisture_readings(self) -> None:
        """Binary sensor is off when no moisture readings exist."""
        plant = _make_plant()
        sensor = DryingReadyForCureSensor(_make_coordinator(plant), plant)
        assert sensor.is_on is False
