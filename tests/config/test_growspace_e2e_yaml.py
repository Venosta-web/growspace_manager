"""Tests for growspace_e2e.yaml — verifies the E2E simulation package defines all pump switches."""

from pathlib import Path

import pytest
import yaml

YAML_PATH = Path(__file__).parent / "configs" / "growspace_e2e.yaml"
STAGES = ["mother", "clone", "veg", "flower", "dry", "cure"]


@pytest.fixture(scope="module")
def e2e_config() -> dict:
    """Load growspace_e2e.yaml once for all tests in this module."""
    return yaml.safe_load(YAML_PATH.read_text())


def test_file_exists() -> None:
    """growspace_e2e.yaml must exist in the test config package directory."""
    assert YAML_PATH.exists(), f"growspace_e2e.yaml not found at {YAML_PATH}"


@pytest.mark.parametrize("stage", STAGES)
def test_irrigation_pump_defined(stage: str, e2e_config: dict) -> None:
    """Each stage must have an irrigation pump input_boolean defined."""
    entity_id = f"sim_e2e_{stage}_irrigation_pump"
    assert entity_id in e2e_config.get("input_boolean", {}), (
        f"input_boolean.{entity_id} missing from growspace_e2e.yaml"
    )


@pytest.mark.parametrize("stage", STAGES)
def test_drain_pump_defined(stage: str, e2e_config: dict) -> None:
    """Each stage must have a drain pump input_boolean defined."""
    entity_id = f"sim_e2e_{stage}_drain_pump"
    assert entity_id in e2e_config.get("input_boolean", {}), (
        f"input_boolean.{entity_id} missing from growspace_e2e.yaml"
    )
