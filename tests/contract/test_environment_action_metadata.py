"""Structural guard for the public Environment Change action metadata."""

from pathlib import Path

import yaml

from custom_components.growspace_manager.schemas import CONFIGURE_ENVIRONMENT_SCHEMA

ROOT = Path(__file__).resolve().parents[2]
SERVICES_YAML = ROOT / "custom_components" / "growspace_manager" / "services.yaml"


def test_configure_environment_metadata_is_accepted_by_schema() -> None:
    """Every documented field is accepted without documenting all schema fields."""
    metadata = yaml.safe_load(SERVICES_YAML.read_text(encoding="utf-8"))
    documented = metadata["configure_environment"]["fields"]
    schema_fields = {marker.schema for marker in CONFIGURE_ENVIRONMENT_SCHEMA.schema}

    assert set(documented) <= schema_fields
    assert {
        name for name, field in documented.items() if field.get("required", False)
    } == {"growspace_id"}
