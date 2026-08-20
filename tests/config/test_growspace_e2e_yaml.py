"""Tests for growspace_e2e.yaml.

Verifies the E2E simulation package defines all pump switches and VWC sensor helpers.
"""

from pathlib import Path

import pytest
import yaml

YAML_PATH = Path(__file__).parent / "configs" / "growspace_e2e.yaml"
STAGES = ["mother", "clone", "veg", "flower", "dry", "cure"]
VWC_SLUGS = ["vwc_veg", "vwc_flower"]
VWC_SENSORS = [
    "substrate_moisture",
    "substrate_ec",
    "runoff_ec",
    "feed_ec",
    "drain_volume",
    "irrigation_flow",
    "irrigation_tank",
    "temperature",
    "humidity",
    "vpd",
    "co2",
    "ph",
    "substrate_temperature",
    "power",
    "energy",
]


@pytest.fixture(scope="module")
def e2e_config() -> dict:
    """Load growspace_e2e.yaml once for all tests in this module."""
    return yaml.safe_load(YAML_PATH.read_text())


def test_file_exists() -> None:
    """growspace_e2e.yaml must exist in the test config package directory."""
    assert YAML_PATH.exists(), f"growspace_e2e.yaml not found at {YAML_PATH}"


@pytest.mark.parametrize("stage", STAGES + VWC_SLUGS)
def test_irrigation_pump_defined(stage: str, e2e_config: dict) -> None:
    """Each stage must have an irrigation pump input_boolean defined."""
    entity_id = f"sim_e2e_{stage}_irrigation_pump"
    assert entity_id in e2e_config.get("input_boolean", {}), (
        f"input_boolean.{entity_id} missing from growspace_e2e.yaml"
    )


@pytest.mark.parametrize("stage", STAGES + VWC_SLUGS)
def test_drain_pump_defined(stage: str, e2e_config: dict) -> None:
    """Each stage must have a drain pump input_boolean defined."""
    entity_id = f"sim_e2e_{stage}_drain_pump"
    assert entity_id in e2e_config.get("input_boolean", {}), (
        f"input_boolean.{entity_id} missing from growspace_e2e.yaml"
    )


@pytest.mark.parametrize("slug", VWC_SLUGS)
@pytest.mark.parametrize("sensor", VWC_SENSORS)
def test_vwc_sensor_helper_defined(slug: str, sensor: str, e2e_config: dict) -> None:
    """Each VWC growspace must have all 15 input_number sensor helpers defined."""
    entity_id = f"e2e_{slug}_{sensor}"
    assert entity_id in e2e_config.get("input_number", {}), (
        f"input_number.{entity_id} missing from growspace_e2e.yaml"
    )


@pytest.mark.parametrize("slug", VWC_SLUGS)
@pytest.mark.parametrize("sensor", VWC_SENSORS)
def test_vwc_sensor_helper_has_required_fields(
    slug: str, sensor: str, e2e_config: dict
) -> None:
    """Each VWC input_number helper must have min, max, step, and initial values."""
    entity_id = f"e2e_{slug}_{sensor}"
    entry = e2e_config.get("input_number", {}).get(entity_id, {})
    for field in ("min", "max", "step", "initial"):
        assert field in entry, (
            f"input_number.{entity_id} is missing required field '{field}'"
        )


@pytest.mark.parametrize(
    ("slug", "expected_initial"),
    [
        ("vwc_flower", 55),
        ("vwc_veg", 65),
    ],
)
def test_substrate_moisture_initial_value(
    slug: str, expected_initial: int, e2e_config: dict
) -> None:
    """substrate_moisture initial values must match the VWC strategy target.

    vwc_flower targets 55% and vwc_veg targets 65% — these are the seeds the
    coordinator needs to avoid reading None and aborting its monitoring loop.
    """
    entity_id = f"e2e_{slug}_substrate_moisture"
    entry = e2e_config.get("input_number", {}).get(entity_id, {})
    assert entry.get("initial") == expected_initial, (
        f"input_number.{entity_id} must have initial: {expected_initial}, "
        f"got: {entry.get('initial')}"
    )
