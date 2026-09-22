"""Compare vendored Vision fixtures with the manifest-owned contract source."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


def _load_manifest(path: Path, owner: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{owner}: cannot read {path}: {error}") from error
    if not isinstance(document, dict):
        raise TypeError(f"{owner}: {path} must contain a JSON object")
    return document


def _manifest_files(manifest: dict[str, Any], owner: str) -> set[Path]:
    files = {Path("manifest.json")}
    for section in ("valid", "invalid"):
        entries = manifest.get(section)
        if not isinstance(entries, list):
            raise TypeError(f"{owner}: manifest.{section} must be an array")
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("file"), str):
                raise TypeError(
                    f"{owner}: manifest.{section} has an invalid file entry"
                )
            relative = Path(entry["file"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"{owner}: unsafe fixture path {relative}")
            if relative in files:
                raise ValueError(f"{owner}: manifest repeats {relative}")
            files.add(relative)
    return files


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def compare_vision_contract_fixtures(canonical: Path, vendored: Path) -> list[str]:
    """Return actionable differences at the backend fixture boundary."""
    canonical_manifest = _load_manifest(
        canonical / "manifest.json", "Vision contract boundary"
    )
    vendored_manifest = _load_manifest(
        vendored / "manifest.json", "backend fixture boundary"
    )
    expected = _manifest_files(canonical_manifest, "Vision contract boundary")
    declared = _manifest_files(vendored_manifest, "backend fixture boundary")
    actual = {
        path.relative_to(vendored)
        for path in vendored.rglob("*")
        if path.is_file() and path.name != "README.md"
    }

    diagnostics: list[str] = []
    diagnostics.extend(
        f"missing from backend manifest: {relative}"
        for relative in sorted(expected - declared)
    )
    diagnostics.extend(
        f"not declared by Vision manifest: {relative}"
        for relative in sorted(declared - expected)
    )
    diagnostics.extend(
        f"missing backend fixture: {relative}" for relative in sorted(expected - actual)
    )
    diagnostics.extend(
        f"unexpected backend fixture: {relative}"
        for relative in sorted(actual - expected)
    )
    for relative in sorted(expected & actual):
        source = canonical / relative
        target = vendored / relative
        if not source.is_file():
            diagnostics.append(f"Vision manifest names missing fixture: {relative}")
        elif source.read_bytes() != target.read_bytes():
            diagnostics.append(
                f"payload differs: {relative} "
                f"(Vision {_digest(source)} != backend {_digest(target)})"
            )
    return diagnostics


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vision-root", type=Path, required=True)
    parser.add_argument("--backend-root", type=Path, required=True)
    arguments = parser.parse_args()
    canonical = (
        arguments.vision_root / "contracts" / "growspace-vision" / "v1" / "fixtures"
    ).resolve()
    vendored = (
        arguments.backend_root
        / "tests"
        / "fixtures"
        / "vision"
        / "growspace-vision"
        / "v1"
    ).resolve()
    try:
        diagnostics = compare_vision_contract_fixtures(canonical, vendored)
    except (TypeError, ValueError) as error:
        sys.stderr.write(f"{error}\n")
        return 1
    if diagnostics:
        sys.stderr.write(
            "backend fixture boundary: Growspace Vision V1 contract drift\n"
        )
        for diagnostic in diagnostics:
            sys.stderr.write(f"  - {diagnostic}\n")
        sys.stderr.write(
            f"  re-vendor the manifest-owned files from {canonical} into {vendored}\n"
        )
        return 1
    manifest = _load_manifest(canonical / "manifest.json", "Vision contract boundary")
    sys.stdout.write(
        "backend fixture boundary: "
        f"{len(_manifest_files(manifest, 'Vision contract boundary'))} files match "
        "Growspace Vision V1\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
