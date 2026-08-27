"""Prepare isolated Lovelace bundles for backend Home Assistant configs."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

BUNDLE_NAME = "growspace-manager-card.js"
AUTHORITATIVE_FIXTURE = Path("tests/fixtures/lovelace") / BUNDLE_NAME
CHECKSUM_FILE = AUTHORITATIVE_FIXTURE.with_suffix(".sha256")
CONFIGURATION_GLOB = "tests/*/configs/configuration.yaml"
RESOURCE_PATTERN = re.compile(
    r"^\s*-\s+url:\s*['\"]?/local/growspace-manager-card\.js['\"]?\s*(?:#.*)?$",
    re.MULTILINE,
)
PREPARE_COMMAND = "python tests/utils/prepare_lovelace_fixtures.py"


class FixtureError(RuntimeError):
    """Raised when the authoritative or materialized fixture is invalid."""


@dataclass(frozen=True)
class PreparationSummary:
    """Result counts for a fixture preparation run."""

    configurations: int
    created: int
    refreshed: int
    current: int


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fixture_file:
        for chunk in iter(lambda: fixture_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent,
            prefix=f".{destination.name}.",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            with source.open("rb") as source_file:
                shutil.copyfileobj(source_file, temporary_file)
        shutil.copymode(source, temporary_path)
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _write_checksum(checksum_path: Path, digest: str) -> None:
    checksum_path.write_text(f"{digest}  {BUNDLE_NAME}\n", encoding="utf-8")


def _validate_bundle_shape(bundle: Path) -> None:
    if not bundle.is_file():
        raise FixtureError(
            f"Authoritative Lovelace fixture is missing: {bundle}. "
            f"Restore it or run {PREPARE_COMMAND} --update-from <built-bundle>."
        )
    if b"growspace-manager-card" not in bundle.read_bytes():
        raise FixtureError(
            f"Lovelace fixture does not contain the card registration marker: {bundle}. "
            f"Run {PREPARE_COMMAND} --update-from <built-bundle>."
        )


def _expected_digest(checksum_path: Path) -> str:
    if not checksum_path.is_file():
        raise FixtureError(
            f"Fixture checksum is missing: {checksum_path}. "
            f"Run {PREPARE_COMMAND} --update-from <built-bundle>."
        )
    fields = checksum_path.read_text(encoding="utf-8").split()
    if len(fields) != 2 or fields[1] != BUNDLE_NAME or len(fields[0]) != 64:
        raise FixtureError(
            f"Fixture checksum has an invalid format: {checksum_path}. "
            f"Run {PREPARE_COMMAND} --update-from <built-bundle>."
        )
    return fields[0]


def validate_authoritative_fixture(repository_root: Path) -> tuple[Path, str]:
    """Return the authoritative bundle and digest after integrity validation."""
    bundle = repository_root / AUTHORITATIVE_FIXTURE
    checksum_path = repository_root / CHECKSUM_FILE
    _validate_bundle_shape(bundle)
    expected = _expected_digest(checksum_path)
    actual = _digest(bundle)
    if actual != expected:
        raise FixtureError(
            "Authoritative Lovelace fixture is stale or corrupted: "
            f"expected {expected}, found {actual}. "
            f"Run {PREPARE_COMMAND} --update-from <built-bundle> intentionally."
        )
    return bundle, actual


def declared_configurations(repository_root: Path) -> tuple[Path, ...]:
    """Find every test configuration declaring the local card resource."""
    configurations = tuple(
        configuration
        for configuration in sorted(repository_root.glob(CONFIGURATION_GLOB))
        if RESOURCE_PATTERN.search(configuration.read_text(encoding="utf-8"))
    )
    if not configurations:
        raise FixtureError(
            f"No Lovelace test configurations matched {CONFIGURATION_GLOB}."
        )
    return configurations


def update_authoritative_fixture(repository_root: Path, built_bundle: Path) -> None:
    """Replace the tracked fixture and checksum from an explicit build output."""
    built_bundle = built_bundle.resolve()
    _validate_bundle_shape(built_bundle)
    destination = repository_root / AUTHORITATIVE_FIXTURE
    _atomic_copy(built_bundle, destination)
    _write_checksum(repository_root / CHECKSUM_FILE, _digest(destination))


def prepare_fixtures(
    repository_root: Path,
    *,
    check: bool = False,
) -> PreparationSummary:
    """Prepare or verify configuration-local copies of the tracked fixture."""
    source, expected_digest = validate_authoritative_fixture(repository_root)
    configurations = declared_configurations(repository_root)
    created = refreshed = current = 0
    problems: list[str] = []

    for configuration in configurations:
        destination = configuration.parent / "www" / BUNDLE_NAME
        if not destination.is_file():
            created += 1
            problems.append(f"missing: {destination.relative_to(repository_root)}")
            if not check:
                _atomic_copy(source, destination)
            continue

        actual_digest = _digest(destination)
        if actual_digest != expected_digest:
            refreshed += 1
            problems.append(
                f"stale: {destination.relative_to(repository_root)} "
                f"(found {actual_digest}, expected {expected_digest})"
            )
            if not check:
                _atomic_copy(source, destination)
            continue
        current += 1

    if check and problems:
        details = "\n  - ".join(problems)
        raise FixtureError(
            "Lovelace configuration fixtures are not prepared:\n"
            f"  - {details}\nRun {PREPARE_COMMAND} to repair them."
        )

    return PreparationSummary(
        configurations=len(configurations),
        created=created,
        refreshed=refreshed,
        current=current,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report missing or stale configuration copies without changing them",
    )
    parser.add_argument(
        "--update-from",
        type=Path,
        metavar="BUNDLE",
        help="intentionally replace the authoritative fixture from a built card",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help=argparse.SUPPRESS,
    )
    return parser.parse_args()


def main() -> int:
    """Run fixture preparation from the command line."""
    args = _parse_args()
    repository_root = args.root.resolve()
    if args.update_from is not None and args.check:
        sys.stderr.write("ERROR: --check and --update-from cannot be used together.\n")
        return 1
    try:
        if args.update_from is not None:
            update_authoritative_fixture(repository_root, args.update_from)
        summary = prepare_fixtures(repository_root, check=args.check)
    except FixtureError as err:
        sys.stderr.write(f"ERROR: {err}\n")
        return 1

    action = "Verified" if args.check else "Prepared"
    sys.stdout.write(
        f"{action} {summary.configurations} Lovelace configuration fixtures "
        f"({summary.created} missing, {summary.refreshed} stale, "
        f"{summary.current} current).\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
