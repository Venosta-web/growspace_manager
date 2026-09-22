"""Build the runtime-only Growspace Manager release archive."""

from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = REPOSITORY_ROOT / "custom_components/growspace_manager"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "growspace_manager.zip"

RUNTIME_METADATA = {
    "icons.json",
    "manifest.json",
    "services.yaml",
    "strings.json",
}
RUNTIME_ASSET_DIRECTORIES = {
    "brand",
    "images",
    "sentences",
    "static",
    "translations",
}
FORBIDDEN_DIRECTORIES = {
    "__pycache__",
    ".pytest_cache",
    "scratch",
    "test",
    "tests",
}
REQUIRED_MEMBERS = {
    PurePosixPath("__init__.py"),
    PurePosixPath("manifest.json"),
    PurePosixPath("services.yaml"),
    PurePosixPath("strings.json"),
    PurePosixPath("translations/en.json"),
}


def _is_runtime_file(path: Path, source: Path) -> bool:
    relative = path.relative_to(source)
    if FORBIDDEN_DIRECTORIES.intersection(relative.parts):
        return False
    if path.suffix == ".py":
        return True
    if len(relative.parts) == 1:
        return relative.name in RUNTIME_METADATA
    return relative.parts[0] in RUNTIME_ASSET_DIRECTORIES


def build_archive(source: Path, output: Path) -> None:
    """Write the runtime package rooted at ``source`` to ``output``."""
    runtime_files = sorted(
        path
        for path in source.rglob("*")
        if path.is_file() and _is_runtime_file(path, source)
    )
    members = {
        PurePosixPath(path.relative_to(source).as_posix()) for path in runtime_files
    }
    missing = REQUIRED_MEMBERS - members
    if missing:
        missing_list = ", ".join(sorted(path.as_posix() for path in missing))
        raise SystemExit(f"Release archive is missing required files: {missing_list}")

    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as release_zip:
        for path in runtime_files:
            release_zip.write(path, path.relative_to(source).as_posix())


def main() -> None:
    """Parse command-line arguments and build the release archive."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    build_archive(args.source.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
