"""Tests for isolated Lovelace fixture preparation."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from .prepare_lovelace_fixtures import (
    BUNDLE_NAME,
    FixtureError,
    declared_configurations,
    prepare_fixtures,
    validate_authoritative_fixture,
)

CARD_BYTES = b"customElements.define('growspace-manager-card', Card);\n"


def _create_repository(root: Path) -> None:
    fixture_dir = root / "tests" / "fixtures" / "lovelace"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / BUNDLE_NAME).write_bytes(CARD_BYTES)
    digest = hashlib.sha256(CARD_BYTES).hexdigest()
    (fixture_dir / "growspace-manager-card.sha256").write_text(
        f"{digest}  {BUNDLE_NAME}\n", encoding="utf-8"
    )

    for suite in ("components", "services"):
        config_dir = root / "tests" / suite / "configs"
        config_dir.mkdir(parents=True)
        (config_dir / "configuration.yaml").write_text(
            "lovelace:\n"
            "  resources:\n"
            "    - url: /local/growspace-manager-card.js\n"
            "      type: module\n",
            encoding="utf-8",
        )

    unrelated = root / "tests" / "unrelated" / "configs"
    unrelated.mkdir(parents=True)
    (unrelated / "configuration.yaml").write_text("frontend:\n", encoding="utf-8")


def test_prepare_materializes_private_copies(tmp_path: Path) -> None:
    _create_repository(tmp_path)

    summary = prepare_fixtures(tmp_path)

    assert summary.configurations == 2
    assert summary.created == 2
    assert summary.refreshed == 0
    assert summary.current == 0
    destinations = [
        configuration.parent / "www" / BUNDLE_NAME
        for configuration in declared_configurations(tmp_path)
    ]
    assert all(destination.read_bytes() == CARD_BYTES for destination in destinations)

    second_summary = prepare_fixtures(tmp_path, check=True)
    assert second_summary.current == 2


def test_check_reports_missing_and_stale_copies(tmp_path: Path) -> None:
    _create_repository(tmp_path)
    prepare_fixtures(tmp_path)
    configurations = declared_configurations(tmp_path)
    (configurations[0].parent / "www" / BUNDLE_NAME).unlink()
    (configurations[1].parent / "www" / BUNDLE_NAME).write_text(
        "stale", encoding="utf-8"
    )

    with pytest.raises(FixtureError) as error:
        prepare_fixtures(tmp_path, check=True)

    message = str(error.value)
    assert "missing:" in message
    assert "stale:" in message
    assert "python tests/utils/prepare_lovelace_fixtures.py" in message


def test_authoritative_checksum_detects_stale_bundle(tmp_path: Path) -> None:
    _create_repository(tmp_path)
    bundle, _ = validate_authoritative_fixture(tmp_path)
    bundle.write_bytes(CARD_BYTES + b"changed")

    with pytest.raises(FixtureError, match="stale or corrupted") as error:
        validate_authoritative_fixture(tmp_path)

    assert "--update-from <built-bundle>" in str(error.value)


def test_repository_declares_all_eight_fixture_consumers() -> None:
    repository_root = Path(__file__).resolve().parents[2]

    suites = {
        configuration.parents[1].name
        for configuration in declared_configurations(repository_root)
    }

    assert suites == {
        "components",
        "config",
        "core",
        "integration",
        "issue_fixes",
        "logic",
        "services",
        "utils",
    }
