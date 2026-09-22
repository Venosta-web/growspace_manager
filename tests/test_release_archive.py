"""Regression tests for the published integration archive."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import subprocess
import sys
from zipfile import ZipFile

REPOSITORY_ROOT = Path(__file__).parents[1]
BUILD_SCRIPT = REPOSITORY_ROOT / ".github/scripts/build_release_archive.py"


def test_release_archive_contains_only_runtime_files(tmp_path: Path) -> None:
    """The published ZIP contains runtime files and excludes repository artifacts."""
    archive = tmp_path / "growspace_manager.zip"

    subprocess.run(
        [sys.executable, str(BUILD_SCRIPT), "--output", str(archive)],
        cwd=REPOSITORY_ROOT,
        check=True,
    )

    with ZipFile(archive) as release_zip:
        members = {
            PurePosixPath(name)
            for name in release_zip.namelist()
            if not name.endswith("/")
        }

    assert {
        PurePosixPath("__init__.py"),
        PurePosixPath("manifest.json"),
        PurePosixPath("services.yaml"),
        PurePosixPath("strings.json"),
        PurePosixPath("translations/en.json"),
    } <= members

    forbidden_names = {
        "CONTEXT.md",
        "README.md",
        "module.json",
        "pytest.ini",
        "ruff_output.txt",
        "search_results.html",
    }
    forbidden_directories = {"__pycache__", ".pytest_cache", "scratch", "tests"}

    assert not any(path.name in forbidden_names for path in members)
    assert not any(forbidden_directories.intersection(path.parts) for path in members)
    assert not any(path.suffix in {".log", ".pyc"} for path in members)
