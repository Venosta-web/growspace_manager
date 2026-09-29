"""Print the line a stable release body opens with: a link to its changelog section.

GitHub prepends a release's ``body`` to its generated notes, so this line sits
above the generated PR list (ADR-0063 decision 5). A version with no
``## [X.Y.Z]`` section in the changelog is refused, which stops a stable release
from being published before its notes are written.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CHANGELOG = REPOSITORY_ROOT / "CHANGELOG.md"


class MissingChangelogSection(LookupError):
    """The changelog has no section for the version being released."""


def github_anchor(heading: str) -> str:
    """Return the fragment GitHub renders for a Markdown heading's text."""
    slug = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return slug.replace(" ", "-")


def changelog_heading(changelog: str, version: str) -> str:
    """Return the text of the ``## [version]`` heading in the changelog."""
    pattern = re.compile(rf"^## (\[{re.escape(version)}\].*)$", re.MULTILINE)
    match = pattern.search(changelog)
    if match is None:
        raise MissingChangelogSection(
            f"CHANGELOG.md has no '## [{version}]' section to link the release to"
        )
    return match[1].strip()


def release_notes_header(changelog: str, version: str, repository: str) -> str:
    """Return the Markdown line linking the release to its changelog section."""
    anchor = github_anchor(changelog_heading(changelog, version))
    url = f"https://github.com/{repository}/blob/v{version}/CHANGELOG.md#{anchor}"
    return f"**What changes for you in {version}:** [CHANGELOG.md § {version}]({url})"


def main(argv: list[str] | None = None) -> int:
    """Print the header for the requested version, or refuse without a section."""
    parser = argparse.ArgumentParser()
    parser.add_argument("version")
    parser.add_argument("repository", help="owner/name, as in GITHUB_REPOSITORY")
    parser.add_argument("--changelog", type=Path, default=DEFAULT_CHANGELOG)
    args = parser.parse_args(argv)
    try:
        header = release_notes_header(
            args.changelog.read_text(encoding="utf-8"), args.version, args.repository
        )
    except MissingChangelogSection as err:
        sys.stderr.write(f"{err}\n")
        return 1
    sys.stdout.write(f"{header}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
