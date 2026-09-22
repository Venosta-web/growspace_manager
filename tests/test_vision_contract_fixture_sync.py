"""Tests for the vendored Growspace Vision V1 contract boundary."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

from tests.utils.vision_contract_fixtures import compare_vision_contract_fixtures


def _fixture_trees(root: Path) -> tuple[Path, Path]:
    canonical = root / "canonical"
    vendored = root / "vendored"
    manifest = {
        "valid": [{"file": "valid/info.json", "schema": "InfoResponse"}],
        "invalid": [],
    }
    for directory in (canonical, vendored):
        (directory / "valid").mkdir(parents=True)
        (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (directory / "valid" / "info.json").write_text(
            '{"schema_version":1}\n', encoding="utf-8"
        )
    (vendored / "README.md").write_text("provenance\n", encoding="utf-8")
    return canonical, vendored


def test_manifest_owned_fixtures_match_byte_for_byte() -> None:
    with tempfile.TemporaryDirectory() as directory:
        canonical, vendored = _fixture_trees(Path(directory))

        assert compare_vision_contract_fixtures(canonical, vendored) == []


def test_payload_drift_is_attributed_to_the_backend_fixture_boundary() -> None:
    with tempfile.TemporaryDirectory() as directory:
        canonical, vendored = _fixture_trees(Path(directory))
        (vendored / "valid" / "info.json").write_text(
            '{"schema_version":2}\n', encoding="utf-8"
        )

        diagnostics = compare_vision_contract_fixtures(canonical, vendored)

        assert len(diagnostics) == 1
        assert diagnostics[0].startswith("payload differs: valid/info.json")
