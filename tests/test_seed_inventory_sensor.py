"""Tests for SeedInventorySensor."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.sensor import SeedInventorySensor


@pytest.fixture
def coordinator():
    """Return a mock coordinator with a genetics_manager."""
    c = MagicMock()
    c.genetics_manager.get_total_seed_count.return_value = 42
    c.genetics_manager.seed_batches = {}
    return c


class TestSeedInventorySensor:
    """Tests for SeedInventorySensor."""

    def test_unique_id(self, coordinator):
        """Sensor has a stable unique ID."""
        sensor = SeedInventorySensor(coordinator)
        assert sensor.unique_id == "growspace_manager_seed_inventory"

    def test_native_value_returns_total_seed_count(self, coordinator):
        """native_value delegates to genetics_manager.get_total_seed_count."""
        sensor = SeedInventorySensor(coordinator)
        assert sensor.native_value == 42

    def test_native_value_zero_when_no_seeds(self, coordinator):
        """native_value is 0 when there are no seeds."""
        coordinator.genetics_manager.get_total_seed_count.return_value = 0
        sensor = SeedInventorySensor(coordinator)
        assert sensor.native_value == 0

    def test_extra_state_attributes_contains_seed_batches(self, coordinator):
        """extra_state_attributes exposes each seed batch as a dict."""
        from custom_components.growspace_manager.models import SeedBatch

        batch = SeedBatch(
            batch_id="b1",
            strain_name="OG Kush",
            breeder="DNA Genetics",
            quantity=10,
            acquisition_date="2026-01-01",
            generation="F1",
            lineage="",
        )
        coordinator.genetics_manager.seed_batches = {"b1": batch}
        sensor = SeedInventorySensor(coordinator)
        attrs = sensor.extra_state_attributes
        assert "seed_batches" in attrs
        batches = attrs["seed_batches"]
        assert isinstance(batches, list)
        assert len(batches) == 1
        assert batches[0]["batch_id"] == "b1"
        assert batches[0]["strain_name"] == "OG Kush"
        assert batches[0]["quantity"] == 10

    def test_device_info_uses_service_device(self, coordinator):
        """Sensor attaches to the service device (not a growspace)."""
        sensor = SeedInventorySensor(coordinator)
        assert sensor.device_info is not None
        identifiers = dict(sensor.device_info.get("identifiers", set()))
        assert "growspace_manager" in identifiers
        assert identifiers["growspace_manager"] == "service"
