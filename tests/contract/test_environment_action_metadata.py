"""Structural guard for the public Environment Change action metadata."""

from pathlib import Path

import voluptuous as vol
import yaml

from custom_components.growspace_manager.domain.environment_patch import (
    ENVIRONMENT_SERVICE_ALIASES,
)
from custom_components.growspace_manager.models import ENVIRONMENT_FIELD_OWNERSHIP
from custom_components.growspace_manager.schemas import CONFIGURE_ENVIRONMENT_SCHEMA

ROOT = Path(__file__).resolve().parents[2]
SERVICES_YAML = ROOT / "custom_components" / "growspace_manager" / "services.yaml"


def _schema_fields() -> dict[str, vol.Marker]:
    return {
        marker.schema: marker
        for marker in CONFIGURE_ENVIRONMENT_SCHEMA.schema
        if isinstance(marker, vol.Marker)
    }


def test_configure_environment_metadata_matches_canonical_patch_interface() -> None:
    """Metadata exposes every canonical field and no compatibility alias."""
    metadata = yaml.safe_load(SERVICES_YAML.read_text(encoding="utf-8"))
    documented = metadata["configure_environment"]["fields"]
    schema_fields = _schema_fields()
    canonical = set(schema_fields) - ENVIRONMENT_SERVICE_ALIASES

    assert set(documented) == canonical
    assert canonical - {"growspace_id"} <= set(ENVIRONMENT_FIELD_OWNERSHIP)

    for name in canonical:
        marker = schema_fields[name]
        assert documented[name].get("required", False) is isinstance(
            marker, vol.Required
        )
        assert "default" not in documented[name]
