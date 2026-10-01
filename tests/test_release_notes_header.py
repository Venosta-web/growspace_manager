"""The stable release body opens with a link to its changelog section."""

import json
from pathlib import Path
import runpy

import pytest

REPO_ROOT = Path(__file__).parents[1]
SCRIPT = runpy.run_path(str(REPO_ROOT / ".github/scripts/release_notes_header.py"))

CHANGELOG = """# Changelog

## [1.3.0] - 2026-09-29

### Changed

- Something.

## [1.2.3] - 2026-09-22
"""


def test_header_links_the_versions_changelog_section_at_its_tag() -> None:
    """The link names the tag's changelog, anchored the way GitHub renders it."""
    header = SCRIPT["release_notes_header"](CHANGELOG, "1.3.0", "owner/repo")

    assert header == (
        "**What changes for you in 1.3.0:** [CHANGELOG.md § 1.3.0]"
        "(https://github.com/owner/repo/blob/v1.3.0/CHANGELOG.md#130---2026-09-29)"
    )


def test_a_version_without_a_section_is_refused() -> None:
    """A stable release cannot be published before its notes are written."""
    with pytest.raises(SCRIPT["MissingChangelogSection"]):
        SCRIPT["release_notes_header"](CHANGELOG, "1.3.1", "owner/repo")


def test_a_version_is_not_matched_by_its_prefix() -> None:
    """1.3.0 is not found in a heading for 1.3.0b1 or 11.3.0."""
    changelog = "## [1.3.0b1] - x\n\n## [11.3.0] - y\n"
    with pytest.raises(SCRIPT["MissingChangelogSection"]):
        SCRIPT["changelog_heading"](changelog, "1.3.0")


def test_main_prints_the_header_or_refuses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The workflow reads stdout, and a missing section fails the step."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(CHANGELOG, encoding="utf-8")

    assert SCRIPT["main"](["1.3.0", "o/r", "--changelog", str(changelog)]) == 0
    assert "#130---2026-09-29" in capsys.readouterr().out

    assert SCRIPT["main"](["9.9.9", "o/r", "--changelog", str(changelog)]) == 1
    assert "## [9.9.9]" in capsys.readouterr().err


def test_the_real_changelog_has_a_section_for_the_manifest_version() -> None:
    """Whatever main publishes next already has its notes."""
    manifest = REPO_ROOT / "custom_components/growspace_manager/manifest.json"
    version = json.loads(manifest.read_text())["version"]
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert SCRIPT["changelog_heading"](changelog, version).startswith(f"[{version}]")


def test_zone_release_links_upgrade_guide_above_generated_notes() -> None:
    """The one-way migration's recovery guide opens the release body."""
    header = SCRIPT["release_notes_header"](
        "## [1.4.0] - Unreleased\n", "1.4.0", "owner/repo"
    )
    assert header == (
        "**What changes for you in 1.4.0:** [CHANGELOG.md § 1.4.0]"
        "(https://github.com/owner/repo/blob/v1.4.0/CHANGELOG.md#140---unreleased)"
        " · [Upgrading to zones]"
        "(https://github.com/owner/repo/blob/v1.4.0/docs/upgrading/zones.md)"
    )
